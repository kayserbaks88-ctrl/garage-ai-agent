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


SERVICE_REMINDER_DAYS = (30, 7, 0)
CUSTOMER_LOOKBACK_YEARS = 10

# Used when calculating a new service date automatically.
DEFAULT_SERVICE_INTERVAL_MONTHS = 12


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()

    if not value:
        raise ValueError(f"Missing {name}")

    return value


def _clean_registration(registration: str) -> str:
    """
    Convert a registration into a reliable comparison key.

    Example:
    ab12 cde -> AB12CDE
    """
    return "".join(
        character
        for character in str(registration or "").upper()
        if character.isalnum()
    )


def _display_registration(registration: str) -> str:
    """
    Convert a registration into a readable UK format.

    Example:
    AB12CDE -> AB12 CDE
    """
    cleaned = _clean_registration(registration)

    if len(cleaned) > 3:
        return f"{cleaned[:-3]} {cleaned[-3:]}"

    return cleaned


def _parse_date(value: Any) -> date | None:
    """
    Accept common date formats.

    Examples:
    2027-08-31
    31/08/2027
    31-08-2027
    31 August 2027
    """
    raw_value = str(value or "").strip()

    if not raw_value:
        return None

    cleaned_value = raw_value.replace(
        "Z",
        "+00:00",
    )

    formats = (
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%d %B %Y",
        "%d %b %Y",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S%z",
    )

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
    return value.strftime(
        "%A %-d %B %Y"
    )


def _safe_int(value: Any) -> int | None:
    raw_value = str(value or "").strip()

    if not raw_value:
        return None

    cleaned_value = (
        raw_value
        .replace(",", "")
        .replace("miles", "")
        .replace("mile", "")
        .strip()
    )

    try:
        return int(cleaned_value)

    except (TypeError, ValueError):
        return None


def _private_data(event: dict) -> dict:
    return (
        (event.get("extendedProperties") or {})
        .get("private")
        or {}
    )


