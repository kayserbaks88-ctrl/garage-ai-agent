"""Agency assignments, consented estimates and audited corrections.

Callers authorize the actor and supply a transaction. Business advisory locks
serialize assignment, mode, clocking and payroll mutations across workers.
Travel is an estimate only; nothing in this module adds mileage to payroll.
"""
from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from psycopg2.extras import Json

from trimtech.modules.staff.database import fetch_all, fetch_one
from trimtech.modules.staff.location import distance_miles as _haversine_miles
from trimtech.modules.staff.payroll import UK_TIMEZONE, parse_shift_datetime


def lock_business(cursor, business_id):
    cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 73194))", (business_id,))


def settings(business_id):
    return fetch_one("SELECT * FROM staff_settings WHERE business_id=%s", (business_id,)) or {
        "organisation_mode": "fixed", "travel_enabled": False,
    }


def locked_settings(cursor, business_id):
    lock_business(cursor, business_id)
    cursor.execute("INSERT INTO staff_settings (business_id) VALUES (%s) ON CONFLICT DO NOTHING", (business_id,))
    cursor.execute("SELECT * FROM staff_settings WHERE business_id=%s FOR UPDATE", (business_id,))
    return cursor.fetchone()


def audit(cursor, business_id, actor, action, entity_type, entity_id, old, new, reason):
    if not str(reason or "").strip():
        raise ValueError("A reason is required for this change.")
    encode = lambda value: Json(value, dumps=lambda data: json.dumps(data, default=str))
    cursor.execute("""INSERT INTO staff_audit
        (business_id,actor,action,entity_type,entity_id,old_values,new_values,reason)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
        (business_id, actor, action, entity_type, entity_id, encode(old), encode(new), reason))


def change_mode(cursor, business_id, actor, mode, travel_enabled, reason):
    if mode not in {"fixed", "agency"}:
        raise ValueError("Select fixed workplace or agency.")
    old = dict(locked_settings(cursor, business_id))
    cursor.execute("SELECT id FROM staff_shifts WHERE business_id=%s AND clock_out_at IS NULL", (business_id,))
    if mode != old["organisation_mode"] and cursor.fetchone():
        raise ValueError("Close all open shifts before changing organisation mode.")
    cursor.execute("UPDATE staff_settings SET organisation_mode=%s,travel_enabled=%s,updated_at=NOW() WHERE business_id=%s",
                   (mode, travel_enabled, business_id))
    audit(cursor, business_id, actor, "settings_changed", "settings", None, old,
          {"organisation_mode": mode, "travel_enabled": travel_enabled}, reason)


def save_assignment(cursor, business_id, actor, values, assignment_id=None, cancel=False):
    lock_business(cursor, business_id)
    old = None
    if assignment_id:
        cursor.execute("SELECT * FROM staff_assignments WHERE id=%s AND business_id=%s FOR UPDATE",
                       (assignment_id, business_id))
        old = cursor.fetchone()
        if not old:
            raise ValueError("That assignment could not be found.")
    reason = str(values.get("reason") or "").strip()[:1000]
    if not reason:
        raise ValueError("Enter a reason for the assignment change.")
    if cancel:
        cursor.execute("UPDATE staff_assignments SET status='cancelled',updated_at=NOW() WHERE id=%s AND business_id=%s",
                       (assignment_id, business_id))
        audit(cursor, business_id, actor, "assignment_cancelled", "assignment", assignment_id,
              dict(old), {"status": "cancelled"}, reason)
        return assignment_id
    try:
        employee_id, site_id = int(values.get("employee_id", "")), int(values.get("site_id", ""))
    except (TypeError, ValueError) as error:
        raise ValueError("Select an employee and work site.") from error
    starts = parse_shift_datetime(values.get("starts_at"), "assignment start")
    ends = parse_shift_datetime(values.get("ends_at"), "assignment end")
    if ends.astimezone(timezone.utc) <= starts.astimezone(timezone.utc):
        raise ValueError("Assignment end must be after its start.")
    cursor.execute("SELECT id FROM staff_employees WHERE id=%s AND business_id=%s AND status='active' FOR UPDATE",
                   (employee_id, business_id))
    if not cursor.fetchone():
        raise ValueError("Select an active employee from this business.")
    cursor.execute("SELECT * FROM staff_sites WHERE id=%s AND business_id=%s AND active FOR SHARE", (site_id, business_id))
    site = cursor.fetchone()
    if not site or site["latitude"] is None or site["longitude"] is None or not site["address"]:
        raise ValueError("The assigned site needs an address and verified coordinates.")
    cursor.execute("""SELECT id FROM staff_assignments WHERE business_id=%s AND employee_id=%s
        AND status='scheduled' AND starts_at<%s AND ends_at>%s AND id<>%s""",
        (business_id, employee_id, ends, starts, assignment_id or 0))
    if cursor.fetchone():
        raise ValueError("This employee already has an overlapping assignment.")
    override = reason if values.get("override") == "on" else None
    if assignment_id:
        cursor.execute("""UPDATE staff_assignments SET employee_id=%s,site_id=%s,starts_at=%s,ends_at=%s,
            status='scheduled',override_reason=%s,updated_at=NOW() WHERE id=%s AND business_id=%s""",
            (employee_id, site_id, starts, ends, override, assignment_id, business_id))
    else:
        cursor.execute("""INSERT INTO staff_assignments
            (business_id,employee_id,site_id,starts_at,ends_at,created_by,override_reason)
            VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            (business_id, employee_id, site_id, starts, ends, actor, override))
        assignment_id = cursor.fetchone()["id"]
    audit(cursor, business_id, actor, "assignment_override" if override else "assignment_saved",
          "assignment", assignment_id, dict(old) if old else None,
          {"employee_id": employee_id, "site_id": site_id, "starts_at": starts, "ends_at": ends}, reason)
    return assignment_id


