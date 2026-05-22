import os
import re
import requests
from datetime import datetime

import dateparser

from garage_calendar import (
    create_booking,
    cancel_booking,
    list_bookings,
    reschedule_booking,
)
from garage_config import SERVICES, SERVICE_ALIASES, TIMEZONE


DVLA_API_KEY = os.getenv("DVLA_API_KEY")


# -----------------------------
# DVLA
# -----------------------------

def lookup_vehicle(reg: str):
    if not DVLA_API_KEY:
        print("DVLA ERROR: Missing DVLA_API_KEY")
        return None

    try:
        response = requests.post(
            "https://driver-vehicle-licensing.api.gov.uk/vehicle-enquiry/v1/vehicles",
            headers={
                "x-api-key": DVLA_API_KEY,
                "Content-Type": "application/json",
            },
            json={"registrationNumber": reg},
            timeout=10,
        )

        if response.status_code != 200:
            print("DVLA ERROR:", response.text)
            return None

        data = response.json()

        return {
            "make_model": data.get("make"),
            "fuel": data.get("fuelType"),
            "colour": data.get("colour"),
            "mot": data.get("motStatus"),
        }

    except Exception as e:
        print("DVLA FAIL:", e)
        return None


# -----------------------------
# Helpers
# -----------------------------

def _clean(text: str) -> str:
    return (text or "").strip().lower()


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


def _looks_like_date_without_time(text: str) -> bool:
    lower = _clean(text)

    has_date_word = any(
        w in lower
        for w in [
            "today", "tomorrow", "monday", "tuesday", "wednesday",
            "thursday", "friday", "saturday", "sunday",
            "jan", "feb", "mar", "apr", "may", "jun",
            "jul", "aug", "sep", "oct", "nov", "dec",
        ]
    )

    has_time = bool(
        re.search(r"\b\d{1,2}(:\d{2})?\s?(am|pm)\b", lower)
        or re.search(r"\b\d{1,2}:\d{2}\b", lower)
        or any(w in lower for w in ["morning", "afternoon", "evening", "after work"])
    )

    return has_date_word and not has_time


def _extract_reg(text: str):
    cleaned = (text or "").upper().replace(" ", "")
    match = re.search(r"\b[A-Z]{2}[0-9]{2}[A-Z]{3}\b", cleaned)
    return match.group(0) if match else None


def _extract_service(text: str):
    lower = _clean(text)
    for phrase, service_key in SERVICE_ALIASES.items():
        if phrase in lower:
            return service_key
    return None


def _is_confirm(text: str):
    return _clean(text) in {
        "yes", "yes please", "yeah", "yep", "ok", "okay",
        "confirm", "book", "book it", "go ahead", "correct",
        "that's right", "thats right", "right car"
    }


def _is_no(text: str):
    return _clean(text) in {
        "no", "nope", "wrong", "wrong car", "different", "different vehicle",
        "not correct", "nah"
    }


def _is_acknowledgement(text: str):
    return _clean(text) in {
        "thanks", "thank you", "cheers", "nice one", "perfect",
        "ok thanks", "okay thanks", "thanks mate", "cheers mate"
    }


def _is_cancel(text: str):
    lower = _clean(text)
    return "cancel" in lower


def _is_reschedule(text: str):
    lower = _clean(text)
    return any(w in lower for w in ["reschedule", "move", "change time", "change booking"])


def _is_show_bookings(text: str):
    lower = _clean(text)
    return any(
        phrase in lower
        for phrase in [
            "show my booking", "show bookings", "my bookings",
            "what bookings", "view booking", "view bookings",
            "not on calendar", "calendar"
        ]
    )


def _format_time(dt: datetime):
    return dt.astimezone(TIMEZONE).strftime("%A %d %b at %-I:%M %p")


def _services_menu(name: str | None = None):
    greeting = f"Hi {name} 👋" if name else "Hi 👋"

    lines = [
        greeting,
        "",
        "What can I help with?",
        "",
    ]

    for svc in SERVICES.values():
        lines.append(f"• {svc['label']}")

    lines.extend([
        "• View bookings",
        "• Reschedule",
        "• Cancel booking",
    ])

    return "\n".join(lines)


