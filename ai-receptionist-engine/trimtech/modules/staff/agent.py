from __future__ import annotations

import math
import json
import os
import re
import threading
import time
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from openai import OpenAI
from psycopg2.extras import RealDictCursor

from trimtech.modules.staff.database import (
    StaffDatabaseError,
    fetch_all,
    fetch_one,
    init_staff_database,
    transaction,
)


MANAGER_ROLES = {"owner", "manager"}
SESSION_TTL_SECONDS = 30 * 60
UK_TIMEZONE = ZoneInfo("Europe/London")

_SESSIONS: dict[str, dict[str, Any]] = {}
_SESSION_LOCK = threading.Lock()


def _clean_text(value: Any, maximum_length: int = 1000) -> str:
    return str(value or "").strip()[:maximum_length]


def _normalise_words(value: Any) -> str:
    text = _clean_text(value).lower().replace("’", "'")
    text = re.sub(r"[^a-z0-9'+\-/. ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _phone_digits(value: Any) -> str:
    text = _clean_text(value, 50)
    if text.lower().startswith("whatsapp:"):
        text = text.split(":", 1)[1]
    return "".join(character for character in text if character.isdigit())


def _phone_candidates(value: Any) -> list[str]:
    digits = _phone_digits(value)
    candidates = {digits} if digits else set()

    if digits.startswith("0044"):
        candidates.add(digits[2:])
        candidates.add("0" + digits[4:])
    elif digits.startswith("44"):
        candidates.add("0" + digits[2:])
    elif digits.startswith("0"):
        candidates.add("44" + digits[1:])

    return sorted(candidate for candidate in candidates if candidate)


def _business_id(value: Any) -> str:
    return _clean_text(value, 100).lower()


def _session_key(business_id: str, phone: Any) -> str:
    return f"{business_id}:{_phone_digits(phone)}"


def _clear_expired_sessions() -> None:
    now = time.time()
    with _SESSION_LOCK:
        expired = [
            key
            for key, session in _SESSIONS.items()
            if now - float(session.get("updated_at", 0)) > SESSION_TTL_SECONDS
        ]
        for key in expired:
            _SESSIONS.pop(key, None)


def _get_session(key: str) -> dict[str, Any] | None:
    _clear_expired_sessions()
    with _SESSION_LOCK:
        value = _SESSIONS.get(key)
        return dict(value) if value else None


def _set_session(key: str, **values: Any) -> None:
    with _SESSION_LOCK:
        _SESSIONS[key] = {**values, "updated_at": time.time()}


def _drop_session(key: str) -> None:
    with _SESSION_LOCK:
        _SESSIONS.pop(key, None)


def _first_name(employee: dict[str, Any]) -> str:
    full_name = _clean_text(employee.get("full_name"), 160)
    return full_name.split()[0] if full_name else "there"


def _is_manager(employee: dict[str, Any]) -> bool:
    return _clean_text(employee.get("role"), 40).lower() in MANAGER_ROLES


def _find_employee(business_id: str, phone: Any) -> dict[str, Any] | None:
    candidates = _phone_candidates(phone)
    if not candidates:
        return None

    return fetch_one(
        """
        SELECT id, business_id, full_name, phone, role, hourly_rate, status
        FROM staff_employees
        WHERE business_id = %s
          AND REGEXP_REPLACE(phone, '[^0-9]', '', 'g') = ANY(%s)
        ORDER BY CASE WHEN status = 'active' THEN 0 ELSE 1 END, id
        LIMIT 1
        """,
        (business_id, candidates),
    )


def _active_shift(business_id: str, employee_id: int) -> dict[str, Any] | None:
    return fetch_one(
        """
        SELECT id, site_id, site_name, clock_in_at, clock_in_latitude,
               clock_in_longitude, clock_in_photo_url
        FROM staff_shifts
        WHERE business_id = %s
          AND employee_id = %s
          AND clock_out_at IS NULL
        ORDER BY clock_in_at DESC
        LIMIT 1
        """,
        (business_id, employee_id),
    )


def _active_sites(business_id: str) -> list[dict[str, Any]]:
    return fetch_all(
        """
        SELECT id, name, address, latitude, longitude,
               allowed_radius_metres, photo_required
        FROM staff_sites
        WHERE business_id = %s AND active = TRUE
        ORDER BY LOWER(name), id
        """,
        (business_id,),
    )


def _find_site(business_id: str, supplied_name: Any) -> dict[str, Any] | None:
    wanted = _normalise_words(supplied_name)
    if not wanted:
        return None

    sites = _active_sites(business_id)
    exact = [site for site in sites if _normalise_words(site["name"]) == wanted]
    if exact:
        return exact[0]

    partial = [
        site
        for site in sites
        if wanted in _normalise_words(site["name"])
        or _normalise_words(site["name"]) in wanted
    ]
    return partial[0] if len(partial) == 1 else None


def _site_choices(business_id: str) -> str:
    sites = _active_sites(business_id)
    if not sites:
        return "No active work sites have been added yet. Please ask your manager to add one in the dashboard."

    names = "\n".join(f"• {site['name']}" for site in sites[:12])
    return f"Which site are you working at?\n\n{names}"


def _coordinates(location: dict[str, Any] | None) -> tuple[float, float] | None:
    location = location or {}
    try:
        latitude = float(location.get("latitude"))
        longitude = float(location.get("longitude"))
    except (TypeError, ValueError):
        return None

    if not math.isfinite(latitude) or not math.isfinite(longitude):
        return None
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        return None
    return latitude, longitude


def _distance_metres(lat1: float, lon1: float, lat2: Any, lon2: Any) -> int:
    earth_radius = 6_371_000
    phi1 = math.radians(lat1)
    phi2 = math.radians(float(lat2))
    delta_phi = math.radians(float(lat2) - lat1)
    delta_lambda = math.radians(float(lon2) - lon1)
    haversine = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    haversine = min(1.0, max(0.0, haversine))
    return round(earth_radius * 2 * math.atan2(math.sqrt(haversine), math.sqrt(1 - haversine)))


def _format_time(value: datetime | None) -> str:
    if not value:
        return "an unknown time"
    if value.tzinfo is None:
        value = value.replace(tzinfo=UK_TIMEZONE)
    return value.astimezone(UK_TIMEZONE).strftime("%H:%M")


def _hours_between(start: datetime, end: datetime) -> Decimal:
    seconds = max(0, (end - start).total_seconds())
    return (Decimal(str(seconds)) / Decimal("3600")).quantize(Decimal("0.01"))


def _first_photo(media_urls: Any) -> str:
    if isinstance(media_urls, str):
        return _clean_text(media_urls, 2000)
    if isinstance(media_urls, (list, tuple)):
        for value in media_urls:
            url = _clean_text(value, 2000)
            if url:
                return url
    return ""


def _looks_like_cancel(text: str) -> bool:
    return text in {"cancel", "stop", "never mind", "nevermind", "forget it", "leave it"}


def _looks_like_thanks(text: str) -> bool:
    return text in {"thanks", "thank you", "cheers", "nice one", "great", "perfect"}

def _ai_intent(text: Any) -> str | None:
    """Use AI to understand natural Staff Manager messages."""
    if not os.getenv("OPENAI_API_KEY"):
        return None

    try:
        client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You classify messages for a UK staff management assistant. "
                        "Return ONLY one of these intents: "
                        "greeting, help, clock_in, clock_out, break_start, break_end, "
                        "status, holiday_request, working_now, staff_report, payroll, "
                        "cancel, thanks, unknown."
                    ),
                },
                {
                    "role": "user",
                    "content": str(text or ""),
                },
            ],
        )

        intent = (response.choices[0].message.content or "").strip().lower()

        allowed = {
            "greeting", "help", "clock_in", "clock_out",
            "break_start", "break_end", "status",
            "holiday_request", "working_now",
            "staff_report", "payroll", "cancel",
            "thanks", "unknown",
        }

        return intent if intent in allowed else None

    except Exception:
        return None

