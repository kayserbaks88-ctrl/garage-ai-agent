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


def lookup_vehicle(reg):
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


def _extract_reg(text: str):
    cleaned = (text or "").upper().replace(" ", "")
    match = re.search(r"\b[A-Z]{2}[0-9]{2}[A-Z]{3}\b", cleaned)
    return match.group(0) if match else None


def _extract_service(text: str):
    lower = (text or "").lower()
    for phrase, service_key in SERVICE_ALIASES.items():
        if phrase in lower:
            return service_key
    return None


def _is_confirm(text: str):
    return (text or "").strip().lower() in {
        "yes", "yes please", "yeah", "yep", "ok", "okay",
        "confirm", "book", "book it", "go ahead"
    }


def _is_cancel(text: str):
    lower = (text or "").lower()
    return "cancel" in lower


def _is_reschedule(text: str):
    lower = (text or "").lower()
    return any(w in lower for w in ["reschedule", "move", "change time", "change booking"])


def _format_time(dt: datetime):
    return dt.astimezone(TIMEZONE).strftime("%A %d %b at %-I:%M %p")


def _services_menu():
    lines = ["Hi 👋\n\nWhat can I help with?"]
    for svc in SERVICES.values():
        lines.append(f"• {svc['label']}")
    return "\n".join(lines)


def _booking_preview(pending: dict, customer: dict, vehicle: dict):
    service_key = pending["service"]
    svc = SERVICES[service_key]
    dt = datetime.fromisoformat(pending["datetime"])

    return (
        "I can book:\n\n"
        f"👤 {customer.get('name', 'Customer')}\n"
        f"🔧 {svc['label']}\n"
        f"🚗 {vehicle.get('make_model', 'Vehicle')}\n"
        f"🔖 {vehicle.get('reg', 'Reg')}\n"
        f"🕒 {_format_time(dt)}\n\n"
        "Shall I confirm?"
    )


def _format_booking_line(b: dict, index: int | None = None):
    label = f"{index}. " if index else ""
    service = SERVICES.get(b.get("service"), {}).get("label", b.get("service", "Booking"))
    start = b.get("start")
    nice_time = ""
    if start:
        nice_time = datetime.fromisoformat(start).astimezone(TIMEZONE).strftime("%A %d %b at %-I:%M %p")
    return f"{label}{service} - {b.get('reg', 'No reg')} - {nice_time}"


def _capture_message(user_message: str, session: dict):
    customer = session.setdefault("customer", {})
    vehicle = session.setdefault("vehicle", {})
    pending = session.setdefault("pending", {})

    reg = _extract_reg(user_message)
    if reg:
        vehicle["reg"] = reg

        dvla = lookup_vehicle(reg)

        if dvla:
            vehicle["make_model"] = dvla.get("make_model")

            session.setdefault("vehicle", {})["fuel"] = dvla.get("fuel")
            session.setdefault("vehicle", {})["mot"] = dvla.get("mot")

            print("DVLA FOUND:", dvla)

        return

    service = _extract_service(user_message)
    if service:
        pending["service"] = service
        return

    dt = _parse_when(user_message)
    if dt:
        pending["datetime"] = dt.isoformat()
        return

    # If we have reg but no make/model, next normal text is vehicle make/model.
    if vehicle.get("reg") and not vehicle.get("make_model"):
        text = user_message.strip()
        if text and len(text) > 2:
            vehicle["make_model"] = text
        return

    # If diagnostic/brake needs notes, capture normal text as notes after service + vehicle.
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
            customer["name"] = profile_name.strip()
        else:
            return "No problem 👍 What name should I put the booking under?"

    if not pending.get("service"):
        return _services_menu()

    svc = SERVICES[pending["service"]]

    if svc.get("needs_reg") and not vehicle.get("reg"):
        return "No worries 👍 What’s the registration number?"

    if svc.get("needs_vehicle") and not vehicle.get("make_model"):
        return "Thanks 👍 What make and model is the vehicle?"

    if svc.get("needs_notes") and not pending.get("notes"):
        return "Thanks 👍 What issue should I put in the notes?"

    if not pending.get("datetime"):
        return "What day/time would you like?"

    if not pending.get("confirming"):
        pending["confirming"] = True
        return _booking_preview(pending, customer, vehicle)

    return None


def _confirm_booking(phone: str, profile_name: str | None, session: dict):
    customer = session.setdefault("customer", {})
    vehicle = session.setdefault("vehicle", {})
    pending = session.setdefault("pending", {})

    if profile_name and not customer.get("name"):
        customer["name"] = profile_name.strip()

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
    session["pending"] = {}

    svc = SERVICES[service_key]

    msg = (
        f"Nice one {customer['name']} 👍\n\n"
        "Booked in:\n\n"
        f"👤 {customer['name']}\n"
        f"🔧 {svc['label']}\n"
        f"🚗 {vehicle.get('make_model')}\n"
        f"🔖 {vehicle.get('reg')}\n"
        f"🕒 {_format_time(booking_dt)}"
    )

    if result.get("link"):
        msg += f"\n\nCalendar link:\n{result['link']}"

    return msg


def _handle_cancel(phone: str, session: dict):
    bookings = list_bookings(phone)
    if not bookings:
        return "I can’t see any upcoming bookings for you."

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
        return "I can’t see any upcoming bookings for you."

    new_dt = _parse_when(user_message)

    if len(bookings) == 1:
        if new_dt:
            result = reschedule_booking(bookings[0]["id"], new_dt)
            session["last_booking"] = result
            return f"Done 👍 I’ve moved that booking to {_format_time(new_dt)}."

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


def run_receptionist_agent(
    user_message: str,
    phone: str,
    profile_name: str | None,
    session: dict,
    business_name: str,
    timezone_name: str,
) -> str:
    user_message = (user_message or "").strip()
    customer = session.setdefault("customer", {})
    session.setdefault("vehicle", {})
    session.setdefault("pending", {})

    if profile_name and not customer.get("name"):
        customer["name"] = profile_name.strip().split()[0]

    try:
        number_reply = _handle_number_reply(user_message, phone, session)
        if number_reply:
            return number_reply

        if session.get("reschedule_target"):
            new_dt = _parse_when(user_message)
            if not new_dt:
                return "What new date/time would you like?"
            target = session.pop("reschedule_target")
            result = reschedule_booking(target["id"], new_dt)
            session["last_booking"] = result
            return f"Done 👍 I’ve moved that booking to {_format_time(new_dt)}."

        if _is_cancel(user_message):
            return _handle_cancel(phone, session)

        if _is_reschedule(user_message):
            return _handle_reschedule(user_message, phone, session)

        pending = session.setdefault("pending", {})

        if pending.get("confirming") and _is_confirm(user_message):
            return _confirm_booking(phone, profile_name, session)

        if user_message.lower() in {"hi", "hello", "hey"} and not pending.get("service"):
            name = customer.get("name") or "there"
            return f"Hi {name} 👋\n\nWhat can I help with?\n\n" + "\n".join(
                f"• {svc['label']}" for svc in SERVICES.values()
            )

        _capture_message(user_message, session)

        next_q = _next_question(session, profile_name)
        if next_q:
            return next_q

        return "No worries 👍 What would you like to do?"

    except Exception as e:
        print("❌ BOT ERROR:", e)
        return "Sorry, something went wrong on my side. Try that again 👍"
