from __future__ import annotations

from datetime import datetime
from typing import Any

from flask import Blueprint, jsonify, request

from integrations.garage_config import SERVICES, TIMEZONE


vapi_bp = Blueprint(
    "trimtech_vapi",
    __name__,
    url_prefix="/vapi",
)


# =========================================================
# Shared helpers
# =========================================================

def _payload() -> dict[str, Any]:
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _normalise_phone(value: Any) -> str:
    return str(value or "").strip()


def _service_exists(service_key: str) -> bool:
    return service_key in SERVICES


def _service_label(service_key: str) -> str:
    service = SERVICES.get(service_key)

    if isinstance(service, dict):
        return str(
            service.get("label")
            or service.get("name")
            or service_key.replace("_", " ").title()
        )

    label = getattr(service, "label", None)
    name = getattr(service, "name", None)

    return str(
        label
        or name
        or service_key.replace("_", " ").title()
    )


def _parse_datetime(
    raw_datetime: Any,
    *,
    require_future: bool = False,
) -> datetime:
    raw_value = str(raw_datetime or "").strip()

    if not raw_value:
        raise ValueError("missing_datetime")

    try:
        parsed = datetime.fromisoformat(
            raw_value.replace("Z", "+00:00")
        )
    except ValueError as error:
        raise ValueError("invalid_datetime") from error

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=TIMEZONE)
    else:
        parsed = parsed.astimezone(TIMEZONE)

    if require_future and parsed <= datetime.now(TIMEZONE):
        raise ValueError("past_datetime")

    return parsed


def _spoken_datetime(value: str | datetime) -> str:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = _parse_datetime(value)

    parsed = parsed.astimezone(TIMEZONE)

    weekday = parsed.strftime("%A")
    month = parsed.strftime("%B")
    time_label = parsed.strftime("%I:%M %p").lstrip("0")

    if time_label.endswith(":00 AM"):
        time_label = time_label.replace(":00 AM", " AM")
    elif time_label.endswith(":00 PM"):
        time_label = time_label.replace(":00 PM", " PM")

    return (
        f"{weekday} {parsed.day} {month} "
        f"at {time_label}"
    )


def _public_booking(booking: dict[str, Any]) -> dict[str, Any]:
    start = booking.get("start") or ""

    try:
        spoken = _spoken_datetime(start) if start else ""
    except (TypeError, ValueError):
        spoken = ""

    return {
        "booking_id": booking.get("id"),
        "service_key": booking.get("service"),
        "customer_name": booking.get("customer_name"),
        "registration": booking.get("reg"),
        "make_model": booking.get("make_model"),
        "requested_datetime": start,
        "spoken_datetime": spoken,
        "summary": booking.get("summary"),
    }


def _availability_result(arguments: dict[str, Any]) -> dict[str, Any]:
    from core.booking_engine import check_requested_slot

    service_key = str(
        arguments.get("service_key") or ""
    ).strip().lower()

    raw_datetime = str(
        arguments.get("requested_datetime") or ""
    ).strip()

    preferred_period = str(
        arguments.get("preferred_period") or ""
    ).strip().lower()

    if not service_key:
        return {
            "success": False,
            "message": "The service is missing.",
        }

    if not raw_datetime:
        return {
            "success": False,
            "message": "The requested date and time are missing.",
        }

    try:
        requested_datetime = _parse_datetime(raw_datetime)
    except ValueError:
        return {
            "success": False,
            "message": (
                "The requested date and time could not be understood."
            ),
        }

    result = check_requested_slot(
        {
            "service_key": service_key,
            "requested_datetime": requested_datetime,
            "preferred_period": preferred_period,
        }
    )

    if result.get("error") == "missing_details":
        return {
            "success": False,
            "message": (
                "The service or requested appointment time is missing."
            ),
        }

    if result.get("error") == "calendar_unavailable":
        return {
            "success": False,
            "message": (
                "The garage calendar is temporarily unavailable."
            ),
        }

    slots = result.get("slots") or []

    if result.get("available") and slots:
        slot = slots[0].astimezone(TIMEZONE)

        return {
            "success": True,
            "available": True,
            "requested_datetime": slot.isoformat(),
            "alternatives": [],
            "message": (
                "The requested appointment is available on "
                f"{_spoken_datetime(slot)}."
            ),
        }

    alternatives = [
        {
            "datetime": slot.astimezone(TIMEZONE).isoformat(),
            "spoken": _spoken_datetime(
                slot.astimezone(TIMEZONE)
            ),
        }
        for slot in slots
    ]

    if alternatives:
        labels = [
            item["spoken"]
            for item in alternatives
        ]

        return {
            "success": True,
            "available": False,
            "alternatives": alternatives,
            "message": (
                "The requested time is unavailable. "
                "Available alternatives are: "
                f"{', '.join(labels)}."
            ),
        }

    return {
        "success": True,
        "available": False,
        "alternatives": [],
        "message": (
            "The requested time is unavailable and there are "
            "no alternative slots that day."
        ),
    }