def _intent(text: Any) -> str:
    value = _normalise_words(text)
    
    ai_intent = _ai_intent(value)
    if ai_intent and ai_intent != "unknown":
        # Translate classifier labels into the existing message-handler routes.
        return {
            "clock_in": "start",
            "clock_out": "finish",
            "holiday_request": "leave",
            "working_now": "on_site",
            "staff_report": "report",
        }.get(ai_intent, ai_intent)

    if not value:
        return "unknown"
    if _looks_like_cancel(value):
        return "cancel"
    if value in {"hi", "hello", "hey", "hiya", "morning", "good morning", "afternoon", "evening"}:
        return "greeting"
    if value in {"help", "menu", "what can you do", "options"}:
        return "help"
    if any(phrase in value for phrase in ("start break", "on a break", "take a break", "begin break")):
        return "break_start"
    if any(phrase in value for phrase in ("end break", "finish break", "back from break", "break over", "resume work")):
        return "break_end"
    if any(phrase in value for phrase in ("who is working", "who's working", "whos working", "who is on site", "who's on site", "who is clocked in", "staff on site")):
        return "on_site"
    if any(phrase in value for phrase in ("payroll", "wages", "staff pay", "hours and pay", "pay summary")):
        return "payroll"
    if any(phrase in value for phrase in ("team report", "staff report", "shift report", "today's report", "today report")) or value in {"report", "summary"}:
        return "report"
    if any(phrase in value for phrase in ("my status", "am i clocked in", "where am i checked in", "current status", "my shift")) or value == "status":
        return "status"
    if any(phrase in value for phrase in ("holiday", "annual leave", "book leave", "request leave", "time off")):
        return "leave"
    if any(phrase in value for phrase in ("clock me out", "clock out", "check me out", "check out", "sign me out", "sign out", "end my shift", "finish shift", "finished work", "done for today", "leaving site")) or value in {"finish", "finished", "done"}:
        return "finish"
    if any(phrase in value for phrase in ("clock me in", "clock in", "check me in", "check in", "sign me in", "sign in", "start shift", "starting work", "arrived at", "i'm at", "im at", "i am at", "working at", "on site at")):
        return "start"
    return "unknown"


