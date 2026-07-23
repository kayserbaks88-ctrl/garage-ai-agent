import json
import os
from datetime import date, datetime, time, timedelta

from google.oauth2 import service_account
from googleapiclient.discovery import build

from integrations.garage_config import (
    GARAGE_CALENDAR_ID,
    SERVICES,
    TIMEZONE,
)


CALENDAR_SCOPES = [
    "https://www.googleapis.com/auth/calendar",
]

OPENING_HOUR = 9
CLOSING_HOUR = 17
SLOT_INTERVAL_MINUTES = 30


def _load_service_account_json() -> dict:
    raw = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()

    if not raw:
        raise ValueError("Missing GOOGLE_SERVICE_ACCOUNT_JSON")

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        fixed = raw.replace("\\n", "\n")
        return json.loads(fixed)


def _get_calendar_service():
    info = _load_service_account_json()

    credentials = (
        service_account.Credentials.from_service_account_info(
            info,
            scopes=CALENDAR_SCOPES,
        )
    )

    return build(
        "calendar",
        "v3",
        credentials=credentials,
        cache_discovery=False,
    )


def _calendar_id() -> str:
    if not GARAGE_CALENDAR_ID:
        raise ValueError("Missing GARAGE_CALENDAR_ID")

    return GARAGE_CALENDAR_ID


def _normalise_service_key(service_key: str) -> str:
    key = (service_key or "").strip().lower()

    if key in SERVICES:
        return key

    return "diagnostic"


def normalise_phone(phone: str) -> str:
    """
    Convert common UK phone-number formats into +44 format.

    Examples:
    07368593535      -> +447368593535
    447368593535     -> +447368593535
    +447368593535    -> +447368593535
    00447368593535   -> +447368593535
    """
    value = str(phone or "").strip().lower()
    value = value.replace("whatsapp:", "")

    # Remove spaces, brackets, dashes and other spoken formatting.
    digits = "".join(character for character in value if character.isdigit())

    if not digits:
        return ""

    if digits.startswith("0044"):
        return "+44" + digits[4:]

    if digits.startswith("44"):
        return "+" + digits

    if digits.startswith("0"):
        return "+44" + digits[1:]

    # Preserve non-UK numbers in international-looking format.
    return "+" + digits


def _service_minutes(service_key: str) -> int:
    key = _normalise_service_key(service_key)
    return int(SERVICES[key]["minutes"])


def _event_overlaps(
    event: dict,
    start_dt: datetime,
    end_dt: datetime,
) -> bool:
    event_start_raw = (event.get("start") or {}).get("dateTime")
    event_end_raw = (event.get("end") or {}).get("dateTime")

    if not event_start_raw or not event_end_raw:
        return True

    event_start = datetime.fromisoformat(
        event_start_raw.replace("Z", "+00:00")
    ).astimezone(TIMEZONE)

    event_end = datetime.fromisoformat(
        event_end_raw.replace("Z", "+00:00")
    ).astimezone(TIMEZONE)

    return event_start < end_dt and event_end > start_dt


