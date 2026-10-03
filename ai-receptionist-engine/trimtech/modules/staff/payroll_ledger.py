"""Tenant-scoped statutory payroll snapshots; all mutations share business lock."""
from datetime import date
from decimal import Decimal
from psycopg2.extras import Json, RealDictCursor
from trimtech.modules.staff import statutory
from trimtech.modules.staff.agency import audit, lock_business
from trimtech.modules.staff.payroll import PayrollError


def serial(values):
    return {k: str(v) if isinstance(v, (Decimal, date)) else v for k, v in values.items()}


def save_profile(cursor, business_id, employee_id, values, actor):
    lock_business(cursor, business_id)
    cursor.execute("SELECT id FROM staff_employees WHERE business_id=%s AND id=%s FOR UPDATE", (business_id, employee_id))
    if not cursor.fetchone():
        raise PayrollError("Employee unavailable.")
    profile = {k: str(values.get(k, "")).strip() for k in (
        "tax_code", "tax_basis", "frequency", "ni_category", "pension_method", "pension_basis")}
    profile["tax_code"] = profile["tax_code"].upper()
    profile["ni_category"] = profile["ni_category"].upper()
    profile["tax_year"] = statutory.YEAR
    for key in ("employee_pension_rate", "employer_pension_rate", "opening_taxable_pay", "opening_paye"):
        profile[key] = statutory.money(values.get(key), key.replace("_", " "))
    try:
        profile["opening_through"] = date.fromisoformat(values.get("opening_through", ""))
    except (ValueError, TypeError):
        raise PayrollError("Enter the date through which opening payroll balances apply.") from None
    if not date(2026, 4, 5) <= profile["opening_through"] < date(2027, 4, 5):
        raise PayrollError("Opening balances must be within the 2026/27 tax year, or 5 April for zero opening balances.")
    if profile['opening_through'] == date(2026,4,5) and (profile['opening_taxable_pay'] or profile['opening_paye']):
        raise PayrollError("Opening balances before the tax year starts must be zero.")
    if values.get("scope_confirmed") != "yes":
        raise PayrollError("Confirm this is regular employee pay with no unsupported deductions or statutory payments.")
    statutory.calculate(0, profile, date(2026, 5, 1))
    cursor.execute("SELECT * FROM staff_payroll_profiles WHERE business_id=%s AND employee_id=%s", (business_id, employee_id))
    old = cursor.fetchone()
    cursor.execute("SELECT 1 FROM staff_payroll_calculations WHERE business_id=%s AND employee_id=%s LIMIT 1", (business_id, employee_id))
    if cursor.fetchone() and old:
        for key in ("frequency", "opening_through", "opening_taxable_pay", "opening_paye"):
            if old[key] != profile[key]:
                raise PayrollError("Opening balances and pay frequency cannot change after payroll starts. Review an adjustment externally.")
    columns = list(profile)
    cursor.execute("""INSERT INTO staff_payroll_profiles (business_id,employee_id,""" + ",".join(columns) + ",reviewed_by) VALUES (%s,%s," +
                   ",".join(["%s"] * len(columns)) + ",%s) ON CONFLICT (business_id,employee_id) DO UPDATE SET " +
                   ",".join(f"{key}=EXCLUDED.{key}" for key in columns) + ",reviewed_by=EXCLUDED.reviewed_by,updated_at=NOW()",
                   (business_id, employee_id, *profile.values(), actor))
    cursor.execute("""UPDATE staff_payroll_runs SET needs_recalculation=TRUE WHERE business_id=%s AND status='draft'
        AND calculation_version IS NOT NULL AND id IN (SELECT payroll_run_id FROM staff_payslips WHERE employee_id=%s AND business_id=%s)""",
                   (business_id, employee_id, business_id))
    audit(cursor, business_id, actor, "payroll_profile_reviewed", "employee", employee_id,
          serial(dict(old)) if old else None, serial(profile), "Manager reviewed tax, pension and opening balances")


