"""Offline UK payroll calculations. No HMRC client or submission capability.

2026/27: HMRC PAYE tax table routines v24, exact-percentage Class 1 NICs.
Regular weekly/monthly employees only; directors and irregular pay need review.
"""
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_DOWN, ROUND_UP, ROUND_HALF_UP
import re

from trimtech.modules.staff.payroll import PayrollError

D = Decimal
YEAR = "2026/27"
VERSION = "uk-2026-27-v1"
PENNY = D(".01")


def money(value, label="amount", signed=False):
    try:
        value = D(str(value))
        if not value.is_finite() or abs(value) > D("999999999.99") or (not signed and value < 0):
            raise ValueError()
        return value.quantize(PENNY, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, TypeError):
        raise PayrollError(f"Enter a valid {label}.") from None


def tax_period(payment_date, frequency):
    if not date(2026, 4, 6) <= payment_date <= date(2027, 4, 5):
        raise PayrollError("Only tax year 2026/27 is supported. Review rates before using another year.")
    if frequency == "weekly":
        return (payment_date - date(2026, 4, 6)).days // 7 + 1
    if frequency == "monthly":
        return ((payment_date.year - 2026) * 12 + payment_date.month - 4 - (payment_date.day < 6)) + 1
    raise PayrollError("Select regular weekly or monthly pay. Other frequencies require external payroll review.")


def parse_code(code):
    code = str(code or "").strip().upper()
    if code == "NT":
        return "", code
    region = code[:1] if code[:1] in {"S", "C"} else ""
    core = code[1:] if region else code
    allowed = {"BR", "D0", "D1"} | ({"D2", "D3"} if region == "S" else set())
    if core not in allowed and not re.fullmatch(r"(?:[0-9]{1,6}[LMNT]|K[1-9][0-9]{0,5})", core):
        raise PayrollError("Enter a supported HMRC tax code; choose cumulative or W1/M1 separately.")
    return region, core


def paye(taxable_pay, code, frequency, period, basis="cumulative", previous_pay=0, previous_tax=0, cash_pay=None):
    gross = money(taxable_pay)
    previous_pay, previous_tax = money(previous_pay), money(previous_tax)
    region, core = parse_code(code)
    divisor = {"weekly": 52, "monthly": 12}.get(frequency)
    if not divisor or not isinstance(period, int) or not 1 <= period <= (53 if frequency == "weekly" else 12):
        raise PayrollError("Invalid tax period or pay frequency.")
    if basis not in {"cumulative", "noncumulative"}:
        raise PayrollError("Choose cumulative or W1/M1 tax basis.")
    cumulative = basis == "cumulative" and period <= divisor
    n = period if cumulative else 1
    pay = gross + (previous_pay if cumulative else D(0))
    prior_tax = previous_tax if cumulative else D(0)
    if core == "NT":
        liability = D(0)
    elif core == "BR" or core.startswith("D"):
        rates = [D(".21"), D(".42"), D(".45"), D(".48")] if region == "S" else [D(".40"), D(".45")]
        rate = D(".20") if core == "BR" else rates[int(core[1:])]
        liability = (pay.to_integral_value(rounding=ROUND_DOWN) * rate).quantize(PENNY, rounding=ROUND_DOWN)
    else:
        negative = core.startswith("K")
        number = int(core[1:] if negative else core[:-1])
        adjustment = D(0)
        if number:
            quotient, remainder = divmod(number - 1, 500)
            # Table A adjustment is shared by suffix and K codes (v24 4.3).
            annual = D((remainder + 1) * 10 + 9)
            adjustment = (annual / divisor).quantize(PENNY, rounding=ROUND_UP)
            adjustment += quotient * (D(5000) / divisor).quantize(PENNY, rounding=ROUND_UP)
        unrounded = max(D(0), pay + adjustment * n if negative else pay - adjustment * n)
        rounded = unrounded.to_integral_value(rounding=ROUND_DOWN)
        limits = [3967, 16956, 31092, 62430, 125140] if region == "S" else [37700, 125140]
        rates = list(map(D, [".19", ".20", ".21", ".42", ".45", ".48"] if region == "S" else [".20", ".40", ".45"]))
        lower, annual_tax, liability = D(0), D(0), None
        for index, upper in enumerate(limits):
            threshold = (D(upper) * n / divisor).quantize(D(".0001"), rounding=ROUND_DOWN)
            if unrounded <= threshold.to_integral_value(rounding=ROUND_UP):
                break
            annual_tax += (D(upper) - lower) * rates[index]
            lower = D(upper)
        else:
            index = len(limits)
        threshold = (lower * n / divisor).quantize(D(".0001"), rounding=ROUND_DOWN)
        threshold_tax = (annual_tax * n / divisor).quantize(D(".0001"), rounding=ROUND_DOWN)
        liability = (threshold_tax + (rounded - threshold) * rates[index]).quantize(PENNY, rounding=ROUND_DOWN)
    cap = (money(cash_pay if cash_pay is not None else gross) / 2).quantize(PENNY, rounding=ROUND_DOWN)
    return min(liability - prior_tax, cap)