def is_free(
    start_dt: datetime,
    end_dt: datetime,
    ignore_event_id: str | None = None,
) -> bool:
    service = _get_calendar_service()

    start_dt = start_dt.astimezone(TIMEZONE)
    end_dt = end_dt.astimezone(TIMEZONE)

    result = (
        service.events()
        .list(
            calendarId=_calendar_id(),
            timeMin=start_dt.isoformat(),
            timeMax=end_dt.isoformat(),
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )

    for event in result.get("items", []):
        if ignore_event_id and event.get("id") == ignore_event_id:
            continue

        if event.get("status") == "cancelled":
            continue

        if _event_overlaps(event, start_dt, end_dt):
            return False

    return True


def get_available_slots(
    requested_date: date,
    service_key: str,
    limit: int = 4,
    preferred_period: str = "",
) -> list[datetime]:
    """
    Return available appointment start times for one date.

    preferred_period may be:
    morning, afternoon, evening, or blank.
    """
    duration = _service_minutes(service_key)

    day_start = datetime.combine(
        requested_date,
        time(hour=OPENING_HOUR),
        tzinfo=TIMEZONE,
    )

    day_end = datetime.combine(
        requested_date,
        time(hour=CLOSING_HOUR),
        tzinfo=TIMEZONE,
    )

    now = datetime.now(TIMEZONE)
    period = (preferred_period or "").strip().lower()

    available = []
    candidate = day_start

    while candidate + timedelta(minutes=duration) <= day_end:
        if candidate <= now:
            candidate += timedelta(minutes=SLOT_INTERVAL_MINUTES)
            continue

        if period == "morning" and candidate.hour >= 12:
            candidate += timedelta(minutes=SLOT_INTERVAL_MINUTES)
            continue

        if period == "afternoon" and candidate.hour < 12:
            candidate += timedelta(minutes=SLOT_INTERVAL_MINUTES)
            continue

        if period == "evening":
            candidate += timedelta(minutes=SLOT_INTERVAL_MINUTES)
            continue

        candidate_end = candidate + timedelta(minutes=duration)

        if is_free(candidate, candidate_end):
            available.append(candidate)

            if len(available) >= limit:
                break

        candidate += timedelta(minutes=SLOT_INTERVAL_MINUTES)

    return available


def find_next_available_slots(
    start_date: date,
    service_key: str,
    preferred_period: str = "",
    days_to_check: int = 7,
    limit: int = 4,
) -> list[datetime]:
    slots = []

    for offset in range(days_to_check):
        current_date = start_date + timedelta(days=offset)

        # Skip Sundays.
        if current_date.weekday() == 6:
            continue

        day_slots = get_available_slots(
            requested_date=current_date,
            service_key=service_key,
            limit=limit - len(slots),
            preferred_period=preferred_period,
        )

        slots.extend(day_slots)

        if len(slots) >= limit:
            break

    return slots


def create_booking(
    phone: str,
    service_key: str,
    start_dt: datetime,
    customer_name: str,
    vehicle: dict,
    notes: str = "",
    source: str = "WhatsApp AI",
) -> dict:
    service = _get_calendar_service()

    service_key = _normalise_service_key(service_key)
    service_config = SERVICES[service_key]

    # Always save phone numbers in one consistent format.
    phone = normalise_phone(phone)

    start_dt = start_dt.astimezone(TIMEZONE)
    end_dt = start_dt + timedelta(
        minutes=service_config["minutes"]
    )

    if not is_free(start_dt, end_dt):
        raise ValueError("slot_taken")

    vehicle = vehicle or {}

    registration = (
        vehicle.get("reg")
        or vehicle.get("registration")
        or "Unknown reg"
    )

    make_model = (
        vehicle.get("make_model")
        or vehicle.get("vehicle")
        or "Vehicle not confirmed"
    )

    event = {
        "summary": (
            f"{service_config['label']} - "
            f"{registration} - "
            f"{customer_name}"
        ),
        "description": (
            f"Customer: {customer_name}\n"
            f"Phone: {phone}\n"
            f"Service: {service_config['label']}\n"
            f"Registration: {registration}\n"
            f"Vehicle: {make_model}\n"
            f"Notes: {notes or 'None'}\n\n"
            f"Booked via {source}"
        ),
        "start": {
            "dateTime": start_dt.isoformat(),
            "timeZone": str(TIMEZONE),
        },
        "end": {
            "dateTime": end_dt.isoformat(),
            "timeZone": str(TIMEZONE),
        },
        "extendedProperties": {
            "private": {
                "phone": phone,
                "customer_name": customer_name,
                "service": service_key,
                "reg": registration,
                "make_model": make_model,
                "notes": notes or "",
                "source": source,
            }
        },
    }

    created = (
        service.events()
        .insert(
            calendarId=_calendar_id(),
            body=event,
        )
        .execute()
    )

    return {
        "id": created.get("id"),
        "link": created.get("htmlLink"),
        "phone": phone,
        "service": service_key,
        "service_label": service_config["label"],
        "start": start_dt.isoformat(),
        "end": end_dt.isoformat(),
        "customer_name": customer_name,
        "vehicle": vehicle,
        "notes": notes,
        "source": source,
    }


def list_bookings(phone: str) -> list[dict]:
    service = _get_calendar_service()

    # This makes 073..., 4473... and +4473... match.
    wanted_phone = normalise_phone(phone)

    # Never allow an empty phone number to match old blank events.
    if not wanted_phone:
        print("LIST BOOKINGS: missing phone number")
        return []

    now = datetime.now(TIMEZONE).isoformat()

    result = (
        service.events()
        .list(
            calendarId=_calendar_id(),
            timeMin=now,
            singleEvents=True,
            orderBy="startTime",
            maxResults=50,
        )
        .execute()
    )

    bookings = []

    for event in result.get("items", []):
        if event.get("status") == "cancelled":
            continue

        private = (
            (event.get("extendedProperties") or {})
            .get("private")
            or {}
        )

        saved_phone = normalise_phone(
            private.get("phone", "")
        )

        if not saved_phone:
            continue

        if saved_phone != wanted_phone:
            continue

        bookings.append({
            "id": event.get("id"),
            "summary": event.get("summary"),
            "start": (event.get("start") or {}).get("dateTime"),
            "end": (event.get("end") or {}).get("dateTime"),
            "link": event.get("htmlLink"),
            "phone": saved_phone,
            "service": private.get("service"),
            "customer_name": private.get("customer_name"),
            "reg": private.get("reg"),
            "make_model": private.get("make_model"),
            "notes": private.get("notes"),
            "source": private.get("source"),
        })

    bookings.sort(
        key=lambda booking: booking.get("start") or ""
    )

    return bookings


def cancel_booking(event_id: str) -> bool:
    service = _get_calendar_service()

    (
        service.events()
        .delete(
            calendarId=_calendar_id(),
            eventId=event_id,
        )
        .execute()
    )

    return True


def reschedule_booking(
    event_id: str,
    new_start: datetime,
) -> dict:
    service = _get_calendar_service()

    event = (
        service.events()
        .get(
            calendarId=_calendar_id(),
            eventId=event_id,
        )
        .execute()
    )

    private = (
        (event.get("extendedProperties") or {})
        .get("private")
        or {}
    )

    service_key = _normalise_service_key(
        private.get("service", "mot")
    )

    new_start = new_start.astimezone(TIMEZONE)
    new_end = new_start + timedelta(
        minutes=_service_minutes(service_key)
    )

    if not is_free(
        new_start,
        new_end,
        ignore_event_id=event_id,
    ):
        raise ValueError("slot_taken")

    event["start"] = {
        "dateTime": new_start.isoformat(),
        "timeZone": str(TIMEZONE),
    }

    event["end"] = {
        "dateTime": new_end.isoformat(),
        "timeZone": str(TIMEZONE),
    }

    updated = (
        service.events()
        .update(
            calendarId=_calendar_id(),
            eventId=event_id,
            body=event,
        )
        .execute()
    )

    return {
        "id": updated.get("id"),
        "link": updated.get("htmlLink"),
        "phone": normalise_phone(private.get("phone", "")),
        "service": service_key,
        "start": new_start.isoformat(),
        "end": new_end.isoformat(),
    }