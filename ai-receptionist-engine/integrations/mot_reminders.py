from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from typing import Any

from integrations.customer_history import get_customer_events
from integrations.garage_calendar import (
    _calendar_id,
    _get_calendar_service,
    normalise_phone,
)
from integrations.garage_config import TIMEZONE
from integrations.reminder_sender import send_whatsapp_template


MOT_REMINDER_DAYS = (30, 7, 0)
CUSTOMER_LOOKBACK_YEARS = 10


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()

    if not value:
        raise ValueError(f"Missing {name}")

    return value


def _clean_registration(registration: str) -> str:
    return "".join(
        character
        for character in str(registration or "").upper()
        if character.isalnum()
    )


def _display_registration(registration: str) -> str:
    cleaned = _clean_registration(registration)

    if len(cleaned) > 3:
        return f"{cleaned[:-3]} {cleaned[-3:]}"

    return cleaned


def _parse_date(value: Any) -> date | None:
    """
    Accept MOT dates in common formats, including:

    2026-08-31
    31/08/2026
    31-08-2026
    31 August 2026
    """
    raw_value = str(value or "").strip()

    if not raw_value:
        return None

    formats = (
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%d %B %Y",
        "%d %b %Y",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S%z",
    )

    cleaned_value = raw_value.replace("Z", "+00:00")

    for date_format in formats:
        try:
            parsed = datetime.strptime(
                cleaned_value,
                date_format,
            )
            return parsed.date()
        except ValueError:
            continue

    try:
        return datetime.fromisoformat(
            cleaned_value
        ).date()
    except ValueError:
        return None


def _format_date(value: date) -> str:
    return value.strftime("%A %-d %B %Y")


def _private_data(event: dict) -> dict:
    return (
        (event.get("extendedProperties") or {})
        .get("private")
        or {}
    )


def _event_datetime(event: dict) -> datetime | None:
    raw_value = str(
        (event.get("start") or {}).get("dateTime")
        or ""
    ).strip()

    if not raw_value:
        return None

    try:
        parsed = datetime.fromisoformat(
            raw_value.replace("Z", "+00:00")
        )
    except ValueError:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=TIMEZONE)

    return parsed.astimezone(TIMEZONE)


def _fetch_calendar_events() -> list[dict]:
    """
    Retrieve historical and future garage appointments.

    Vehicle and MOT information is stored in the private metadata
    of these Google Calendar events.
    """
    now = datetime.now(TIMEZONE)

    time_min = now - timedelta(
        days=365 * CUSTOMER_LOOKBACK_YEARS
    )

    time_max = now + timedelta(
        days=365 * 2
    )

    service = _get_calendar_service()

    events: list[dict] = []
    page_token: str | None = None

    while True:
        result = (
            service.events()
            .list(
                calendarId=_calendar_id(),
                timeMin=time_min.isoformat(),
                timeMax=time_max.isoformat(),
                singleEvents=True,
                orderBy="startTime",
                maxResults=2500,
                pageToken=page_token,
            )
            .execute()
        )

        events.extend(
            result.get("items", [])
        )

        page_token = result.get(
            "nextPageToken"
        )

        if not page_token:
            break

    return events


def _extract_vehicle_record(
    event: dict,
) -> dict[str, Any] | None:
    if event.get("status") == "cancelled":
        return None

    private = _private_data(event)

    phone = normalise_phone(
        private.get("phone") or ""
    )

    registration = (
        private.get("registration")
        or private.get("reg")
        or private.get("vehicle_reg")
        or ""
    )

    registration_key = _clean_registration(
        registration
    )

    mot_expiry = _parse_date(
        private.get("mot_expiry")
        or private.get("mot_due_date")
        or private.get("motExpiryDate")
        or ""
    )

    if (
        not phone
        or not registration_key
        or not mot_expiry
    ):
        return None

    event_time = _event_datetime(event)

    return {
        "event_id": event.get("id", ""),
        "event": event,
        "event_time": event_time,
        "phone": phone,
        "customer_name": str(
            private.get("customer_name")
            or private.get("name")
            or "Customer"
        ).strip(),
        "registration": _display_registration(
            registration
        ),
        "registration_key": registration_key,
        "vehicle_make": str(
            private.get("vehicle_make")
            or private.get("make")
            or ""
        ).strip(),
        "vehicle_model": str(
            private.get("vehicle_model")
            or private.get("model")
            or ""
        ).strip(),
        "mot_expiry": mot_expiry,
        "private": private,
    }


