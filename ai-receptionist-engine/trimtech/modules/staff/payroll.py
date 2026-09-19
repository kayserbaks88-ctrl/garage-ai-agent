from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Iterable, Mapping



MONEY = Decimal("0.01")


class PayrollError(ValueError):
    """Raised when a payroll run cannot be safely generated or changed."""


@dataclass(frozen=True)
class ShiftPay:
    shift_id: int
    employee_id: int
    worked_minutes: int
    paid_break_minutes: int
    unpaid_break_minutes: int
    payable_minutes: int
    hourly_rate: Decimal
    gross_pay: Decimal
    deductions: Decimal = Decimal("0.00")
    net_pay: Decimal = Decimal("0.00")


def shift_is_eligible(
    shift: Mapping[str, Any],
    period_start: date,
    period_end: date,
    claimed_shift_ids: Iterable[int] = (),
) -> bool:
    """Express the payroll eligibility contract for validation and callers."""
    clock_in = shift.get("clock_in_at")
    clock_out = shift.get("clock_out_at")
    shift_id = int(shift.get("id") or 0)
    return bool(
        shift_id > 0
        and clock_in
        and clock_out
        and shift.get("approval_status") == "approved"
        and period_start <= clock_in.date() <= period_end
        and shift_id not in set(claimed_shift_ids)
    )


def _minutes(start: datetime, end: datetime) -> int:
    minutes = Decimal(str((end - start).total_seconds())) / Decimal("60")
    return max(0, int(minutes.quantize(Decimal("1"), rounding=ROUND_HALF_UP)))


def _clip_interval(start: datetime, end: datetime, lower: datetime, upper: datetime) -> tuple[datetime, datetime] | None:
    clipped_start = max(start, lower)
    clipped_end = min(end, upper)
    return (clipped_start, clipped_end) if clipped_end > clipped_start else None


def calculate_shift_pay(
    shift: Mapping[str, Any],
    breaks: Iterable[Mapping[str, Any]],
) -> ShiftPay:
    """Calculate Phase 1 gross pay from one completed, approved shift.

    The caller is responsible for enforcing the completed/approved eligibility
    query. Breaks are clipped to the shift so malformed or overlapping records
    cannot make payable minutes negative.
    """
    clock_in = shift["clock_in_at"]
    clock_out = shift.get("clock_out_at")
    if not clock_out or shift.get("approval_status") != "approved":
        raise PayrollError("Only completed and approved shifts can be paid.")
    if clock_out < clock_in:
        raise PayrollError("Shift clock-out cannot be before clock-in.")

    worked_minutes = _minutes(clock_in, clock_out)
    paid_break_minutes = 0
    unpaid_break_minutes = 0
    intervals: list[tuple[datetime, datetime, bool]] = []
    for break_record in breaks:
        started = break_record["started_at"]
        ended = break_record.get("ended_at") or clock_out
        clipped = _clip_interval(started, ended, clock_in, clock_out)
        if clipped:
            intervals.append((clipped[0], clipped[1], bool(break_record.get("paid"))))

    # Breaks should normally not overlap because the schema allows one open
    # break, but merge each category defensively before counting minutes.
    for paid in (True, False):
        merged: list[tuple[datetime, datetime]] = []
        for started, ended, is_paid in sorted(
            (item for item in intervals if item[2] is paid), key=lambda item: item[0]
        ):
            if merged and started <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], ended))
            else:
                merged.append((started, ended))
        minutes = sum(_minutes(started, ended) for started, ended in merged)
        if paid:
            paid_break_minutes = min(worked_minutes, minutes)
        else:
            unpaid_break_minutes = min(worked_minutes, minutes)

    unpaid_break_minutes = min(unpaid_break_minutes, worked_minutes)
    payable_minutes = max(0, worked_minutes - unpaid_break_minutes)
    hourly_rate = Decimal(str(shift.get("hourly_rate") or "0")).quantize(MONEY)
    gross_pay = (Decimal(payable_minutes) / Decimal("60") * hourly_rate).quantize(MONEY, rounding=ROUND_HALF_UP)
    deductions = Decimal("0.00")
    return ShiftPay(
        shift_id=int(shift["id"]),
        employee_id=int(shift["employee_id"]),
        worked_minutes=worked_minutes,
        paid_break_minutes=paid_break_minutes,
        unpaid_break_minutes=unpaid_break_minutes,
        payable_minutes=payable_minutes,
        hourly_rate=hourly_rate,
        gross_pay=gross_pay,
        deductions=deductions,
        net_pay=(gross_pay - deductions).quantize(MONEY, rounding=ROUND_HALF_UP),
    )


def period_dates(value: str, label: str) -> date:
    try:
        return date.fromisoformat(str(value or "").strip())
    except ValueError as error:
        raise PayrollError(f"Enter a valid payroll {label}.") from error


def period_end_exclusive(period_end: date) -> datetime:
    return datetime.combine(period_end + timedelta(days=1), datetime.min.time())