# =========================================================
# Generic Vapi tool-calls endpoint
# =========================================================

@vapi_bp.route("/tools", methods=["POST"])
def vapi_tools():
    payload = _payload()
    message = payload.get("message") or {}
    tool_calls = message.get("toolCallList") or []

    results: list[dict[str, Any]] = []

    for tool_call in tool_calls:
        tool_call_id = str(tool_call.get("id") or "")
        tool_name = str(tool_call.get("name") or "")
        arguments = tool_call.get("arguments") or {}

        try:
            if tool_name == "check_availability":
                result = _availability_result(arguments)

                results.append(
                    {
                        "toolCallId": tool_call_id,
                        "result": result.get("message", ""),
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
                    "error": (
                        "The requested action could not be "
                        "completed right now."
                    ),
                }
            )

    return jsonify({"results": results}), 200


# =========================================================
# Vehicle lookup
# =========================================================

@vapi_bp.route("/lookup-vehicle", methods=["POST"])
def lookup_vehicle():
    from trimtech.integrations.dvla import (
        safely_lookup_vehicle,
        vehicle_confirmation_question,
    )

    data = _payload()
    registration = str(
        data.get("registration") or ""
    ).strip()

    if not registration:
        return jsonify(
            {
                "success": False,
                "message": (
                    "The vehicle registration is missing."
                ),
            }
        ), 200

    result = safely_lookup_vehicle(registration)

    if not result.get("success"):
        reasons = {
            "invalid_registration": (
                "That registration does not appear to be valid."
            ),
            "key_missing": (
                "The DVLA service has not been configured."
            ),
            "key_rejected": (
                "The DVLA API key was rejected."
            ),
            "forbidden": (
                "The DVLA service denied the request."
            ),
            "not_found": (
                "I could not find a vehicle with that registration."
            ),
            "rate_limited": (
                "The DVLA service is temporarily busy."
            ),
            "service_unavailable": (
                "The DVLA service is temporarily unavailable."
            ),
            "invalid_response": (
                "The DVLA service returned an invalid response."
            ),
        }

        reason = str(result.get("reason") or "")

        return jsonify(
            {
                "success": False,
                "reason": reason,
                "message": reasons.get(
                    reason,
                    "The vehicle could not be looked up.",
                ),
            }
        ), 200

    vehicle = result["vehicle"]

    return jsonify(
        {
            "success": True,
            "vehicle": {
                "registration": vehicle.get("registration"),
                "registration_compact": vehicle.get(
                    "registration_compact"
                ),
                "make": vehicle.get("make"),
                "model": vehicle.get("model"),
                "make_model": vehicle.get("make_model"),
                "colour": vehicle.get("colour"),
                "year_of_manufacture": vehicle.get(
                    "year_of_manufacture"
                ),
                "fuel_type": vehicle.get("fuel_type"),
                "engine_capacity": vehicle.get(
                    "engine_capacity"
                ),
                "tax_status": vehicle.get("tax_status"),
                "tax_due_date": vehicle.get("tax_due_date"),
                "mot_status": vehicle.get("mot_status"),
                "mot_expiry_date": vehicle.get(
                    "mot_expiry_date"
                ),
            },
            "message": vehicle_confirmation_question(vehicle),
        }
    ), 200