def resolve_assignment(cursor, business_id, employee_id, assignment_id):
    """Use server time; half-open windows permit consecutive jobs and overnight work."""
    cursor.execute("""SELECT a.* FROM staff_assignments a
        JOIN staff_employees e ON e.id=a.employee_id AND e.business_id=a.business_id
        JOIN staff_sites s ON s.id=a.site_id AND s.business_id=a.business_id
        WHERE a.id=%s AND a.business_id=%s AND a.employee_id=%s
          AND a.status='scheduled' AND e.status='active' AND s.active
          AND a.starts_at<=clock_timestamp() AND a.ends_at>clock_timestamp()
          AND (a.starts_at AT TIME ZONE 'Europe/London')::date <=
              (clock_timestamp() AT TIME ZONE 'Europe/London')::date
          AND (a.ends_at AT TIME ZONE 'Europe/London')::date >=
              (clock_timestamp() AT TIME ZONE 'Europe/London')::date
        FOR UPDATE OF a""", (assignment_id, business_id, employee_id))
    assignment = cursor.fetchone()
    if not assignment:
        raise ValueError("No eligible assignment for this time. Contact your manager for an assignment or an audited override.")
    return assignment


def _cipher():
    # Separate from the session secret. Never fall back to plaintext storage.
    from cryptography.fernet import Fernet
    try:
        return Fernet(os.environ.get("STAFF_TRAVEL_KEY", "").encode())
    except (ValueError, TypeError) as error:
        raise ValueError("Travel origin storage is unavailable. Ask your manager to configure its encryption key.") from error


def decrypt_origin(token):
    from cryptography.fernet import InvalidToken
    try:
        return json.loads(_cipher().decrypt(token.encode()))
    except (InvalidToken, ValueError, TypeError):
        return None