def _extract_site_name(text: Any) -> str:
    value = _clean_text(text, 500).strip()
    patterns = (
        r"^(?:hi|hello|hey|hiya|morning|good morning)[, ]+",
        r"^(?:please |can you |could you )*",
        r"^(?:clock|check|sign) me in(?: at| to)?\s*",
        r"^(?:clock|check|sign) in(?: at| to)?\s*",
        r"^(?:start(?: my)? shift|starting work)(?: at)?\s*",
        r"^(?:i'm|im|i am|working|on site|arrived)(?: at)?\s*",
    )
    previous = None
    while previous != value:
        previous = value
        for pattern in patterns:
            value = re.sub(pattern, "", value, flags=re.IGNORECASE).strip()
    value = re.sub(r"\s+(?:please|pls|thanks|thank you|cheers|now)[.! ]*$", "", value, flags=re.IGNORECASE)
    return value.strip(" .,!?-")[:160]


def _request_location(first_name: str, site_name: str) -> str:
    return (
        f"Thanks, {first_name}. Please share your current WhatsApp location so I can check you in at {site_name}.\n\n"
        "Tap + or 📎 → Location → Send current location."
    )


def _menu(employee: dict[str, Any]) -> str:
    first_name = _first_name(employee)
    reply = (
        f"Hi {first_name} 👋 I can help with your shift.\n\n"
        "Try saying:\n"
        "• Clock me in at Demo Test Site\n"
        "• Start break\n"
        "• Finished\n"
        "• My status\n"
        "• Request holiday"
    )
    if _is_manager(employee):
        reply += "\n\nManager options:\n• Who is working?\n• Staff report\n• Payroll"
    return reply


def _status_reply(business_id: str, employee: dict[str, Any]) -> str:
    shift = _active_shift(business_id, employee["id"])
    first_name = _first_name(employee)
    if not shift:
        return f"{first_name}, you're currently checked out 👍"
    return (
        f"{first_name}, you're checked in at {shift['site_name']} since "
        f"{_format_time(shift['clock_in_at'])} 👍"
    )


