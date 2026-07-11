from __future__ import annotations

from datetime import date, datetime
from typing import Any

from integrations.garage_calendar import (
    create_booking,
    find_next_available_slots,
    get_available_slots,
)
from integrations.garage_config import SERVICES, TIMEZONE


def clean(value: Any) -> str:
    return str(value or "").strip()


def get_service_label(service_key: str) -> str:
    service = SERVICES.get(clean(service_key))

    if not service:
        return "Garage Appointment"

    return clean(service.get("label")) or "Garage Appointment"


def get_vehicle_payload(conversation: dict) -> dict:
    """
    Build the vehicle format expected by garage_calendar.create_booking().
    """
    vehicle = dict(conversation.get("vehicle") or {})

    registration = clean(
        conversation.get("registration")
        or vehicle.get("reg")
        or vehicle.get("registration")
    ).upper()

    make_model = clean(
        vehicle.get("make_model")
        or vehicle.get("description")
        or vehicle.get("vehicle")
    )

    return {
        "reg": registration or "Unknown reg",
        "make_model": make_model or "Vehicle not confirmed",
    }


def format_slot_for_speech(slot: datetime) -> str:
    slot = slot.astimezone(TIMEZONE)

    day_text = slot.strftime("%A %-d %B")
    hour = slot.strftime("%-I")
    minute = slot.strftime("%M")
    period = slot.strftime("%p").lower()

    if minute == "00":
        time_text = f"{hour} {period}"
    else:
        time_text = f"{hour} {minute} {period}"

    return f"{day_text} at {time_text}"


def format_time_only(slot: datetime) -> str:
    slot = slot.astimezone(TIMEZONE)

    hour = slot.strftime("%-I")
    minute = slot.strftime("%M")
    period = slot.strftime("%p").lower()

    if minute == "00":
        return f"{hour} {period}"

    return f"{hour} {minute} {period}"


def get_slots_for_conversation(
    conversation: dict,
    limit: int = 4,
) -> list[datetime]:
    """
    Find suitable slots using the caller's requested date and period.
    """
    requested_date = conversation.get("requested_date")
    service_key = clean(conversation.get("service_key"))
    preferred_period = clean(
        conversation.get("preferred_period")
    )

    if not isinstance(requested_date, date):
        return []

    if service_key not in SERVICES:
        return []

    try:
        return get_available_slots(
            requested_date=requested_date,
            service_key=service_key,
            limit=limit,
            preferred_period=preferred_period,
        )

    except Exception as error:
        print(
            "VOICE CALENDAR SLOT ERROR:",
            repr(error),
        )
        return []


def get_next_slots_for_conversation(
    conversation: dict,
    days_to_check: int = 7,
    limit: int = 4,
) -> list[datetime]:
    """
    Search beyond the requested date if that day has no availability.
    """
    requested_date = conversation.get("requested_date")
    service_key = clean(conversation.get("service_key"))
    preferred_period = clean(
        conversation.get("preferred_period")
    )

    if not isinstance(requested_date, date):
        return []

    if service_key not in SERVICES:
        return []

    try:
        return find_next_available_slots(
            start_date=requested_date,
            service_key=service_key,
            preferred_period=preferred_period,
            days_to_check=days_to_check,
            limit=limit,
        )

    except Exception as error:
        print(
            "VOICE NEXT SLOT ERROR:",
            repr(error),
        )
        return []