def _latest_vehicle_records() -> list[dict[str, Any]]:
    """
    Deduplicate repeated calendar records.

    One customer may have several appointments for the same car.
    The latest appointment containing MOT information is used.
    """
    records: dict[
        tuple[str, str],
        dict[str, Any],
    ] = {}

    for event in _fetch_calendar_events():
        record = _extract_vehicle_record(event)

        if not record:
            continue

        key = (
            record["phone"],
            record["registration_key"],
        )

        existing = records.get(key)

        if not existing:
            records[key] = record
            continue

        existing_time = existing.get(
            "event_time"
        )

        new_time = record.get(
            "event_time"
        )

        if (
            new_time is not None
            and (
                existing_time is None
                or new_time > existing_time
            )
        ):
            records[key] = record

    return list(records.values())


def _reminder_metadata_key(
    days_before: int,
    mot_expiry: date,
) -> str:
    """
    Include the expiry date in the key.

    This allows a fresh reminder cycle after the MOT expiry
    is updated next year.
    """
    expiry_key = mot_expiry.strftime(
        "%Y%m%d"
    )

    if days_before == 0:
        return f"mot_due_today_{expiry_key}_sent"

    return (
        f"mot_{days_before}d_{expiry_key}_sent"
    )


def _content_sid_for_days(
    days_before: int,
) -> str:
    if days_before == 30:
        return _required_env(
            "TWILIO_MOT_30D_CONTENT_SID"
        )

    if days_before == 7:
        return _required_env(
            "TWILIO_MOT_7D_CONTENT_SID"
        )

    if days_before == 0:
        return _required_env(
            "TWILIO_MOT_DUE_CONTENT_SID"
        )

    raise ValueError(
        f"Unsupported MOT reminder day: {days_before}"
    )


def _vehicle_description(
    record: dict[str, Any],
) -> str:
    parts = [
        record.get("vehicle_make", ""),
        record.get("vehicle_model", ""),
    ]

    description = " ".join(
        part.strip()
        for part in parts
        if str(part).strip()
    )

    return description or "your vehicle"


def _mark_reminder_sent(
    record: dict[str, Any],
    metadata_key: str,
    message_sid: str,
    sent_at: datetime,
) -> None:
    event = record["event"]

    extended_properties = (
        event.get("extendedProperties")
        or {}
    )

    private = (
        extended_properties.get("private")
        or {}
    )

    private[metadata_key] = (
        sent_at.isoformat()
    )

    if message_sid:
        private[f"{metadata_key}_sid"] = (
            message_sid
        )

    extended_properties["private"] = private
    event["extendedProperties"] = (
        extended_properties
    )

    (
        _get_calendar_service()
        .events()
        .update(
            calendarId=_calendar_id(),
            eventId=record["event_id"],
            body=event,
        )
        .execute()
    )

    record["private"] = private


def _send_mot_reminder(
    record: dict[str, Any],
    days_before: int,
    current_time: datetime,
) -> dict[str, Any] | None:
    metadata_key = _reminder_metadata_key(
        days_before=days_before,
        mot_expiry=record["mot_expiry"],
    )

    if record["private"].get(
        metadata_key
    ):
        return None

    result = send_whatsapp_template(
        phone=record["phone"],
        content_sid=_content_sid_for_days(
            days_before
        ),
        variables={
            "1": record["customer_name"],
            "2": record["registration"],
            "3": _vehicle_description(record),
            "4": _format_date(
                record["mot_expiry"]
            ),
        },
    )

    _mark_reminder_sent(
        record=record,
        metadata_key=metadata_key,
        message_sid=str(
            result.get("sid") or ""
        ),
        sent_at=current_time,
    )

    print(
        "MOT REMINDER SENT:",
        days_before,
        record["phone"],
        record["registration"],
        record["mot_expiry"],
    )

    return {
        "type": (
            "mot_due_today"
            if days_before == 0
            else f"mot_{days_before}_days"
        ),
        "phone": record["phone"],
        "customer_name": record[
            "customer_name"
        ],
        "registration": record[
            "registration"
        ],
        "mot_expiry": record[
            "mot_expiry"
        ].isoformat(),
        "message_sid": result.get("sid"),
        "event_id": record["event_id"],
    }


