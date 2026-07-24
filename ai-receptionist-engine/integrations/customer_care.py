from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Any

from integrations.customer_history import (
    get_customer_profile,
    mark_customer_no_show,
)
from integrations.garage_calendar import (
    _calendar_id,
    _get_calendar_service,
    normalise_phone,
)
from integrations.garage_config import SERVICES, TIMEZONE
from integrations.reminder_sender import send_whatsapp_template


CUSTOMER_CARE_LOOKBACK_DAYS = 14

THANK_YOU_DELAY_MINUTES = 30
SERVICE_CHECK_DELAY_DAYS = 3
NO_SHOW_FOLLOW_UP_DELAY_MINUTES = 30

VIP_VISIT_THRESHOLD = 5
VIP_SPEND_THRESHOLD = 750.00

REPEAT_CANCELLATION_THRESHOLD = 3
REPEAT_NO_SHOW_THRESHOLD = 2


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()

    if not value:
        raise ValueError(f"Missing {name}")

    return value


def _parse_datetime(value: str) -> datetime | None:
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


def _private_data(event: dict) -> dict:
    return (
        (event.get("extendedProperties") or {})
        .get("private")
        or {}
    )


def _event_start(event: dict) -> datetime | None:
    return _parse_datetime(
        (event.get("start") or {}).get("dateTime", "")
    )


def _event_end(event: dict) -> datetime | None:
    return _parse_datetime(
        (event.get("end") or {}).get("dateTime", "")
    )


def _service_label(service_key: str) -> str:
    key = str(service_key or "").strip().lower()

    service = SERVICES.get(key) or {}

    return str(
        service.get("label")
        or key.replace("_", " ").title()
        or "Garage Appointment"
    )


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


def _vehicle_description(private: dict) -> str:
    make = str(
        private.get("vehicle_make")
        or private.get("make")
        or ""
    ).strip()

    model = str(
        private.get("vehicle_model")
        or private.get("model")
        or ""
    ).strip()

    description = " ".join(
        part for part in (make, model) if part
    ).strip()

    return description or "your vehicle"


def _event_to_record(
    event: dict,
) -> dict[str, Any] | None:
    if event.get("status") == "cancelled":
        return None

    private = _private_data(event)

    start_time = _event_start(event)
    end_time = _event_end(event)

    if not start_time or not end_time:
        return None

    phone = normalise_phone(
        private.get("phone") or ""
    )

    if not phone:
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

    return {
        "event_id": event.get("id", ""),
        "event": event,
        "private": private,
        "phone": phone,
        "customer_name": str(
            private.get("customer_name")
            or private.get("name")
            or "Customer"
        ).strip(),
        "registration": _display_registration(
            registration
        ),
        "service_key": service_key,
        "service_label": _service_label(
            service_key
        ),
        "vehicle": _vehicle_description(
            private
        ),
        "start": start_time,
        "end": end_time,
        "service_completed": str(
            private.get("service_completed") or ""
        ).strip().lower()
        in {
            "true",
            "yes",
            "1",
            "completed",
        },
        "no_show": str(
            private.get("no_show") or ""
        ).strip().lower()
        in {
            "true",
            "yes",
            "1",
            "no_show",
        },
    }


def _fetch_recent_events(
    current_time: datetime,
) -> list[dict]:
    service = _get_calendar_service()

    time_min = current_time - timedelta(
        days=CUSTOMER_CARE_LOOKBACK_DAYS
    )

    time_max = current_time + timedelta(
        days=1
    )

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


def _update_event_private_data(
    event: dict,
    updates: dict[str, str],
) -> dict:
    event_id = str(
        event.get("id") or ""
    ).strip()

    if not event_id:
        raise ValueError(
            "Missing Google Calendar event ID"
        )

    extended_properties = (
        event.get("extendedProperties")
        or {}
    )

    private = (
        extended_properties.get("private")
        or {}
    )

    for key, value in updates.items():
        private[str(key)] = str(value)

    extended_properties["private"] = private
    event["extendedProperties"] = (
        extended_properties
    )

    return (
        _get_calendar_service()
        .events()
        .update(
            calendarId=_calendar_id(),
            eventId=event_id,
            body=event,
        )
        .execute()
    )


