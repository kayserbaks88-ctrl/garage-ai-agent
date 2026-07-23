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

@app.route("/vapi/check-availability", methods=["POST"])
def vapi_check_availability():
    from core.booking_engine import check_requested_slot

    data = request.get_json(silent=True) or {}

    service_key = str(data.get("service_key") or "").strip().lower()
    raw_datetime = str(data.get("requested_datetime") or "").strip()
    preferred_period = str(data.get("preferred_period") or "").strip().lower()

    if not service_key:
        return jsonify({
            "success": False,
            "message": "The service is missing."
        }), 200

    if not raw_datetime:
        return jsonify({
            "success": False,
            "message": "The requested date and time are missing."
        }), 200

    try:
        requested_datetime = datetime.fromisoformat(
            raw_datetime.replace("Z", "+00:00")
        )
    except ValueError:
        return jsonify({
            "success": False,
            "message": "The requested date and time could not be understood."
        }), 200

    if requested_datetime.tzinfo is None:
        requested_datetime = requested_datetime.replace(tzinfo=TIMEZONE)
    else:
        requested_datetime = requested_datetime.astimezone(TIMEZONE)

    result = check_requested_slot({
        "service_key": service_key,
        "requested_datetime": requested_datetime,
        "preferred_period": preferred_period,
    })

    if result.get("error") == "calendar_unavailable":
        return jsonify({
            "success": False,
            "message": "The garage calendar is temporarily unavailable."
        }), 200

    slots = result.get("slots") or []

    if result.get("available") and slots:
        slot = slots[0].astimezone(TIMEZONE)
        spoken = slot.strftime("%A %-d %B at %-I:%M %p").replace(":00", "")

        return jsonify({
            "success": True,
            "available": True,
            "requested_datetime": slot.isoformat(),
            "message": f"The requested appointment is available on {spoken}."
        }), 200

    alternatives = []

    for slot in slots:
        local_slot = slot.astimezone(TIMEZONE)
        alternatives.append({
            "datetime": local_slot.isoformat(),
            "spoken": local_slot.strftime(
                "%A %-d %B at %-I:%M %p"
            ).replace(":00", ""),
        })

    if alternatives:
        labels = [item["spoken"] for item in alternatives]

        return jsonify({
            "success": True,
            "available": False,
            "alternatives": alternatives,
            "message": (
                "The requested time is unavailable. "
                f"Available alternatives are: {', '.join(labels)}."
            ),
        }), 200

    return jsonify({
        "success": True,
        "available": False,
        "alternatives": [],
        "message": (
            "The requested time is unavailable and "
            "there are no alternative slots that day."
        ),
    }), 200