# =========================================================
# Availability
# =========================================================

@vapi_bp.route("/check-availability", methods=["POST"])
def check_availability():
    try:
        result = _availability_result(_payload())
        return jsonify(result), 200

    except Exception as error:
        print("VAPI AVAILABILITY ERROR:", repr(error))

        return jsonify(
            {
                "success": False,
                "message": (
                    "The garage calendar is temporarily unavailable."
                ),
            }
        ), 200


# =========================================================
# Create booking
# =========================================================

@vapi_bp.route("/book-appointment", methods=["POST"])
def book_appointment():
    from integrations.garage_calendar import create_booking

    data = _payload()

    message = data.get("message") or {}
    call = message.get("call") or data.get("call") or {}
    customer = call.get("customer") or {}

    phone = _normalise_phone(
        data.get("phone")
        or customer.get("number")
        or call.get("customerNumber")
    )

    service_key = str(
        data.get("service_key") or ""
    ).strip().lower()

    raw_datetime = str(
        data.get("requested_datetime") or ""
    ).strip()

    customer_name = str(
        data.get("customer_name") or ""
    ).strip()

    registration = str(
        data.get("registration") or ""
    ).strip().upper()

    make_model = str(
        data.get("make_model") or ""
    ).strip()

    notes = str(
        data.get("notes") or ""
    ).strip()

    print("VAPI BOOKING PHONE:", repr(phone))

    if not _service_exists(service_key):
        return jsonify(
            {
                "success": False,
                "message": (
                    "The garage service is missing or invalid."
                ),
            }
        ), 200

    if not raw_datetime:
        return jsonify(
            {
                "success": False,
                "message": (
                    "The appointment date and time are missing."
                ),
            }
        ), 200

    if not customer_name:
        return jsonify(
            {
                "success": False,
                "message": (
                    "The customer's full name is required."
                ),
            }
        ), 200

    if not registration:
        return jsonify(
            {
                "success": False,
                "message": (
                    "The vehicle registration is required."
                ),
            }
        ), 200

    try:
        requested_datetime = _parse_datetime(
            raw_datetime,
            require_future=True,
        )
    except ValueError as error:
        messages = {
            "missing_datetime": (
                "The appointment date and time are missing."
            ),
            "invalid_datetime": (
                "The appointment date and time could not "
                "be understood."
            ),
            "past_datetime": (
                "That appointment date is in the past. "
                "Please confirm a future date and time."
            ),
        }

        return jsonify(
            {
                "success": False,
                "message": messages.get(
                    str(error),
                    "The appointment date and time are invalid.",
                ),
            }
        ), 200

    try:
        booking = create_booking(
            phone=phone,
            service_key=service_key,
            start_dt=requested_datetime,
            customer_name=customer_name,
            vehicle={
                "reg": registration,
                "registration": registration,
                "make_model": (
                    make_model
                    or "Vehicle confirmed by customer"
                ),
            },
            notes=notes,
            source="Vapi Voice AI",
        )

    except ValueError as error:
        if str(error) == "slot_taken":
            return jsonify(
                {
                    "success": False,
                    "message": (
                        "That appointment time has just become "
                        "unavailable. Please check availability again."
                    ),
                }
            ), 200

        print("VAPI BOOKING VALUE ERROR:", repr(error))

        return jsonify(
            {
                "success": False,
                "message": (
                    "The appointment could not be booked."
                ),
            }
        ), 200

    except Exception as error:
        print("VAPI BOOKING ERROR:", repr(error))

        return jsonify(
            {
                "success": False,
                "message": (
                    "The garage booking system is temporarily "
                    "unavailable."
                ),
            }
        ), 200

    label = _service_label(service_key)

    return jsonify(
        {
            "success": True,
            "booking_id": booking.get("id"),
            "calendar_link": booking.get("link"),
            "service_key": service_key,
            "service": label,
            "requested_datetime": (
                requested_datetime.isoformat()
            ),
            "message": (
                f"The {label} appointment is now booked for "
                f"{customer_name} on "
                f"{_spoken_datetime(requested_datetime)}."
            ),
        }
    ), 200