def coordinate(value, limit):
    try:
        result = Decimal(str(value))
        if not result.is_finite() or not -limit <= result <= limit:
            raise ValueError()
        return result.quantize(Decimal("0.0000001"))
    except (ValueError, InvalidOperation):
        raise ValueError("Enter valid travel-origin coordinates.") from None


def save_origin(cursor, business_id, employee_id, values):
    lock_business(cursor, business_id)
    cursor.execute("SELECT id FROM staff_employees WHERE id=%s AND business_id=%s AND status='active' FOR UPDATE",
                   (employee_id, business_id))
    if not cursor.fetchone():
        raise ValueError("That active employee could not be found.")
    if values.get("disable") == "on":
        cursor.execute("""UPDATE staff_travel_origins SET encrypted_origin=NULL,disabled_at=NOW(),updated_at=NOW()
            WHERE business_id=%s AND employee_id=%s""", (business_id, employee_id))
        action = "origin_disabled"
    else:
        if values.get("consent") != "on":
            raise ValueError("Consent is required to save a travel origin.")
        lat, lon = values.get("origin_latitude", "").strip(), values.get("origin_longitude", "").strip()
        if bool(lat) != bool(lon):
            raise ValueError("Supply both origin coordinates or leave both blank.")
        address = str(values.get("origin_address") or "").strip()[:1000]
        if not address and not lat:
            raise ValueError("Enter an origin address/postcode or verified coordinates.")
        approximate = values.get("approximate") == "on"
        if lat and values.get("coordinates_verified") != "on":
            raise ValueError("Confirm that the origin coordinates have been checked.")
        origin = {"address": address, "latitude": str(coordinate(lat, 90)) if lat else None,
                  "longitude": str(coordinate(lon, 180)) if lon else None, "approximate": approximate}
        token = _cipher().encrypt(json.dumps(origin).encode()).decode()
        cursor.execute("""INSERT INTO staff_travel_origins (business_id,employee_id,encrypted_origin,consented_at)
            VALUES (%s,%s,%s,NOW()) ON CONFLICT (business_id,employee_id) DO UPDATE
            SET encrypted_origin=EXCLUDED.encrypted_origin,consented_at=NOW(),updated_at=NOW(),disabled_at=NULL""",
            (business_id, employee_id, token))
        action = "origin_consented"
    audit(cursor, business_id, f"employee:{employee_id}", action, "employee", employee_id,
          None, {"enabled": action == "origin_consented"}, "Employee travel-origin preference")


def origin_for_employee(business_id, employee_id):
    row = fetch_one("SELECT * FROM staff_travel_origins WHERE business_id=%s AND employee_id=%s",
                    (business_id, employee_id))
    if not row or row["disabled_at"] or not row["encrypted_origin"]:
        return None
    result = decrypt_origin(row["encrypted_origin"])
    if result:
        result["consented_at"] = row["consented_at"]
    return result


