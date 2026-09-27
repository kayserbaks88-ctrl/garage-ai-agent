"""Foreground shift-presence evidence, independent of attendance approval/payroll."""
import os
from datetime import datetime, timedelta, timezone

from psycopg2.extras import RealDictCursor
from trimtech.modules.staff.agency import coordinate
from trimtech.modules.staff.database import transaction
from trimtech.modules.staff.location import distance_metres


def settings():
    def bounded(name, default, low, high):
        try:
            return max(low, min(high, int(os.getenv(name, default))))
        except ValueError:
            return default
    return {"grace_seconds": bounded("STAFF_PRESENCE_GRACE_SECONDS", 60, 0, 3600),
            "confirmations": bounded("STAFF_PRESENCE_CONFIRMATIONS", 3, 2, 10),
            "stale_seconds": bounded("STAFF_PRESENCE_STALE_SECONDS", 120, 60, 3600)}


def utcnow():
    return datetime.now(timezone.utc)


def _event(cursor, state, now, reason, captured=None, distance=None, accuracy=None, effective=None):
    cursor.execute("""INSERT INTO staff_presence_events
        (shift_id,business_id,employee_id,status,captured_at,recorded_at,effective_at,distance_metres,accuracy_metres,reason)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", (state["shift_id"], state["business_id"],
        state["employee_id"], state["status"], captured, now, effective or now, distance, accuracy, reason))


def _ensure(cursor, shift, now):
    cursor.execute("SELECT * FROM staff_sites WHERE id=%s AND business_id=%s", (shift["site_id"], shift["business_id"]))
    site = cursor.fetchone() or {}
    def target(snapshot, live):
        return shift.get(snapshot) if shift.get(snapshot) is not None else site.get(live)
    cursor.execute("""INSERT INTO staff_shift_presence
        (shift_id,business_id,employee_id,site_latitude,site_longitude,radius_metres,updated_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (shift_id) DO NOTHING RETURNING shift_id""",
        (shift["id"], shift["business_id"], shift["employee_id"], target("site_latitude_snapshot", "latitude"),
         target("site_longitude_snapshot", "longitude"), target("site_radius_snapshot", "allowed_radius_metres"), now))
    created = bool(cursor.fetchone())
    cursor.execute("SELECT * FROM staff_shift_presence WHERE shift_id=%s FOR UPDATE", (shift["id"],))
    state = dict(cursor.fetchone())
    if created:
        _event(cursor, state, now, "awaiting_fresh_location")
    return state


def _expire(cursor, state, now, config):
    last = state["last_received_at"]
    if last and now - last >= timedelta(seconds=config["stale_seconds"]):
        changed = state["status"] != "location_stale"
        state.update(status="location_stale", outside_since=None, outside_count=0)
        cursor.execute("""UPDATE staff_shift_presence SET status='location_stale',outside_since=NULL,
            outside_count=0,updated_at=%s WHERE shift_id=%s""", (now, state["shift_id"]))
        if changed:
            _event(cursor, state, now, "updates_stopped", effective=last + timedelta(seconds=config["stale_seconds"]))


def advance(state, distance, accuracy, now, config):
    """Accuracy buffer + repeated samples AND elapsed grace prevent drift alarms."""
    result = dict(state)
    radius = float(state["radius_metres"])
    if distance <= radius:
        result.update(status="returned" if state["departed"] else
                      ("returned" if state["status"] == "returned" else "on_site"),
                      departed=False, outside_since=None, outside_count=0)
        reason = "inside_radius"
    elif distance - accuracy > radius:
        since = state["outside_since"] or now
        count = state["outside_count"] + 1
        result.update(outside_since=since, outside_count=count)
        reason = "outside_pending_confirmation"
        if count >= config["confirmations"] and (now - since).total_seconds() >= config["grace_seconds"]:
            result.update(status="left_site", departed=True)
            reason = "outside_confirmed"
    else:
        result.update(outside_since=None, outside_count=0)
        reason = "accuracy_overlaps_boundary"
    return result, reason


def record(cursor, business_id, employee_id, shift_id, values):
    now, config = utcnow(), settings()
    cursor.execute("""SELECT * FROM staff_shifts WHERE id=%s AND business_id=%s AND employee_id=%s
        AND clock_out_at IS NULL FOR UPDATE""", (shift_id, business_id, employee_id))
    shift = cursor.fetchone()
    if not shift:
        raise ValueError("This shift is no longer open or does not belong to you.")
    state = _ensure(cursor, shift, now)
    _expire(cursor, state, now, config)
    if any(state[key] is None for key in ("site_latitude", "site_longitude", "radius_metres")):
        raise ValueError("The shift has no verified site coordinates. Contact your manager.")
    try:
        latitude, longitude = float(coordinate(values.get("latitude"), 90)), float(coordinate(values.get("longitude"), 180))
        accuracy = float(coordinate(values.get("accuracy"), 10000))
    except ValueError:
        raise ValueError("Provide valid location coordinates and accuracy.") from None
    if not 0 < accuracy <= min(100, state["radius_metres"]):
        raise ValueError("Location accuracy is too low. Try again in an open area.")
    try:
        captured = datetime.fromisoformat(str(values.get("captured_at", "")).replace("Z", "+00:00"))
        if captured.tzinfo is None or not -10 <= (now - captured).total_seconds() <= 60:
            raise ValueError()
    except (ValueError, TypeError):
        raise ValueError("A fresh timestamped location is required.") from None
    if state["last_captured_at"] and captured <= state["last_captured_at"]:
        raise ValueError("This location sample has already been received or is out of order.")
    if state["last_received_at"] and (now - state["last_received_at"]).total_seconds() < 10:
        raise ValueError("Wait before sending another presence update.")
    distance = distance_metres(latitude, longitude, float(state["site_latitude"]), float(state["site_longitude"]))
    updated, reason = advance(state, distance, accuracy, now, config)
    cursor.execute("""UPDATE staff_shift_presence SET status=%s,last_captured_at=%s,last_received_at=%s,
        outside_since=%s,outside_count=%s,departed=%s,updated_at=%s WHERE shift_id=%s""",
        (updated["status"], captured, now, updated["outside_since"], updated["outside_count"], updated["departed"], now, shift_id))
    _event(cursor, updated, now, reason, captured, round(distance, 2), accuracy)
    return {"status": updated["status"], "last_received_at": now.isoformat(), "stale_seconds": config["stale_seconds"]}


def overview(business_id):
    """Materialize stale transitions when the dashboard polls; no background tracker."""
    now, config = utcnow(), settings()
    with transaction() as connection:
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("SELECT * FROM staff_shifts WHERE business_id=%s AND clock_out_at IS NULL ORDER BY id FOR UPDATE", (business_id,))
            shifts = cursor.fetchall()
            result = {}
            for shift in shifts:
                state = _ensure(cursor, shift, now)
                _expire(cursor, state, now, config)
                result[shift["id"]] = {"status": state["status"],
                    "last_received_at": state["last_received_at"].isoformat() if state["last_received_at"] else None,
                    "outside_count": state["outside_count"], "stale_seconds": config["stale_seconds"]}
            return result