def _send_template(
    phone: str,
    content_sid_env: str,
    variables: dict[str, str],
) -> dict[str, Any]:
    return send_whatsapp_template(
        phone=phone,
        content_sid=_required_env(
            content_sid_env
        ),
        variables=variables,
    )


def send_service_thank_you(
    record: dict[str, Any],
    current_time: datetime | None = None,
) -> dict[str, Any] | None:
    now = (
        current_time.astimezone(TIMEZONE)
        if current_time
        else datetime.now(TIMEZONE)
    )

    private = record["private"]

    if private.get(
        "customer_thank_you_sent"
    ):
        return None

    result = _send_template(
        phone=record["phone"],
        content_sid_env=(
            "TWILIO_SERVICE_THANK_YOU_CONTENT_SID"
        ),
        variables={
            "1": record["customer_name"],
            "2": record["service_label"],
            "3": record["registration"]
            or record["vehicle"],
        },
    )

    sent_at = now.isoformat()
    message_sid = str(
        result.get("sid") or ""
    )

    _update_event_private_data(
        event=record["event"],
        updates={
            "customer_thank_you_sent": sent_at,
            "customer_thank_you_sent_sid": (
                message_sid
            ),
        },
    )

    return {
        "type": "service_thank_you",
        "event_id": record["event_id"],
        "phone": record["phone"],
        "customer_name": record[
            "customer_name"
        ],
        "message_sid": message_sid,
        "sent_at": sent_at,
    }


def send_service_check_in(
    record: dict[str, Any],
    current_time: datetime | None = None,
) -> dict[str, Any] | None:
    now = (
        current_time.astimezone(TIMEZONE)
        if current_time
        else datetime.now(TIMEZONE)
    )

    private = record["private"]

    if private.get(
        "service_check_in_sent"
    ):
        return None

    result = _send_template(
        phone=record["phone"],
        content_sid_env=(
            "TWILIO_SERVICE_CHECK_IN_CONTENT_SID"
        ),
        variables={
            "1": record["customer_name"],
            "2": record["service_label"],
            "3": record["registration"]
            or record["vehicle"],
        },
    )

    sent_at = now.isoformat()
    message_sid = str(
        result.get("sid") or ""
    )

    _update_event_private_data(
        event=record["event"],
        updates={
            "service_check_in_sent": sent_at,
            "service_check_in_sent_sid": (
                message_sid
            ),
        },
    )

    return {
        "type": "service_check_in",
        "event_id": record["event_id"],
        "phone": record["phone"],
        "customer_name": record[
            "customer_name"
        ],
        "message_sid": message_sid,
        "sent_at": sent_at,
    }


def send_no_show_follow_up(
    record: dict[str, Any],
    current_time: datetime | None = None,
) -> dict[str, Any] | None:
    now = (
        current_time.astimezone(TIMEZONE)
        if current_time
        else datetime.now(TIMEZONE)
    )

    private = record["private"]

    if private.get(
        "no_show_follow_up_sent"
    ):
        return None

    result = _send_template(
        phone=record["phone"],
        content_sid_env=(
            "TWILIO_NO_SHOW_FOLLOW_UP_CONTENT_SID"
        ),
        variables={
            "1": record["customer_name"],
            "2": record["service_label"],
            "3": record["start"].strftime(
                "%A %-d %B at %-I:%M %p"
            ).replace(":00", "").lower(),
        },
    )

    sent_at = now.isoformat()
    message_sid = str(
        result.get("sid") or ""
    )

    _update_event_private_data(
        event=record["event"],
        updates={
            "no_show_follow_up_sent": sent_at,
            "no_show_follow_up_sent_sid": (
                message_sid
            ),
        },
    )

    return {
        "type": "no_show_follow_up",
        "event_id": record["event_id"],
        "phone": record["phone"],
        "customer_name": record[
            "customer_name"
        ],
        "message_sid": message_sid,
        "sent_at": sent_at,
    }


