from __future__ import annotations

import json
import os
import re
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from google.oauth2 import service_account
from googleapiclient.discovery import build

from trimtech.core.business import BusinessConfig, ServiceDefinition

GOOGLE_CALENDAR_SCOPES = [
    "https://www.googleapis.com/auth/calendar",
]

DEFAULT_OPENING_HOUR = 9
DEFAULT_CLOSING_HOUR = 17
DEFAULT_SLOT_INTERVAL_MINUTES = 30


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _env_prefix(value: Any) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", _clean_text(value))
    return cleaned.strip("_").upper()


def business_env_prefix(business: BusinessConfig) -> str:
    return _env_prefix(business.business_id)


def _is_legacy_garage(business: BusinessConfig) -> bool:
    return _clean_text(business.business_id).lower() in {
        "trimtech-garage",
        "garage",
    }


def _metadata_value(business: BusinessConfig, key: str) -> Any:
    metadata = getattr(business, "metadata", {})
    return metadata.get(key) if isinstance(metadata, dict) else None


def _int_setting(
    business: BusinessConfig,
    *,
    metadata_key: str,
    env_suffix: str,
    default: int,
    legacy_env_name: str | None = None,
) -> int:
    metadata_value = _metadata_value(business, metadata_key)

    if metadata_value not in {None, ""}:
        try:
            return int(metadata_value)
        except (TypeError, ValueError):
            pass

    prefix = business_env_prefix(business)
    env_value = _clean_text(os.getenv(f"{prefix}_{env_suffix}"))

    if not env_value and legacy_env_name and _is_legacy_garage(business):
        env_value = _clean_text(os.getenv(legacy_env_name))

    if env_value:
        try:
            return int(env_value)
        except ValueError:
            pass

    return int(default)


def timezone_name(business: BusinessConfig) -> str:
    return business.timezone_name


def timezone(business: BusinessConfig):
    return business.timezone


def opening_hour(business: BusinessConfig) -> int:
    return _int_setting(
        business,
        metadata_key="opening_hour",
        env_suffix="OPENING_HOUR",
        legacy_env_name="GARAGE_OPENING_HOUR",
        default=DEFAULT_OPENING_HOUR,
    )


def closing_hour(business: BusinessConfig) -> int:
    return _int_setting(
        business,
        metadata_key="closing_hour",
        env_suffix="CLOSING_HOUR",
        legacy_env_name="GARAGE_CLOSING_HOUR",
        default=DEFAULT_CLOSING_HOUR,
    )


def slot_interval_minutes(business: BusinessConfig) -> int:
    return max(
        5,
        _int_setting(
            business,
            metadata_key="slot_interval_minutes",
            env_suffix="SLOT_INTERVAL_MINUTES",
            legacy_env_name="GARAGE_SLOT_INTERVAL_MINUTES",
            default=DEFAULT_SLOT_INTERVAL_MINUTES,
        ),
    )


def calendar_id(business: BusinessConfig) -> str:
    metadata_calendar_id = _clean_text(
        _metadata_value(business, "calendar_id")
    )
    if metadata_calendar_id:
        return metadata_calendar_id

    prefix = business_env_prefix(business)
    value = _clean_text(os.getenv(f"{prefix}_CALENDAR_ID"))
    if value:
        return value

    if _is_legacy_garage(business):
        value = _clean_text(os.getenv("GARAGE_CALENDAR_ID"))
        if value:
            return value

    return ""


def required_calendar_env_name(business: BusinessConfig) -> str:
    if _is_legacy_garage(business):
        return "GARAGE_CALENDAR_ID"
    return f"{business_env_prefix(business)}_CALENDAR_ID"


def service_definition(
    business: BusinessConfig,
    value: Any,
) -> ServiceDefinition:
    service = business.resolve_service(value)

    if service is not None and service.enabled:
        return service

    raise ValueError("invalid_service")


def configured_services(
    business: BusinessConfig,
) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "key": service.key,
            "name": service.name,
            "duration_minutes": service.duration_minutes,
            "price": service.price,
        }
        for service in business.enabled_services()
    )


