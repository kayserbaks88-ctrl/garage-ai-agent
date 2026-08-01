from __future__ import annotations

import os
from typing import Any

from dotenv import load_dotenv
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse

from garage_agent import run_receptionist_agent
from garage_config import BUSINESS_NAME, TIMEZONE_NAME


load_dotenv()

app = Flask(__name__)

SESSIONS: dict[str, dict[str, Any]] = {}


def normalise_message(value: str) -> str:
    """
    Convert an incoming WhatsApp message into a predictable format
    for command matching.
    """
    return " ".join(str(value or "").strip().lower().split())


def create_whatsapp_response(message: str) -> str:
    """
    Return a valid Twilio MessagingResponse.
    """
    response = MessagingResponse()
    response.message(message)
    return str(response)


def handle_reminder_reply(
    incoming_message: str,
    session: dict[str, Any],
) -> str | None:
    """
    Intercept replies from appointment reminder templates before they
    reach the normal garage receptionist conversation.

    Return a reply when the message is a reminder action.
    Return None when the normal receptionist should handle the message.
    """
    normalised = normalise_message(incoming_message)

    confirm_replies = {
        "confirm",
        "confirmed",
        "yes confirm",
        "confirm appointment",
        "confirm booking",
        "yes",
    }

    cancel_replies = {
        "cancel",
        "cancel appointment",
        "cancel booking",
        "i need to cancel",
        "i want to cancel",
    }

    if normalised in confirm_replies:
        # Clear any abandoned conversation so the reminder response
        # does not continue an old booking flow.
        session.clear()

        session["last_action"] = "appointment_reminder_confirmed"
        session["appointment_confirmed"] = True

        return (
            "Thanks, your appointment is confirmed.\n\n"
            "We look forward to seeing you at TrimTech Garage."
        )

    if normalised in cancel_replies:
        # Do not cancel an appointment immediately.
        # Pass a clear cancellation request into the receptionist so it
        # can retrieve the customer's booking and ask for confirmation.
        session.clear()
        session["last_action"] = "appointment_reminder_cancel_requested"
        session["reminder_cancel_requested"] = True

        return None

    return None


@app.route("/", methods=["GET"])
def home():
    return {
        "ok": True,
        "service": BUSINESS_NAME,
    }


@app.route("/health", methods=["GET"])
def health():
    return {
        "ok": True,
        "service": BUSINESS_NAME,
    }


@app.route("/whatsapp", methods=["POST"])
def whatsapp():
    from_number = str(request.values.get("From", "") or "").strip()
    body = str(request.values.get("Body", "") or "").strip()
    profile_name = str(request.values.get("ProfileName", "") or "").strip()

    if not from_number:
        print("⚠️ WHATSAPP ERROR: Missing sender number")
        return create_whatsapp_response(
            "Sorry, we couldn't process that message. Please try again."
        )

    session = SESSIONS.setdefault(from_number, {})

    print("📩 MESSAGE:", body)
    print("👤 USER:", from_number)
    print("🧾 PROFILE NAME:", profile_name)

    normalised_body = normalise_message(body)

    # Handle reminder quick replies before sending anything to the
    # original garage receptionist agent.
    reminder_reply = handle_reminder_reply(
        incoming_message=body,
        session=session,
    )

    if reminder_reply is not None:
        print("⏰ REMINDER REPLY:", reminder_reply)
        return create_whatsapp_response(reminder_reply)

    # A Cancel quick reply should enter the proper cancellation flow
    # rather than being interpreted as a new greeting or menu request.
    if session.get("reminder_cancel_requested") and normalised_body in {
        "cancel",
        "cancel appointment",
        "cancel booking",
        "i need to cancel",
        "i want to cancel",
    }:
        agent_message = "I would like to cancel my existing appointment."
        session.pop("reminder_cancel_requested", None)
    else:
        agent_message = body

    try:
        reply = run_receptionist_agent(
            user_message=agent_message,
            phone=from_number,
            profile_name=profile_name,
            session=session,
            business_name=BUSINESS_NAME,
            timezone_name=TIMEZONE_NAME,
        )
    except Exception as error:
        print("❌ GARAGE AGENT ERROR:", repr(error))

        reply = (
            "Sorry, we're having a little trouble processing that at the moment. "
            "Please try again shortly or contact TrimTech Garage directly."
        )

    reply = str(reply or "").strip()

    if not reply:
        reply = (
            "Sorry, I couldn't process that message. "
            "Please tell me how I can help."
        )

    print("🤖 REPLY:", reply)

    return create_whatsapp_response(reply)


if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    app.run(
        host="0.0.0.0",
        port=port,
    )