"""Read-only attendance evidence. Never changes shifts, approvals or pay."""
import math
import os

from trimtech.modules.staff.database import fetch_all


def grace_minutes():
    try:
        return max(0, min(120, int(os.getenv("STAFF_LATE_GRACE_MINUTES", "5"))))
    except ValueError:
        return 5


def late_minutes(clocked_at, scheduled_at):
    if scheduled_at is None:
        return None
    seconds = (clocked_at - scheduled_at).total_seconds()
    return math.ceil(seconds / 60) if seconds > grace_minutes() * 60 else None


def timeline(shift, events):
    """Collapse repeated GPS samples; unavailable evidence is never a departure."""
    items = []
    def add(at, label):
        items.append({"at": at, "label": label})
    if shift.get("scheduled_at"):
        add(shift["scheduled_at"], "Scheduled")
    late = shift.get("late_minutes")
    add(shift["clock_in_at"], "Clocked in" + (f" ({late} min late)" if late else ""))
    departed = False
    unavailable = False
    for event in events:
        # Historical status may be retained on uncertain/pending samples.
        # Only affirmative evidence proves departure or return.
        if event["reason"] == "outside_confirmed":
            if not departed:
                add(event["effective_at"], "Left site")
            departed, unavailable = True, False
        elif event["reason"] == "inside_radius":
            if departed:
                add(event["effective_at"], "Returned")
            elif unavailable:
                add(event["effective_at"], "On site confirmed")
            departed, unavailable = False, False
        elif event["reason"] == "updates_stopped" and not unavailable:
            add(event["effective_at"], "Location unavailable/stale")
            unavailable = True
    if shift["clock_out_at"]:
        add(shift["clock_out_at"], "Clocked out")
    return sorted(items, key=lambda item: item["at"])


def enrich(business_id, shifts):
    """Scope all evidence to the business and shifts already selected for review."""
    ids = list({shift["id"] for shift in shifts})
    if not ids:
        return
    rows = fetch_all("""SELECT sh.*,
        CASE WHEN COUNT(a.id)=1 THEN MIN(a.id) END AS matched_assignment_id,
        COALESCE(sh.planned_start_at,
          CASE WHEN COUNT(a.id)=1 THEN MIN(a.starts_at) END) AS scheduled_at
        FROM staff_shifts sh
        LEFT JOIN staff_assignments a ON a.business_id=sh.business_id
          AND a.employee_id=sh.employee_id AND a.site_id=sh.site_id
          AND (a.id=sh.assignment_id OR
            (sh.assignment_id IS NULL AND a.status='scheduled'
             AND COALESCE((SELECT organisation_mode FROM staff_settings st
                 WHERE st.business_id=sh.business_id),'fixed')='fixed'
             AND sh.clock_in_at<a.ends_at
             AND COALESCE(sh.clock_out_at,NOW())>a.starts_at))
        WHERE sh.business_id=%s AND sh.id=ANY(%s)
        GROUP BY sh.id""", (business_id, ids))
    events = fetch_all("""SELECT ev.* FROM staff_presence_events ev
        JOIN staff_shifts sh ON sh.id=ev.shift_id AND sh.business_id=ev.business_id
          AND sh.employee_id=ev.employee_id
        WHERE ev.business_id=%s AND ev.shift_id=ANY(%s)
        ORDER BY ev.shift_id,ev.id""", (business_id, ids))
    by_shift = {shift_id: [] for shift_id in ids}
    for event in events:
        by_shift[event["shift_id"]].append(event)
    evidence = {}
    for row in rows:
        row["late_minutes"] = late_minutes(row["clock_in_at"], row["scheduled_at"])
        # Retain existing review keys for fixed shifts matched to an assignment.
        identity = (f"assignment:{row['matched_assignment_id']}"
                    if row['assignment_id'] is None and row['planned_start_at'] is None
                    and row['matched_assignment_id'] is not None else f"shift:{row['id']}")
        evidence[row["id"]] = {"scheduled_at": row["scheduled_at"],
                               "late_minutes": row["late_minutes"],
                               "late_event_key": f"{identity}:late:{row['clock_in_at'].isoformat()}",
                               "timeline": timeline(row, by_shift[row["id"]])}
    for shift in shifts:
        shift.update(evidence.get(shift["id"], {}))
