from __future__ import annotations

from datetime import datetime, timedelta

from integrations.garage_calendar import (
    _calendar_id,
    _get_calendar_service,
    normalise_phone,
)
from integrations.garage_config import SERVICES, TIMEZONE
from integrations.reminder_sender import (
    send_24_hour_reminder,
    send_2_hour_reminder,
    send_follow_up,
)


# These windows allow the scheduler to run every five minutes
# without needing to execute at one exact second.
REMINDER_WINDOW_MINUTES = 10

# Send the customer follow-up two hours after the appointment ends.
FOLLOW_UP_DELAY_HOURS = 2


def _parse_calendar_datetime(raw_value: str) -> datetime | None:
    """
    Convert a Google Calendar dateTime value into Europe/London time.
    """
    value = str(raw_value or "").strip()

    if not value:
        return None

    try:
        parsed = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )
    except ValueError:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=TIMEZONE)

    return parsed.astimezone(TIMEZONE)


def _service_label(service_key: str) -> str:
    key = str(service_key or "").strip().lower()
    config = SERVICES.get(key) or {}

    return str(
        config.get("label")
        or key.replace("_", " ").title()
        or "Garage Appointment"
    )


def _event_private_data(event: dict) -> dict:
    return (
        (event.get("extendedProperties") or {})
        .get("private")
        or {}
    )


def _within_due_window(
    target_time: datetime,
    current_time: datetime,
) -> bool:
    """
    Return True when target_time is due now or was due within the
    previous reminder window.
    """
    window_start = current_time - timedelta(
        minutes=REMINDER_WINDOW_MINUTES
    )

    return window_start <= target_time <= current_time


def _format_reminder_date(start_dt: datetime) -> str:
    return start_dt.strftime("%A %-d %B")


def _format_reminder_time(start_dt: datetime) -> str:
    return start_dt.strftime("%-I:%M %p").lower()


def _get_relevant_events(
    current_time: datetime,
) -> list[dict]:
    """
    Retrieve events covering:
    - recently completed appointments
    - appointments occurring during the next 25 hours
    """
    service = _get_calendar_service()

    time_min = current_time - timedelta(
        hours=FOLLOW_UP_DELAY_HOURS + 1
    )

    time_max = current_time + timedelta(hours=25)

    result = (
        service.events()
        .list(
            calendarId=_calendar_id(),
            timeMin=time_min.isoformat(),
            timeMax=time_max.isoformat(),
            singleEvents=True,
            orderBy="startTime",
            maxResults=100,
        )
        .execute()
    )

    return result.get("items", [])


def _mark_reminder_sent(
    event: dict,
    reminder_key: str,
    sent_at: datetime,
    message_sid: str = "",
) -> None:
    """
    Save reminder status in the calendar event's private metadata.

    This prevents the same reminder from being sent more than once.
    """
    service = _get_calendar_service()

    extended_properties = (
        event.get("extendedProperties") or {}
    )

    private = (
        extended_properties.get("private") or {}
    )

    private[reminder_key] = sent_at.isoformat()

    if message_sid:
        private[f"{reminder_key}_sid"] = message_sid

    extended_properties["private"] = private
    event["extendedProperties"] = extended_properties

    (
        service.events()
        .update(
            calendarId=_calendar_id(),
            eventId=event["id"],
            body=event,
        )
        .execute()
    )


def _appointment_details(
    event: dict,
) -> dict | None:
    private = _event_private_data(event)

    phone = normalise_phone(
        private.get("phone", "")
    )

    if not phone:
        print(
            "REMINDER SKIPPED — MISSING PHONE:",
            event.get("id"),
            event.get("summary"),
        )
        return None

    start_dt = _parse_calendar_datetime(
        (event.get("start") or {}).get("dateTime", "")
    )

    end_dt = _parse_calendar_datetime(
        (event.get("end") or {}).get("dateTime", "")
    )

    if not start_dt or not end_dt:
        print(
            "REMINDER SKIPPED — INVALID EVENT TIME:",
            event.get("id"),
        )
        return None

    service_key = str(
        private.get("service") or ""
    ).strip().lower()

    return {
        "phone": phone,
        "customer_name": (
            str(private.get("customer_name") or "Customer")
            .strip()
        ),
        "service_key": service_key,
        "service_label": _service_label(service_key),
        "registration": (
            str(private.get("reg") or "your vehicle")
            .strip()
            .upper()
        ),
        "start": start_dt,
        "end": end_dt,
        "private": private,
    }