def match_spoken_slot(
    speech_text: str,
    slots: list[datetime],
) -> datetime | None:
    """
    Match natural replies such as:
        "the first one"
        "ten o'clock"
        "the 11 thirty slot"
        "option two"
    """
    text = clean(speech_text).lower()

    if not text or not slots:
        return None

    position_words = {
        "first": 0,
        "one": 0,
        "option one": 0,
        "number one": 0,
        "second": 1,
        "two": 1,
        "option two": 1,
        "number two": 1,
        "third": 2,
        "three": 2,
        "option three": 2,
        "number three": 2,
        "fourth": 3,
        "four": 3,
        "option four": 3,
        "number four": 3,
    }

    for phrase, index in position_words.items():
        if phrase in text and index < len(slots):
            return slots[index]

    for slot in slots:
        spoken_time = format_time_only(slot).lower()

        alternatives = {
            spoken_time,
            spoken_time.replace(" am", ""),
            spoken_time.replace(" pm", ""),
            spoken_time.replace(" ", ""),
        }

        slot_hour = slot.astimezone(TIMEZONE).strftime("%-I")
        slot_minute = slot.astimezone(TIMEZONE).strftime("%M")

        alternatives.add(slot_hour)

        if slot_minute != "00":
            alternatives.add(
                f"{slot_hour} {slot_minute}"
            )
            alternatives.add(
                f"{slot_hour}:{slot_minute}"
            )

        if any(
            alternative
            and alternative in text.replace("o'clock", "").strip()
            for alternative in alternatives
        ):
            return slot

    return None


def build_slot_offer(slots: list[datetime]) -> str:
    if not slots:
        return ""

    if len(slots) == 1:
        return (
            f"I have {format_slot_for_speech(slots[0])} available. "
            "Would you like that appointment?"
        )

    same_date = all(
        slot.date() == slots[0].date()
        for slot in slots
    )

    if same_date:
        day_text = slots[0].strftime("%A %-d %B")
        times = [
            format_time_only(slot)
            for slot in slots
        ]

        if len(times) == 2:
            options = f"{times[0]} or {times[1]}"
        else:
            options = (
                ", ".join(times[:-1])
                + f", or {times[-1]}"
            )

        return (
            f"On {day_text}, I have {options} available. "
            "Which time would suit you?"
        )

    descriptions = [
        format_slot_for_speech(slot)
        for slot in slots
    ]

    if len(descriptions) == 2:
        options = (
            f"{descriptions[0]} or {descriptions[1]}"
        )
    else:
        options = (
            ", ".join(descriptions[:-1])
            + f", or {descriptions[-1]}"
        )

    return (
        f"I have {options} available. "
        "Which appointment would suit you?"
    )


def create_booking_from_conversation(
    conversation: dict,
) -> dict:
    """
    Create the real Google Calendar booking using the collected details.
    """
    service_key = clean(
        conversation.get("service_key")
    )

    selected_slot = (
        conversation.get("selected_slot")
        or conversation.get("requested_datetime")
    )

    customer_name = clean(
        conversation.get("name")
    )

    phone = clean(
        conversation.get("phone")
    )

    issue = clean(
        conversation.get("issue")
    )

    if service_key not in SERVICES:
        raise ValueError("missing_service")

    if not isinstance(selected_slot, datetime):
        raise ValueError("missing_slot")

    if not customer_name:
        raise ValueError("missing_name")

    vehicle = get_vehicle_payload(conversation)

    return create_booking(
        phone=phone,
        service_key=service_key,
        start_dt=selected_slot,
        customer_name=customer_name,
        vehicle=vehicle,
        notes=issue,
        source="Voice AI",
    )


def safely_create_booking(
    conversation: dict,
) -> dict:
    """
    Never allow a calendar failure to crash the phone call.
    """
    try:
        booking = create_booking_from_conversation(
            conversation
        )

        return {
            "success": True,
            "booking": booking,
            "error": "",
        }

    except ValueError as error:
        reason = clean(error)

        return {
            "success": False,
            "booking": None,
            "error": reason,
        }

    except Exception as error:
        print(
            "VOICE BOOKING ERROR:",
            repr(error),
        )

        return {
            "success": False,
            "booking": None,
            "error": "calendar_unavailable",
        }


def booking_snapshot(conversation: dict) -> dict:
    slots = list(
        conversation.get("available_slots") or []
    )

    selected = conversation.get("selected_slot")

    return {
        "service_key": clean(
            conversation.get("service_key")
        ),
        "requested_date": str(
            conversation.get("requested_date") or ""
        ),
        "requested_datetime": str(
            conversation.get(
                "requested_datetime"
            )
            or ""
        ),
        "available_slots": [
            slot.isoformat()
            for slot in slots
            if isinstance(slot, datetime)
        ],
        "selected_slot": (
            selected.isoformat()
            if isinstance(selected, datetime)
            else ""
        ),
    }