def apply_calculations(connection, business_id, run_id, payment_date, frequency, employer_name=None):
    """Apply one regular earnings period; snapshots exist for every employee or none."""
    period = statutory.tax_period(payment_date, frequency)
    with connection.cursor(cursor_factory=RealDictCursor) as cursor:
        lock_business(cursor, business_id)
        cursor.execute("SELECT * FROM staff_payroll_runs WHERE business_id=%s AND id=%s FOR UPDATE", (business_id, run_id))
        run = cursor.fetchone()
        if not run or run["status"] != "draft":
            raise PayrollError("Only draft payroll can be calculated.")
        employer_name = str(employer_name or run.get('employer_name') or '').strip()
        if not employer_name or len(employer_name)>160:
            raise PayrollError("Enter the employer name to appear on payslips (up to 160 characters).")
        if payment_date < run["period_end"]:
            raise PayrollError("Payment date must be on or after the work period end.")
        cursor.execute("""SELECT id FROM staff_payroll_runs WHERE business_id=%s AND id<>%s
            AND status='draft' AND calculation_version IS NOT NULL LIMIT 1""", (business_id, run_id))
        if cursor.fetchone():
            raise PayrollError("Approve the existing statutory draft before creating another payroll run.")
        cursor.execute("""SELECT p.*,e.full_name FROM staff_payslips p JOIN staff_employees e
            ON e.id=p.employee_id AND e.business_id=p.business_id
            WHERE p.business_id=%s AND p.payroll_run_id=%s ORDER BY p.employee_id FOR UPDATE OF p""", (business_id, run_id))
        payslips = cursor.fetchall()
        totals = {k: Decimal(0) for k in ("deductions", "net_pay", "employer_ni", "employer_pension")}
        for slip in payslips:
            employee_id = slip["employee_id"]
            cursor.execute("SELECT * FROM staff_payroll_profiles WHERE business_id=%s AND employee_id=%s", (business_id, employee_id))
            profile = cursor.fetchone()
            if not profile or profile["frequency"] != frequency:
                raise PayrollError(f"Review payroll settings and pay frequency for {slip['full_name']} first.")
            if payment_date <= profile["opening_through"]:
                raise PayrollError("Payment date must follow the opening balance date.")
            if profile["opening_through"] >= date(2026, 4, 6) and statutory.tax_period(profile["opening_through"], frequency) == period:
                raise PayrollError("Opening balances already cover this earnings period. Use the next regular period.")
            cursor.execute("""SELECT c.*,r.status FROM staff_payroll_calculations c JOIN staff_payroll_runs r ON r.id=c.payroll_run_id
                AND r.business_id=c.business_id WHERE c.business_id=%s AND c.employee_id=%s AND c.payroll_run_id<>%s
                ORDER BY c.payment_date""", (business_id, employee_id, run_id))
            history = cursor.fetchall()
            if any(h["payment_date"] >= payment_date or h["tax_period"] >= period or h["status"] == "draft" for h in history):
                raise PayrollError("Payroll must be processed in payment-date order, once per employee per tax period.")
            # Never infer opening PAYE from old gross-only records.
            cursor.execute("""SELECT 1 FROM staff_payslips p JOIN staff_payroll_runs r ON r.id=p.payroll_run_id
                WHERE p.business_id=%s AND p.employee_id=%s AND r.calculation_version IS NULL
                AND r.id<>%s AND r.period_end>%s LIMIT 1""", (business_id, employee_id, run_id, profile["opening_through"]))
            if cursor.fetchone():
                raise PayrollError("Reconcile gross-only payroll in the employee's opening balances before calculating PAYE.")
            previous_pay = profile["opening_taxable_pay"] + sum((Decimal(h["result"]["taxable_pay"]) for h in history), Decimal(0))
            previous_tax = profile["opening_paye"] + sum((Decimal(h["result"]["paye"]) for h in history), Decimal(0))
            result = statutory.calculate(slip["gross_pay"], profile, payment_date, previous_pay, previous_tax)
            cursor.execute("""INSERT INTO staff_payroll_calculations
                (payslip_id,business_id,employee_id,payroll_run_id,payment_date,tax_year,tax_period,frequency,profile,employee_name,employer_name,result)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(payslip_id) DO UPDATE SET
                profile=EXCLUDED.profile,result=EXCLUDED.result,employee_name=EXCLUDED.employee_name""",
                (slip["id"], business_id, employee_id, run_id, payment_date, statutory.YEAR, period, frequency,
                 Json(serial(dict(profile))), slip["full_name"], employer_name, Json(serial(result))))
            cursor.execute("UPDATE staff_payslips SET deductions=%s,net_pay=%s,updated_at=NOW() WHERE id=%s AND business_id=%s",
                           (result["deductions"], result["net_pay"], slip["id"], business_id))
            for key in totals:
                totals[key] += result[key]
        cursor.execute("""UPDATE staff_payroll_runs SET calculation_version=%s,payment_date=%s,pay_frequency=%s,employer_name=%s,
            total_deductions=%s,total_net_pay=%s,employer_ni=%s,employer_pension=%s,needs_recalculation=FALSE WHERE id=%s AND business_id=%s""",
            (statutory.VERSION, payment_date, frequency, employer_name, *totals.values(), run_id, business_id))


def discard_draft(cursor, business_id, run_id, reason, actor):
    if not str(reason or '').strip():
        raise PayrollError('Enter a reason to discard a draft.')
    lock_business(cursor,business_id)
    cursor.execute("SELECT * FROM staff_payroll_runs WHERE business_id=%s AND id=%s FOR UPDATE",(business_id,run_id))
    run=cursor.fetchone()
    if not run or run['status']!='draft':
        raise PayrollError('Only unapproved drafts can be discarded.')
    cursor.execute("SELECT * FROM staff_payroll_calculations WHERE business_id=%s AND payroll_run_id=%s",(business_id,run_id))
    calculations=[dict(row) for row in cursor.fetchall()]
    cursor.execute("SELECT * FROM staff_payslips WHERE business_id=%s AND payroll_run_id=%s",(business_id,run_id))
    slips=[dict(row) for row in cursor.fetchall()]
    audit(cursor,business_id,actor,'payroll_draft_discarded','payroll',run_id,
          {'run':dict(run),'payslips':slips,'calculations':calculations},None,str(reason)[:1000])
    cursor.execute("DELETE FROM staff_payslip_shifts WHERE payroll_run_id=%s",(run_id,))
    cursor.execute("DELETE FROM staff_payroll_calculations WHERE business_id=%s AND payroll_run_id=%s",(business_id,run_id))
    cursor.execute("DELETE FROM staff_payslips WHERE business_id=%s AND payroll_run_id=%s",(business_id,run_id))
    cursor.execute("DELETE FROM staff_payroll_runs WHERE business_id=%s AND id=%s",(business_id,run_id))
