import json
import os
from datetime import datetime, timedelta

from google.oauth2 import service_account
from googleapiclient.discovery import build

from garage_config import GARAGE_CALENDAR_ID, SERVICES, TIMEZONE


def _get_calendar_service():
    raw = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    if not raw:
        raise ValueError("Missing GOOGLE_SERVICE_ACCOUNT_JSON")

    info = json.loads(raw)
    creds = service_account.Credentials.from_service_account_info(
        info,
        scopes=["https://www.googleapis.com/auth/calendar"],
    )
    return build("calendar", "v3", credentials=creds)


def _calendar_id():
    if not GARAGE_CALENDAR_ID:
        raise ValueError("Missing GARAGE_CALENDAR_ID")
    return GARAGE_CALENDAR_ID


def is_free(start_dt: datetime, end_dt: datetime, ignore_event_id: str | None = None) -> bool:
    service = _get_calendar_service()

    result = service.events().list(
        calendarId=_calendar_id(),
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
    service_key: str,
    start_dt: datetime,
    customer_name: str,
    vehicle: dict,
    notes: str = "",
) -> dict:
    service = _get_calendar_service()
    svc = SERVICES[service_key]
    end_dt = start_dt + timedelta(minutes=svc["minutes"])

    if not is_free(start_dt, end_dt):
        raise ValueError("slot_taken")

    reg = vehicle.get("reg", "Unknown reg")
    make_model = vehicle.get("make_model", "Unknown vehicle")

    event = {
        "summary": f"{svc['label']} - {reg} - {customer_name}",
        "description": (
            f"Customer: {customer_name}\n"
            f"Phone: {phone}\n"
            f"Service: {svc['label']}\n"
            f"Registration: {reg}\n"
            f"Vehicle: {make_model}\n"
            f"Notes: {notes or 'None'}\n\n"
            f"Booked via WhatsApp AI"
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
                "customer_name": customer_name,
                "service": service_key,
                "reg": reg,
                "make_model": make_model,
                "notes": notes or "",
            }
        },
    }

    created = service.events().insert(
        calendarId=_calendar_id(),
        body=event,
    ).execute()

    return {
        "id": created.get("id"),
        "link": created.get("htmlLink"),
        "service": service_key,
        "start": start_dt.isoformat(),
        "end": end_dt.isoformat(),
        "customer_name": customer_name,
        "vehicle": vehicle,
        "notes": notes,
    }


def list_bookings(phone: str) -> list[dict]:
    service = _get_calendar_service()
    now = datetime.now(TIMEZONE).isoformat()

    result = service.events().list(
        calendarId=_calendar_id(),
        timeMin=now,
        singleEvents=True,
        orderBy="startTime",
        maxResults=20,
    ).execute()

    bookings = []

    for event in result.get("items", []):
        if event.get("status") == "cancelled":
            continue

        private = ((event.get("extendedProperties") or {}).get("private") or {})
        if private.get("phone") != phone:
            continue

        bookings.append({
            "id": event.get("id"),
            "summary": event.get("summary"),
            "start": (event.get("start") or {}).get("dateTime"),
            "end": (event.get("end") or {}).get("dateTime"),
            "link": event.get("htmlLink"),
            "service": private.get("service"),
            "customer_name": private.get("customer_name"),
            "reg": private.get("reg"),
            "make_model": private.get("make_model"),
            "notes": private.get("notes"),
        })

    return bookings


def cancel_booking(event_id: str) -> bool:
    service = _get_calendar_service()
    service.events().delete(
        calendarId=_calendar_id(),
        eventId=event_id,
    ).execute()
    return True


def reschedule_booking(event_id: str, new_start: datetime) -> dict:
    service = _get_calendar_service()

    event = service.events().get(
        calendarId=_calendar_id(),
        eventId=event_id,
    ).execute()

    private = ((event.get("extendedProperties") or {}).get("private") or {})
    service_key = private.get("service", "mot")
    minutes = SERVICES.get(service_key, SERVICES["mot"])["minutes"]
    new_end = new_start + timedelta(minutes=minutes)

    if not is_free(new_start, new_end, ignore_event_id=event_id):
        raise ValueError("slot_taken")

    event["start"] = {
        "dateTime": new_start.astimezone(TIMEZONE).isoformat(),
        "timeZone": str(TIMEZONE),
    }
    event["end"] = {
        "dateTime": new_end.astimezone(TIMEZONE).isoformat(),
        "timeZone": str(TIMEZONE),
    }

    updated = service.events().update(
        calendarId=_calendar_id(),
        eventId=event_id,
        body=event,
    ).execute()

    return {
        "id": updated.get("id"),
        "link": updated.get("htmlLink"),
        "service": service_key,
        "start": new_start.isoformat(),
        "end": new_end.isoformat(),
    }