def _vehicle_text(vehicle: dict):
    lines = []

    if vehicle.get("make_model"):
        lines.append(f"🚗 {vehicle.get('make_model')}")

    if vehicle.get("reg"):
        lines.append(f"🔖 {vehicle.get('reg')}")

    if vehicle.get("fuel"):
        lines.append(f"⛽ {vehicle.get('fuel')}")

    if vehicle.get("colour"):
        lines.append(f"🎨 {vehicle.get('colour')}")

    if vehicle.get("mot"):
        lines.append(f"✅ MOT: {vehicle.get('mot')}")

    return "\n".join(lines)


def _booking_preview(pending: dict, customer: dict, vehicle: dict):
    service_key = pending["service"]
    svc = SERVICES[service_key]
    dt = datetime.fromisoformat(pending["datetime"])

    notes = pending.get("notes")

    msg = (
        "I can book this in:\n\n"
        f"👤 {customer.get('name', 'Customer')}\n"
        f"🔧 {svc['label']}\n"
        f"🚗 {vehicle.get('make_model', 'Vehicle')}\n"
        f"🔖 {vehicle.get('reg', 'Reg')}\n"
        f"🕒 {_format_time(dt)}\n"
        f"⏱ Approx {svc['minutes']} mins"
    )

    if notes:
        msg += f"\n📝 Notes: {notes}"

    msg += "\n\nShall I confirm? 👍"

    return msg


def _format_booking_line(b: dict, index: int | None = None):
    label = f"{index}. " if index else ""
    service = SERVICES.get(b.get("service"), {}).get("label", b.get("service", "Booking"))
    start = b.get("start")
    nice_time = ""
    if start:
        nice_time = datetime.fromisoformat(start).astimezone(TIMEZONE).strftime("%A %d %b at %-I:%M %p")

    reg = b.get("reg", "No reg")
    vehicle = b.get("make_model") or "Vehicle"

    return f"{label}{service} - {vehicle} - {reg} - {nice_time}"


def _remember_vehicle(session: dict, vehicle: dict):
    if vehicle.get("reg"):
        session["saved_vehicle"] = {
            "reg": vehicle.get("reg"),
            "make_model": vehicle.get("make_model"),
            "fuel": vehicle.get("fuel"),
            "colour": vehicle.get("colour"),
            "mot": vehicle.get("mot"),
        }


# -----------------------------
# Conversation capture
# -----------------------------

def _capture_message(user_message: str, session: dict):
    vehicle = session.setdefault("vehicle", {})
    pending = session.setdefault("pending", {})

    reg = _extract_reg(user_message)
    if reg:
        vehicle["reg"] = reg

        dvla = lookup_vehicle(reg)

        if dvla:
            vehicle["make_model"] = dvla.get("make_model")
            vehicle["fuel"] = dvla.get("fuel")
            vehicle["colour"] = dvla.get("colour")
            vehicle["mot"] = dvla.get("mot")

            pending["vehicle_confirmation_needed"] = True
            print("DVLA FOUND:", dvla)
        else:
            pending["manual_vehicle_needed"] = True

        return

    service = _extract_service(user_message)
    if service:
        pending["service"] = service
        return

    if _looks_like_date_without_time(user_message):
        dt = _parse_when(user_message)
        if dt:
            pending["date_only"] = dt.isoformat()
            return

    dt = _parse_when(user_message)
    if dt:
        pending["datetime"] = dt.isoformat()
        return

    if vehicle.get("reg") and not vehicle.get("make_model"):
        text = user_message.strip()
        if text and len(text) > 2:
            vehicle["make_model"] = text
            pending.pop("manual_vehicle_needed", None)
        return

    if pending.get("service") and SERVICES[pending["service"]].get("needs_notes") and not pending.get("notes"):
        text = user_message.strip()
        if text and len(text) > 2:
            pending["notes"] = text
        return


