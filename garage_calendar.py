import json
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from google.oauth2 import service_account
from googleapiclient.discovery import build

TIMEZONE = ZoneInfo(os.getenv("TIMEZONE", "Europe/London"))

SERVICES = {
    "mot": {"label": "MOT", "minutes": 60},
    "full service": {"label": "Full Service", "minutes": 180},
    "diagnostic": {"label": "Diagnostic Check", "minutes": 60},
    "oil change": {"label": "Oil Change", "minutes": 45},
    "brake check": {"label": "Brake Check", "minutes": 60},
}

GARAGE_CALENDAR_ID = os.getenv("GARAGE_CALENDAR_ID", "")


def _get_service():
    raw = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    if not raw:
        raise ValueError("Missing GOOGLE_SERVICE_ACCOUNT_JSON")

    info = json.loads(raw)
    creds = service_account.Credentials.from_service_account_info(
        info,
        scopes=["https://www.googleapis.com/auth/calendar"],
    )
    return build("calendar", "v3", credentials=creds)


def _calendar_id() -> str:
    if not GARAGE_CALENDAR_ID:
        raise ValueError("Missing GARAGE_CALENDAR_ID")
    return GARAGE_CALENDAR_ID


def is_free(start_dt: datetime, end_dt: datetime, ignore_event_id: str | None = None) -> bool:
    service = _get_service()
    calendar_id = _calendar_id()

    result = service.events().list(
        calendarId=calendar_id,
        timeMin=start_dt.astimezone(TIMEZONE).isoformat(),
        timeMax=end_dt.astimezone(TIMEZONE).isoformat(),
        singleEvents=True,
        orderBy="startTime",
    ).execute()

    for event in result.get("items", []):
        if ignore_event_id and event.get("id") == ignore_event_id:
            continue
        if event.get("status") == "cancelled":
            continue
        return False

    return True


def create_booking(
    phone: str,
    service_name: str,
    start_dt: datetime,
    minutes: int,
    name: str,
    vehicle: dict,
) -> dict:
    service = _get_service()
    calendar_id = _calendar_id()

    end_dt = start_dt + timedelta(minutes=minutes)

    if not is_free(start_dt, end_dt):
        raise ValueError("That slot is not available")

    service_label = SERVICES.get(service_name, {}).get("label", service_name.title())
    reg = vehicle.get("reg", "Unknown reg")
    make_model = vehicle.get("make_model", "Vehicle details not provided")

    event = {
        "summary": f"{service_label} - {reg} - {name}",
        "description": (
            f"Customer: {name}\n"
            f"Phone: {phone}\n"
            f"Service: {service_label}\n"
            f"Registration: {reg}\n"
            f"Vehicle: {make_model}"
        ),
        "start": {
            "dateTime": start_dt.astimezone(TIMEZONE).isoformat(),
            "timeZone": str(TIMEZONE),
        },
        "end": {
            "dateTime": end_dt.astimezone(TIMEZONE).isoformat(),
            "timeZone": str(TIMEZONE),
        },
        "extendedProperties": {
            "private": {
                "phone": phone,
                "service": service_name,
                "customer_name": name,
                "reg": reg,
                "make_model": make_model,
            }
        },
    }

    created = service.events().insert(calendarId=calendar_id, body=event).execute()

    return {
        "id": created.get("id"),
        "link": created.get("htmlLink"),
        "calendar_id": calendar_id,
        "service": service_name,
        "customer_name": name,
        "vehicle": vehicle,
        "start": start_dt.isoformat(),
        "end": end_dt.isoformat(),
    }


def list_bookings(phone: str) -> list[dict]:
    service = _get_service()
    calendar_id = _calendar_id()
    now = datetime.now(TIMEZONE).isoformat()

    result = service.events().list(
        calendarId=calendar_id,
        timeMin=now,
        singleEvents=True,
        orderBy="startTime",
        maxResults=30,
    ).execute()

    found = []

    for event in result.get("items", []):
        if event.get("status") == "cancelled":
            continue

        private = ((event.get("extendedProperties") or {}).get("private") or {})
        description = event.get("description") or ""
        event_phone = private.get("phone") or ""

        if phone != event_phone and phone not in description:
            continue

        found.append(
            {
                "id": event.get("id"),
                "summary": event.get("summary"),
                "start": (event.get("start") or {}).get("dateTime", ""),
                "end": (event.get("end") or {}).get("dateTime", ""),
                "link": event.get("htmlLink"),
                "service": private.get("service"),
                "customer_name": private.get("customer_name"),
                "reg": private.get("reg"),
                "make_model": private.get("make_model"),
                "calendar_id": calendar_id,
            }
        )

    found.sort(key=lambda x: x.get("start", ""))
    return found


def cancel_booking(event_id: str) -> bool:
    service = _get_service()
    calendar_id = _calendar_id()

    try:
        service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
        return True
    except Exception:
        return False


def reschedule_booking(event_id: str, new_start: datetime) -> dict | None:
    service = _get_service()
    calendar_id = _calendar_id()

    event = service.events().get(calendarId=calendar_id, eventId=event_id).execute()
    private = ((event.get("extendedProperties") or {}).get("private") or {})

    service_name = private.get("service", "mot")
    minutes = SERVICES.get(service_name, {"minutes": 60})["minutes"]
    new_end = new_start + timedelta(minutes=minutes)

    if not is_free(new_start, new_end, ignore_event_id=event_id):
        raise ValueError("That new slot is not available")

    event["start"] = {
        "dateTime": new_start.astimezone(TIMEZONE).isoformat(),
        "timeZone": str(TIMEZONE),
    }
    event["end"] = {
        "dateTime": new_end.astimezone(TIMEZONE).isoformat(),
        "timeZone": str(TIMEZONE),
    }

    updated = service.events().update(
        calendarId=calendar_id,
        eventId=event_id,
        body=event,
    ).execute()

    return {
        "id": updated.get("id"),
        "link": updated.get("htmlLink"),
        "service": service_name,
        "start": new_start.isoformat(),
        "end": new_end.isoformat(),
    }