@app.route("/vapi/book-appointment", methods=["POST"])
def vapi_book_appointment():
    from integrations.garage_calendar import create_booking
    from integrations.garage_config import SERVICES

    data = request.get_json(silent=True) or {}

    message = data.get("message") or {}
    call = message.get("call") or data.get("call") or {}
    customer = call.get("customer") or {}

    phone = str(
        data.get("phone")
        or customer.get("number")
        or call.get("customerNumber")
        or ""
    ).strip()

    print("VAPI BOOKING PHONE:", repr(phone))
    service_key = str(data.get("service_key") or "").strip().lower()
    raw_datetime = str(data.get("requested_datetime") or "").strip()
    customer_name = str(data.get("customer_name") or "").strip()
    registration = str(data.get("registration") or "").strip().upper()
    make_model = str(data.get("make_model") or "").strip()
    notes = str(data.get("notes") or "").strip()

    if service_key not in SERVICES:
        return jsonify({
            "success": False,
            "message": "The garage service is missing or invalid.",
        }), 200

    if not raw_datetime:
        return jsonify({
            "success": False,
            "message": "The appointment date and time are missing.",
        }), 200

    if not customer_name:
        return jsonify({
            "success": False,
            "message": "The customer's full name is required.",
        }), 200

    if not registration:
        return jsonify({
            "success": False,
            "message": "The vehicle registration is required.",
        }), 200

    try:
        requested_datetime = datetime.fromisoformat(
            raw_datetime.replace("Z", "+00:00")
        )
    except ValueError:
        return jsonify({
            "success": False,
            "message": "The appointment date and time could not be understood.",
        }), 200

    if requested_datetime.tzinfo is None:
        requested_datetime = requested_datetime.replace(tzinfo=TIMEZONE)
    else:
        requested_datetime = requested_datetime.astimezone(TIMEZONE)

    if requested_datetime <= datetime.now(TIMEZONE):
        return jsonify({
            "success": False,
            "message": (
                "That appointment date is in the past. "
                "Please confirm a future date and time."
            ),
        }), 200

    try:
        booking = create_booking(
            phone=phone,
            service_key=service_key,
            start_dt=requested_datetime,
            customer_name=customer_name,
            vehicle={
                "reg": registration,
                "registration": registration,
                "make_model": make_model or "Vehicle confirmed by customer",
            },
            notes=notes,
            source="Vapi Voice AI",
        )

    except ValueError as error:
        if str(error) == "slot_taken":
            return jsonify({
                "success": False,
                "message": (
                    "That appointment time has just become unavailable. "
                    "Please check availability again."
                ),
            }), 200

        print("VAPI BOOKING VALUE ERROR:", repr(error))

        return jsonify({
            "success": False,
            "message": "The appointment could not be booked.",
        }), 200

    except Exception as error:
        print("VAPI BOOKING ERROR:", repr(error))

        return jsonify({
            "success": False,
            "message": (
                "The garage booking system is temporarily unavailable."
            ),
        }), 200

    service_label = SERVICES[service_key]["label"]
    spoken_time = requested_datetime.strftime(
        "%A %-d %B at %-I:%M %p"
    ).replace(":00", "")

    return jsonify({
        "success": True,
        "booking_id": booking.get("id"),
        "calendar_link": booking.get("link"),
        "service_key": service_key,
        "service": service_label,
        "requested_datetime": requested_datetime.isoformat(),
        "message": (
            f"The {service_label} appointment is now booked for "
            f"{customer_name} on {spoken_time}."
        ),
    }), 200

@app.route("/vapi/lookup-vehicle", methods=["POST"])
def vapi_lookup_vehicle():
    from core.dvla_helper import (
        safely_lookup_vehicle,
        vehicle_confirmation_question,
    )

    data = request.get_json(silent=True) or {}
    registration = str(data.get("registration") or "").strip()

    if not registration:
        return jsonify({
            "success": False,
            "message": "The vehicle registration is missing.",
        }), 200

    result = safely_lookup_vehicle(registration)

    if not result.get("success"):
        reasons = {
            "invalid_registration": "That registration does not appear to be valid.",
            "key_missing": "The DVLA service has not been configured.",
            "key_rejected": "The DVLA API key was rejected.",
            "forbidden": "The DVLA service denied the request.",
            "not_found": "I could not find a vehicle with that registration.",
            "rate_limited": "The DVLA service is temporarily busy.",
            "service_unavailable": "The DVLA service is temporarily unavailable.",
        }

        return jsonify({
            "success": False,
            "reason": result.get("reason"),
            "message": reasons.get(
                result.get("reason"),
                "The vehicle could not be looked up.",
            ),
        }), 200

    vehicle = result["vehicle"]

    return jsonify({
        "success": True,
        "vehicle": {
            "registration": vehicle.get("registration"),
            "make": vehicle.get("make"),
            "model": vehicle.get("model"),
            "make_model": vehicle.get("make_model"),
            "colour": vehicle.get("colour"),
            "year_of_manufacture": vehicle.get("year_of_manufacture"),
            "mot_status": vehicle.get("mot_status"),
            "mot_expiry_date": vehicle.get("mot_expiry_date"),
        },
        "message": vehicle_confirmation_question(vehicle),
    }), 200


# =========================================================
# Vapi booking-management routes
# =========================================================

def _normalise_phone(value: str) -> str:
    """Keep phone matching consistent with the value stored on calendar events."""
    return str(value or "").strip()


def _parse_vapi_datetime(raw_datetime: str) -> datetime:
    """
    Parse an ISO-8601 datetime and convert it to Europe/London.

    Raises ValueError when the value is missing, invalid, or in the past.
    """
    raw_datetime = str(raw_datetime or "").strip()

    if not raw_datetime:
        raise ValueError("missing_datetime")

    try:
        parsed = datetime.fromisoformat(
            raw_datetime.replace("Z", "+00:00")
        )
    except ValueError as error:
        raise ValueError("invalid_datetime") from error

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=TIMEZONE)
    else:
        parsed = parsed.astimezone(TIMEZONE)

    if parsed <= datetime.now(TIMEZONE):
        raise ValueError("past_datetime")

    return parsed


