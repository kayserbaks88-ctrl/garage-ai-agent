"""Manager exceptions derived from recorded schedules, shifts and GPS evidence.

No inference of a fixed worker's expected start when no schedule exists.
Location unavailable is a review alert, never proof of absence or a pay deduction.
"""
from trimtech.modules.staff import attendance
from datetime import datetime, timedelta, timezone
from trimtech.modules.staff.database import fetch_all
from trimtech.modules.staff.payroll import UK_TIMEZONE


def collect(business_id, current_presence=None, now=None):
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(days=14)
    events = []
    def add(key, kind, name, site, at, detail):
        events.append(dict(event_key=key,kind=kind,full_name=name,site_name=site,at=at,detail=detail))
    assignments = fetch_all("""SELECT a.*,e.full_name,e.status AS employee_status,s.name,s.active,
        EXISTS(SELECT 1 FROM staff_shifts sh WHERE sh.business_id=a.business_id AND sh.assignment_id=a.id) AS linked_shift,
        (SELECT MIN(sh.clock_in_at) FROM staff_shifts sh WHERE sh.business_id=a.business_id AND sh.employee_id=a.employee_id
            AND (sh.assignment_id=a.id OR (sh.assignment_id IS NULL AND sh.site_id=a.site_id
                AND COALESCE((SELECT organisation_mode FROM staff_settings st WHERE st.business_id=a.business_id),'fixed')='fixed'
                AND sh.clock_in_at<a.ends_at AND COALESCE(sh.clock_out_at,%s)>a.starts_at))) AS clocked_at,
        EXISTS(SELECT 1 FROM staff_leave_requests l WHERE l.business_id=a.business_id AND l.employee_id=a.employee_id
            AND l.approval_status='approved' AND l.start_date<=(a.starts_at AT TIME ZONE 'Europe/London')::date
            AND l.end_date>=(a.starts_at AT TIME ZONE 'Europe/London')::date) AS on_leave
        FROM staff_assignments a JOIN staff_employees e ON e.id=a.employee_id AND e.business_id=a.business_id
        JOIN staff_sites s ON s.id=a.site_id AND s.business_id=a.business_id
        WHERE a.business_id=%s AND a.status='scheduled' AND a.starts_at>=%s AND a.starts_at<=%s""",
        (now,business_id,since,now+timedelta(days=1)))
    for a in assignments:
        if a['employee_status'] != 'active':
            continue
        if a['on_leave']:
            add(f"assignment:{a['id']}:leave",'Assignment / approved leave conflict',a['full_name'],a['name'],a['starts_at'],
                'Review the assignment against approved leave; no absence has been assumed.')
        elif not a['active']:
            add(f"assignment:{a['id']}:inactive",'Assigned site inactive',a['full_name'],a['name'],a['starts_at'],
                'The assigned site is inactive. Review before the employee attempts to clock in.')
        elif not a['clocked_at'] and now >= a['starts_at']+timedelta(minutes=15):
            add(f"assignment:{a['id']}:missed",'Missed clock-in',a['full_name'],a['name'],a['starts_at'],
                'No clock-in recorded for this assignment 15 minutes after its scheduled start. Check with the employee.')
    shifts = fetch_all("""SELECT sh.*,e.full_name FROM staff_shifts sh JOIN staff_employees e
        ON e.id=sh.employee_id AND e.business_id=sh.business_id
        WHERE sh.business_id=%s AND (sh.clock_in_at>=%s OR sh.clock_out_at IS NULL) ORDER BY sh.clock_in_at DESC""",(business_id,since))
    attendance.enrich(business_id, shifts)
    for s in shifts:
        if s['late_minutes']:
            add(s['late_event_key'],'Late clock-in',s['full_name'],s['site_name'],s['clock_in_at'],
                f"Late by {s['late_minutes']} minutes ({attendance.grace_minutes()}-minute grace). Manager review only; pay is unchanged.")
        if s['clock_out_at'] is None:
            end = s['planned_end_at'] or s['clock_in_at']+timedelta(hours=16)
            if now > end+timedelta(minutes=30):
                add(f"shift:{s['id']}:open",'Missed clock-out / long open shift',s['full_name'],s['site_name'],end,
                    'Still open 30 minutes after the planned end, or after 16 hours when no planned end exists.')
            state = (current_presence or {}).get(s['id'],{})
            if state.get('status') in {'left_site','location_stale'}:
                last = fetch_all("SELECT id,effective_at FROM staff_presence_events WHERE business_id=%s AND shift_id=%s ORDER BY id DESC LIMIT 1",(business_id,s['id']))
                event_id = last[0]['id'] if last else 0
                at = last[0]['effective_at'] if last else s['clock_in_at']
                add(f"shift:{s['id']}:presence:{event_id}",'Left site' if state['status']=='left_site' else 'Location unavailable',
                    s['full_name'],s['site_name'],at,'Review recorded location evidence. This alert does not establish absence or alter pay.')
    reviews = {r['event_key']:r for r in fetch_all("SELECT * FROM staff_attendance_reviews WHERE business_id=%s",(business_id,))}
    owners = {f"assignment:{a['id']}": a['employee_id'] for a in assignments}
    owners.update({f"shift:{s['id']}": s['employee_id'] for s in shifts})
    for event in events:
        event['employee_id'] = owners.get(':'.join(event['event_key'].split(':')[:2]))
        event['review'] = reviews.get(event['event_key'])
        event['display_time'] = event['at'].astimezone(UK_TIMEZONE).strftime('%d %b %Y %H:%M %Z')
    return sorted(events,key=lambda e:(bool(e['review']),-e['at'].timestamp(),e['event_key']))