def _event_datetime(
    event: dict,
) -> datetime | None:
    raw_value = str(
        (event.get("start") or {}).get(
            "dateTime"
        )
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
        parsed = parsed.replace(
            tzinfo=TIMEZONE
        )

    return parsed.astimezone(TIMEZONE)


def _fetch_calendar_events() -> list[dict]:
    """
    Retrieve historical and future garage appointments.

    Vehicle reminder information is stored inside each
    Google Calendar event's private metadata.
    """
    now = datetime.now(TIMEZONE)

    time_min = now - timedelta(
        days=365 * CUSTOMER_LOOKBACK_YEARS
    )

    time_max = now + timedelta(
        days=365 * 3
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
    """
    Create one maintenance-reminder record from a calendar event.
    """
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

    service_due_date = _parse_date(
        private.get("service_due_date")
        or private.get("next_service_date")
        or private.get("vehicle_service_due")
        or ""
    )

    if (
        not phone
        or not registration_key
        or not service_due_date
    ):
        return None

    return {
        "event_id": event.get("id", ""),
        "event": event,
        "event_time": _event_datetime(event),
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
        "vehicle_colour": str(
            private.get("vehicle_colour")
            or private.get("colour")
            or ""
        ).strip(),
        "current_mileage": _safe_int(
            private.get("mileage")
            or private.get("current_mileage")
        ),
        "service_due_mileage": _safe_int(
            private.get("service_due_mileage")
            or private.get("next_service_mileage")
        ),
        "last_service_date": _parse_date(
            private.get("last_service_date")
            or private.get("completed_at")
            or ""
        ),
        "last_service_mileage": _safe_int(
            private.get("last_service_mileage")
            or private.get("mileage")
        ),
        "service_due_date": service_due_date,
        "private": private,
    }


def _latest_vehicle_records() -> list[
    dict[str, Any]
]:
    """
    Deduplicate repeated appointments for the same customer and car.

    The most recent event containing a service-due date is used.
    """
    records: dict[
        tuple[str, str],
        dict[str, Any],
    ] = {}

    for event in _fetch_calendar_events():
        record = _extract_vehicle_record(
            event
        )

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


def _vehicle_description(
    record: dict[str, Any],
) -> str:
    parts = [
        record.get("vehicle_make", ""),
        record.get("vehicle_model", ""),
    ]

    description = " ".join(
        str(part).strip()
        for part in parts
        if str(part).strip()
    )

    return description or "your vehicle"


def _reminder_metadata_key(
    days_before: int,
    due_date: date,
) -> str:
    """
    Include the due date in the reminder key.

    This means a new reminder cycle starts when the next
    service date is updated.
    """
    due_date_key = due_date.strftime(
        "%Y%m%d"
    )

    if days_before == 0:
        return (
            f"service_due_today_"
            f"{due_date_key}_sent"
        )

    return (
        f"service_{days_before}d_"
        f"{due_date_key}_sent"
    )


def _content_sid_for_days(
    days_before: int,
) -> str:
    if days_before == 30:
        return _required_env(
            "TWILIO_SERVICE_30D_CONTENT_SID"
        )

    if days_before == 7:
        return _required_env(
            "TWILIO_SERVICE_7D_CONTENT_SID"
        )

    if days_before == 0:
        return _required_env(
            "TWILIO_SERVICE_DUE_CONTENT_SID"
        )

    raise ValueError(
        "Unsupported service reminder day: "
        f"{days_before}"
    )


def _mark_reminder_sent(
    record: dict[str, Any],
    metadata_key: str,
    message_sid: str,
    sent_at: datetime,
) -> None:
    """
    Save the sent status into the Google Calendar event.

    This prevents duplicate reminder messages.
    """
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
        private[
            f"{metadata_key}_sid"
        ] = message_sid

    extended_properties["private"] = (
        private
    )

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


def _send_service_reminder(
    record: dict[str, Any],
    days_before: int,
    current_time: datetime,
) -> dict[str, Any] | None:
    metadata_key = _reminder_metadata_key(
        days_before=days_before,
        due_date=record[
            "service_due_date"
        ],
    )

    if record["private"].get(
        metadata_key
    ):
        return None

    due_mileage = record.get(
        "service_due_mileage"
    )

    mileage_text = (
        f"{due_mileage:,} miles"
        if due_mileage is not None
        else "the recommended mileage"
    )

    result = send_whatsapp_template(
        phone=record["phone"],
        content_sid=_content_sid_for_days(
            days_before
        ),
        variables={
            "1": record["customer_name"],
            "2": record["registration"],
            "3": _vehicle_description(
                record
            ),
            "4": _format_date(
                record["service_due_date"]
            ),
            "5": mileage_text,
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
        "SERVICE REMINDER SENT:",
        days_before,
        record["phone"],
        record["registration"],
        record["service_due_date"],
    )

    return {
        "type": (
            "service_due_today"
            if days_before == 0
            else (
                f"service_{days_before}_days"
            )
        ),
        "phone": record["phone"],
        "customer_name": record[
            "customer_name"
        ],
        "registration": record[
            "registration"
        ],
        "service_due_date": (
            record[
                "service_due_date"
            ].isoformat()
        ),
        "service_due_mileage": (
            due_mileage
        ),
        "message_sid": result.get(
            "sid"
        ),
        "event_id": record["event_id"],
    }


def process_vehicle_reminders(
    now: datetime | None = None,
) -> dict[str, Any]:
    """
    Send vehicle-service reminders due today.

    Reminder stages:
    - 30 days before the service due date
    - 7 days before the service due date
    - On the service due date
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
        "VEHICLE REMINDER CHECK STARTED:",
        current_time.isoformat(),
        "VEHICLES:",
        len(records),
    )

    for record in records:
        days_until_due = (
            record["service_due_date"]
            - today
        ).days

        if days_until_due not in (
            SERVICE_REMINDER_DAYS
        ):
            skipped += 1
            continue

        try:
            result = (
                _send_service_reminder(
                    record=record,
                    days_before=days_until_due,
                    current_time=current_time,
                )
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
                "service_due_date": (
                    record[
                        "service_due_date"
                    ].isoformat()
                ),
                "error": repr(error),
            }

            errors.append(error_record)

            print(
                "VEHICLE REMINDER ERROR:",
                error_record,
            )

    summary = {
        "success": len(errors) == 0,
        "checked_at": (
            current_time.isoformat()
        ),
        "vehicles_checked": len(
            records
        ),
        "sent_count": len(sent),
        "sent": sent,
        "skipped_count": skipped,
        "error_count": len(errors),
        "errors": errors,
    }

    print(
        "VEHICLE REMINDER CHECK COMPLETE:",
        summary,
    )

    return summary


def update_vehicle_service_due(
    phone: str,
    registration: str,
    service_due_date: str | date,
    service_due_mileage: int | None = None,
    last_service_date: str | date | None = None,
    last_service_mileage: int | None = None,
) -> dict[str, Any]:
    """
    Save the next service date and optional mileage across the
    customer's matching calendar records.

    This can be called after the garage completes a service.
    """
    normalised_phone = normalise_phone(
        phone
    )

    registration_key = (
        _clean_registration(
            registration
        )
    )

    parsed_due_date = (
        service_due_date
        if isinstance(
            service_due_date,
            date,
        )
        else _parse_date(
            service_due_date
        )
    )

    parsed_last_service_date = None

    if last_service_date:
        parsed_last_service_date = (
            last_service_date
            if isinstance(
                last_service_date,
                date,
            )
            else _parse_date(
                last_service_date
            )
        )

    if not normalised_phone:
        raise ValueError(
            "Missing customer phone number"
        )

    if not registration_key:
        raise ValueError(
            "Missing vehicle registration"
        )

    if not parsed_due_date:
        raise ValueError(
            "Invalid service due date"
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
            event.get(
                "extendedProperties"
            )
            or {}
        )

        private = (
            extended_properties.get(
                "private"
            )
            or {}
        )

        private[
            "service_due_date"
        ] = parsed_due_date.isoformat()

        private[
            "service_due_updated_at"
        ] = datetime.now(
            TIMEZONE
        ).isoformat()

        if (
            service_due_mileage
            is not None
        ):
            private[
                "service_due_mileage"
            ] = str(
                int(
                    service_due_mileage
                )
            )

        if parsed_last_service_date:
            private[
                "last_service_date"
            ] = (
                parsed_last_service_date
                .isoformat()
            )

        if (
            last_service_mileage
            is not None
        ):
            private[
                "last_service_mileage"
            ] = str(
                int(
                    last_service_mileage
                )
            )

        extended_properties[
            "private"
        ] = private

        event[
            "extendedProperties"
        ] = extended_properties

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
        "service_due_date": (
            parsed_due_date.isoformat()
        ),
        "service_due_mileage": (
            service_due_mileage
        ),
        "last_service_date": (
            parsed_last_service_date
            .isoformat()
            if parsed_last_service_date
            else ""
        ),
        "last_service_mileage": (
            last_service_mileage
        ),
        "updated_events": (
            updated_count
        ),
        "event_ids": (
            updated_event_ids
        ),
    }


def set_annual_service_due(
    phone: str,
    registration: str,
    last_service_date: (
        str | date | None
    ) = None,
    last_service_mileage: (
        int | None
    ) = None,
    mileage_interval: int = 10000,
) -> dict[str, Any]:
    """
    Automatically calculate the next annual service date.

    The default is:
    - 12 months after the last service
    - 10,000 miles after the last recorded mileage
    """
    parsed_last_date = (
        last_service_date
        if isinstance(
            last_service_date,
            date,
        )
        else _parse_date(
            last_service_date
        )
        if last_service_date
        else datetime.now(
            TIMEZONE
        ).date()
    )

    if not parsed_last_date:
        raise ValueError(
            "Invalid last service date"
        )

    try:
        next_service_date = (
            parsed_last_date.replace(
                year=(
                    parsed_last_date.year
                    + 1
                )
            )
        )

    except ValueError:
        # Handles 29 February safely.
        next_service_date = (
            parsed_last_date.replace(
                month=2,
                day=28,
                year=(
                    parsed_last_date.year
                    + 1
                ),
            )
        )

    next_service_mileage = None

    if last_service_mileage is not None:
        next_service_mileage = (
            int(last_service_mileage)
            + int(mileage_interval)
        )

    return update_vehicle_service_due(
        phone=phone,
        registration=registration,
        service_due_date=(
            next_service_date
        ),
        service_due_mileage=(
            next_service_mileage
        ),
        last_service_date=(
            parsed_last_date
        ),
        last_service_mileage=(
            last_service_mileage
        ),
    )


def get_upcoming_service_due(
    days_ahead: int = 60,
) -> list[dict[str, Any]]:
    """
    Return vehicles with a service due within the requested period.

    This will be used later by garage reports and the dashboard.
    """
    today = datetime.now(
        TIMEZONE
    ).date()

    maximum_date = today + timedelta(
        days=max(
            1,
            int(days_ahead),
        )
    )

    due_vehicles: list[
        dict[str, Any]
    ] = []

    for record in (
        _latest_vehicle_records()
    ):
        due_date = record[
            "service_due_date"
        ]

        if (
            today
            <= due_date
            <= maximum_date
        ):
            due_vehicles.append(
                {
                    "customer_name": (
                        record[
                            "customer_name"
                        ]
                    ),
                    "phone": record[
                        "phone"
                    ],
                    "registration": (
                        record[
                            "registration"
                        ]
                    ),
                    "vehicle": (
                        _vehicle_description(
                            record
                        )
                    ),
                    "service_due_date": (
                        due_date.isoformat()
                    ),
                    "service_due_text": (
                        _format_date(
                            due_date
                        )
                    ),
                    "service_due_mileage": (
                        record.get(
                            "service_due_mileage"
                        )
                    ),
                    "current_mileage": (
                        record.get(
                            "current_mileage"
                        )
                    ),
                    "days_remaining": (
                        due_date - today
                    ).days,
                }
            )

    due_vehicles.sort(
        key=lambda item: item[
            "service_due_date"
        ]
    )

    return due_vehicles


def get_overdue_services() -> list[
    dict[str, Any]
]:
    """
    Return vehicles whose recorded service date has already passed.
    """
    today = datetime.now(
        TIMEZONE
    ).date()

    overdue: list[dict[str, Any]] = []

    for record in (
        _latest_vehicle_records()
    ):
        due_date = record[
            "service_due_date"
        ]

        if due_date >= today:
            continue

        overdue.append(
            {
                "customer_name": record[
                    "customer_name"
                ],
                "phone": record[
                    "phone"
                ],
                "registration": record[
                    "registration"
                ],
                "vehicle": (
                    _vehicle_description(
                        record
                    )
                ),
                "service_due_date": (
                    due_date.isoformat()
                ),
                "service_due_text": (
                    _format_date(
                        due_date
                    )
                ),
                "service_due_mileage": (
                    record.get(
                        "service_due_mileage"
                    )
                ),
                "days_overdue": (
                    today - due_date
                ).days,
            }
        )

    overdue.sort(
        key=lambda item: item[
            "days_overdue"
        ],
        reverse=True,
    )

    return overdue