def _create_shift(
    business_id: str,
    employee: dict[str, Any],
    site: dict[str, Any],
    latitude: float,
    longitude: float,
    photo_url: str = "",
) -> tuple[bool, dict[str, Any]]:
    with transaction() as connection:
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                SELECT id, site_name, clock_in_at
                FROM staff_shifts
                WHERE business_id = %s AND employee_id = %s
                  AND clock_out_at IS NULL
                FOR UPDATE
                """,
                (business_id, employee["id"]),
            )
            active = cursor.fetchone()
            if active:
                return False, dict(active)

            cursor.execute(
                """
                INSERT INTO staff_shifts (
                    business_id, employee_id, site_id, site_name,
                    clock_in_latitude, clock_in_longitude, clock_in_photo_url
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id, site_name, clock_in_at
                """,
                (
                    business_id,
                    employee["id"],
                    site["id"],
                    site["name"],
                    latitude,
                    longitude,
                    photo_url or None,
                ),
            )
            return True, dict(cursor.fetchone())


def _verify_and_check_in(
    business_id: str,
    employee: dict[str, Any],
    site: dict[str, Any],
    location: dict[str, Any] | None,
    session_key: str,
    photo_url: str = "",
) -> str:
    first_name = _first_name(employee)
    coordinates = _coordinates(location)
    if not coordinates:
        _set_session(session_key, stage="awaiting_location", site_id=site["id"])
        return _request_location(first_name, site["name"])

    if site.get("latitude") is None or site.get("longitude") is None:
        return f"Sorry {first_name}, GPS has not been configured for {site['name']}. Please ask your manager to update the site."

    latitude, longitude = coordinates
    distance = _distance_metres(latitude, longitude, site["latitude"], site["longitude"])
    radius = int(site.get("allowed_radius_metres") or 250)
    if distance > radius:
        _set_session(session_key, stage="awaiting_location", site_id=site["id"])
        return (
            f"I can't check you in yet, {first_name}. You're about {distance}m from {site['name']}; "
            f"you need to be within {radius}m. Move closer and share your location again."
        )

    if bool(site.get("photo_required")) and not photo_url:
        _set_session(
            session_key,
            stage="awaiting_photo",
            site_id=site["id"],
            latitude=latitude,
            longitude=longitude,
            distance=distance,
        )
        return (
            f"Location confirmed, {first_name} — you're {distance}m from {site['name']} ✅\n\n"
            "Please send a current photo from the site to complete your check-in."
        )

    created, shift = _create_shift(
        business_id,
        employee,
        site,
        latitude,
        longitude,
        photo_url,
    )
    _drop_session(session_key)
    if not created:
        return (
            f"You're already checked in at {shift['site_name']}, {first_name} — "
            f"since {_format_time(shift['clock_in_at'])} 👍"
        )
    return (
        f"You're checked in, {first_name} ✅\n\n"
        f"Site: {site['name']}\nGPS: verified ({distance}m away)\n"
        f"Time: {_format_time(shift['clock_in_at'])}\n\nHave a good shift 👍"
    )


def _clock_out(
    business_id: str,
    employee: dict[str, Any],
    location: dict[str, Any] | None,
    photo_url: str,
) -> str:
    first_name = _first_name(employee)
    coordinates = _coordinates(location)
    latitude = coordinates[0] if coordinates else None
    longitude = coordinates[1] if coordinates else None
    now = datetime.now(UK_TIMEZONE)

    with transaction() as connection:
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                SELECT id, site_name, clock_in_at
                FROM staff_shifts
                WHERE business_id = %s AND employee_id = %s
                  AND clock_out_at IS NULL
                ORDER BY clock_in_at DESC
                LIMIT 1
                FOR UPDATE
                """,
                (business_id, employee["id"]),
            )
            shift = cursor.fetchone()
            if not shift:
                return f"You're already checked out, {first_name} 👍"

            cursor.execute(
                """
                UPDATE staff_breaks
                SET ended_at = %s, updated_at = NOW()
                WHERE business_id = %s AND shift_id = %s AND ended_at IS NULL
                """,
                (now, business_id, shift["id"]),
            )
            cursor.execute(
                """
                UPDATE staff_shifts
                SET clock_out_at = %s,
                    clock_out_latitude = %s,
                    clock_out_longitude = %s,
                    clock_out_photo_url = %s,
                    approval_status = 'pending',
                    updated_at = NOW()
                WHERE id = %s AND business_id = %s AND clock_out_at IS NULL
                """,
                (now, latitude, longitude, photo_url or None, shift["id"], business_id),
            )

    hours = _hours_between(shift["clock_in_at"], now)
    return (
        f"You're checked out, {first_name} ✅\n\n"
        f"Site: {shift['site_name']}\nFinished: {_format_time(now)}\n"
        f"Shift length: {hours} hours\n\nYour hours are waiting for manager approval."
    )


