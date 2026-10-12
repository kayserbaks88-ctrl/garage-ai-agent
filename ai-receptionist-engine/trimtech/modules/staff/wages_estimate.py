"""Read-only attendance estimates, never payroll runs, payslips or net pay."""
from trimtech.modules.staff.database import fetch_one

def weekly(business_id, *, as_of=None, approved_only=False):
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