def national_insurance(gross, category, frequency):
    gross = money(gross)
    if category not in set("ABCDEFGH IJKLMNSVXZ".replace(" ", "")) - {"G"}:
        raise PayrollError("Unsupported NI category.")
    if category == "X":
        return D("0.00"), D("0.00")
    if frequency not in {"weekly", "monthly"}:
        raise PayrollError("Unsupported NI earnings period.")
    pt, st, uel, freeport = (map(D, (242, 96, 967, 481)) if frequency == "weekly" else map(D, (1048, 417, 4189, 2083)))
    main = D(".0185") if category in "BEI" else D(".02") if category in "DJLZ" else D(".08")
    employee = D(0) if category in "CKS" else max(D(0), min(gross, uel) - pt) * main + max(D(0), gross - uel) * D(".02")
    secondary = uel if category in "HMVZ" else freeport if category in "DEFIKLNS" else st
    employer = max(D(0), gross - secondary) * D(".15")
    # HMRC software method looks only at the third decimal: 6+ rounds up.
    def ni_round(value):
        return (value.quantize(D(".001"), rounding=ROUND_DOWN) + D(".004")).quantize(PENNY, rounding=ROUND_DOWN)
    return ni_round(employee), ni_round(employer)


def calculate(gross, profile, payment_date, previous_pay=0, previous_tax=0):
    gross = money(gross)
    frequency = profile["frequency"]
    period = tax_period(payment_date, frequency)
    if profile.get("tax_year") != YEAR:
        raise PayrollError("Review employee payroll settings for tax year 2026/27.")
    method = profile["pension_method"]
    if method not in {"none", "net_pay", "relief_at_source"}:
        raise PayrollError("Unsupported pension method. Salary sacrifice needs external review.")
    basis = profile["pension_basis"]
    if basis not in {"qualifying", "all"}:
        raise PayrollError("Choose qualifying earnings or all gross pay for pension contributions.")
    lower, upper = (D(120), D(967)) if frequency == "weekly" else (D(520), D(4189))
    earnings = max(D(0), min(gross, upper) - lower) if basis == "qualifying" else gross
    erate, rrate = money(profile["employee_pension_rate"]), money(profile["employer_pension_rate"])
    if max(erate, rrate) > 100:
        raise PayrollError("Pension rates must be between 0 and 100 percent.")
    pension_gross = money(earnings * erate / 100) if method != "none" else D("0.00")
    employee_pension = money(pension_gross * D(".8")) if method == "relief_at_source" else pension_gross
    employer_pension = money(earnings * rrate / 100) if method != "none" else D("0.00")
    taxable = gross - employee_pension if method == "net_pay" else gross
    tax = paye(taxable, profile["tax_code"], frequency, period, profile["tax_basis"], previous_pay, previous_tax, gross)
    employee_ni, employer_ni = national_insurance(gross, profile["ni_category"], frequency)
    deductions = tax + employee_ni + employee_pension
    net = gross - deductions
    if net < 0:
        raise PayrollError("Deductions exceed gross pay. Review the pension settings and payroll externally.")
    return dict(engine_version=VERSION, tax_year=YEAR, tax_period=period, taxable_pay=taxable,
                paye=tax, employee_ni=employee_ni, employer_ni=employer_ni,
                employee_pension=employee_pension, employer_pension=employer_pension,
                pension_tax_relief=pension_gross-employee_pension, deductions=deductions, net_pay=net,
                taxable_pay_ytd=money(previous_pay)+taxable, paye_ytd=money(previous_tax)+tax,
                employer_cost=gross+employer_ni+employer_pension)