def _spoken_datetime(value: str | datetime) -> str:
    """Return a phone-friendly UK date and time."""
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(
            str(value).replace("Z", "+00:00")
        )

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=TIMEZONE)
    else:
        parsed = parsed.astimezone(TIMEZONE)

    return parsed.strftime(
        "%A %-d %B at %-I:%M %p"
    ).replace(":00", "")


def _public_booking(booking: dict) -> dict:
    """Return only the booking fields Vapi needs."""
    start = booking.get("start") or ""

    return {
        "booking_id": booking.get("id"),
        "service_key": booking.get("service"),
        "customer_name": booking.get("customer_name"),
        "registration": booking.get("reg"),
        "make_model": booking.get("make_model"),
        "requested_datetime": start,
        "spoken_datetime": _spoken_datetime(start) if start else "",
        "summary": booking.get("summary"),
    }


@app.route("/vapi/list-bookings", methods=["POST"])
def vapi_list_bookings():
    """
    Find future garage bookings belonging to the caller.

    Expected JSON:
    {
        "phone": "+447368593535"
    }
    """
    from integrations.garage_calendar import list_bookings

    data = request.get_json(silent=True) or {}
    phone = _normalise_phone(data.get("phone"))

    if not phone:
        return jsonify({
            "success": False,
            "bookings": [],
            "message": (
                "The caller's phone number is required to find "
                "their appointments."
            ),
        }), 200

    try:
        bookings = list_bookings(phone)
    except Exception as error:
        print("VAPI LIST BOOKINGS ERROR:", repr(error))

        return jsonify({
            "success": False,
            "bookings": [],
            "message": (
                "The garage calendar is temporarily unavailable."
            ),
        }), 200

    public_bookings = [
        _public_booking(booking)
        for booking in bookings
    ]

    if not public_bookings:
        return jsonify({
            "success": True,
            "bookings": [],
            "message": (
                "I could not find any upcoming appointments "
                "for this phone number."
            ),
        }), 200

    if len(public_bookings) == 1:
        booking = public_bookings[0]
        service = booking.get("service_key") or "garage"
        registration = booking.get("registration") or "the vehicle"

        return jsonify({
            "success": True,
            "bookings": public_bookings,
            "message": (
                f"I found one upcoming {service} appointment for "
                f"{registration} on {booking['spoken_datetime']}."
            ),
        }), 200

    labels = []

    for index, booking in enumerate(public_bookings, start=1):
        service = booking.get("service_key") or "garage"
        registration = booking.get("registration") or "the vehicle"
        labels.append(
            f"option {index}: {service} for {registration} "
            f"on {booking['spoken_datetime']}"
        )

    return jsonify({
        "success": True,
        "bookings": public_bookings,
        "message": (
            "I found more than one upcoming appointment. "
            + "; ".join(labels)
            + ". Ask the caller which one they mean."
        ),
    }), 200


@app.route("/vapi/cancel-appointment", methods=["POST"])
def vapi_cancel_appointment():
    """
    Cancel a confirmed booking.

    Expected JSON:
    {
        "phone": "+447368593535",
        "booking_id": "google-calendar-event-id"
    }
    """
    from integrations.garage_calendar import (
        cancel_booking,
        list_bookings,
    )

    data = request.get_json(silent=True) or {}
    phone = _normalise_phone(data.get("phone"))
    booking_id = str(data.get("booking_id") or "").strip()

    if not phone:
        return jsonify({
            "success": False,
            "message": (
                "The caller's phone number is required before "
                "an appointment can be cancelled."
            ),
        }), 200

    if not booking_id:
        return jsonify({
            "success": False,
            "message": (
                "The booking must be found and confirmed before "
                "it can be cancelled."
            ),
        }), 200

    try:
        bookings = list_bookings(phone)
    except Exception as error:
        print("VAPI CANCEL LOOKUP ERROR:", repr(error))

        return jsonify({
            "success": False,
            "message": (
                "The garage calendar is temporarily unavailable."
            ),
        }), 200

    booking = next(
        (
            item for item in bookings
            if str(item.get("id") or "") == booking_id
        ),
        None,
    )

    if not booking:
        return jsonify({
            "success": False,
            "message": (
                "That upcoming appointment could not be found for "
                "this caller. Please search for the booking again."
            ),
        }), 200

    try:
        cancel_booking(booking_id)
    except Exception as error:
        print("VAPI CANCEL APPOINTMENT ERROR:", repr(error))

        return jsonify({
            "success": False,
            "message": (
                "The appointment could not be cancelled right now."
            ),
        }), 200

    service = booking.get("service") or "garage"
    registration = booking.get("reg") or "the vehicle"
    spoken = _spoken_datetime(booking.get("start"))

    return jsonify({
        "success": True,
        "booking_id": booking_id,
        "message": (
            f"The {service} appointment for {registration} "
            f"on {spoken} has been cancelled."
        ),
    }), 200