# =========================================================
# List bookings
# =========================================================

@vapi_bp.route("/list-bookings", methods=["POST"])
def list_customer_bookings():
    from integrations.garage_calendar import list_bookings

    data = _payload()
    phone = _normalise_phone(data.get("phone"))

    if not phone:
        return jsonify(
            {
                "success": False,
                "bookings": [],
                "message": (
                    "The caller's phone number is required to "
                    "find their appointments."
                ),
            }
        ), 200

    try:
        bookings = list_bookings(phone)
    except Exception as error:
        print("VAPI LIST BOOKINGS ERROR:", repr(error))

        return jsonify(
            {
                "success": False,
                "bookings": [],
                "message": (
                    "The garage calendar is temporarily unavailable."
                ),
            }
        ), 200

    public_bookings = [
        _public_booking(booking)
        for booking in bookings
    ]

    if not public_bookings:
        return jsonify(
            {
                "success": True,
                "bookings": [],
                "message": (
                    "I could not find any upcoming appointments "
                    "for this phone number."
                ),
            }
        ), 200

    if len(public_bookings) == 1:
        booking = public_bookings[0]
        service = (
            booking.get("service_key") or "garage"
        )
        registration = (
            booking.get("registration") or "the vehicle"
        )

        return jsonify(
            {
                "success": True,
                "bookings": public_bookings,
                "message": (
                    f"I found one upcoming {service} appointment "
                    f"for {registration} on "
                    f"{booking['spoken_datetime']}."
                ),
            }
        ), 200

    labels = []

    for index, booking in enumerate(
        public_bookings,
        start=1,
    ):
        service = (
            booking.get("service_key") or "garage"
        )
        registration = (
            booking.get("registration") or "the vehicle"
        )

        labels.append(
            f"option {index}: {service} for {registration} "
            f"on {booking['spoken_datetime']}"
        )

    return jsonify(
        {
            "success": True,
            "bookings": public_bookings,
            "message": (
                "I found more than one upcoming appointment. "
                + "; ".join(labels)
                + ". Ask the caller which one they mean."
            ),
        }
    ), 200


# =========================================================
# Cancel booking
# =========================================================

@vapi_bp.route("/cancel-appointment", methods=["POST"])
def cancel_appointment():
    from integrations.garage_calendar import (
        cancel_booking,
        list_bookings,
    )

    data = _payload()
    phone = _normalise_phone(data.get("phone"))
    booking_id = str(
        data.get("booking_id") or ""
    ).strip()

    if not phone:
        return jsonify(
            {
                "success": False,
                "message": (
                    "The caller's phone number is required before "
                    "an appointment can be cancelled."
                ),
            }
        ), 200

    if not booking_id:
        return jsonify(
            {
                "success": False,
                "message": (
                    "The booking must be found and confirmed "
                    "before it can be cancelled."
                ),
            }
        ), 200

    try:
        bookings = list_bookings(phone)
    except Exception as error:
        print("VAPI CANCEL LOOKUP ERROR:", repr(error))

        return jsonify(
            {
                "success": False,
                "message": (
                    "The garage calendar is temporarily unavailable."
                ),
            }
        ), 200

    booking = next(
        (
            item
            for item in bookings
            if str(item.get("id") or "") == booking_id
        ),
        None,
    )

    if not booking:
        return jsonify(
            {
                "success": False,
                "message": (
                    "That upcoming appointment could not be found "
                    "for this caller. Please search again."
                ),
            }
        ), 200

    try:
        cancel_booking(booking_id)
    except Exception as error:
        print("VAPI CANCEL ERROR:", repr(error))

        return jsonify(
            {
                "success": False,
                "message": (
                    "The appointment could not be cancelled "
                    "right now."
                ),
            }
        ), 200

    service = booking.get("service") or "garage"
    registration = booking.get("reg") or "the vehicle"

    return jsonify(
        {
            "success": True,
            "booking_id": booking_id,
            "message": (
                f"The {service} appointment for {registration} "
                f"on {_spoken_datetime(booking.get('start'))} "
                "has been cancelled."
            ),
        }
    ), 200