def distance_km(origin, site):
    if not origin or any(origin.get(k) is None or site.get(k) is None for k in ("latitude", "longitude")):
        return None
    lat1, lon1, lat2, lon2 = map(math.radians, map(float, (
        origin["latitude"], origin["longitude"], site["latitude"], site["longitude"])))
    hav = math.sin((lat2-lat1)/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
    return Decimal(str(6371 * 2 * math.asin(math.sqrt(min(1, max(0, hav)))))).quantize(Decimal("0.01"))


def distance_miles(origin, site):
    """Employee-facing guidance figure only; payroll and manager views stay in distance_km."""
    if not origin or any(origin.get(k) is None or site.get(k) is None for k in ("latitude", "longitude")):
        return None
    miles = _haversine_miles(float(origin["latitude"]), float(origin["longitude"]),
                             float(site["latitude"]), float(site["longitude"]))
    return Decimal(str(miles)).quantize(Decimal("0.1"))


def snapshot_shift(cursor, business_id, employee_id, shift_id, site, assignment, config, evidence):
    cursor.execute("""UPDATE staff_shifts SET assignment_id=%s,assigned_site_name=%s,assigned_site_address=%s,
        planned_start_at=%s,planned_end_at=%s,site_latitude_snapshot=%s,site_longitude_snapshot=%s,
        site_radius_snapshot=%s,clock_in_accuracy=%s,clock_in_captured_at=%s,clock_in_verification='within_radius'
        WHERE id=%s AND business_id=%s AND employee_id=%s""",
        ((assignment or {}).get("id"), site["name"], site.get("address"),
         (assignment or {}).get("starts_at"), (assignment or {}).get("ends_at"), site["latitude"],
         site["longitude"], site["allowed_radius_metres"], evidence[0], evidence[1], shift_id, business_id, employee_id))
    if config["organisation_mode"] != "agency" and not config["travel_enabled"]:
        return
    cursor.execute("""SELECT encrypted_origin FROM staff_travel_origins
        WHERE business_id=%s AND employee_id=%s AND disabled_at IS NULL""", (business_id, employee_id))
    row = cursor.fetchone()
    token = row["encrypted_origin"] if row else None
    origin = decrypt_origin(token) if token else None
    cursor.execute("""INSERT INTO staff_shift_travel
        (shift_id,business_id,encrypted_origin_snapshot,site_latitude,site_longitude,distance_km)
        VALUES (%s,%s,%s,%s,%s,%s)""",
        (shift_id, business_id, token, site["latitude"], site["longitude"], distance_km(origin, site)))


def gps_evidence(values, required=False):
    """Browser timestamp is untrusted evidence; require freshness on agency clocks."""
    raw = str(values.get("captured_at") or "").strip()
    now = datetime.now(timezone.utc)
    if not raw and required:
        raise ValueError("Capture a fresh GPS reading before clocking.")
    try:
        captured = datetime.fromisoformat(raw.replace("Z", "+00:00")) if raw else now
        if captured.tzinfo is None or not -30 <= (now-captured).total_seconds() <= 120:
            raise ValueError()
        accuracy = Decimal(str(values.get("accuracy")))
        if not accuracy.is_finite() or accuracy < 0:
            raise ValueError()
    except (ValueError, TypeError, InvalidOperation):
        raise ValueError("Capture a fresh, accurate GPS reading and try again.") from None
    return accuracy, captured


def upcoming_assignments(business_id, employee_id):
    origin = origin_for_employee(business_id, employee_id)
    rows = fetch_all("""SELECT a.*,s.name,s.address,s.latitude,s.longitude,s.photo_required,
        (a.starts_at<=NOW() AND a.ends_at>NOW()) AS eligible
        FROM staff_assignments a JOIN staff_sites s ON s.id=a.site_id AND s.business_id=a.business_id
        WHERE a.business_id=%s AND a.employee_id=%s AND a.status='scheduled' AND s.active
          AND a.ends_at>NOW() ORDER BY a.starts_at LIMIT 100""", (business_id, employee_id))
    for row in rows:
        row["distance_km"] = distance_km(origin, row)
        row["distance_miles"] = distance_miles(origin, row)
        row["approximate_origin"] = bool(origin and origin.get("approximate"))
    return rows


def correct_shift(cursor, business_id, actor, shift, values, edited_breaks):
    """Preserve GPS/assignment snapshots; finalized runs get an adjustment request."""
    reason = str(values.get("adjustment_reason") or "").strip()[:1000]
    if not reason:
        raise ValueError("Enter a reason for the correction.")
    try:
        site_id = int(values.get("site_id") or shift["site_id"])
    except (ValueError, TypeError):
        raise ValueError("Select a valid work site.") from None
    cursor.execute("SELECT id,name FROM staff_sites WHERE id=%s AND business_id=%s FOR SHARE", (site_id, business_id))
    site = cursor.fetchone()
    if not site:
        raise ValueError("Select a site from this business.")
    raw_distance = str(values.get("manager_distance_km") or "").strip()
    distance = None
    if raw_distance:
        try:
            distance = Decimal(raw_distance)
            if not distance.is_finite() or not 0 <= distance < 1000000:
                raise ValueError()
            distance = distance.quantize(Decimal("0.01"))
        except (ValueError, InvalidOperation):
            raise ValueError("Enter a valid nonnegative travel estimate.") from None
    new = {"clock_in_at": values["clock_in_at"], "clock_out_at": values["clock_out_at"],
           "site_id": site_id, "site_name": site["name"], "breaks": edited_breaks,
           "manager_distance_km": distance}
    cursor.execute("SELECT * FROM staff_shift_travel WHERE shift_id=%s AND business_id=%s FOR UPDATE",
                   (shift["id"], business_id))
    travel = cursor.fetchone()
    if distance is not None and (not travel or travel["distance_km"] is None):
        raise ValueError("Travel distance is unavailable without an origin and site snapshot.")
    cursor.execute("""SELECT r.* FROM staff_payroll_runs r JOIN staff_payslip_shifts p ON p.payroll_run_id=r.id
        WHERE p.shift_id=%s AND r.business_id=%s FOR UPDATE OF r""", (shift["id"], business_id))
    run = cursor.fetchone()
    if run and run["status"] != "draft":
        cursor.execute("""INSERT INTO staff_payroll_adjustments
            (business_id,shift_id,payroll_run_id,requested_by,proposed_values,reason)
            VALUES (%s,%s,%s,%s,%s,%s) RETURNING id""",
            (business_id, shift["id"], run["id"], actor, Json(new, dumps=lambda x: json.dumps(x, default=str)), reason))
        audit(cursor, business_id, actor, "payroll_adjustment_requested", "shift", shift["id"], dict(shift), new, reason)
        return "Finalized payroll preserved. An adjustment request is awaiting payroll review."
    cursor.execute("SELECT id,started_at,ended_at,paid FROM staff_breaks WHERE shift_id=%s AND business_id=%s ORDER BY id",
                   (shift["id"], business_id))
    old = {"shift": dict(shift), "breaks": [dict(x) for x in cursor.fetchall()],
           "travel": {k: v for k, v in dict(travel or {}).items() if k != "encrypted_origin_snapshot"}}
    cursor.execute("""UPDATE staff_shifts SET clock_in_at=%s,clock_out_at=%s,site_id=%s,site_name=%s,
        adjustment_reason=%s,approval_status='pending',approved_by=NULL,approved_at=NULL,updated_at=NOW()
        WHERE id=%s AND business_id=%s""",
        (new["clock_in_at"], new["clock_out_at"], site_id, site["name"], reason, shift["id"], business_id))
    for br in edited_breaks:
        cursor.execute("UPDATE staff_breaks SET started_at=%s,ended_at=%s,updated_at=NOW() WHERE id=%s AND shift_id=%s AND business_id=%s",
                       (br["started_at"], br["ended_at"], br["id"], shift["id"], business_id))
    if travel:
        cursor.execute("""UPDATE staff_shift_travel SET manager_distance_km=%s,adjustment_reason=%s,
            review_status='reviewed',reviewed_by=%s,reviewed_at=NOW() WHERE shift_id=%s AND business_id=%s""",
            (distance, reason, actor, shift["id"], business_id))
    if run:
        cursor.execute("UPDATE staff_payroll_runs SET needs_recalculation=TRUE,updated_at=NOW() WHERE id=%s AND business_id=%s",
                       (run["id"], business_id))
    audit(cursor, business_id, actor, "shift_corrected", "shift", shift["id"], old, new, reason)
    return "Correction saved; shift returned to pending review. Any affected draft payroll needs recalculation."


def uk_input(value):
    return value.astimezone(UK_TIMEZONE).isoformat(timespec="seconds") if value else ""
