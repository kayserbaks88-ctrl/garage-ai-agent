from __future__ import annotations

import json
import os
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from google.oauth2 import service_account
from googleapiclient.discovery import build

from trimtech.businesses.garage.config import BUSINESS_CONFIG
from trimtech.businesses.garage.services import (
    GARAGE_SERVICES,
    get_garage_service,
)
from trimtech.core.business import ServiceDefinition


GARAGE_CALENDAR_ID = os.getenv(
    "GARAGE_CALENDAR_ID",
    "",
).strip()

TIMEZONE = ZoneInfo(
    BUSINESS_CONFIG.timezone_name
)

OPENING_HOUR = int(
    os.getenv(
        "GARAGE_OPENING_HOUR",
        "9",
    )
)

CLOSING_HOUR = int(
    os.getenv(
        "GARAGE_CLOSING_HOUR",
        "17",
    )
)

SLOT_INTERVAL_MINUTES = int(
    os.getenv(
        "GARAGE_SLOT_INTERVAL_MINUTES",
        "30",
    )
)

DEFAULT_SERVICE_KEY = "diagnostic"


def _load_json() -> dict:
    raw = os.getenv(
        "GOOGLE_SERVICE_ACCOUNT_JSON",
        "",
    ).strip()

    if not raw:
        raise ValueError(
            "Missing GOOGLE_SERVICE_ACCOUNT_JSON"
        )

    try:
        credentials = json.loads(raw)

    except json.JSONDecodeError:
        credentials = json.loads(
            raw.replace("\\n", "\n")
        )

    if not isinstance(credentials, dict):
        raise ValueError(
            "GOOGLE_SERVICE_ACCOUNT_JSON must contain a JSON object."
        )

    return credentials


