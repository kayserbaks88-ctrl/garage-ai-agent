from __future__ import annotations

import json
import os

from twilio.base.exceptions import TwilioRestException
from twilio.rest import Client

from integrations.garage_calendar import normalise_phone


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()

    if not value:
        raise ValueError(f"Missing {name}")

    return value


def _twilio_client() -> Client:
    account_sid = _required_env("TWILIO_ACCOUNT_SID")
    auth_token = _required_env("TWILIO_AUTH_TOKEN")

    return Client(account_sid, auth_token)


def _whatsapp_address(phone: str) -> str:
    """
    Convert a phone number into Twilio's WhatsApp address format.

    Example:
    07368593535 -> whatsapp:+447368593535
    """
    normalised = normalise_phone(phone)

    if not normalised:
        raise ValueError("Missing customer phone number")

    return f"whatsapp:{normalised}"


def _from_address() -> str:
    """
    TWILIO_WHATSAPP_FROM may contain either:
    +447...
    or
    whatsapp:+447...
    """
    sender = _required_env("TWILIO_WHATSAPP_FROM")

    if sender.startswith("whatsapp:"):
        return sender

    return f"whatsapp:{sender}"


def send_whatsapp_message(
    phone: str,
    body: str,
) -> dict:
    """
    Send a normal WhatsApp message.

    This should only be used when free-form WhatsApp messaging is allowed,
    such as during the active customer-service window.
    """
    if not body.strip():
        raise ValueError("Reminder message body is empty")

    try:
        message = _twilio_client().messages.create(
            from_=_from_address(),
            to=_whatsapp_address(phone),
            body=body.strip(),
        )
    except TwilioRestException as error:
        print(
            "TWILIO WHATSAPP SEND ERROR:",
            error.code,
            error.msg,
        )
        raise

    print(
        "WHATSAPP MESSAGE SENT:",
        message.sid,
        message.status,
        phone,
    )

    return {
        "success": True,
        "sid": message.sid,
        "status": message.status,
        "phone": normalise_phone(phone),
    }


def send_whatsapp_template(
    phone: str,
    content_sid: str,
    variables: dict[str, str] | None = None,
) -> dict:
    """
    Send an approved Twilio Content Template.

    Twilio Content variables must use numbered keys such as:
    {
        "1": "Baks",
        "2": "Full Service",
        "3": "MC65 XON",
        "4": "Monday 27 July",
        "5": "3:00 pm",
    }
    """
    content_sid = str(content_sid or "").strip()

    if not content_sid:
        raise ValueError("Missing Twilio Content SID")

    create_args = {
        "from_": _from_address(),
        "to": _whatsapp_address(phone),
        "content_sid": content_sid,
    }

    if variables:
        create_args["content_variables"] = json.dumps(
            {
                str(key): str(value)
                for key, value in variables.items()
            }
        )

    try:
        message = _twilio_client().messages.create(
            **create_args
        )
    except TwilioRestException as error:
        print(
            "TWILIO TEMPLATE SEND ERROR:",
            error.code,
            error.msg,
        )
        raise

    print(
        "WHATSAPP TEMPLATE SENT:",
        message.sid,
        message.status,
        content_sid,
        phone,
    )

    return {
        "success": True,
        "sid": message.sid,
        "status": message.status,
        "phone": normalise_phone(phone),
        "content_sid": content_sid,
    }


def send_24_hour_reminder(
    phone: str,
    customer_name: str,
    service_label: str,
    registration: str,
    date_text: str,
    time_text: str,
) -> dict:
    content_sid = _required_env(
        "TWILIO_REMINDER_24H_CONTENT_SID"
    )

    return send_whatsapp_template(
        phone=phone,
        content_sid=content_sid,
        variables={
            "1": customer_name,
            "2": service_label,
            "3": registration,
            "4": date_text,
            "5": time_text,
        },
    )


def send_2_hour_reminder(
    phone: str,
    customer_name: str,
    service_label: str,
    registration: str,
    time_text: str,
) -> dict:
    content_sid = _required_env(
        "TWILIO_REMINDER_2H_CONTENT_SID"
    )

    return send_whatsapp_template(
        phone=phone,
        content_sid=content_sid,
        variables={
            "1": customer_name,
            "2": service_label,
            "3": registration,
            "4": time_text,
        },
    )


def send_follow_up(
    phone: str,
    customer_name: str,
    service_label: str,
    registration: str,
) -> dict:
    content_sid = _required_env(
        "TWILIO_FOLLOW_UP_CONTENT_SID"
    )

    return send_whatsapp_template(
        phone=phone,
        content_sid=content_sid,
        variables={
            "1": customer_name,
            "2": service_label,
            "3": registration,
        },
    )