def _load_credentials_json(raw: str) -> dict[str, Any]:
    try:
        credentials = json.loads(raw)
    except json.JSONDecodeError:
        credentials = json.loads(raw.replace("\\n", "\n"))

    if not isinstance(credentials, dict):
        raise ValueError(
            "Google service account JSON must contain an object."
        )

    return credentials


def load_google_credentials(business: BusinessConfig):
    prefix = business_env_prefix(business)

    business_raw = _clean_text(
        os.getenv(f"{prefix}_GOOGLE_SERVICE_ACCOUNT_JSON")
    )
    shared_raw = _clean_text(
        os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    )
    raw = business_raw or shared_raw

    if raw:
        return (
            service_account.Credentials.from_service_account_info(
                _load_credentials_json(raw),
                scopes=GOOGLE_CALENDAR_SCOPES,
            )
        )

    business_path = _clean_text(
        os.getenv(f"{prefix}_GOOGLE_APPLICATION_CREDENTIALS")
    )
    shared_path = _clean_text(
        os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    )
    credentials_path = business_path or shared_path

    if credentials_path:
        path = Path(credentials_path)
        if path.exists():
            return (
                service_account.Credentials.from_service_account_file(
                    str(path),
                    scopes=GOOGLE_CALENDAR_SCOPES,
                )
            )

    raise RuntimeError("Google Calendar credentials were not found.")


def calendar_service(business: BusinessConfig):
    return build(
        "calendar",
        "v3",
        credentials=load_google_credentials(business),
        cache_discovery=False,
    )


def ensure_timezone(
    business: BusinessConfig,
    value: datetime,
) -> datetime:
    business_timezone = timezone(business)

    if value.tzinfo is None:
        return value.replace(tzinfo=business_timezone)

    return value.astimezone(business_timezone)


def _required_calendar_id(business: BusinessConfig) -> str:
    value = calendar_id(business)

    if not value:
        raise ValueError(
            f"Missing {required_calendar_env_name(business)}"
        )

    return value


