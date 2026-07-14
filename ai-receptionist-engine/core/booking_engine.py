from __future__ import annotations

from datetime import datetime

from integrations.garage_calendar import create_booking, get_available_slots, is_free
from integrations.garage_config import SERVICES, TIMEZONE


def service_label(service_key: str) -> str:
    return SERVICES.get(service_key, {}).get("label", "Garage Appointment")


def format_slot(slot: datetime) -> str:
    return slot.astimezone(TIMEZONE).strftime("%A %-d %B at %-I:%M %p").replace(":00", "").lower()


def check_requested_slot(session: dict) -> dict:
    slot = session.get("requested_datetime")
    key = session.get("service_key")
    if not isinstance(slot, datetime) or key not in SERVICES:
        return {"available": False, "slots": [], "error": "missing_details"}

    minutes = int(SERVICES[key]["minutes"])
    try:
        available = is_free(slot, slot + __import__("datetime").timedelta(minutes=minutes))
    except Exception as error:
        print("CALENDAR CHECK ERROR:", repr(error))
        return {"available": False, "slots": [], "error": "calendar_unavailable"}

    if available:
        return {"available": True, "slots": [slot], "error": ""}

    try:
        alternatives = get_available_slots(
            requested_date=slot.date(),
            service_key=key,
            preferred_period=session.get("preferred_period", ""),
            limit=4,
        )
    except Exception as error:
        print("SLOT LOOKUP ERROR:", repr(error))
        return {"available": False, "slots": [], "error": "calendar_unavailable"}

    return {"available": False, "slots": alternatives, "error": "slot_taken"}


def build_slot_offer(slots: list[datetime]) -> str:
    if not slots:
        return "I couldn't find another available time that day. What other day would suit you?"
    labels = [slot.strftime("%-I:%M %p").replace(":00", "").lower() for slot in slots]
    if len(labels) == 1:
        options = labels[0]
    elif len(labels) == 2:
        options = f"{labels[0]} or {labels[1]}"
    else:
        options = ", ".join(labels[:-1]) + f", or {labels[-1]}"
    return f"That time is unavailable. I have {options}. Which one would suit you?"


def match_slot(text: str, slots: list[datetime]) -> datetime | None:
    t = str(text or "").lower()
    positions = {
        "first": 0, "one": 0, "option one": 0,
        "second": 1, "two": 1, "option two": 1,
        "third": 2, "three": 2, "option three": 2,
        "fourth": 3, "four": 3, "option four": 3,
    }
    for phrase, index in positions.items():
        if phrase in t and index < len(slots):
            return slots[index]

    from core.speech_parser import parse_requested_time
    if slots:
        parsed = parse_requested_time(text, requested_date=slots[0].date())
        if parsed:
            for slot in slots:
                if slot.hour == parsed.hour and slot.minute == parsed.minute:
                    return slot
    return None


def create_from_session(session: dict) -> dict:
    vehicle = session.get("vehicle") or {
        "reg": session.get("registration", ""),
        "make_model": "Vehicle not confirmed",
    }
    return create_booking(
        phone=session.get("phone", ""),
        service_key=session["service_key"],
        start_dt=session.get("selected_slot") or session["requested_datetime"],
        customer_name=session["name"],
        vehicle=vehicle,
        notes=session.get("issue", ""),
        source="Voice AI",
    )