def generate_payroll_run(connection, business_id: str, period_start: date, period_end: date) -> dict[str, Any]:
    """Create one draft run and atomically claim its eligible shifts.

    The caller must provide an open transaction. The unique shift allocation
    table is the final duplicate-payment guard across all payroll periods.
    """
    if period_end < period_start:
        raise PayrollError("Payroll end date cannot be before the start date.")

    from psycopg2.extras import RealDictCursor

    with connection.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(
            """SELECT id FROM staff_payroll_runs
               WHERE business_id=%s AND period_start=%s AND period_end=%s
               FOR UPDATE""",
            (business_id, period_start, period_end),
        )
        if cursor.fetchone():
            raise PayrollError("A payroll run already exists for this period.")

        cursor.execute(
            """INSERT INTO staff_payroll_runs
               (business_id,period_start,period_end,status)
               VALUES (%s,%s,%s,'draft') RETURNING id""",
            (business_id, period_start, period_end),
        )
        run_id = int(cursor.fetchone()["id"])
        cursor.execute(
            """SELECT shift.id,shift.employee_id,shift.clock_in_at,shift.clock_out_at,
                      shift.approval_status,employee.hourly_rate
               FROM staff_shifts AS shift
               JOIN staff_employees AS employee
                 ON employee.id=shift.employee_id AND employee.business_id=shift.business_id
               WHERE shift.business_id=%s
                 AND shift.clock_out_at IS NOT NULL
                 AND shift.approval_status='approved'
                 AND (shift.clock_in_at AT TIME ZONE 'Europe/London')::date >= %s
                 AND (shift.clock_in_at AT TIME ZONE 'Europe/London')::date <= %s
                 AND NOT EXISTS (
                     SELECT 1 FROM staff_payslip_shifts AS claimed
                     WHERE claimed.shift_id=shift.id
                 )
               ORDER BY shift.employee_id,shift.clock_in_at,shift.id
               FOR UPDATE OF shift,employee""",
            (business_id, period_start, period_end),
        )
        shifts = [dict(row) for row in cursor.fetchall()]
        if not shifts:
            raise PayrollError("No completed and approved shifts are available for this period.")

        employee_totals: dict[int, dict[str, Any]] = {}
        for shift in shifts:
            cursor.execute(
                """SELECT id,started_at,ended_at,paid
                   FROM staff_breaks
                   WHERE business_id=%s AND shift_id=%s AND employee_id=%s
                   ORDER BY started_at,id""",
                (business_id, shift["id"], shift["employee_id"]),
            )
            result = calculate_shift_pay(shift, cursor.fetchall())
            totals = employee_totals.setdefault(
                result.employee_id,
                {
                    "worked_minutes": 0,
                    "paid_break_minutes": 0,
                    "unpaid_break_minutes": 0,
                    "payable_minutes": 0,
                    "gross_pay": Decimal("0.00"),
                    "deductions": Decimal("0.00"),
                    "net_pay": Decimal("0.00"),
                    "hourly_rate": result.hourly_rate,
                    "shift_ids": [],
                },
            )
            totals["worked_minutes"] += result.worked_minutes
            totals["paid_break_minutes"] += result.paid_break_minutes
            totals["unpaid_break_minutes"] += result.unpaid_break_minutes
            totals["payable_minutes"] += result.payable_minutes
            totals["gross_pay"] += result.gross_pay
            totals["net_pay"] += result.net_pay
            totals["shift_ids"].append(result.shift_id)

        total_gross = Decimal("0.00")
        total_deductions = Decimal("0.00")
        total_net = Decimal("0.00")
        for employee_id, totals in employee_totals.items():
            for key in ("gross_pay", "deductions", "net_pay"):
                totals[key] = totals[key].quantize(MONEY, rounding=ROUND_HALF_UP)
            totals["net_pay"] = (totals["gross_pay"] - totals["deductions"]).quantize(
                MONEY, rounding=ROUND_HALF_UP
            )
            cursor.execute(
                """INSERT INTO staff_payslips
                   (business_id,payroll_run_id,employee_id,worked_minutes,
                    paid_break_minutes,unpaid_break_minutes,payable_minutes,
                    hourly_rate,gross_pay,deductions,net_pay)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   RETURNING id""",
                (
                    business_id, run_id, employee_id, totals["worked_minutes"],
                    totals["paid_break_minutes"], totals["unpaid_break_minutes"],
                    totals["payable_minutes"], totals["hourly_rate"],
                    totals["gross_pay"], totals["deductions"], totals["net_pay"],
                ),
            )
            payslip_id = int(cursor.fetchone()["id"])
            for shift_id in totals["shift_ids"]:
                cursor.execute(
                    """INSERT INTO staff_payslip_shifts
                       (shift_id,payroll_run_id,payslip_id) VALUES (%s,%s,%s)""",
                    (shift_id, run_id, payslip_id),
                )
            total_gross += totals["gross_pay"]
            total_deductions += totals["deductions"]
            total_net += totals["net_pay"]

        cursor.execute(
            """UPDATE staff_payroll_runs
               SET total_gross_pay=%s,total_deductions=%s,total_net_pay=%s,updated_at=NOW()
               WHERE id=%s""",
            (total_gross, total_deductions, total_net, run_id),
        )
        return {
            "id": run_id,
            "business_id": business_id,
            "period_start": period_start,
            "period_end": period_end,
            "status": "draft",
            "total_gross_pay": total_gross,
            "total_deductions": total_deductions,
            "total_net_pay": total_net,
            "shift_count": len(shifts),
            "payslip_count": len(employee_totals),
        }
