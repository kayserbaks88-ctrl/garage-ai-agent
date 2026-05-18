import os
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import dateparser
from openai import OpenAI

from garage_calendar import (
    SERVICES,
    cancel_booking,
    create_booking,
    is_free,
    list_bookings,
    reschedule_booking,
)

TIMEZONE = ZoneInfo(os.getenv("TIMEZONE", "Europe/London"))
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


SERVICE_ALIASES = {
    "mot": "mot",
    "m.o.t": "mot",
    "full service": "full service",
    "service": "full service",
    "diagnostic": "diagnostic",
    "diagnostics": "diagnostic",
    "oil": "oil change",
    "oil change": "oil change",
    "brake": "brake check",
    "brakes": "brake check",
    "brake check": "brake check",
}


def _parse_when(text: str):
    dt = dateparser.parse(
        text or "",
        settings={
            "PREFER_DATES_FROM": "future",
            "RETURN_AS_TIMEZONE_AWARE": False,
        },
    )
    if not dt:
        return None
    return dt.replace(tzinfo=TIMEZONE)


def _extract_service(text: str) -> str | None:
    t = (text or "").lower()
    for phrase, service in SERVICE_ALIASES.items():
        if phrase in t:
            return service
    return None


def _extract_reg(text: str) -> str | None:
    text = (text or "").upper().replace(" ", "")
    match = re.search(r"\b[A-Z]{2}[0-9]{2}[A-Z]{3}\b", text)
    if match:
        return match.group(0)
    return None


def _is_confirm(text: str) -> bool:
    return (text or "").strip().lower() in {
        "yes", "yes please", "yeah", "yep", "ok", "okay", "confirm", "book it", "go ahead"
    }


def _format_time(dt: datetime) -> str:
    return dt.astimezone(TIMEZONE).strftime("%A %d %b at %-I:%M %p")


def _services_menu() -> str:
    lines = ["Here’s what we can help with 👇"]
    for key, svc in SERVICES.items():
        lines.append(f"- {svc['label']} ({svc['minutes']} mins)")
    return "\n".join(lines)


def _format_booking(b: dict, index: int | None = None) -> str:
    start = datetime.fromisoformat(b["start"]).astimezone(TIMEZONE)
    service = SERVICES.get(b.get("service"), {}).get("label", b.get("service", "Booking"))
    label = f"{index}. " if index else ""
    reg = b.get("reg") or "No reg"
    return f"{label}{service} for {reg} — {start.strftime('%A %d %b at %-I:%M %p')}"


def _need_vehicle_details(session: dict) -> bool:
    vehicle = session.get("vehicle") or {}
    return not vehicle.get("reg")


def _ensure_customer(session: dict, profile_name: str | None):
    customer = session.setdefault("customer", {})
    if profile_name and not customer.get("name"):
        customer["name"] = profile_name.strip()
    return customer


def _ask_next_missing(session: dict) -> str:
    pending = session.setdefault("pending_booking", {})
    vehicle = session.setdefault("vehicle", {})

    if not pending.get("service"):
        return _services_menu()

    if not vehicle.get("reg"):
        return "No problem 👍 What’s the vehicle registration? 🚗"

    if not vehicle.get("make_model"):
        return "Thanks 👍 What make and model is the vehicle?"

    if not pending.get("when"):
        service_label = SERVICES[pending["service"]]["label"]
        return f"Nice one. When would you like to book the {service_label}?"

    if not session.get("customer", {}).get("name"):
        return "What name should I put the booking under?"

    return ""


def _try_prepare_booking(user_message: str, session: dict, profile_name: str | None):
    pending = session.setdefault("pending_booking", {})
    vehicle = session.setdefault("vehicle", {})
    customer = _ensure_customer(session, profile_name)

    service = _extract_service(user_message)
    if service:
        pending["service"] = service

    reg = _extract_reg(user_message)
    if reg:
        vehicle["reg"] = reg

    # If waiting for make/model and message is not a time/service/reg
    if vehicle.get("reg") and not vehicle.get("make_model"):
        maybe_time = _parse_when(user_message)
        if not maybe_time and not service and not reg and len(user_message.strip()) > 2:
            vehicle["make_model"] = user_message.strip()

    dt = _parse_when(user_message)
    if dt:
        pending["when"] = user_message
        pending["start_iso"] = dt.isoformat()

    if profile_name and not customer.get("name"):
        customer["name"] = profile_name.strip()


def _confirm_booking(phone: str, profile_name: str | None, session: dict) -> str:
    pending = session.get("pending_booking") or {}
    vehicle = session.get("vehicle") or {}
    customer = _ensure_customer(session, profile_name)

    service = pending.get("service")
    start_iso = pending.get("start_iso")

    if not service or not start_iso or not vehicle.get("reg") or not vehicle.get("make_model"):
        missing = _ask_next_missing(session)
        return missing or "I just need a few more details before I book that 👍"

    name = customer.get("name") or profile_name or "Customer"
    start_dt = datetime.fromisoformat(start_iso)
    minutes = SERVICES[service]["minutes"]
    end_dt = start_dt.replace()  # harmless copy
    end_dt = start_dt

    try:
        if not is_free(start_dt, start_dt.replace() if False else start_dt):
            pass
    except Exception:
        pass

    try:
        result = create_booking(
            phone=phone,
            service_name=service,
            start_dt=start_dt,
            minutes=minutes,
            name=name,
            vehicle=vehicle,
        )

        session["last_booking"] = result
        session.pop("pending_booking", None)

        service_label = SERVICES[service]["label"]
        nice_time = _format_time(start_dt)

        msg = (
            f"All set {name} 🙌\n\n"
            f"{service_label} booked for:\n"
            f"🚗 {vehicle.get('make_model')}\n"
            f"🔖 {vehicle.get('reg')}\n"
            f"🕒 {nice_time}"
        )

        if result.get("link"):
            msg += f"\n\nCalendar link:\n{result['link']}"

        return msg

    except Exception as e:
        return f"Sorry {name}, I couldn’t book that slot. It may already be taken. Try another time?"


