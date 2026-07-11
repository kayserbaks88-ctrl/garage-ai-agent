from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime
from typing import Any

from core.speech_parser import merge_parsed_details


DEFAULT_REQUIRED_FIELDS = [
    "service_key",
    "registration",
    "requested_date",
    "requested_datetime",
    "name",
]


def clean(value: Any) -> str:
    return str(value or "").strip()


def first_name(full_name: str) -> str:
    name = clean(full_name)

    if not name:
        return ""

    return name.split()[0].capitalize()


def create_conversation(
    call_sid: str,
    phone: str,
    returning_customer: dict | None = None,
) -> dict:
    """
    Create the complete memory for one phone call.

    returning_customer may contain:
        name
        vehicle_reg
        service_needed
        previous_visits
    """
    returning_customer = returning_customer or {}

    known_name = clean(returning_customer.get("name"))
    known_registration = clean(
        returning_customer.get("vehicle_reg")
    ).upper()

    return {
        "call_sid": clean(call_sid),
        "phone": clean(phone),

        # Information collected during this call.
        "name": known_name,
        "service_key": "",
        "registration": known_registration,
        "vehicle": {},
        "vehicle_confirmed": False,
        "issue": "",
        "requested_date": None,
        "requested_datetime": None,
        "date_phrase": "",
        "time_phrase": "",
        "preferred_period": "",

        # Booking information.
        "available_slots": [],
        "selected_slot": None,
        "booking": None,
        "booking_attempted": False,
        "booking_error": "",

        # Customer memory.
        "returning_customer": bool(known_name),
        "previous_name": known_name,
        "previous_registration": known_registration,
        "previous_visits": int(
            returning_customer.get("previous_visits") or 0
        ),
        "same_vehicle_answered": False,

        # Conversation control.
        "awaiting": "",
        "confirmation_pending": False,
        "confirmed": False,
        "retry_count": 0,
        "silence_count": 0,
        "correction_count": 0,
        "last_question": "",
        "last_response": "",
        "raw_messages": [],
        "completed": False,
        "ended": False,
    }


def update_conversation(
    conversation: dict,
    parsed: dict,
    raw_text: str = "",
) -> dict:
    """
    Merge newly understood speech into the current conversation.

    Empty parser values never erase information already collected.
    """
    updated = deepcopy(conversation or {})
    updated = merge_parsed_details(updated, parsed or {})

    raw_text = clean(raw_text or parsed.get("raw_text"))

    if raw_text:
        updated.setdefault("raw_messages", []).append(raw_text)
        updated["last_response"] = raw_text

    if parsed.get("issue"):
        updated["issue"] = clean(parsed["issue"])

    if parsed.get("registration"):
        new_registration = clean(
            parsed["registration"]
        ).upper()

        if new_registration != updated.get(
            "previous_registration",
            "",
        ):
            updated["vehicle"] = {}
            updated["vehicle_confirmed"] = False

        updated["registration"] = new_registration

    # If a precise time was extracted, it replaces a broad period.
    if parsed.get("requested_datetime"):
        updated["requested_datetime"] = parsed[
            "requested_datetime"
        ]

    # Reset retry count after a useful response.
    useful_fields = [
        parsed.get("name"),
        parsed.get("service_key"),
        parsed.get("registration"),
        parsed.get("requested_date"),
        parsed.get("requested_datetime"),
        parsed.get("preferred_period"),
        parsed.get("issue"),
        parsed.get("confirmation"),
    ]

    if any(value not in (None, "", []) for value in useful_fields):
        updated["retry_count"] = 0
        updated["silence_count"] = 0

    return updated


def set_awaiting(
    conversation: dict,
    awaiting: str,
    question: str = "",
) -> dict:
    updated = deepcopy(conversation)

    updated["awaiting"] = clean(awaiting)

    if question:
        updated["last_question"] = clean(question)

    return updated


def register_retry(
    conversation: dict,
    silence: bool = False,
) -> dict:
    updated = deepcopy(conversation)

    updated["retry_count"] = int(
        updated.get("retry_count") or 0
    ) + 1

    if silence:
        updated["silence_count"] = int(
            updated.get("silence_count") or 0
        ) + 1

    return updated


