import re
from datetime import datetime

import dateparser
from openai import OpenAI
import os

from garage_calendar import (
    create_booking,
    cancel_booking,
    list_bookings,
    reschedule_booking,
)

from garage_config import (
    SERVICES,
    SERVICE_ALIASES,
    TIMEZONE,
)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def _parse_when(text):
    dt = dateparser.parse(
        text,
        settings={
            "PREFER_DATES_FROM": "future",
            "RETURN_AS_TIMEZONE_AWARE": False,
        }
    )

    if not dt:
        return None

    return dt.replace(tzinfo=TIMEZONE)


def _extract_reg(text):

    text = (text or "").upper().replace(" ", "")

    match = re.search(
        r"\b[A-Z]{2}[0-9]{2}[A-Z]{3}\b",
        text
    )

    return match.group(0) if match else None


def _extract_service(text):

    text = (text or "").lower()

    for k, v in SERVICE_ALIASES.items():
        if k in text:
            return v

    return None


def _is_confirm(text):

    return (text or "").lower().strip() in {
        "yes",
        "yes please",
        "confirm",
        "book",
        "book it",
        "ok",
        "okay"
    }


def _format_time(dt):

    return dt.astimezone(TIMEZONE).strftime(
        "%A %d %b at %-I:%M %p"
    )


def run_receptionist_agent(
    user_message,
    phone,
    profile_name,
    session,
    business_name,
    timezone_name,
):

    customer = session.setdefault("customer", {})
    vehicle = session.setdefault("vehicle", {})
    pending = session.setdefault("pending", {})

    if profile_name:
        customer["name"] = profile_name


    # -------- capture reg ----------

    reg = _extract_reg(user_message)

    if reg:
        vehicle["reg"] = reg


    # -------- capture service ----------

    service = _extract_service(user_message)

    if service:
        pending["service"] = service


    # -------- capture datetime ----------

    dt = _parse_when(user_message)

    if dt:
        pending["datetime"] = dt.isoformat()


    # -------- capture make/model ----------

    if (
        vehicle.get("reg")
        and not vehicle.get("make_model")
        and len(user_message.strip()) > 3
        and not dt
        and not service
    ):

        vehicle["make_model"] = user_message


    # -------- ask missing info ----------

    if not pending.get("service"):

        menu = "\n".join(
            f"- {v['label']}"
            for v in SERVICES.values()
        )

        return f"""
Hi {customer.get("name","")} 👋

What can I help with?

{menu}
"""


    svc = SERVICES[pending["service"]]


    if svc["needs_reg"] and not vehicle.get("reg"):

        return "No worries 👍 What’s the registration number?"


    if svc["needs_vehicle"] and not vehicle.get("make_model"):

        return "Nice one 👍 What make/model is it?"


    if svc["needs_notes"] and not pending.get("notes"):

        pending["notes"] = user_message

        return "Thanks 👍 What date suits you?"


    if not pending.get("datetime"):

        return "What day/time would you like?"


    # ---------- confirm booking ----------

    booking_dt = datetime.fromisoformat(
        pending["datetime"]
    )

    if not pending.get("confirm"):

        pending["confirm"] = True

        return f"""
I can book:

🔧 {svc["label"]}
🚗 {vehicle["make_model"]}
🔖 {vehicle["reg"]}
🕒 {_format_time(booking_dt)}

Shall I confirm?
"""


    if _is_confirm(user_message):

        result = create_booking(
            phone=phone,
            service_key=pending["service"],
            start_dt=booking_dt,
            customer_name=customer.get(
                "name",
                profile_name or "Customer"
            ),
            vehicle=vehicle,
            notes=pending.get("notes","")
        )

        session["last_booking"] = result
        session["pending"] = {}

        return f"""
Nice one {customer.get("name","")} 👍

Booked in:

🔧 {svc["label"]}
🚗 {vehicle["make_model"]}
🔖 {vehicle["reg"]}
🕒 {_format_time(booking_dt)}

Calendar:

{result.get("link")}
"""


    # -------- cancel --------

    if "cancel" in user_message.lower():

        bookings = list_bookings(phone)

        if not bookings:
            return "No bookings found."

        cancel_booking(
            bookings[0]["id"]
        )

        return "Done 👍 cancelled."


    # -------- reschedule --------

    if "reschedule" in user_message.lower():

        bookings = list_bookings(phone)

        if not bookings:
            return "No booking found."

        return "What new time?"


    return (
        "Sorry 😊 "
        "I didn’t quite get that."
    )