def process_mot_reminders(
    now: datetime | None = None,
) -> dict[str, Any]:
    """
    Send MOT reminders that are due today.

    Reminder stages:
    - 30 days before expiry
    - 7 days before expiry
    - On the expiry date
    """
    current_time = (
        now.astimezone(TIMEZONE)
        if now is not None
        else datetime.now(TIMEZONE)
    )

    today = current_time.date()

    records = _latest_vehicle_records()

    sent: list[dict[str, Any]] = []
    skipped = 0
    errors: list[dict[str, Any]] = []

    print(
        "MOT REMINDER CHECK STARTED:",
        current_time.isoformat(),
        "VEHICLES:",
        len(records),
    )

    for record in records:
        days_until_expiry = (
            record["mot_expiry"] - today
        ).days

        if days_until_expiry not in (
            MOT_REMINDER_DAYS
        ):
            skipped += 1
            continue

        try:
            result = _send_mot_reminder(
                record=record,
                days_before=days_until_expiry,
                current_time=current_time,
            )

            if result:
                sent.append(result)
            else:
                skipped += 1

        except Exception as error:
            error_record = {
                "phone": record.get(
                    "phone",
                    "",
                ),
                "registration": record.get(
                    "registration",
                    "",
                ),
                "mot_expiry": record[
                    "mot_expiry"
                ].isoformat(),
                "error": repr(error),
            }

            errors.append(error_record)

            print(
                "MOT REMINDER ERROR:",
                error_record,
            )

    summary = {
        "success": len(errors) == 0,
        "checked_at": (
            current_time.isoformat()
        ),
        "vehicles_checked": len(records),
        "sent_count": len(sent),
        "sent": sent,
        "skipped_count": skipped,
        "error_count": len(errors),
        "errors": errors,
    }

    print(
        "MOT REMINDER CHECK COMPLETE:",
        summary,
    )

    return summary


def update_vehicle_mot_expiry(
    phone: str,
    registration: str,
    mot_expiry: str | date,
) -> dict[str, Any]:
    """
    Update the MOT expiry date across the customer's matching
    calendar records.

    This can later be called after a DVLA lookup or when the garage
    manually confirms a new MOT expiry date.
    """
    normalised_phone = normalise_phone(
        phone
    )

    registration_key = _clean_registration(
        registration
    )

    parsed_expiry = (
        mot_expiry
        if isinstance(mot_expiry, date)
        else _parse_date(mot_expiry)
    )

    if not normalised_phone:
        raise ValueError(
            "Missing customer phone number"
        )

    if not registration_key:
        raise ValueError(
            "Missing vehicle registration"
        )

    if not parsed_expiry:
        raise ValueError(
            "Invalid MOT expiry date"
        )

    customer_events = get_customer_events(
        phone=normalised_phone,
        include_cancelled=True,
        include_future=True,
        limit=500,
    )

    service = _get_calendar_service()

    updated_count = 0
    updated_event_ids: list[str] = []

    for customer_event in customer_events:
        event_registration_key = (
            _clean_registration(
                customer_event.get(
                    "registration",
                    "",
                )
            )
        )

        if (
            event_registration_key
            != registration_key
        ):
            continue

        event_id = customer_event.get(
            "event_id",
            "",
        )

        if not event_id:
            continue

        event = (
            service.events()
            .get(
                calendarId=_calendar_id(),
                eventId=event_id,
            )
            .execute()
        )

        extended_properties = (
            event.get("extendedProperties")
            or {}
        )

        private = (
            extended_properties.get("private")
            or {}
        )

        private["mot_expiry"] = (
            parsed_expiry.isoformat()
        )

        private["mot_updated_at"] = (
            datetime.now(
                TIMEZONE
            ).isoformat()
        )

        extended_properties["private"] = (
            private
        )

        event["extendedProperties"] = (
            extended_properties
        )

        (
            service.events()
            .update(
                calendarId=_calendar_id(),
                eventId=event_id,
                body=event,
            )
            .execute()
        )

        updated_count += 1
        updated_event_ids.append(
            event_id
        )

    return {
        "success": True,
        "phone": normalised_phone,
        "registration": (
            _display_registration(
                registration
            )
        ),
        "mot_expiry": (
            parsed_expiry.isoformat()
        ),
        "updated_events": updated_count,
        "event_ids": updated_event_ids,
    }


def get_upcoming_mot_expiries(
    days_ahead: int = 60,
) -> list[dict[str, Any]]:
    """
    Return vehicles whose MOT expires within the requested period.

    This will later be useful for the garage dashboard and reports.
    """
    today = datetime.now(
        TIMEZONE
    ).date()

    maximum_date = today + timedelta(
        days=max(1, int(days_ahead))
    )

    due_vehicles: list[dict[str, Any]] = []

    for record in _latest_vehicle_records():
        expiry = record["mot_expiry"]

        if today <= expiry <= maximum_date:
            due_vehicles.append(
                {
                    "customer_name": record[
                        "customer_name"
                    ],
                    "phone": record["phone"],
                    "registration": record[
                        "registration"
                    ],
                    "vehicle": (
                        _vehicle_description(
                            record
                        )
                    ),
                    "mot_expiry": (
                        expiry.isoformat()
                    ),
                    "mot_expiry_text": (
                        _format_date(expiry)
                    ),
                    "days_remaining": (
                        expiry - today
                    ).days,
                }
            )

    due_vehicles.sort(
        key=lambda item: item[
            "mot_expiry"
        ]
    )

    return due_vehicles