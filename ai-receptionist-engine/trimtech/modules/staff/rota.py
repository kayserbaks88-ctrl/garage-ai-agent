"""Read-only weekly employee rota built from the existing assignments."""
from datetime import date, datetime, time, timedelta

from trimtech.modules.staff.database import fetch_all
from trimtech.modules.staff.payroll import UK_TIMEZONE


def weekly(business_id, employee_id, selected=None):
    today = datetime.now(UK_TIMEZONE).date()
    anchor = date.fromisoformat(selected) if selected else today
    monday = anchor - timedelta(days=anchor.weekday())
    previous, following = monday - timedelta(days=7), monday + timedelta(days=7)
    boundary = lambda day: datetime.combine(day, time.min, tzinfo=UK_TIMEZONE)
    jobs = fetch_all("""SELECT a.id,a.starts_at,a.ends_at,a.status,s.name AS site_name
        FROM staff_assignments a JOIN staff_sites s ON s.id=a.site_id AND s.business_id=a.business_id
        WHERE a.business_id=%s AND a.employee_id=%s AND a.starts_at<%s AND a.ends_at>%s
        ORDER BY a.starts_at,a.id""", (business_id,employee_id,boundary(following),boundary(monday)))
    days = []
    for offset in range(7):
        day = monday + timedelta(days=offset)
        entries = []
        for job in jobs:
            if job['starts_at'] < boundary(day+timedelta(days=1)) and job['ends_at'] > boundary(day):
                entries.append({**job, 'continues': job['starts_at'].astimezone(UK_TIMEZONE).date() < day})
        days.append({'date': day, 'jobs': entries, 'today': day == today})
    return {'start': monday, 'end': monday+timedelta(days=6), 'previous': previous,
            'following': following, 'days': days}