def _handle_cancel(user_message: str, phone: str, session: dict) -> str | None:
    text = (user_message or "").lower()
    if "cancel" not in text:
        return None

    bookings = list_bookings(phone)
    if not bookings:
        return "I can’t see any upcoming bookings for you."

    if len(bookings) == 1:
        ok = cancel_booking(bookings[0]["id"])
        if ok:
            return "Done 👍 I’ve cancelled that booking for you."
        return "Sorry, I couldn’t cancel that booking."

    session["pending_cancel"] = bookings
    lines = ["Which booking do you want to cancel?"]
    for i, b in enumerate(bookings, 1):
        lines.append(_format_booking(b, i))
    return "\n".join(lines)


def _handle_reschedule(user_message: str, phone: str, session: dict) -> str | None:
    text = (user_message or "").lower()
    if not any(w in text for w in ["reschedule", "move", "change time", "change it"]):
        return None

    bookings = list_bookings(phone)
    if not bookings:
        return "I can’t see any upcoming bookings for you."

    new_time = _parse_when(user_message)

    if len(bookings) > 1 and not new_time:
        session["pending_reschedule"] = bookings
        lines = ["Which booking do you want to move?"]
        for i, b in enumerate(bookings, 1):
            lines.append(_format_booking(b, i))
        return "\n".join(lines)

    booking = session.get("last_booking")
    if booking:
        matching = next((b for b in bookings if b["id"] == booking.get("id")), None)
        booking = matching or bookings[0]
    else:
        booking = bookings[0]

    if not new_time:
        session["reschedule_target"] = booking
        return "No problem 👍 What new time would you like?"

    try:
        result = reschedule_booking(booking["id"], new_time)
        if result:
            session["last_booking"] = result
            return f"Done 👍 I’ve moved that booking to {_format_time(new_time)}."
        return "Sorry, I couldn’t reschedule that one."
    except Exception:
        return "Sorry, that new slot may already be taken. Try another time?"


def _handle_pending_number(user_message: str, phone: str, session: dict) -> str | None:
    match = re.search(r"\b(\d+)\b", user_message or "")
    if not match:
        return None

    index = int(match.group(1)) - 1

    if session.get("pending_cancel"):
        bookings = session["pending_cancel"]
        if index < 0 or index >= len(bookings):
            return "Please choose one of the booking numbers."
        ok = cancel_booking(bookings[index]["id"])
        session.pop("pending_cancel", None)
        return "Done 👍 I’ve cancelled that booking for you." if ok else "Sorry, I couldn’t cancel that booking."

    if session.get("pending_reschedule"):
        bookings = session["pending_reschedule"]
        if index < 0 or index >= len(bookings):
            return "Please choose one of the booking numbers."
        session["reschedule_target"] = bookings[index]
        session.pop("pending_reschedule", None)
        return "No problem 👍 What new time would you like?"

    return None


def run_receptionist_agent(
    user_message: str,
    phone: str,
    profile_name: str | None,
    session: dict,
    business_name: str,
    timezone_name: str,
) -> str:
    user_message = (user_message or "").strip()
    session.setdefault("history", [])
    customer = _ensure_customer(session, profile_name)

    numbered = _handle_pending_number(user_message, phone, session)
    if numbered:
        return numbered

    if session.get("reschedule_target"):
        new_time = _parse_when(user_message)
        if new_time:
            try:
                target = session.pop("reschedule_target")
                result = reschedule_booking(target["id"], new_time)
                if result:
                    session["last_booking"] = result
                    return f"Done 👍 I’ve moved that booking to {_format_time(new_time)}."
            except Exception:
                return "Sorry, that new slot may already be taken. Try another time?"
        return "What new date and time would you like?"

    cancel_reply = _handle_cancel(user_message, phone, session)
    if cancel_reply:
        return cancel_reply

    reschedule_reply = _handle_reschedule(user_message, phone, session)
    if reschedule_reply:
        return reschedule_reply

    if _is_confirm(user_message):
        return _confirm_booking(phone, profile_name, session)

    lower = user_message.lower()

    if lower in {"hi", "hello", "hey"}:
        name = customer.get("name") or "there"
        return f"Hi {name} 👋 How can I help today?"

    if "service" in lower or "price" in lower or "what do you do" in lower:
        return _services_menu()

    _try_prepare_booking(user_message, session, profile_name)

    missing = _ask_next_missing(session)
    if missing:
        return missing

    pending = session["pending_booking"]
    service = pending["service"]
    start_dt = datetime.fromisoformat(pending["start_iso"])
    vehicle = session["vehicle"]

    service_label = SERVICES[service]["label"]
    msg = (
        f"I can book that 👍\n\n"
        f"{service_label}\n"
        f"🚗 {vehicle.get('make_model')}\n"
        f"🔖 {vehicle.get('reg')}\n"
        f"🕒 {_format_time(start_dt)}\n\n"
        f"Shall I confirm it?"
    )
    return msg