def get_customer_care_flags(
    phone: str,
) -> dict[str, Any]:
    profile = get_customer_profile(
        phone
    )

    if not profile.get("found"):
        return {
            "found": False,
            "phone": normalise_phone(phone),
            "returning_customer": False,
            "vip_customer": False,
            "repeat_cancellations": False,
            "repeat_no_shows": False,
            "requires_deposit": False,
            "inactive_customer": False,
            "priority_customer": False,
        }

    completed_visits = int(
        profile.get("completed_visits", 0)
        or 0
    )

    cancelled_visits = int(
        profile.get("cancelled_visits", 0)
        or 0
    )

    no_show_visits = int(
        profile.get("no_show_visits", 0)
        or 0
    )

    total_spent = float(
        profile.get("total_spent", 0.0)
        or 0.0
    )

    vip_customer = bool(
        profile.get("vip_customer")
        or completed_visits
        >= VIP_VISIT_THRESHOLD
        or total_spent
        >= VIP_SPEND_THRESHOLD
    )

    repeat_cancellations = (
        cancelled_visits
        >= REPEAT_CANCELLATION_THRESHOLD
    )

    repeat_no_shows = (
        no_show_visits
        >= REPEAT_NO_SHOW_THRESHOLD
    )

    requires_deposit = (
        repeat_no_shows
        or (
            repeat_cancellations
            and no_show_visits >= 1
        )
    )

    priority_customer = (
        vip_customer
        and not requires_deposit
    )

    return {
        "found": True,
        "phone": profile.get(
            "phone",
            "",
        ),
        "customer_name": profile.get(
            "customer_name",
            "",
        ),
        "returning_customer": profile.get(
            "returning_customer",
            False,
        ),
        "vip_customer": vip_customer,
        "priority_customer": (
            priority_customer
        ),
        "repeat_cancellations": (
            repeat_cancellations
        ),
        "repeat_no_shows": (
            repeat_no_shows
        ),
        "requires_deposit": (
            requires_deposit
        ),
        "inactive_customer": profile.get(
            "inactive_customer",
            False,
        ),
        "completed_visits": (
            completed_visits
        ),
        "cancelled_visits": (
            cancelled_visits
        ),
        "no_show_visits": (
            no_show_visits
        ),
        "total_spent": (
            total_spent
        ),
        "last_visit": profile.get(
            "last_visit",
            "",
        ),
        "last_service": profile.get(
            "last_service",
            "",
        ),
    }


def format_customer_care_for_ai(
    phone: str,
) -> str:
    flags = get_customer_care_flags(
        phone
    )

    if not flags.get("found"):
        return (
            "This appears to be a new customer. "
            "Use a friendly standard greeting."
        )

    name = (
        flags.get("customer_name")
        or "Customer"
    )

    lines = [
        f"Customer name: {name}.",
    ]

    if flags.get("vip_customer"):
        lines.append(
            "This is a VIP customer. Thank them for their loyalty."
        )
    elif flags.get(
        "returning_customer"
    ):
        lines.append(
            "This is a returning customer. Welcome them back."
        )

    if flags.get(
        "priority_customer"
    ):
        lines.append(
            "Where practical, treat this customer as a priority."
        )

    if flags.get(
        "requires_deposit"
    ):
        lines.append(
            "This customer has a history of missed or cancelled appointments. "
            "Do not mention this history directly, but a deposit may be required."
        )
    elif flags.get(
        "repeat_cancellations"
    ):
        lines.append(
            "This customer has several previous cancellations. "
            "Confirm the chosen date and time carefully."
        )

    if flags.get(
        "inactive_customer"
    ):
        lines.append(
            "This customer has not visited for over a year. "
            "Welcome them back warmly."
        )

    if flags.get("last_service"):
        lines.append(
            f"Their last recorded service was {flags['last_service']}."
        )

    return "\n".join(lines)