def _service():
    credentials = (
        service_account.Credentials
        .from_service_account_info(
            _load_json(),
            scopes=[
                "https://www.googleapis.com/auth/calendar",
            ],
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
        raise ValueError(
            "Missing GARAGE_CALENDAR_ID"
        )

    return GARAGE_CALENDAR_ID


def _service_definition(
    value: str | None,
) -> ServiceDefinition:
    service = get_garage_service(
        str(value or "").strip()
    )

    if service is not None and service.enabled:
        return service

    fallback = get_garage_service(
        DEFAULT_SERVICE_KEY
    )

    if fallback is None:
        raise RuntimeError(
            "The default garage service is not configured."
        )

    return fallback


def _service_key(
    value: str | None,
) -> str:
    return _service_definition(value).key


def _ensure_timezone(
    value: datetime,
) -> datetime:
    if value.tzinfo is None:
        return value.replace(
            tzinfo=TIMEZONE
        )

    return value.astimezone(
        TIMEZONE
    )


def is_free(
    start_dt: datetime,
    end_dt: datetime,
    ignore_event_id: str | None = None,
) -> bool:
    start_dt = _ensure_timezone(start_dt)
    end_dt = _ensure_timezone(end_dt)

    result = (
        _service()
        .events()
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
        if event.get("status") == "cancelled":
            continue

        if (
            ignore_event_id
            and event.get("id") == ignore_event_id
        ):
            continue

        return False

    return True


def get_available_slots(
    requested_date: date,
    service_key: str,
    preferred_period: str = "",
    limit: int = 4,
) -> list[datetime]:
    service_definition = _service_definition(
        service_key
    )

    duration = int(
        service_definition.duration_minutes
    )

    current_slot = datetime.combine(
        requested_date,
        time(OPENING_HOUR),
        tzinfo=TIMEZONE,
    )

    closing_time = datetime.combine(
        requested_date,
        time(CLOSING_HOUR),
        tzinfo=TIMEZONE,
    )

    now = datetime.now(
        TIMEZONE
    )

    preferred_period = str(
        preferred_period or ""
    ).strip().lower()

    slots: list[datetime] = []

    while (
        current_slot
        + timedelta(minutes=duration)
        <= closing_time
    ):
        slot_end = current_slot + timedelta(
            minutes=duration
        )

        if current_slot > now:
            period_matches = True

            if preferred_period == "morning":
                period_matches = (
                    current_slot.hour < 12
                )

            elif preferred_period == "afternoon":
                period_matches = (
                    12 <= current_slot.hour < 17
                )

            elif preferred_period == "evening":
                period_matches = (
                    current_slot.hour >= 17
                )

            if (
                period_matches
                and is_free(
                    current_slot,
                    slot_end,
                )
            ):
                slots.append(
                    current_slot
                )

                if len(slots) >= max(
                    1,
                    int(limit),
                ):
                    break

        current_slot += timedelta(
            minutes=SLOT_INTERVAL_MINUTES
        )

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
    service_definition = _service_definition(
        service_key
    )

    start_dt = _ensure_timezone(
        start_dt
    )

    end_dt = start_dt + timedelta(
        minutes=int(
            service_definition.duration_minutes
        )
    )

    if not is_free(
        start_dt,
        end_dt,
    ):
        raise ValueError(
            "slot_taken"
        )

    vehicle = vehicle or {}

    registration = str(
        vehicle.get("reg")
        or vehicle.get("registration")
        or "Unknown reg"
    ).strip().upper()

    make_model = str(
        vehicle.get("make_model")
        or vehicle.get("vehicle")
        or "Vehicle not confirmed"
    ).strip()

    customer_name = str(
        customer_name or "Customer"
    ).strip()

    phone = str(
        phone or ""
    ).strip()

    notes = str(
        notes or ""
    ).strip()

    source = str(
        source or "TrimTech AI"
    ).strip()

    event = {
        "summary": (
            f"{service_definition.name} - "
            f"{registration} - "
            f"{customer_name}"
        ),
        "description": (
            f"Customer: {customer_name}\n"
            f"Phone: {phone}\n"
            f"Service: {service_definition.name}\n"
            f"Registration: {registration}\n"
            f"Vehicle: {make_model}\n"
            f"Notes: {notes or 'None'}\n\n"
            f"Booked via {source}"
        ),
        "start": {
            "dateTime": start_dt.isoformat(),
            "timeZone": BUSINESS_CONFIG.timezone_name,
        },
        "end": {
            "dateTime": end_dt.isoformat(),
            "timeZone": BUSINESS_CONFIG.timezone_name,
        },
        "extendedProperties": {
            "private": {
                "phone": phone,
                "customer_name": customer_name,
                "service": service_definition.key,
                "registration": registration,
                "reg": registration,
                "make_model": make_model,
                "notes": notes,
                "source": source,
                "business_id": (
                    BUSINESS_CONFIG.business_id
                ),
                "business_type": (
                    BUSINESS_CONFIG.business_type
                ),
            }
        },
    }

    created = (
        _service()
        .events()
        .insert(
            calendarId=_calendar_id(),
            body=event,
        )
        .execute()
    )

    return {
        "id": created.get("id"),
        "link": created.get("htmlLink"),
        "service": service_definition.key,
        "service_name": service_definition.name,
        "start": start_dt.isoformat(),
        "end": end_dt.isoformat(),
    }


def list_bookings(
    phone: str,
) -> list[dict]:
    phone = str(
        phone or ""
    ).strip()

    result = (
        _service()
        .events()
        .list(
            calendarId=_calendar_id(),
            timeMin=datetime.now(
                TIMEZONE
            ).isoformat(),
            singleEvents=True,
            orderBy="startTime",
            maxResults=50,
        )
        .execute()
    )

    bookings: list[dict] = []

    for event in result.get("items", []):
        private = (
            (
                event.get(
                    "extendedProperties"
                )
                or {}
            )
            .get(
                "private"
            )
            or {}
        )

        if event.get("status") == "cancelled":
            continue

        if private.get("phone") != phone:
            continue

        bookings.append(
            {
                "id": event.get("id"),
                "summary": event.get(
                    "summary"
                ),
                "start": (
                    event.get("start")
                    or {}
                ).get("dateTime"),
                "end": (
                    event.get("end")
                    or {}
                ).get("dateTime"),
                "link": event.get(
                    "htmlLink"
                ),
                **private,
            }
        )

    return bookings


def cancel_booking(
    event_id: str,
) -> bool:
    event_id = str(
        event_id or ""
    ).strip()

    if not event_id:
        raise ValueError(
            "Missing event_id"
        )

    (
        _service()
        .events()
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
    event_id = str(
        event_id or ""
    ).strip()

    if not event_id:
        raise ValueError(
            "Missing event_id"
        )

    calendar_service = _service()

    event = (
        calendar_service
        .events()
        .get(
            calendarId=_calendar_id(),
            eventId=event_id,
        )
        .execute()
    )

    private = (
        (
            event.get(
                "extendedProperties"
            )
            or {}
        )
        .get(
            "private"
        )
        or {}
    )

    service_definition = _service_definition(
        private.get(
            "service",
            DEFAULT_SERVICE_KEY,
        )
    )

    new_start = _ensure_timezone(
        new_start
    )

    new_end = new_start + timedelta(
        minutes=int(
            service_definition.duration_minutes
        )
    )

    if not is_free(
        new_start,
        new_end,
        ignore_event_id=event_id,
    ):
        raise ValueError(
            "slot_taken"
        )

    event["start"] = {
        "dateTime": new_start.isoformat(),
        "timeZone": BUSINESS_CONFIG.timezone_name,
    }

    event["end"] = {
        "dateTime": new_end.isoformat(),
        "timeZone": BUSINESS_CONFIG.timezone_name,
    }

    private["service"] = (
        service_definition.key
    )

    private["business_id"] = (
        BUSINESS_CONFIG.business_id
    )

    private["business_type"] = (
        BUSINESS_CONFIG.business_type
    )

    event.setdefault(
        "extendedProperties",
        {},
    )["private"] = private

    updated = (
        calendar_service
        .events()
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
        "service": service_definition.key,
        "service_name": service_definition.name,
        "start": new_start.isoformat(),
        "end": new_end.isoformat(),
    }


def configured_services() -> tuple[dict, ...]:
    """
    Diagnostic helper for confirming that Calendar is using the
    services from the new TrimTech Garage configuration.
    """

    return tuple(
        {
            "key": service.key,
            "name": service.name,
            "duration_minutes": (
                service.duration_minutes
            ),
            "price": service.price,
        }
        for service in GARAGE_SERVICES
        if service.enabled
    )