from __future__ import annotations

import json
import os
from datetime import date, datetime, time, timedelta

from google.oauth2 import service_account
from googleapiclient.discovery import build

from garage_config import GARAGE_CALENDAR_ID, SERVICES, TIMEZONE




































































OPENING_HOUR = int(os.getenv("GARAGE_OPENING_HOUR", "9"))
CLOSING_HOUR = int(os.getenv("GARAGE_CLOSING_HOUR", "17"))
SLOT_INTERVAL_MINUTES = 30


def _load_json() -> dict:
    raw = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    if not raw:
        raise ValueError("Missing GOOGLE_SERVICE_ACCOUNT_JSON")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return json.loads(raw.replace("\\n", "\n"))


def _service():
    creds = service_account.Credentials.from_service_account_info(
        _load_json(),
        scopes=["https://www.googleapis.com/auth/calendar"],
    )
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def _calendar_id() -> str:
    if not GARAGE_CALENDAR_ID:
        raise ValueError("Missing GARAGE_CALENDAR_ID")
    return GARAGE_CALENDAR_ID


def _service_key(key: str) -> str:
    return key if key in SERVICES else "diagnostic"


def is_free(start_dt: datetime, end_dt: datetime, ignore_event_id: str | None = None) -> bool:
    result = _service().events().list(
        calendarId=_calendar_id(),
        timeMin=start_dt.astimezone(TIMEZONE).isoformat(),
        timeMax=end_dt.astimezone(TIMEZONE).isoformat(),
        singleEvents=True,
        orderBy="startTime",
    ).execute()

    for event in result.get("items", []):
        if event.get("status") == "cancelled":
            continue
        if ignore_event_id and event.get("id") == ignore_event_id:
            continue
        return False
    return True


def get_available_slots(
    requested_date: date,
    service_key: str,
    preferred_period: str = "",
    limit: int = 4,
) -> list[datetime]:
    key = _service_key(service_key)
    duration = int(SERVICES[key]["minutes"])
    start = datetime.combine(requested_date, time(OPENING_HOUR), tzinfo=TIMEZONE)
    close = datetime.combine(requested_date, time(CLOSING_HOUR), tzinfo=TIMEZONE)
    now = datetime.now(TIMEZONE)
    slots = []

    while start + timedelta(minutes=duration) <= close:
        if start > now:
            if preferred_period == "morning" and start.hour >= 12:
                pass
            elif preferred_period == "afternoon" and start.hour < 12:
                pass
            elif preferred_period == "evening":
                pass
            elif is_free(start, start + timedelta(minutes=duration)):
                slots.append(start)
                if len(slots) >= limit:
                    break
        start += timedelta(minutes=SLOT_INTERVAL_MINUTES)

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
    key = _service_key(service_key)
    config = SERVICES[key]
    start_dt = start_dt.astimezone(TIMEZONE)
    end_dt = start_dt + timedelta(minutes=int(config["minutes"]))

    if not is_free(start_dt, end_dt):
        raise ValueError("slot_taken")

    vehicle = vehicle or {}
    reg = str(vehicle.get("reg") or vehicle.get("registration") or "Unknown reg")
    make_model = str(vehicle.get("make_model") or "Vehicle not confirmed")

    event = {
        "summary": f"{config['label']} - {reg} - {customer_name}",
        "description": (
            f"Customer: {customer_name}\n"
            f"Phone: {phone}\n"
            f"Service: {config['label']}\n"
            f"Registration: {reg}\n"
            f"Vehicle: {make_model}\n"
            f"Notes: {notes or 'None'}\n\n"
            f"Booked via {source}"
        ),
        "start": {"dateTime": start_dt.isoformat(), "timeZone": str(TIMEZONE)},
        "end": {"dateTime": end_dt.isoformat(), "timeZone": str(TIMEZONE)},
        "extendedProperties": {
            "private": {
                "phone": phone,
                "customer_name": customer_name,
                "service": key,
                "reg": reg,
                "make_model": make_model,
                "notes": notes or "",
                "source": source,
            }
        },
    }

    created = _service().events().insert(
        calendarId=_calendar_id(),
        body=event,
    ).execute()

    return {
        "id": created.get("id"),
        "link": created.get("htmlLink"),
        "service": key,
        "start": start_dt.isoformat(),
        "end": end_dt.isoformat(),
    }


def list_bookings(phone: str) -> list[dict]:
    result = _service().events().list(
        calendarId=_calendar_id(),
        timeMin=datetime.now(TIMEZONE).isoformat(),
        singleEvents=True,
        orderBy="startTime",
        maxResults=50,
    ).execute()

    bookings = []
    for event in result.get("items", []):
        private = ((event.get("extendedProperties") or {}).get("private") or {})
        if event.get("status") == "cancelled" or private.get("phone") != phone:
            continue
        bookings.append({
            "id": event.get("id"),
            "summary": event.get("summary"),
            "start": (event.get("start") or {}).get("dateTime"),
            "end": (event.get("end") or {}).get("dateTime"),
            "link": event.get("htmlLink"),
            **private,
        })
    return bookings


def cancel_booking(event_id: str) -> bool:
    _service().events().delete(calendarId=_calendar_id(), eventId=event_id).execute()
    return True


def reschedule_booking(event_id: str, new_start: datetime) -> dict:
    service = _service()
    event = service.events().get(calendarId=_calendar_id(), eventId=event_id).execute()
    private = ((event.get("extendedProperties") or {}).get("private") or {})
    key = _service_key(private.get("service", "mot"))
    new_end = new_start + timedelta(minutes=int(SERVICES[key]["minutes"]))

    if not is_free(new_start, new_end, ignore_event_id=event_id):
        raise ValueError("slot_taken")

    event["start"] = {"dateTime": new_start.astimezone(TIMEZONE).isoformat(), "timeZone": str(TIMEZONE)}
    event["end"] = {"dateTime": new_end.astimezone(TIMEZONE).isoformat(), "timeZone": str(TIMEZONE)}
    updated = service.events().update(
        calendarId=_calendar_id(),
        eventId=event_id,
        body=event,
    ).execute()
    return {"id": updated.get("id"), "link": updated.get("htmlLink")}
