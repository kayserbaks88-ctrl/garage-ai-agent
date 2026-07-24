from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from integrations.garage_calendar import (
    _calendar_id,
    _get_calendar_service,
    normalise_phone,
)
from integrations.garage_config import SERVICES, TIMEZONE


HISTORY_LOOKBACK_YEARS = 10
DEFAULT_HISTORY_LIMIT = 20


def _parse_datetime(value: str) -> datetime | None:
    """
    Convert a Google Calendar dateTime value into Europe/London time.
    """
    raw_value = str(value or "").strip()

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


def _clean_registration(registration: str) -> str:
    """
    Normalise a UK registration for reliable matching.

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
    Return a readable registration.

    Example:
    AB12CDE -> AB12 CDE
    """
    cleaned = _clean_registration(registration)

    if len(cleaned) > 3:
        return f"{cleaned[:-3]} {cleaned[-3:]}"

    return cleaned


def _private_data(event: dict) -> dict:
    return (
        (event.get("extendedProperties") or {})
        .get("private")
        or {}
    )


def _service_label(service_key: str) -> str:
    key = str(service_key or "").strip().lower()
    service = SERVICES.get(key) or {}

    return str(
        service.get("label")
        or key.replace("_", " ").title()
        or "Garage Appointment"
    )


def _event_start(event: dict) -> datetime | None:
    start = event.get("start") or {}

    return _parse_datetime(
        start.get("dateTime") or ""
    )


def _event_end(event: dict) -> datetime | None:
    end = event.get("end") or {}

    return _parse_datetime(
        end.get("dateTime") or ""
    )


def _event_is_completed(
    event: dict,
    current_time: datetime,
) -> bool:
    """
    An event counts as completed when:

    - it has been manually marked completed, or
    - its end time has passed
    """
    if event.get("status") == "cancelled":
        return False

    private = _private_data(event)

    completion_value = str(
        private.get("service_completed") or ""
    ).strip().lower()

    if completion_value in {
        "true",
        "yes",
        "1",
        "completed",
    }:
        return True

    end_time = _event_end(event)

    return bool(
        end_time
        and end_time <= current_time
    )


def _event_to_history_record(
    event: dict,
) -> dict[str, Any] | None:
    private = _private_data(event)

    start_time = _event_start(event)
    end_time = _event_end(event)

    if not start_time or not end_time:
        return None

    service_key = str(
        private.get("service") or ""
    ).strip().lower()

    registration = (
        private.get("registration")
        or private.get("reg")
        or private.get("vehicle_reg")
        or ""
    )

    phone = normalise_phone(
        private.get("phone") or ""
    )

    customer_name = str(
        private.get("customer_name")
        or private.get("name")
        or "Customer"
    ).strip()

    amount_paid_raw = (
        private.get("amount_paid")
        or private.get("price")
        or ""
    )

    mileage_raw = (
        private.get("mileage")
        or ""
    )

    try:
        amount_paid = (
            float(amount_paid_raw)
            if str(amount_paid_raw).strip()
            else None
        )
    except (TypeError, ValueError):
        amount_paid = None

    try:
        mileage = (
            int(str(mileage_raw).replace(",", ""))
            if str(mileage_raw).strip()
            else None
        )
    except (TypeError, ValueError):
        mileage = None

    return {
        "event_id": event.get("id", ""),
        "calendar_link": event.get("htmlLink", ""),
        "customer_name": customer_name,
        "phone": phone,
        "registration": _display_registration(
            registration
        ),
        "registration_key": _clean_registration(
            registration
        ),
        "service_key": service_key,
        "service_label": _service_label(
            service_key
        ),
        "start": start_time,
        "end": end_time,
        "date": start_time.strftime(
            "%Y-%m-%d"
        ),
        "date_text": start_time.strftime(
            "%A %-d %B %Y"
        ),
        "time_text": start_time.strftime(
            "%-I:%M %p"
        ).lower(),
        "vehicle_make": str(
            private.get("vehicle_make") or ""
        ).strip(),
        "vehicle_model": str(
            private.get("vehicle_model") or ""
        ).strip(),
        "vehicle_colour": str(
            private.get("vehicle_colour") or ""
        ).strip(),
        "mileage": mileage,
        "amount_paid": amount_paid,
        "technician": str(
            private.get("technician") or ""
        ).strip(),
        "work_notes": str(
            private.get("work_notes")
            or private.get("notes")
            or ""
        ).strip(),
        "recommendations": str(
            private.get("recommendations")
            or ""
        ).strip(),
        "completed_at": str(
            private.get("completed_at") or ""
        ).strip(),
        "review_requested": bool(
            private.get("review_requested_at")
            or private.get("follow_up_sent")
        ),
    }


def _fetch_calendar_events(
    time_min: datetime,
    time_max: datetime,
) -> list[dict]:
    """
    Retrieve all matching calendar events, including pagination.
    """
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