def _send_due_24_hour_reminder(
    event: dict,
    details: dict,
    current_time: datetime,
) -> dict | None:
    private = details["private"]

    if private.get("reminder_24h_sent"):
        return None

    target_time = details["start"] - timedelta(hours=24)

    if not _within_due_window(
        target_time,
        current_time,
    ):
        return None

    result = send_24_hour_reminder(
        phone=details["phone"],
        customer_name=details["customer_name"],
        service_label=details["service_label"],
        registration=details["registration"],
        date_text=_format_reminder_date(
            details["start"]
        ),
        time_text=_format_reminder_time(
            details["start"]
        ),
    )

    _mark_reminder_sent(
        event=event,
        reminder_key="reminder_24h_sent",
        sent_at=current_time,
        message_sid=str(result.get("sid") or ""),
    )

    return {
        "type": "24_hour",
        "event_id": event.get("id"),
        "phone": details["phone"],
        "message_sid": result.get("sid"),
    }


def _send_due_2_hour_reminder(
    event: dict,
    details: dict,
    current_time: datetime,
) -> dict | None:
    private = details["private"]

    if private.get("reminder_2h_sent"):
        return None

    target_time = details["start"] - timedelta(hours=2)

    if not _within_due_window(
        target_time,
        current_time,
    ):
        return None

    result = send_2_hour_reminder(
        phone=details["phone"],
        customer_name=details["customer_name"],
        service_label=details["service_label"],
        registration=details["registration"],
        time_text=_format_reminder_time(
            details["start"]
        ),
    )

    _mark_reminder_sent(
        event=event,
        reminder_key="reminder_2h_sent",
        sent_at=current_time,
        message_sid=str(result.get("sid") or ""),
    )

    return {
        "type": "2_hour",
        "event_id": event.get("id"),
        "phone": details["phone"],
        "message_sid": result.get("sid"),
    }


def _send_due_follow_up(
    event: dict,
    details: dict,
    current_time: datetime,
) -> dict | None:
    private = details["private"]

    if private.get("follow_up_sent"):
        return None

    target_time = details["end"] + timedelta(
        hours=FOLLOW_UP_DELAY_HOURS
    )

    if not _within_due_window(
        target_time,
        current_time,
    ):
        return None

    result = send_follow_up(
        phone=details["phone"],
        customer_name=details["customer_name"],
        service_label=details["service_label"],
        registration=details["registration"],
    )

    _mark_reminder_sent(
        event=event,
        reminder_key="follow_up_sent",
        sent_at=current_time,
        message_sid=str(result.get("sid") or ""),
    )

    return {
        "type": "follow_up",
        "event_id": event.get("id"),
        "phone": details["phone"],
        "message_sid": result.get("sid"),
    }


def process_reminders(
    now: datetime | None = None,
) -> dict:
    """
    Check Google Calendar and send any reminders that are currently due.

    The scheduler will call this function every five minutes.
    """
    current_time = (
        now.astimezone(TIMEZONE)
        if now is not None
        else datetime.now(TIMEZONE)
    )

    print(
        "REMINDER CHECK STARTED:",
        current_time.isoformat(),
    )

    events = _get_relevant_events(current_time)

    sent = []
    skipped = 0
    errors = []

    for event in events:
        if event.get("status") == "cancelled":
            skipped += 1
            continue

        if not event.get("id"):
            skipped += 1
            continue

        details = _appointment_details(event)

        if not details:
            skipped += 1
            continue

        reminder_handlers = (
            _send_due_24_hour_reminder,
            _send_due_2_hour_reminder,
            _send_due_follow_up,
        )

        for handler in reminder_handlers:
            try:
                result = handler(
                    event,
                    details,
                    current_time,
                )

                if result:
                    sent.append(result)

                    print(
                        "REMINDER SENT:",
                        result["type"],
                        result["phone"],
                        result.get("message_sid"),
                    )

                    # Refresh private values locally so another handler
                    # cannot work with outdated metadata.
                    details["private"][
                        {
                            "24_hour": "reminder_24h_sent",
                            "2_hour": "reminder_2h_sent",
                            "follow_up": "follow_up_sent",
                        }[result["type"]]
                    ] = current_time.isoformat()

            except Exception as error:
                error_record = {
                    "event_id": event.get("id"),
                    "reminder_handler": handler.__name__,
                    "error": repr(error),
                }

                errors.append(error_record)

                print(
                    "REMINDER ERROR:",
                    error_record,
                )

    summary = {
        "checked_at": current_time.isoformat(),
        "events_checked": len(events),
        "sent_count": len(sent),
        "sent": sent,
        "skipped_count": skipped,
        "error_count": len(errors),
        "errors": errors,
    }

    print("REMINDER CHECK COMPLETE:", summary)

    return summary