# =========================================================
# Reschedule booking
# =========================================================

@vapi_bp.route("/reschedule-appointment", methods=["POST"])
def reschedule_appointment():
    from integrations.garage_calendar import (
        list_bookings,
        reschedule_booking,
    )

    data = _payload()
    phone = _normalise_phone(data.get("phone"))
    booking_id = str(
        data.get("booking_id") or ""
    ).strip()

    raw_datetime = str(
        data.get("new_requested_datetime")
        or data.get("requested_datetime")
        or ""
    ).strip()

    if not phone:
        return jsonify(
            {
                "success": False,
                "message": (
                    "The caller's phone number is required before "
                    "an appointment can be rescheduled."
                ),
            }
        ), 200

    if not booking_id:
        return jsonify(
            {
                "success": False,
                "message": (
                    "The existing booking must be found and "
                    "confirmed before it can be rescheduled."
                ),
            }
        ), 200

    try:
        new_start = _parse_datetime(
            raw_datetime,
            require_future=True,
        )
    except ValueError as error:
        messages = {
            "missing_datetime": (
                "The new appointment date and time are missing."
            ),
            "invalid_datetime": (
                "The new appointment date and time could not "
                "be understood."
            ),
            "past_datetime": (
                "The new appointment must be in the future."
            ),
        }

        return jsonify(
            {
                "success": False,
                "message": messages.get(
                    str(error),
                    "The new appointment date and time are invalid.",
                ),
            }
        ), 200

    try:
        bookings = list_bookings(phone)
    except Exception as error:
        print("VAPI RESCHEDULE LOOKUP ERROR:", repr(error))

        return jsonify(
            {
                "success": False,
                "message": (
                    "The garage calendar is temporarily unavailable."
                ),
            }
        ), 200

    existing_booking = next(
        (
            item
            for item in bookings
            if str(item.get("id") or "") == booking_id
        ),
        None,
    )

    if not existing_booking:
        return jsonify(
            {
                "success": False,
                "message": (
                    "That upcoming appointment could not be found "
                    "for this caller. Please search again."
                ),
            }
        ), 200

    try:
        updated = reschedule_booking(
            event_id=booking_id,
            new_start=new_start,
        )

    except ValueError as error:
        if str(error) == "slot_taken":
            return jsonify(
                {
                    "success": False,
                    "message": (
                        "That new appointment time is no longer "
                        "available. Please check availability again."
                    ),
                }
            ), 200

        print("VAPI RESCHEDULE VALUE ERROR:", repr(error))

        return jsonify(
            {
                "success": False,
                "message": (
                    "The appointment could not be rescheduled."
                ),
            }
        ), 200

    except Exception as error:
        print("VAPI RESCHEDULE ERROR:", repr(error))

        return jsonify(
            {
                "success": False,
                "message": (
                    "The garage calendar is temporarily unavailable."
                ),
            }
        ), 200

    service = existing_booking.get("service") or "garage"
    registration = (
        existing_booking.get("reg") or "the vehicle"
    )

    old_spoken = _spoken_datetime(
        existing_booking.get("start")
    )
    new_spoken = _spoken_datetime(new_start)

    return jsonify(
        {
            "success": True,
            "booking_id": updated.get("id"),
            "calendar_link": updated.get("link"),
            "service_key": updated.get("service"),
            "old_requested_datetime": (
                existing_booking.get("start")
            ),
            "new_requested_datetime": updated.get("start"),
            "message": (
                f"The {service} appointment for {registration} "
                f"has been moved from {old_spoken} "
                f"to {new_spoken}."
            ),
        }
    ), 200