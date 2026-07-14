from __future__ import annotations

from datetime import datetime
from typing import Any


STAGES = {
    "service",
    "same_vehicle",
    "registration",
    "registration_confirm",
    "vehicle_confirm",
    "date",
    "time",
    "name",
    "slot_choice",
    "summary",
    "correction",
    "complete",
}


def clean(value: Any) -> str:
    return str(value or "").strip()


def create_session(
    call_sid: str,
    phone: str,
    customer: dict | None = None,
) -> dict:
    customer = customer or {}
    return {
        "call_sid": clean(call_sid),
        "phone": clean(phone),
        "stage": "service",
        "name": clean(customer.get("name")),
        "returning_customer": bool(customer.get("name")),
        "previous_registration": clean(customer.get("vehicle_reg")).upper(),
        "registration": "",
        "registration_confirmed": False,
        "vehicle": {},
        "vehicle_confirmed": False,
        "service_key": "",
        "issue": "",
        "requested_date": None,
        "requested_datetime": None,
        "preferred_period": "",
        "available_slots": [],
        "selected_slot": None,
        "booking": None,
        "retry_count": 0,
        "silence_count": 0,
        "messages": [],
    }


def first_name(name: str) -> str:
    value = clean(name)
    return value.split()[0].capitalize() if value else ""


def set_stage(session: dict, stage: str) -> dict:
    if stage not in STAGES:
        raise ValueError(f"Unknown conversation stage: {stage}")
    session["stage"] = stage
    return session


def record_message(session: dict, text: str) -> dict:
    text = clean(text)
    if text:
        session.setdefault("messages", []).append(text)
    return session


def reset_retries(session: dict) -> dict:
    session["retry_count"] = 0
    session["silence_count"] = 0
    return session


def add_retry(session: dict, silence: bool = False) -> dict:
    session["retry_count"] = int(session.get("retry_count") or 0) + 1
    if silence:
        session["silence_count"] = int(session.get("silence_count") or 0) + 1
    return session


def apply_parsed(session: dict, parsed: dict) -> dict:
    for key in (
        "name",
        "service_key",
        "registration",
        "requested_date",
        "requested_datetime",
        "preferred_period",
        "issue",
    ):
        value = parsed.get(key)
        if value not in (None, "", []):
            session[key] = value
    return session


def next_required_stage(session: dict) -> str:
    if not session.get("service_key"):
        return "service"

    if (
        session.get("returning_customer")
        and session.get("previous_registration")
        and not session.get("registration")
    ):
        return "same_vehicle"

    if not session.get("registration"):
        return "registration"

    if not session.get("registration_confirmed"):
        return "registration_confirm"

    if session.get("vehicle") and not session.get("vehicle_confirmed"):
        return "vehicle_confirm"

    if not session.get("requested_date"):
        return "date"

    if not isinstance(session.get("requested_datetime"), datetime):
        return "time"

    if not session.get("name"):
        return "name"

    if not session.get("selected_slot"):
        session["selected_slot"] = session.get("requested_datetime")

    return "summary"


def summary_text(session: dict, service_label: str) -> str:
    name = first_name(session.get("name"))
    reg = clean(session.get("registration"))
    slot = session.get("selected_slot") or session.get("requested_datetime")

    date_text = slot.strftime("%A %-d %B") if isinstance(slot, datetime) else ""
    time_text = slot.strftime("%-I:%M %p").replace(":00", "").lower() if isinstance(slot, datetime) else ""

    prefix = f"Okay {name}. " if name else ""
    return (
        f"{prefix}Just to confirm, you would like a {service_label} "
        f"for registration {reg}, on {date_text} at {time_text}. "
        "Is that correct?"
    )