def is_free(
    business: BusinessConfig,
    start_dt: datetime,
    end_dt: datetime,
    ignore_event_id: str | None = None,
) -> bool:
    start_dt = ensure_timezone(business, start_dt)
    end_dt = ensure_timezone(business, end_dt)

    result = (
        calendar_service(business)
        .events()
        .list(
            calendarId=_required_calendar_id(business),
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

        if ignore_event_id and event.get("id") == ignore_event_id:
            continue

        return False

    return True


def get_available_slots(
    business: BusinessConfig,
    requested_date: date,
    service_key: str,
    preferred_period: str = "",
    limit: int = 4,
) -> list[datetime]:
    service = service_definition(business, service_key)
    duration = int(service.duration_minutes)
    business_timezone = timezone(business)

    current_slot = datetime.combine(
        requested_date,
        time(opening_hour(business)),
        tzinfo=business_timezone,
    )
    closing_time = datetime.combine(
        requested_date,
        time(closing_hour(business)),
        tzinfo=business_timezone,
    )
    now = datetime.now(business_timezone)
    preferred_period = _clean_text(preferred_period).lower()

    slots: list[datetime] = []

    while current_slot + timedelta(minutes=duration) <= closing_time:
        slot_end = current_slot + timedelta(minutes=duration)

        if current_slot > now:
            period_matches = True

            if preferred_period == "morning":
                period_matches = current_slot.hour < 12
            elif preferred_period == "afternoon":
                period_matches = 12 <= current_slot.hour < 17
            elif preferred_period == "evening":
                period_matches = current_slot.hour >= 17

            if period_matches and is_free(
                business,
                current_slot,
                slot_end,
            ):
                slots.append(current_slot)

                if len(slots) >= max(1, int(limit)):
                    break

        current_slot += timedelta(
            minutes=slot_interval_minutes(business)
        )

    return slots


def create_booking(
    business: BusinessConfig,
    *,
    phone: str,
    service_key: str,
    start_dt: datetime,
    customer_name: str,
    vehicle: dict[str, Any],
    notes: str = "",
    source: str = "TrimTech AI",
) -> dict[str, Any]:
    service = service_definition(business, service_key)
    start_dt = ensure_timezone(business, start_dt)
    end_dt = start_dt + timedelta(
        minutes=int(service.duration_minutes)
    )

    if not is_free(business, start_dt, end_dt):
        raise ValueError("slot_taken")

    vehicle = vehicle or {}

    registration = _clean_text(
        vehicle.get("reg")
        or vehicle.get("registration")
        or vehicle.get("vehicle_reg")
        or vehicle.get("registrationNumber")
        or "Unknown reg"
    ).upper()

    make = _clean_text(
        vehicle.get("make")
        or vehicle.get("vehicle_make")
        or vehicle.get("manufacturer")
    )

    model = _clean_text(
        vehicle.get("model")
        or vehicle.get("vehicle_model")
    )

    colour = _clean_text(
        vehicle.get("colour")
        or vehicle.get("color")
        or vehicle.get("vehicle_colour")
    )

    year = _clean_text(
        vehicle.get("year")
        or vehicle.get("manufacture_year")
        or vehicle.get("year_of_manufacture")
        or vehicle.get("yearOfManufacture")
    )

    fuel_type = _clean_text(
        vehicle.get("fuel_type")
        or vehicle.get("fuel")
        or vehicle.get("fuelType")
    )

    mot_status = _clean_text(
        vehicle.get("mot_status")
        or vehicle.get("mot")
        or vehicle.get("motStatus")
    )

    mot_expiry_date = _clean_text(
        vehicle.get("mot_expiry_date")
        or vehicle.get("mot_expiry")
        or vehicle.get("motExpiryDate")
    )

    supplied_make_model = _clean_text(
        vehicle.get("make_model")
        or vehicle.get("vehicle")
    )

    make_model = (
        supplied_make_model
        or " ".join(
            part
            for part in (make, model)
            if part
        ).strip()
        or "Vehicle not confirmed"
    )

    # Some DVLA payloads only contain make, not model.
    # If make_model is populated but make is not, preserve the available
    # vehicle identity in the make field so the dashboard can display it.
    if not make and supplied_make_model:
        make = supplied_make_model

    customer_name = _clean_text(customer_name) or "Customer"
    phone = _clean_text(phone)
    notes = _clean_text(notes)
    source = _clean_text(source) or "TrimTech AI"

    event = {
        "summary": (
            f"{service.name} - {registration} - {customer_name}"
        ),
        "description": (
            f"Customer: {customer_name}\n"
            f"Phone: {phone}\n"
            f"Service: {service.name}\n"
            f"Registration: {registration}\n"
            f"Vehicle: {make_model}\n"
            f"Make: {make or 'Not recorded'}\n"
            f"Model: {model or 'Not recorded'}\n"
            f"Colour: {colour or 'Not recorded'}\n"
            f"Year: {year or 'Not recorded'}\n"
            f"Fuel type: {fuel_type or 'Not recorded'}\n"
            f"MOT status: {mot_status or 'Not recorded'}\n"
            f"MOT expiry date: {mot_expiry_date or 'Not recorded'}\n"
            f"Notes: {notes or 'None'}\n\n"
            f"Booked via {source}"
        ),
        "start": {
            "dateTime": start_dt.isoformat(),
            "timeZone": timezone_name(business),
        },
        "end": {
            "dateTime": end_dt.isoformat(),
            "timeZone": timezone_name(business),
        },
        "extendedProperties": {
            "private": {
                "phone": phone,
                "customer_name": customer_name,
                "service": service.key,
                "registration": registration,
                "reg": registration,
                "vehicle_reg": registration,
                "make_model": make_model,
                "make": make,
                "model": model,
                "colour": colour,
                "year": year,
                "fuel_type": fuel_type,
                "mot_status": mot_status,
                "mot_expiry_date": mot_expiry_date,
                "notes": notes,
                "source": source,
                "business_id": business.business_id,
                "business_type": business.business_type,
            }
        },
    }

    created = (
        calendar_service(business)
        .events()
        .insert(
            calendarId=_required_calendar_id(business),
            body=event,
        )
        .execute()
    )

    return {
        "id": created.get("id"),
        "link": created.get("htmlLink"),
        "service": service.key,
        "service_name": service.name,
        "start": start_dt.isoformat(),
        "end": end_dt.isoformat(),
        "business_id": business.business_id,
        "vehicle": {
            "registration": registration,
            "make": make,
            "model": model,
            "colour": colour,
            "year": year,
            "fuel_type": fuel_type,
            "mot_status": mot_status,
            "mot_expiry_date": mot_expiry_date,
        },
    }


def list_bookings(
    business: BusinessConfig,
    phone: str,
) -> list[dict[str, Any]]:
    phone = _clean_text(phone)

    result = (
        calendar_service(business)
        .events()
        .list(
            calendarId=_required_calendar_id(business),
            timeMin=datetime.now(timezone(business)).isoformat(),
            singleEvents=True,
            orderBy="startTime",
            maxResults=50,
        )
        .execute()
    )

    bookings: list[dict[str, Any]] = []

    for event in result.get("items", []):
        private = (
            (event.get("extendedProperties") or {})
            .get("private")
            or {}
        )

        if event.get("status") == "cancelled":
            continue

        event_business_id = _clean_text(
            private.get("business_id")
        )

        if (
            event_business_id
            and event_business_id != business.business_id
        ):
            continue

        if _clean_text(private.get("phone")) != phone:
            continue

        bookings.append(
            {
                "id": event.get("id"),
                "summary": event.get("summary"),
                "start": (event.get("start") or {}).get("dateTime"),
                "end": (event.get("end") or {}).get("dateTime"),
                "link": event.get("htmlLink"),
                **private,
            }
        )

    return bookings


def cancel_booking(
    business: BusinessConfig,
    event_id: str,
) -> bool:
    event_id = _clean_text(event_id)

    if not event_id:
        raise ValueError("Missing event_id")

    (
        calendar_service(business)
        .events()
        .delete(
            calendarId=_required_calendar_id(business),
            eventId=event_id,
        )
        .execute()
    )

    return True


def reschedule_booking(
    business: BusinessConfig,
    *,
    event_id: str,
    new_start: datetime,
) -> dict[str, Any]:
    event_id = _clean_text(event_id)

    if not event_id:
        raise ValueError("Missing event_id")

    calendar_id_value = _required_calendar_id(business)
    service_api = calendar_service(business)

    event = (
        service_api
        .events()
        .get(
            calendarId=calendar_id_value,
            eventId=event_id,
        )
        .execute()
    )

    private = (
        (event.get("extendedProperties") or {})
        .get("private")
        or {}
    )

    event_business_id = _clean_text(
        private.get("business_id")
    )

    if (
        event_business_id
        and event_business_id != business.business_id
    ):
        raise PermissionError("booking_business_mismatch")

    service = service_definition(
        business,
        private.get("service"),
    )

    new_start = ensure_timezone(business, new_start)
    new_end = new_start + timedelta(
        minutes=int(service.duration_minutes)
    )

    if not is_free(
        business,
        new_start,
        new_end,
        ignore_event_id=event_id,
    ):
        raise ValueError("slot_taken")

    event["start"] = {
        "dateTime": new_start.isoformat(),
        "timeZone": timezone_name(business),
    }
    event["end"] = {
        "dateTime": new_end.isoformat(),
        "timeZone": timezone_name(business),
    }

    private["service"] = service.key
    private["business_id"] = business.business_id
    private["business_type"] = business.business_type

    event.setdefault("extendedProperties", {})["private"] = private

    updated = (
        service_api
        .events()
        .update(
            calendarId=calendar_id_value,
            eventId=event_id,
            body=event,
        )
        .execute()
    )

    return {
        "id": updated.get("id"),
        "link": updated.get("htmlLink"),
        "service": service.key,
        "service_name": service.name,
        "start": new_start.isoformat(),
        "end": new_end.isoformat(),
        "business_id": business.business_id,
    }