def mark_appointment_no_show(
    event_id: str,
    reason: str = "",
    send_follow_up: bool = False,
) -> dict[str, Any]:
    marked = mark_customer_no_show(
        event_id=event_id,
        reason=reason,
    )

    response: dict[str, Any] = {
        **marked,
        "follow_up_sent": False,
    }

    if not send_follow_up:
        return response

    service = _get_calendar_service()

    event = (
        service.events()
        .get(
            calendarId=_calendar_id(),
            eventId=event_id,
        )
        .execute()
    )

    record = _event_to_record(
        event
    )

    if not record:
        return response

    result = send_no_show_follow_up(
        record
    )

    response["follow_up_sent"] = bool(
        result
    )
    response["follow_up"] = result

    return response


def process_customer_care(
    now: datetime | None = None,
) -> dict[str, Any]:
    current_time = (
        now.astimezone(TIMEZONE)
        if now is not None
        else datetime.now(TIMEZONE)
    )

    events = _fetch_recent_events(
        current_time
    )

    sent: list[dict[str, Any]] = []
    skipped = 0
    errors: list[dict[str, Any]] = []

    for event in events:
        record = _event_to_record(
            event
        )

        if not record:
            skipped += 1
            continue

        try:
            if record["no_show"]:
                no_show_due_at = (
                    record["end"]
                    + timedelta(
                        minutes=(
                            NO_SHOW_FOLLOW_UP_DELAY_MINUTES
                        )
                    )
                )

                if current_time >= no_show_due_at:
                    result = (
                        send_no_show_follow_up(
                            record=record,
                            current_time=current_time,
                        )
                    )

                    if result:
                        sent.append(result)
                    else:
                        skipped += 1
                else:
                    skipped += 1

                continue

            if not record[
                "service_completed"
            ]:
                skipped += 1
                continue

            thank_you_due_at = (
                record["end"]
                + timedelta(
                    minutes=(
                        THANK_YOU_DELAY_MINUTES
                    )
                )
            )

            check_in_due_at = (
                record["end"]
                + timedelta(
                    days=(
                        SERVICE_CHECK_DELAY_DAYS
                    )
                )
            )

            if (
                current_time
                >= thank_you_due_at
            ):
                thank_you_result = (
                    send_service_thank_you(
                        record=record,
                        current_time=current_time,
                    )
                )

                if thank_you_result:
                    sent.append(
                        thank_you_result
                    )

            if (
                current_time
                >= check_in_due_at
            ):
                check_in_result = (
                    send_service_check_in(
                        record=record,
                        current_time=current_time,
                    )
                )

                if check_in_result:
                    sent.append(
                        check_in_result
                    )

            if (
                current_time
                < thank_you_due_at
            ):
                skipped += 1

        except Exception as error:
            error_record = {
                "event_id": record.get(
                    "event_id",
                    "",
                ),
                "phone": record.get(
                    "phone",
                    "",
                ),
                "customer_name": (
                    record.get(
                        "customer_name",
                        "",
                    )
                ),
                "error": repr(error),
            }

            errors.append(
                error_record
            )

            print(
                "CUSTOMER CARE ERROR:",
                error_record,
            )

    summary = {
        "success": len(errors) == 0,
        "checked_at": (
            current_time.isoformat()
        ),
        "events_checked": len(events),
        "sent_count": len(sent),
        "sent": sent,
        "skipped_count": skipped,
        "error_count": len(errors),
        "errors": errors,
    }

    print(
        "CUSTOMER CARE COMPLETE:",
        summary,
    )

    return summary