def reset_retry(conversation: dict) -> dict:
    updated = deepcopy(conversation)
    updated["retry_count"] = 0
    updated["silence_count"] = 0
    return updated


def has_date(conversation: dict) -> bool:
    return isinstance(
        conversation.get("requested_date"),
        date,
    )


def has_exact_time(conversation: dict) -> bool:
    return isinstance(
        conversation.get("requested_datetime"),
        datetime,
    )


def has_period(conversation: dict) -> bool:
    return bool(
        clean(conversation.get("preferred_period"))
    )


def has_vehicle(conversation: dict) -> bool:
    return bool(
        clean(conversation.get("registration"))
    )


def has_customer_name(conversation: dict) -> bool:
    return bool(clean(conversation.get("name")))


def has_service(conversation: dict) -> bool:
    return bool(clean(conversation.get("service_key")))


def needs_same_vehicle_confirmation(
    conversation: dict,
) -> bool:
    """
    A returning caller with a remembered registration should first
    be asked whether today's call concerns the same vehicle.
    """
    return bool(
        conversation.get("returning_customer")
        and conversation.get("previous_registration")
        and not conversation.get("same_vehicle_answered")
        and not conversation.get("vehicle_confirmed")
    )


def missing_information(
    conversation: dict,
    require_exact_time: bool = True,
) -> list[str]:
    missing = []

    if not has_service(conversation):
        missing.append("service_key")

    if not has_vehicle(conversation):
        missing.append("registration")

    if not has_date(conversation):
        missing.append("requested_date")

    if require_exact_time and not has_exact_time(conversation):
        missing.append("requested_datetime")

    if not has_customer_name(conversation):
        missing.append("name")

    return missing


def next_missing_field(
    conversation: dict,
    require_exact_time: bool = True,
) -> str:
    """
    Decide the next most useful question.

    This is intentionally not a fixed stage sequence. It examines what
    is already known and returns only the next missing item.
    """
    if needs_same_vehicle_confirmation(conversation):
        return "same_vehicle_confirmation"

    if not has_service(conversation):
        return "service_key"

    if not has_vehicle(conversation):
        return "registration"

    if not has_date(conversation):
        return "requested_date"

    if require_exact_time and not has_exact_time(conversation):
        return "requested_datetime"

    if not has_customer_name(conversation):
        return "name"

    if not conversation.get("confirmation_pending"):
        return "summary_confirmation"

    if (
        conversation.get("confirmation_pending")
        and not conversation.get("confirmed")
    ):
        return "summary_confirmation"

    return "ready"


def mark_same_vehicle(
    conversation: dict,
    confirmed: bool,
) -> dict:
    updated = deepcopy(conversation)
    updated["same_vehicle_answered"] = True

    if confirmed:
        updated["registration"] = clean(
            updated.get("previous_registration")
        ).upper()
        updated["vehicle_confirmed"] = bool(
            updated.get("vehicle")
        )
    else:
        updated["registration"] = ""
        updated["vehicle"] = {}
        updated["vehicle_confirmed"] = False

    return updated


def set_vehicle(
    conversation: dict,
    vehicle: dict | None,
    confirmed: bool = False,
) -> dict:
    updated = deepcopy(conversation)
    vehicle = vehicle or {}

    updated["vehicle"] = vehicle
    updated["vehicle_confirmed"] = bool(
        confirmed and vehicle
    )

    registration = (
        vehicle.get("reg")
        or vehicle.get("registration")
        or updated.get("registration")
        or ""
    )

    if registration:
        updated["registration"] = clean(
            registration
        ).upper()

    return updated


def mark_vehicle_confirmed(
    conversation: dict,
    confirmed: bool,
) -> dict:
    updated = deepcopy(conversation)
    updated["vehicle_confirmed"] = bool(confirmed)

    if not confirmed:
        updated["registration"] = ""
        updated["vehicle"] = {}

    return updated


def set_available_slots(
    conversation: dict,
    slots: list[datetime],
) -> dict:
    updated = deepcopy(conversation)
    updated["available_slots"] = list(slots or [])
    return updated


def choose_slot(
    conversation: dict,
    selected_slot: datetime,
) -> dict:
    updated = deepcopy(conversation)
    updated["selected_slot"] = selected_slot
    updated["requested_datetime"] = selected_slot
    return updated