def _break_action(business_id: str, employee: dict[str, Any], start: bool) -> str:
    first_name = _first_name(employee)
    shift = _active_shift(business_id, employee["id"])
    if not shift:
        return f"You need to be checked in before using breaks, {first_name}."

    if start:
        existing = fetch_one(
            "SELECT id, started_at FROM staff_breaks WHERE business_id = %s AND shift_id = %s AND ended_at IS NULL",
            (business_id, shift["id"]),
        )
        if existing:
            return f"You're already on a break, {first_name} — it started at {_format_time(existing['started_at'])}."
        with transaction() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    INSERT INTO staff_breaks (business_id, shift_id, employee_id)
                    VALUES (%s, %s, %s) RETURNING started_at
                    """,
                    (business_id, shift["id"], employee["id"]),
                )
                started = cursor.fetchone()["started_at"]
        return f"Break started at {_format_time(started)}, {first_name} 👍 Say “back from break” when you return."

    with transaction() as connection:
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                UPDATE staff_breaks SET ended_at = NOW(), updated_at = NOW()
                WHERE business_id = %s AND shift_id = %s AND ended_at IS NULL
                RETURNING started_at, ended_at
                """,
                (business_id, shift["id"]),
            )
            ended = cursor.fetchone()
    if not ended:
        return f"You don't have an active break, {first_name}."
    minutes = max(0, round((ended["ended_at"] - ended["started_at"]).total_seconds() / 60))
    return f"Welcome back, {first_name} 👍 Your break lasted {minutes} minutes."


def _parse_date(value: Any) -> date | None:
    text = _normalise_words(value)
    today = datetime.now(UK_TIMEZONE).date()
    if text == "today":
        return today
    if text == "tomorrow":
        return today + timedelta(days=1)
    for pattern in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%d-%m-%y"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    return None


def _working_days(start_date: date, end_date: date) -> Decimal:
    count = 0
    current = start_date
    while current <= end_date:
        if current.weekday() < 5:
            count += 1
        current += timedelta(days=1)
    return Decimal(count)


