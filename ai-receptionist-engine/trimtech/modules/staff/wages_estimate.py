"""Read-only attendance estimates, never payroll runs, payslips or net pay."""
from decimal import Decimal, ROUND_HALF_UP
from trimtech.modules.staff.database import fetch_one, fetch_all
from trimtech.modules.staff.payroll import calculate_shift_pay

def approved_weekly(business_id, as_of=None):
    # Reuse the payroll calculator: round each shift/merged break interval to
    # whole minutes, then each shift's gross to pennies. Never update payslips.
    shifts=fetch_all("""WITH period AS (SELECT COALESCE(%s::timestamptz,NOW()) AS ends), bounds AS (
        SELECT ends,DATE_TRUNC('week',ends AT TIME ZONE 'Europe/London') AT TIME ZONE 'Europe/London' AS begins FROM period)
        SELECT s.id,s.employee_id,s.approval_status,e.hourly_rate,
            GREATEST(s.clock_in_at,p.begins) AS clock_in_at,LEAST(s.clock_out_at,p.ends) AS clock_out_at
        FROM staff_shifts s JOIN staff_employees e ON e.id=s.employee_id AND e.business_id=s.business_id
        CROSS JOIN bounds p WHERE s.business_id=%s AND s.approval_status='approved'
        AND s.clock_out_at IS NOT NULL AND s.clock_in_at<p.ends AND s.clock_out_at>p.begins
        ORDER BY s.id""",(as_of,business_id))
    by_shift={s['id']:[] for s in shifts}
    if shifts:
        for br in fetch_all("""SELECT b.shift_id,b.started_at,b.ended_at,b.paid FROM staff_breaks b
            JOIN staff_shifts s ON s.id=b.shift_id AND s.business_id=b.business_id AND s.employee_id=b.employee_id
            WHERE b.business_id=%s AND b.shift_id=ANY(%s) ORDER BY b.shift_id,b.started_at,b.id""",(business_id,list(by_shift))):
            by_shift[br['shift_id']].append(br)
    calculated=[calculate_shift_pay(s,by_shift[s['id']]) for s in shifts]
    money=Decimal('0.01')
    return dict(hours=(Decimal(sum(s.worked_minutes for s in calculated))/60).quantize(money,rounding=ROUND_HALF_UP),
                unpaid_break_hours=(Decimal(sum(s.unpaid_break_minutes for s in calculated))/60).quantize(money,rounding=ROUND_HALF_UP),
                estimated_gross=sum((s.gross_pay for s in calculated),Decimal('0.00')))

def weekly(business_id, *, as_of=None, approved_only=False):
    if approved_only:
        return approved_weekly(business_id,as_of)
    # Clip overnight/open shifts and unpaid breaks to the current UK week.
    # Recorded break treatment is preserved when the company policy changes.
    return fetch_one("""WITH clock AS (SELECT COALESCE(%s::timestamptz,NOW()) AS as_of), period AS (
      SELECT as_of, DATE_TRUNC('week',as_of AT TIME ZONE 'Europe/London') AT TIME ZONE 'Europe/London' AS begins FROM clock
    ), clipped AS (
      SELECT s.id,s.business_id,s.employee_id,e.hourly_rate,GREATEST(s.clock_in_at,p.begins) AS begins,
        LEAST(COALESCE(s.clock_out_at,p.as_of),p.as_of) AS ends
      FROM staff_shifts s JOIN staff_employees e ON e.id=s.employee_id AND e.business_id=s.business_id
      CROSS JOIN period p WHERE s.business_id=%s AND s.approval_status<>'rejected'
        AND (NOT %s OR (s.approval_status='approved' AND s.clock_out_at IS NOT NULL))
        AND s.clock_in_at<p.as_of AND COALESCE(s.clock_out_at,p.as_of)>p.begins
    ), amounts AS (
      SELECT c.hourly_rate,GREATEST(0,EXTRACT(EPOCH FROM(c.ends-c.begins))) AS elapsed,
        LEAST(GREATEST(0,EXTRACT(EPOCH FROM(c.ends-c.begins))),COALESCE((
          SELECT SUM(GREATEST(0,EXTRACT(EPOCH FROM(LEAST(COALESCE(b.ended_at,c.ends),c.ends)-GREATEST(b.started_at,c.begins)))))
          FROM staff_breaks b WHERE b.business_id=c.business_id AND b.employee_id=c.employee_id
            AND b.shift_id=c.id AND NOT b.paid),0)) AS unpaid FROM clipped c
    ) SELECT ROUND(COALESCE(SUM(elapsed),0)/3600,2) AS hours,
      ROUND(COALESCE(SUM(unpaid),0)/3600,2) AS unpaid_break_hours,
      ROUND(COALESCE(SUM((elapsed-unpaid)*hourly_rate),0)/3600,2) AS estimated_gross
      FROM amounts""",(as_of,business_id,approved_only))