def _next_question(session: dict, profile_name: str | None):
    customer = session.setdefault("customer", {})
    vehicle = session.setdefault("vehicle", {})
    pending = session.setdefault("pending", {})

    if not customer.get("name"):
        if profile_name:
            customer["name"] = profile_name.strip().split()[0]
        else:
            return "No problem 👍 What name should I put the booking under?"

    if not pending.get("service"):
        return _services_menu(customer.get("name"))

    svc = SERVICES[pending["service"]]

    saved_vehicle = session.get("saved_vehicle")

    if svc.get("needs_reg") and saved_vehicle and not vehicle.get("reg") and not pending.get("saved_vehicle_checked"):
        pending["saved_vehicle_checked"] = True
        return (
            f"Welcome back {customer.get('name', '')} 👋\n\n"
            "Still for this vehicle?\n\n"
            f"{_vehicle_text(saved_vehicle)}\n\n"
            "Reply Yes, or send a different registration."
        )

    if pending.get("vehicle_confirmation_needed"):
        return (
            "I found this vehicle:\n\n"
            f"{_vehicle_text(vehicle)}\n\n"
            "Is this the right vehicle? 👍"
        )

    if pending.get("manual_vehicle_needed"):
        return "I couldn’t verify the reg just now 👍 What make and model is the vehicle?"

    if svc.get("needs_reg") and not vehicle.get("reg"):
        return "No worries 👍 What’s the registration number?"

    if svc.get("needs_vehicle") and not vehicle.get("make_model"):
        return "Thanks 👍 What make and model is the vehicle?"

    if svc.get("needs_notes") and not pending.get("notes"):
        return "Thanks 👍 What issue should I put in the notes?"

    if pending.get("date_only") and not pending.get("datetime"):
        dt = datetime.fromisoformat(pending["date_only"])
        return f"Nice 👍 What time suits you on {dt.strftime('%A %d %b')}?"

    if not pending.get("datetime"):
        return "What day/time would you like?"

    if not pending.get("confirming"):
        pending["confirming"] = True
        return _booking_preview(pending, customer, vehicle)

    return None


# -----------------------------
# Booking actions
# -----------------------------

def _confirm_booking(phone: str, profile_name: str | None, session: dict):
    customer = session.setdefault("customer", {})
    vehicle = session.setdefault("vehicle", {})
    pending = session.setdefault("pending", {})

    if profile_name and not customer.get("name"):
        customer["name"] = profile_name.strip().split()[0]

    if not customer.get("name"):
        customer["name"] = "Customer"

    service_key = pending["service"]
    booking_dt = datetime.fromisoformat(pending["datetime"])

    result = create_booking(
        phone=phone,
        service_key=service_key,
        start_dt=booking_dt,
        customer_name=customer["name"],
        vehicle=vehicle,
        notes=pending.get("notes", ""),
    )

    session["last_booking"] = result
    _remember_vehicle(session, vehicle)
    session["pending"] = {}

    svc = SERVICES[service_key]

    msg = (
        f"Nice one {customer['name']} 👍\n\n"
        "You're booked in:\n\n"
        f"🔧 {svc['label']}\n"
        f"🚗 {vehicle.get('make_model')}\n"
        f"🔖 {vehicle.get('reg')}\n"
        f"🕒 {_format_time(booking_dt)}\n"
        f"⏱ Approx {svc['minutes']} mins"
    )

    if result.get("link"):
        msg += f"\n\n📅 Calendar link:\n{result['link']}"

    msg += "\n\nSee you then 👋"

    return msg


def _handle_show_bookings(phone: str):
    bookings = list_bookings(phone)
    if not bookings:
        return "I can’t see any upcoming bookings for you 👍"

    lines = ["Here’s what I can see booked in:\n"]
    for i, b in enumerate(bookings, 1):
        lines.append(_format_booking_line(b, i))

    return "\n".join(lines)


def _handle_cancel(phone: str, session: dict):
    bookings = list_bookings(phone)
    if not bookings:
        return "I can’t see any upcoming bookings to cancel 👍"

    if len(bookings) == 1:
        cancel_booking(bookings[0]["id"])
        return "Done 👍 I’ve cancelled that booking for you."

    session["pending_cancel"] = bookings
    lines = ["Which booking would you like to cancel?"]
    for i, b in enumerate(bookings, 1):
        lines.append(_format_booking_line(b, i))
    return "\n".join(lines)


def _handle_reschedule(user_message: str, phone: str, session: dict):
    bookings = list_bookings(phone)
    if not bookings:
        return "I can’t see any upcoming bookings to move 👍"

    new_dt = _parse_when(user_message)

    if len(bookings) == 1:
        if new_dt:
            result = reschedule_booking(bookings[0]["id"], new_dt)
            session["last_booking"] = result

            msg = f"Done 👍 I’ve moved that booking to {_format_time(new_dt)}."
            if result.get("link"):
                msg += f"\n\n📅 Updated calendar link:\n{result['link']}"
            return msg

        session["reschedule_target"] = bookings[0]
        return "No problem 👍 What new date/time would you like?"

    session["pending_reschedule"] = bookings
    lines = ["Which booking would you like to move?"]
    for i, b in enumerate(bookings, 1):
        lines.append(_format_booking_line(b, i))
    return "\n".join(lines)