def _save_leave_request(
    business_id: str,
    employee: dict[str, Any],
    start_date: date,
    end_date: date,
    note: str = "",
) -> str:
    first_name = _first_name(employee)
    if end_date < start_date:
        return f"The end date is before the start date, {first_name}. Please send the end date again."
    total_days = _working_days(start_date, end_date)
    if total_days <= 0:
        return "That range contains no weekdays. Please choose at least one Monday-to-Friday date."

    existing = fetch_one(
        """
        SELECT id FROM staff_leave_requests
        WHERE business_id = %s AND employee_id = %s
          AND approval_status IN ('pending', 'approved')
          AND start_date <= %s AND end_date >= %s
        LIMIT 1
        """,
        (business_id, employee["id"], end_date, start_date),
    )
    if existing:
        return f"You already have a holiday request covering those dates, {first_name}."

    with transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO staff_leave_requests (
                    business_id, employee_id, leave_type, start_date,
                    end_date, total_days, approval_status, employee_note
                ) VALUES (%s, %s, 'holiday', %s, %s, %s, 'pending', %s)
                """,
                (business_id, employee["id"], start_date, end_date, total_days, note or None),
            )
    return (
        f"Your holiday request has been sent, {first_name} ✅\n\n"
        f"Dates: {start_date.strftime('%d %b %Y')} – {end_date.strftime('%d %b %Y')}\n"
        f"Working days: {total_days}\nStatus: waiting for manager approval"
    )


def _manager_on_site(business_id: str) -> str:
    people = fetch_all(
        """
        SELECT employee.full_name, employee.role, shift.site_name, shift.clock_in_at
        FROM staff_shifts AS shift
        JOIN staff_employees AS employee
          ON employee.id = shift.employee_id AND employee.business_id = shift.business_id
        WHERE shift.business_id = %s AND shift.clock_out_at IS NULL
        ORDER BY shift.clock_in_at
        """,
        (business_id,),
    )
    if not people:
        return "Nobody is currently clocked in 👍"
    lines = ["👷 Currently working:"]
    for person in people:
        lines.append(f"• {person['full_name']} — {person['site_name']} since {_format_time(person['clock_in_at'])}")
    return "\n".join(lines)


def _manager_report(business_id: str, include_pay: bool = False) -> str:
    summary = fetch_one(
        """
        SELECT
            COUNT(*) FILTER (WHERE shift.clock_out_at IS NULL) AS working_now,
            COUNT(*) FILTER (
                WHERE shift.clock_out_at IS NOT NULL
                  AND shift.approval_status = 'pending'
            ) AS waiting_approval,
            COALESCE(SUM(
                EXTRACT(EPOCH FROM (COALESCE(shift.clock_out_at, NOW()) - shift.clock_in_at)) / 3600
            ) FILTER (WHERE shift.clock_in_at >= DATE_TRUNC('week', NOW())), 0) AS week_hours,
            COALESCE(SUM(
                (EXTRACT(EPOCH FROM (COALESCE(shift.clock_out_at, NOW()) - shift.clock_in_at)) / 3600)
                * employee.hourly_rate
            ) FILTER (WHERE shift.clock_in_at >= DATE_TRUNC('week', NOW())), 0) AS estimated_pay
        FROM staff_shifts AS shift
        JOIN staff_employees AS employee
          ON employee.id = shift.employee_id AND employee.business_id = shift.business_id
        WHERE shift.business_id = %s
        """,
        (business_id,),
    ) or {}
    hours = Decimal(str(summary.get("week_hours") or 0)).quantize(Decimal("0.1"))
    reply = (
        "📊 Staff summary\n\n"
        f"Working now: {summary.get('working_now') or 0}\n"
        f"Waiting approval: {summary.get('waiting_approval') or 0}\n"
        f"Hours this week: {hours}"
    )
    if include_pay:
        pay = Decimal(str(summary.get("estimated_pay") or 0)).quantize(Decimal("0.01"))
        reply += f"\nEstimated gross pay: £{pay}"
    return reply


def _handle_pending(
    business_id: str,
    employee: dict[str, Any],
    key: str,
    pending: dict[str, Any],
    text: str,
    location: dict[str, Any] | None,
    photo_url: str,
) -> str | None:
    stage = pending.get("stage")
    first_name = _first_name(employee)

    if stage == "awaiting_site":
        site = _find_site(business_id, text)
        if not site:
            return f"I couldn't match that to an active work site, {first_name}.\n\n{_site_choices(business_id)}"
        return _verify_and_check_in(business_id, employee, site, location, key, photo_url)

    if stage == "awaiting_location":
        site = fetch_one(
            """
            SELECT id, name, address, latitude, longitude,
                   allowed_radius_metres, photo_required
            FROM staff_sites
            WHERE id = %s AND business_id = %s AND active = TRUE
            """,
            (pending.get("site_id"), business_id),
        )
        if not site:
            _drop_session(key)
            return "That work site is no longer active. Please start your check-in again."
        if not _coordinates(location):
            return _request_location(first_name, site["name"])
        return _verify_and_check_in(business_id, employee, site, location, key, photo_url)

    if stage == "awaiting_photo":
        if not photo_url:
            return f"Please send a current site photo to complete your check-in, {first_name} 📸"
        site = fetch_one(
            """
            SELECT id, name, latitude, longitude, allowed_radius_metres, photo_required
            FROM staff_sites WHERE id = %s AND business_id = %s AND active = TRUE
            """,
            (pending.get("site_id"), business_id),
        )
        if not site:
            _drop_session(key)
            return "That work site is no longer active. Please start your check-in again."
        created, shift = _create_shift(
            business_id,
            employee,
            site,
            float(pending["latitude"]),
            float(pending["longitude"]),
            photo_url,
        )
        _drop_session(key)
        if not created:
            return f"You're already checked in at {shift['site_name']}, {first_name} 👍"
        return (
            f"Photo received — you're checked in, {first_name} ✅\n\n"
            f"Site: {site['name']}\nTime: {_format_time(shift['clock_in_at'])}\n\nHave a good shift 👍"
        )

    if stage == "awaiting_leave_start":
        start_date = _parse_date(text)
        if not start_date:
            return "Please send the first day as DD/MM/YYYY, for example 21/09/2026."
        _set_session(key, stage="awaiting_leave_end", start_date=start_date.isoformat())
        return f"Thanks, {first_name}. What is the last day of your holiday? Send it as DD/MM/YYYY."

    if stage == "awaiting_leave_end":
        end_date = _parse_date(text)
        if not end_date:
            return "Please send the last day as DD/MM/YYYY, for example 25/09/2026."
        start_date = date.fromisoformat(str(pending["start_date"]))
        if end_date < start_date:
            return "That is before your start date. Please send the correct last day."
        _drop_session(key)
        return _save_leave_request(business_id, employee, start_date, end_date)

    return None


def handle_message(
    business_id: str,
    phone: Any,
    text: Any,
    profile_name: Any = None,
    media_urls: Any = None,
    location: dict[str, Any] | None = None,
) -> str:
    """Handle one Staff Manager WhatsApp message for one resolved business."""
    business_id = _business_id(business_id)
    message = _clean_text(text, 1000)
    normalised = _normalise_words(message)
    photo_url = _first_photo(media_urls)

    if not business_id:
        return "Sorry, this Staff Manager link is not configured correctly."

    try:
        init_staff_database()
        employee = _find_employee(business_id, phone)
        if not employee:
            return (
                "Sorry, I can't find this mobile number on the staff list 🔒\n\n"
                "Please ask your manager to add your number in Staff Manager."
            )
        first_name = _first_name(employee)
        if _clean_text(employee.get("status"), 20).lower() != "active":
            return f"Hi {first_name}. Your staff account is inactive, so I can't record a shift. Please contact your manager."

        key = _session_key(business_id, phone)
        intent = _intent(message)
        if intent == "cancel":
            had_session = _get_session(key) is not None
            _drop_session(key)
            return f"No problem, {first_name} — I've cancelled that request." if had_session else f"There's nothing waiting to cancel, {first_name}."

        pending = _get_session(key)
        if pending:
            pending_reply = _handle_pending(
                business_id, employee, key, pending, message, location, photo_url
            )
            if pending_reply:
                return pending_reply

        if intent == "thanks" or _looks_like_thanks(normalised):
            return f"You're welcome, {first_name} 👍"
        if intent in {"greeting", "help"}:
            return _menu(employee)
        if intent == "status":
            return _status_reply(business_id, employee)
        if intent == "start":
            active = _active_shift(business_id, employee["id"])
            if active:
                return f"You're already checked in at {active['site_name']}, {first_name} — since {_format_time(active['clock_in_at'])} 👍"
            supplied_site = _extract_site_name(message)
            site = _find_site(business_id, supplied_site)
            if not site:
                _set_session(key, stage="awaiting_site")
                return _site_choices(business_id)
            return _verify_and_check_in(business_id, employee, site, location, key, photo_url)
        if intent == "finish":
            _drop_session(key)
            return _clock_out(business_id, employee, location, photo_url)
        if intent == "break_start":
            return _break_action(business_id, employee, start=True)
        if intent == "break_end":
            return _break_action(business_id, employee, start=False)
        if intent == "leave":
            _set_session(key, stage="awaiting_leave_start")
            return f"Of course, {first_name}. What is the first day of your holiday? Send it as DD/MM/YYYY."
        if intent in {"on_site", "report", "payroll"}:
            if not _is_manager(employee):
                return f"Sorry {first_name}, that information is for managers only 🔒"
            if intent == "on_site":
                return _manager_on_site(business_id)
            return _manager_report(business_id, include_pay=intent == "payroll")

        active = _active_shift(business_id, employee["id"])
        if active:
            return (
                f"I didn't quite understand that, {first_name}. You're checked in at {active['site_name']}.\n\n"
                "Try “my status”, “start break” or “finished”."
            )
        return (
            f"I didn't quite understand that, {first_name}.\n\n"
            "Try “clock me in”, “request holiday”, “my status” or “help”."
        )

    except StaffDatabaseError:
        return "Sorry, Staff Manager is temporarily unavailable. Please try again shortly."
    except Exception as error:
        print(
            "STAFF AGENT ERROR:",
            {"business_id": business_id, "phone": _phone_digits(phone), "error": repr(error)},
        )
        return "Sorry, I couldn't complete that just now. Nothing has been changed—please try again."