def begin_confirmation(conversation: dict) -> dict:
    updated = deepcopy(conversation)
    updated["confirmation_pending"] = True
    updated["confirmed"] = False
    updated["awaiting"] = "summary_confirmation"
    return updated


def confirm_conversation(
    conversation: dict,
    confirmed: bool,
) -> dict:
    updated = deepcopy(conversation)
    updated["confirmation_pending"] = True
    updated["confirmed"] = bool(confirmed)

    if confirmed:
        updated["awaiting"] = "booking"
    else:
        updated["awaiting"] = "correction"
        updated["correction_count"] = int(
            updated.get("correction_count") or 0
        ) + 1

    return updated


def mark_booking_attempt(
    conversation: dict,
) -> dict:
    updated = deepcopy(conversation)
    updated["booking_attempted"] = True
    updated["booking_error"] = ""
    return updated


def set_booking_result(
    conversation: dict,
    booking: dict | None = None,
    error: str = "",
) -> dict:
    updated = deepcopy(conversation)
    updated["booking"] = booking
    updated["booking_error"] = clean(error)

    if booking:
        updated["completed"] = True

    return updated


def mark_completed(conversation: dict) -> dict:
    updated = deepcopy(conversation)
    updated["completed"] = True
    return updated


def mark_ended(conversation: dict) -> dict:
    updated = deepcopy(conversation)
    updated["ended"] = True
    return updated


def format_date_for_speech(value: date | None) -> str:
    if not isinstance(value, date):
        return ""

    return value.strftime("%A %-d %B")


def format_time_for_speech(
    value: datetime | None,
) -> str:
    if not isinstance(value, datetime):
        return ""

    hour = value.strftime("%-I")
    minute = value.strftime("%M")
    period = value.strftime("%p").lower()

    if minute == "00":
        return f"{hour} {period}"

    return f"{hour} {minute} {period}"


def vehicle_description(conversation: dict) -> str:
    vehicle = conversation.get("vehicle") or {}

    description = clean(
        vehicle.get("make_model")
        or vehicle.get("description")
        or vehicle.get("vehicle")
    )

    if description:
        return description

    registration = clean(conversation.get("registration"))

    if registration:
        return f"vehicle registration {registration}"

    return "vehicle"


def build_summary(
    conversation: dict,
    service_label: str = "",
) -> str:
    """
    Build a spoken confirmation summary.
    """
    name = first_name(conversation.get("name"))
    service = clean(
        service_label
        or conversation.get("service_key")
        or "appointment"
    )

    vehicle = vehicle_description(conversation)

    date_text = format_date_for_speech(
        conversation.get("requested_date")
    )

    time_text = format_time_for_speech(
        conversation.get("requested_datetime")
    )

    parts = []

    if name:
        parts.append(f"Okay {name}")

    parts.append(
        f"you would like to book {vehicle} "
        f"for a {service}"
    )

    if date_text and time_text:
        parts.append(f"on {date_text} at {time_text}")
    elif date_text:
        parts.append(f"on {date_text}")
    elif time_text:
        parts.append(f"at {time_text}")

    issue = clean(conversation.get("issue"))

    if issue and service.lower() not in issue.lower():
        parts.append(
            f"I've also noted that you said: {issue}"
        )

    summary = ". ".join(parts).strip()

    if summary and not summary.endswith("."):
        summary += "."

    return (
        f"{summary} "
        "Is everything correct?"
    )


def conversation_snapshot(
    conversation: dict,
) -> dict:
    """
    Return a smaller diagnostic view that is safe to print in logs.
    """
    return {
        "call_sid": conversation.get("call_sid"),
        "phone": conversation.get("phone"),
        "name": conversation.get("name"),
        "service_key": conversation.get("service_key"),
        "registration": conversation.get("registration"),
        "requested_date": str(
            conversation.get("requested_date") or ""
        ),
        "requested_datetime": str(
            conversation.get("requested_datetime") or ""
        ),
        "preferred_period": conversation.get(
            "preferred_period"
        ),
        "awaiting": conversation.get("awaiting"),
        "confirmed": conversation.get("confirmed"),
        "completed": conversation.get("completed"),
        "retry_count": conversation.get("retry_count"),
    }