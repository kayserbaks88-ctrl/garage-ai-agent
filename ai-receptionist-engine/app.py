from __future__ import annotations

import json
import os
from datetime import datetime

from flask import Flask, jsonify, request
from twilio.twiml.messaging_response import MessagingResponse

from engine import BUSINESS
from integrations.garage_config import TIMEZONE
from integrations.garage_voice_agent import (
    handle_voice_process,
    handle_voice_start,
)

app = Flask(__name__)


# =========================================================
# Health check
# =========================================================

@app.route("/", methods=["GET"])
def home():
    return jsonify(
        {
            "ok": True,
            "service": "TrimTech AI Receptionist",
            "business": BUSINESS,
        }
    )


# =========================================================
# WhatsApp
# =========================================================

@app.route("/whatsapp", methods=["POST"])
def whatsapp():
    incoming = request.values.get("Body", "")
    phone = request.values.get("From", "")
    profile_name = request.values.get("ProfileName", "")

    if BUSINESS == "garage":
        from integrations.garage_agent import handle_message

        reply = handle_message(incoming, phone, profile_name)

    elif BUSINESS == "barber":
        from integrations.barber_agent import handle_message

        reply = handle_message(incoming, phone, profile_name)

    elif BUSINESS == "lead_gen":
        from integrations.lead_gen_agent import handle_message

        reply = handle_message(incoming, phone, profile_name)

    elif BUSINESS == "quote_builder":
        from integrations.quote_builder_agent import handle_message

        num_media = int(request.values.get("NumMedia", 0))
        media_urls = []

        for index in range(num_media):
            media_url = request.values.get(f"MediaUrl{index}")
            if media_url:
                media_urls.append(media_url)

        reply = handle_message(
            phone=phone,
            text=incoming,
            profile_name=profile_name,
            media_urls=media_urls,
        )

    elif BUSINESS == "staff_manager":
        from integrations.staff_manager_agent import handle_message

        num_media = int(request.values.get("NumMedia", 0))
        media_urls = []

        for index in range(num_media):
            media_url = request.values.get(f"MediaUrl{index}")
            if media_url:
                media_urls.append(media_url)

        reply = handle_message(
            phone=phone,
            text=incoming.strip(),
            profile_name=profile_name,
            media_urls=media_urls,
            location={
                "latitude": request.values.get("Latitude", ""),
                "longitude": request.values.get("Longitude", ""),
            },
        )

    else:
        reply = "Sorry, this service is not currently available."

    response = MessagingResponse()
    response.message(reply)

    return str(response)


# =========================================================
# Existing Twilio voice routes
# =========================================================

@app.route("/voice", methods=["POST"])
def voice():
    call_sid = request.values.get("CallSid", "")
    caller_number = request.values.get("From", "")

    return handle_voice_start(call_sid, caller_number)


@app.route("/voice/process", methods=["POST"])
def voice_process():
    call_sid = request.values.get("CallSid", "")
    caller_number = request.values.get("From", "")
    speech_text = request.values.get("SpeechResult", "")

    return handle_voice_process(
        call_sid=call_sid,
        caller_number=caller_number,
        speech_text=speech_text,
    )


# =========================================================
# Vapi tool endpoint
# =========================================================

@app.route("/vapi/tools", methods=["POST"])
def vapi_tools():
    """
    Receives Vapi custom-tool requests.

    Vapi sends:
    {
        "message": {
            "type": "tool-calls",
            "toolCallList": [
                {
                    "id": "...",
                    "name": "check_availability",
                    "arguments": {...}
                }
            ]
        }
    }
    """

    payload = request.get_json(silent=True) or {}
    message = payload.get("message") or {}
    tool_calls = message.get("toolCallList") or []

    results = []

    for tool_call in tool_calls:
        tool_call_id = str(tool_call.get("id") or "")
        tool_name = str(tool_call.get("name") or "")
        arguments = tool_call.get("arguments") or {}

        try:
            if tool_name == "check_availability":
                result_text = _vapi_check_availability(arguments)

                results.append(
                    {
                        "toolCallId": tool_call_id,
                        "result": result_text,
                    }
                )

            else:
                results.append(
                    {
                        "toolCallId": tool_call_id,
                        "error": f"Unknown tool: {tool_name}",
                    }
                )

        except Exception as error:
            print(
                "VAPI TOOL ERROR:",
                {
                    "tool": tool_name,
                    "arguments": arguments,
                    "error": repr(error),
                },
            )

            results.append(
                {
                    "toolCallId": tool_call_id,
                    "error": "The calendar could not be checked right now.",
                }
            )

    return jsonify({"results": results}), 200


def _vapi_check_availability(arguments: dict) -> str:
    """
    Checks an exact requested appointment time.

    Expected arguments:
    {
        "service_key": "mot",
        "requested_datetime": "2026-07-22T10:00:00+01:00",
        "preferred_period": "morning"
    }
    """

    from core.booking_engine import check_requested_slot

    service_key = str(arguments.get("service_key") or "").strip().lower()
    raw_datetime = str(arguments.get("requested_datetime") or "").strip()
    preferred_period = str(arguments.get("preferred_period") or "").strip().lower()

    if not service_key:
        return "A valid service is required before checking availability."

    if not raw_datetime:
        return "A requested date and time are required before checking availability."

    try:
        requested_datetime = datetime.fromisoformat(
            raw_datetime.replace("Z", "+00:00")
        )
    except ValueError:
        return "The requested date and time could not be understood."

    if requested_datetime.tzinfo is None:
        requested_datetime = requested_datetime.replace(tzinfo=TIMEZONE)
    else:
        requested_datetime = requested_datetime.astimezone(TIMEZONE)

    session = {
        "service_key": service_key,
        "requested_datetime": requested_datetime,
        "preferred_period": preferred_period,
    }

    result = check_requested_slot(session)

    if result.get("error") == "missing_details":
        return "The service or requested appointment time is missing."

    if result.get("error") == "calendar_unavailable":
        return "The garage calendar is temporarily unavailable."

    slots = result.get("slots") or []

    if result.get("available") and slots:
        slot = slots[0].astimezone(TIMEZONE)
        spoken = slot.strftime("%A %-d %B at %-I:%M %p").replace(":00", "")
        return f"The requested appointment is available on {spoken}."

    if slots:
        labels = [
            slot.astimezone(TIMEZONE)
            .strftime("%A %-d %B at %-I:%M %p")
            .replace(":00", "")
            for slot in slots
        ]

        return (
            "The requested time is unavailable. "
            f"Available alternatives are: {', '.join(labels)}."
        )

    return "The requested time is unavailable and there are no other slots that day."


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)