@app.route("/vapi/reschedule-appointment", methods=["POST"])
def vapi_reschedule_appointment():
    """
    Move an existing confirmed booking to a new confirmed time.

    The assistant must call check_availability first.

    Expected JSON:
    {
        "phone": "+447368593535",
        "booking_id": "google-calendar-event-id",
        "new_requested_datetime": "2026-07-24T10:00:00+01:00"
    }
    """
    from integrations.garage_calendar import (
        list_bookings,
        reschedule_booking,
    )

    data = request.get_json(silent=True) or {}
    phone = _normalise_phone(data.get("phone"))
    booking_id = str(data.get("booking_id") or "").strip()
    raw_datetime = str(
        data.get("new_requested_datetime")
        or data.get("requested_datetime")
        or ""
    ).strip()

    if not phone:
        return jsonify({
            "success": False,
            "message": (
                "The caller's phone number is required before "
                "an appointment can be rescheduled."
            ),
        }), 200

    if not booking_id:
        return jsonify({
            "success": False,
            "message": (
                "The existing booking must be found and confirmed "
                "before it can be rescheduled."
            ),
        }), 200

    try:
        new_start = _parse_vapi_datetime(raw_datetime)
    except ValueError as error:
        reason = str(error)

        messages = {
            "missing_datetime": (
                "The new appointment date and time are missing."
            ),
            "invalid_datetime": (
                "The new appointment date and time could not be understood."
            ),
            "past_datetime": (
                "The new appointment must be in the future."
            ),
        }

        return jsonify({
            "success": False,
            "message": messages.get(
                reason,
                "The new appointment date and time are invalid.",
            ),
        }), 200

    try:
        bookings = list_bookings(phone)
    except Exception as error:
        print("VAPI RESCHEDULE LOOKUP ERROR:", repr(error))

        return jsonify({
            "success": False,
            "message": (
                "The garage calendar is temporarily unavailable."
            ),
        }), 200

    existing_booking = next(
        (
            item for item in bookings
            if str(item.get("id") or "") == booking_id
        ),
        None,
    )

    if not existing_booking:
        return jsonify({
            "success": False,
            "message": (
                "That upcoming appointment could not be found for "
                "this caller. Please search for the booking again."
            ),
        }), 200

    try:
        updated = reschedule_booking(
            event_id=booking_id,
            new_start=new_start,
        )
    except ValueError as error:
        if str(error) == "slot_taken":
            return jsonify({
                "success": False,
                "message": (
                    "That new appointment time is no longer available. "
                    "Please check availability again."
                ),
            }), 200

        print("VAPI RESCHEDULE VALUE ERROR:", repr(error))

        return jsonify({
            "success": False,
            "message": (
                "The appointment could not be rescheduled."
            ),
        }), 200
    except Exception as error:
        print("VAPI RESCHEDULE APPOINTMENT ERROR:", repr(error))

        return jsonify({
            "success": False,
            "message": (
                "The garage calendar is temporarily unavailable."
            ),
        }), 200

    service = existing_booking.get("service") or "garage"
    registration = existing_booking.get("reg") or "the vehicle"
    old_spoken = _spoken_datetime(existing_booking.get("start"))
    new_spoken = _spoken_datetime(new_start)

    return jsonify({
        "success": True,
        "booking_id": updated.get("id"),
        "calendar_link": updated.get("link"),
        "service_key": updated.get("service"),
        "old_requested_datetime": existing_booking.get("start"),
        "new_requested_datetime": updated.get("start"),
        "message": (
            f"The {service} appointment for {registration} has been "
            f"moved from {old_spoken} to {new_spoken}."
        ),
    }), 200

if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)