def list_service_history(
    phone: str = "",
    registration: str = "",
    limit: int = DEFAULT_HISTORY_LIMIT,
    include_future: bool = False,
) -> list[dict[str, Any]]:
    """
    Return completed service history.

    The history can be filtered by:
    - customer phone
    - vehicle registration
    - both together
    """
    current_time = datetime.now(TIMEZONE)

    normalised_phone = (
        normalise_phone(phone)
        if phone
        else ""
    )

    registration_key = (
        _clean_registration(registration)
        if registration
        else ""
    )

    time_min = current_time - timedelta(
        days=365 * HISTORY_LOOKBACK_YEARS
    )

    time_max = (
        current_time + timedelta(days=365)
        if include_future
        else current_time + timedelta(minutes=1)
    )

    events = _fetch_calendar_events(
        time_min=time_min,
        time_max=time_max,
    )

    records: list[dict[str, Any]] = []

    for event in events:
        if event.get("status") == "cancelled":
            continue

        if (
            not include_future
            and not _event_is_completed(
                event,
                current_time,
            )
        ):
            continue

        record = _event_to_history_record(
            event
        )

        if not record:
            continue

        if (
            normalised_phone
            and record["phone"]
            != normalised_phone
        ):
            continue

        if (
            registration_key
            and record["registration_key"]
            != registration_key
        ):
            continue

        records.append(record)

    records.sort(
        key=lambda item: item["start"],
        reverse=True,
    )

    safe_limit = max(
        1,
        min(int(limit or DEFAULT_HISTORY_LIMIT), 100),
    )

    return records[:safe_limit]


def get_latest_service(
    registration: str,
) -> dict[str, Any] | None:
    """
    Return the most recent completed service for a vehicle.
    """
    history = list_service_history(
        registration=registration,
        limit=1,
    )

    return history[0] if history else None


def get_customer_service_summary(
    phone: str,
) -> dict[str, Any]:
    """
    Create a simple customer history summary for the AI.
    """
    normalised_phone = normalise_phone(phone)

    history = list_service_history(
        phone=normalised_phone,
        limit=100,
    )

    registrations: list[str] = []

    for record in history:
        registration = record.get(
            "registration",
            "",
        )

        if (
            registration
            and registration not in registrations
        ):
            registrations.append(
                registration
            )

    total_spent = round(
        sum(
            record["amount_paid"]
            for record in history
            if record.get("amount_paid")
            is not None
        ),
        2,
    )

    latest = (
        history[0]
        if history
        else None
    )

    return {
        "found": bool(history),
        "phone": normalised_phone,
        "customer_name": (
            latest.get("customer_name", "")
            if latest
            else ""
        ),
        "total_visits": len(history),
        "vehicles": registrations,
        "vehicle_count": len(registrations),
        "total_spent": total_spent,
        "last_visit": (
            latest.get("date", "")
            if latest
            else ""
        ),
        "last_visit_text": (
            latest.get("date_text", "")
            if latest
            else ""
        ),
        "last_service": (
            latest.get("service_label", "")
            if latest
            else ""
        ),
        "last_registration": (
            latest.get("registration", "")
            if latest
            else ""
        ),
        "history": history,
    }


def mark_service_completed(
    event_id: str,
    mileage: int | None = None,
    amount_paid: float | None = None,
    technician: str = "",
    work_notes: str = "",
    recommendations: str = "",
) -> dict[str, Any]:
    """
    Mark a Google Calendar appointment as completed and store
    useful service information inside its private metadata.
    """
    event_id = str(event_id or "").strip()

    if not event_id:
        raise ValueError(
            "Missing Google Calendar event ID"
        )

    service = _get_calendar_service()

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

    completed_at = datetime.now(
        TIMEZONE
    ).isoformat()

    private["service_completed"] = "true"
    private["completed_at"] = completed_at

    if mileage is not None:
        private["mileage"] = str(
            int(mileage)
        )

    if amount_paid is not None:
        private["amount_paid"] = (
            f"{float(amount_paid):.2f}"
        )

    if technician.strip():
        private["technician"] = (
            technician.strip()
        )

    if work_notes.strip():
        private["work_notes"] = (
            work_notes.strip()
        )

    if recommendations.strip():
        private["recommendations"] = (
            recommendations.strip()
        )

    extended_properties["private"] = private
    event["extendedProperties"] = (
        extended_properties
    )

    updated_event = (
        service.events()
        .update(
            calendarId=_calendar_id(),
            eventId=event_id,
            body=event,
        )
        .execute()
    )

    history_record = (
        _event_to_history_record(
            updated_event
        )
    )

    print(
        "SERVICE MARKED COMPLETED:",
        event_id,
        completed_at,
    )

    return {
        "success": True,
        "event_id": event_id,
        "completed_at": completed_at,
        "service": history_record,
    }


def format_service_history_for_ai(
    phone: str = "",
    registration: str = "",
    limit: int = 5,
) -> str:
    """
    Return a short natural-language history that can later be
    passed to the voice agent or WhatsApp assistant.
    """
    history = list_service_history(
        phone=phone,
        registration=registration,
        limit=limit,
    )

    if not history:
        return (
            "No previous completed service history was found."
        )

    lines = []

    for record in history:
        line = (
            f"{record['date_text']}: "
            f"{record['service_label']}"
        )

        if record.get("registration"):
            line += (
                f" for {record['registration']}"
            )

        if record.get("mileage") is not None:
            line += (
                f" at {record['mileage']:,} miles"
            )

        if record.get("work_notes"):
            line += (
                f". Work notes: "
                f"{record['work_notes']}"
            )

        if record.get("recommendations"):
            line += (
                f". Recommendations: "
                f"{record['recommendations']}"
            )

        lines.append(line)

    return "\n".join(lines)