def _handle_number_reply(user_message: str, phone: str, session: dict):
    match = re.search(r"\b(\d+)\b", user_message or "")
    if not match:
        return None

    index = int(match.group(1)) - 1

    if session.get("pending_cancel"):
        bookings = session["pending_cancel"]
        if index < 0 or index >= len(bookings):
            return "Please choose one of the booking numbers."
        cancel_booking(bookings[index]["id"])
        session.pop("pending_cancel", None)
        return "Done 👍 I’ve cancelled that booking for you."

    if session.get("pending_reschedule"):
        bookings = session["pending_reschedule"]
        if index < 0 or index >= len(bookings):
            return "Please choose one of the booking numbers."
        session["reschedule_target"] = bookings[index]
        session.pop("pending_reschedule", None)
        return "No problem 👍 What new date/time would you like?"

    return None


# -----------------------------
# Main agent
# -----------------------------

def run_receptionist_agent(
    user_message: str,
    phone: str,
    profile_name: str | None,
    session: dict,
    business_name: str,
    timezone_name: str,
) -> str:
    user_message = (user_message or "").strip()
    lower = _clean(user_message)

    customer = session.setdefault("customer", {})
    vehicle = session.setdefault("vehicle", {})
    pending = session.setdefault("pending", {})

    if profile_name and not customer.get("name"):
        customer["name"] = profile_name.strip().split()[0]

    try:
        if not user_message:
            return _services_menu(customer.get("name"))

        number_reply = _handle_number_reply(user_message, phone, session)
        if number_reply:
            return number_reply

        if pending.get("vehicle_confirmation_needed"):
            if _is_confirm(user_message):
                pending.pop("vehicle_confirmation_needed", None)
                _remember_vehicle(session, vehicle)
                return "Perfect 👍 What day/time would you like?"
            if _is_no(user_message):
                session["vehicle"] = {}
                pending.pop("vehicle_confirmation_needed", None)
                pending.pop("manual_vehicle_needed", None)
                return "No worries 👍 send me the correct registration number."

        if pending.get("saved_vehicle_checked") and not vehicle.get("reg") and session.get("saved_vehicle"):
            if _is_confirm(user_message):
                session["vehicle"] = dict(session["saved_vehicle"])
                return "Perfect 👍 What day/time would you like?"

            reg = _extract_reg(user_message)
            if reg:
                session["vehicle"] = {}
                _capture_message(user_message, session)
                next_q = _next_question(session, profile_name)
                return next_q or "Perfect 👍 What day/time would you like?"

        if session.get("reschedule_target"):
            new_dt = _parse_when(user_message)
            if not new_dt:
                return "What new date/time would you like?"
            target = session.pop("reschedule_target")
            result = reschedule_booking(target["id"], new_dt)
            session["last_booking"] = result

            msg = f"Done 👍 I’ve moved that booking to {_format_time(new_dt)}."
            if result.get("link"):
                msg += f"\n\n📅 Updated calendar link:\n{result['link']}"
            return msg

        if _is_acknowledgement(user_message):
            name = customer.get("name") or ""
            return (
                f"You're welcome {name} 👍\n\n"
                "Anything else I can help with?\n\n"
                + "\n".join(f"• {svc['label']}" for svc in SERVICES.values())
                + "\n• View bookings\n• Reschedule\n• Cancel booking"
            )

        if _is_show_bookings(user_message):
            return _handle_show_bookings(phone)

        if _is_cancel(user_message):
            return _handle_cancel(phone, session)

        if _is_reschedule(user_message):
            return _handle_reschedule(user_message, phone, session)

        if pending.get("confirming") and _is_confirm(user_message):
            return _confirm_booking(phone, profile_name, session)

        if lower in {"hi", "hello", "hey", "start", "menu"} and not pending.get("service"):
            return _services_menu(customer.get("name"))

        _capture_message(user_message, session)

        next_q = _next_question(session, profile_name)
        if next_q:
            return next_q

        return (
            "No worries 👍 I can help with bookings, reschedules or cancellations.\n\n"
            + "\n".join(f"• {svc['label']}" for svc in SERVICES.values())
        )

    except Exception as e:
        print("❌ BOT ERROR:", e)
        return "Sorry, something went wrong on my side. Try that again 👍"