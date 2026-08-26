from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Any

from flask import Blueprint, jsonify, request

from trimtech.core.business import BusinessConfig
from trimtech.core.registry import get_active_business, load_business_instance
from trimtech.integrations.google_calendar.service import (
    cancel_booking,
    create_booking,
    list_bookings,
    reschedule_booking,
    service_definition,
    timezone,
)
from trimtech.modules.onboarding.service import list_onboarding_businesses
from trimtech.modules.reminders.sender import send_booking_confirmation



vapi_bp = Blueprint("trimtech_vapi", __name__, url_prefix="/vapi")


def _payload() -> dict[str, Any]:
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _phone(value: Any) -> str:
    raw = _text(value)
    if raw.lower().startswith("tel:"):
        raw = raw[4:]
    raw = re.sub(r"[^0-9+]", "", raw)
    if raw.startswith("00"):
        raw = "+" + raw[2:]
    if raw.startswith("+"):
        return "+" + re.sub(r"[^0-9]", "", raw[1:])
    return re.sub(r"[^0-9]", "", raw)


def _env_prefix(value: Any) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", _text(value)).strip("_").upper()


def _is_legacy_garage(business: BusinessConfig) -> bool:
    return _text(business.business_id).lower() in {"trimtech-garage", "garage"}


def _configured_vapi_numbers(business: BusinessConfig) -> set[str]:
    prefix = _env_prefix(business.business_id)
    names = [
        f"{prefix}_VAPI_PHONE_NUMBER",
        f"{prefix}_AI_PHONE_NUMBER",
        f"{prefix}_TWILIO_PHONE_NUMBER",
    ]

    if _is_legacy_garage(business):
        names += [
            "GARAGE_VAPI_PHONE_NUMBER",
            "GARAGE_AI_PHONE_NUMBER",
            "VAPI_PHONE_NUMBER",
            "TWILIO_PHONE_NUMBER",
        ]

    return {
        number
        for name in names
        if (number := _phone(os.getenv(name, "")))
    }


def _business_candidates() -> list[BusinessConfig]:
    businesses: list[BusinessConfig] = []
    seen: set[str] = set()

    try:
        active = get_active_business()
        businesses.append(active)
        seen.add(active.business_id)
    except Exception as error:
        print("VAPI ACTIVE BUSINESS ERROR:", repr(error))

    try:
        records = list_onboarding_businesses()
    except Exception as error:
        print("VAPI ONBOARDING LIST ERROR:", repr(error))
        records = []

    for record in records:
        slug = _text(getattr(record, "business_slug", ""))
        if not slug:
            continue

        try:
            business = load_business_instance(slug, refresh=True)
        except Exception as error:
            print("VAPI BUSINESS LOAD ERROR:", slug, repr(error))
            continue

        if business.business_id not in seen:
            businesses.append(business)
            seen.add(business.business_id)

    return businesses


def _message_type(data: dict[str, Any]) -> str:
    message = data.get("message") if isinstance(data.get("message"), dict) else {}
    return _text(message.get("type") or data.get("type")).lower()


def _called_number(data: dict[str, Any]) -> str:
    direct = _phone(data.get("called_number") or data.get("calledNumber"))
    if direct:
        return direct

    message = data.get("message") if isinstance(data.get("message"), dict) else {}

    call = message.get("call") if isinstance(message.get("call"), dict) else {}
    if not call and isinstance(data.get("call"), dict):
        call = data.get("call") or {}

    call_phone_number = (
        call.get("phoneNumber")
        if isinstance(call.get("phoneNumber"), dict)
        else {}
    )

    message_phone_number = (
        message.get("phoneNumber")
        if isinstance(message.get("phoneNumber"), dict)
        else {}
    )

    data_phone_number = (
        data.get("phoneNumber")
        if isinstance(data.get("phoneNumber"), dict)
        else {}
    )

    return _phone(
        call_phone_number.get("number")
        or call.get("phoneNumberNumber")
        or message_phone_number.get("number")
        or data_phone_number.get("number")
    )


def _resolve_business(data: dict[str, Any]) -> BusinessConfig:
    called_number = _called_number(data)

    if not called_number:
        raise LookupError("missing_called_number")

    matches = [
        business
        for business in _business_candidates()
        if called_number in _configured_vapi_numbers(business)
    ]

    if not matches:
        raise LookupError("business_not_configured")

    if len(matches) > 1:
        raise RuntimeError("duplicate_vapi_phone_mapping")

    return matches[0]


def _business_error(error: Exception):
    reason = str(error)

    messages = {
        "missing_called_number": "The business phone context was not supplied.",
        "business_not_configured": (
            "This AI phone number has not been connected to a TrimTech business yet."
        ),
        "duplicate_vapi_phone_mapping": (
            "This AI phone number is connected to more than one TrimTech business."
        ),
    }

    return jsonify(
        {
            "success": False,
            "error": reason,
            "message": messages.get(
                reason,
                "The business configuration could not be resolved.",
            ),
        }
    ), 200


def _caller_phone(data: dict[str, Any]) -> str:
    if _text(data.get("caller_number")):
        return _text(data.get("caller_number"))

    message = data.get("message") if isinstance(data.get("message"), dict) else {}
    call = message.get("call") if isinstance(message.get("call"), dict) else {}

    if not call and isinstance(data.get("call"), dict):
        call = data.get("call") or {}

    customer = call.get("customer") if isinstance(call.get("customer"), dict) else {}

    return _text(
        data.get("phone")
        or customer.get("number")
        or call.get("customerNumber")
    )


def _parse_datetime(
    business: BusinessConfig,
    raw_datetime: Any,
    *,
    require_future: bool = False,
) -> datetime:
    raw = _text(raw_datetime)
    if not raw:
        raise ValueError("missing_datetime")

    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("invalid_datetime") from error

    tz = timezone(business)
    parsed = parsed.replace(tzinfo=tz) if parsed.tzinfo is None else parsed.astimezone(tz)

    if require_future and parsed <= datetime.now(tz):
        raise ValueError("past_datetime")

    return parsed


def _spoken_datetime(business: BusinessConfig, value: str | datetime) -> str:
    parsed = value if isinstance(value, datetime) else _parse_datetime(business, value)
    parsed = parsed.astimezone(timezone(business))
    label = parsed.strftime("%I:%M %p").lstrip("0").replace(":00 ", " ")
    return f"{parsed.strftime('%A')} {parsed.day} {parsed.strftime('%B')} at {label}"


def _service_label(business: BusinessConfig, service_key: str) -> str:
    try:
        return service_definition(business, service_key).name
    except ValueError:
        return _text(service_key).replace("_", " ").title() or "Garage Appointment"


def _availability_result(
    data: dict[str, Any],
    business: BusinessConfig,
) -> dict[str, Any]:
    from trimtech.core.booking_engine import check_requested_slot

    service_key = _text(data.get("service_key")).lower()
    raw_datetime = _text(data.get("requested_datetime"))
    preferred_period = _text(data.get("preferred_period")).lower()

    if not service_key:
        return {"success": False, "message": "The service is missing."}

    if not raw_datetime:
        return {
            "success": False,
            "message": "The requested date and time are missing.",
        }

    try:
        requested_datetime = _parse_datetime(business, raw_datetime)
    except ValueError:
        return {
            "success": False,
            "message": "The requested date and time could not be understood.",
        }

    result = check_requested_slot(
        {
            "service_key": service_key,
            "requested_datetime": requested_datetime,
            "preferred_period": preferred_period,
        },
        business=business,
    )

    if result.get("error") == "missing_details":
        return {
            "success": False,
            "message": "The service or requested appointment time is missing.",
        }

    if result.get("error") == "past_datetime":
        return {
            "success": False,
            "message": "That appointment time is in the past.",
        }

    if result.get("error") == "calendar_unavailable":
        return {
            "success": False,
            "message": f"{business.name}'s calendar is temporarily unavailable.",
        }

    slots = result.get("slots") or []

    if result.get("available") and slots:
        slot = slots[0].astimezone(timezone(business))
        return {
            "success": True,
            "available": True,
            "requested_datetime": slot.isoformat(),
            "alternatives": [],
            "message": (
                "The requested appointment is available on "
                f"{_spoken_datetime(business, slot)}."
            ),
        }

    alternatives = [
        {
            "datetime": slot.astimezone(timezone(business)).isoformat(),
            "spoken": _spoken_datetime(business, slot),
        }
        for slot in slots
    ]

    if alternatives:
        return {
            "success": True,
            "available": False,
            "alternatives": alternatives,
            "message": (
                "The requested time is unavailable. Available alternatives are: "
                + ", ".join(item["spoken"] for item in alternatives)
                + "."
            ),
        }

    return {
        "success": True,
        "available": False,
        "alternatives": [],
        "message": (
            "The requested time is unavailable and there are no alternative slots that day."
        ),
    }


def _public_booking(
    business: BusinessConfig,
    booking: dict[str, Any],
) -> dict[str, Any]:
    start = booking.get("start") or ""

    try:
        spoken = _spoken_datetime(business, start) if start else ""
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


@vapi_bp.route("/tools", methods=["POST"])
def vapi_tools():
    payload = _payload()

    try:
        business = _resolve_business(payload)
    except Exception as error:
        return _business_error(error)

    message = payload.get("message") or {}
    tool_calls = message.get("toolCallList") or []
    results: list[dict[str, Any]] = []

    for tool_call in tool_calls:
        tool_call_id = _text(tool_call.get("id"))
        tool_name = _text(tool_call.get("name"))
        arguments = tool_call.get("arguments") or {}

        try:
            if tool_name == "check_availability":
                result = _availability_result(arguments, business)
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
                business.business_id,
                tool_name,
                repr(error),
            )
            results.append(
                {
                    "toolCallId": tool_call_id,
                    "error": "The requested action could not be completed right now.",
                }
            )

    return jsonify({"results": results}), 200


@vapi_bp.route("/lookup-vehicle", methods=["POST"])
def lookup_vehicle():
    data = _payload()

    try:
        business = _resolve_business(data)
    except Exception as error:
        return _business_error(error)

    from trimtech.integrations.dvla import (
        safely_lookup_vehicle,
        vehicle_confirmation_question,
    )

    registration = _text(data.get("registration"))

    if not registration:
        return jsonify(
            {"success": False, "message": "The vehicle registration is missing."}
        ), 200

    result = safely_lookup_vehicle(registration)

    if not result.get("success"):
        reason = _text(result.get("reason"))
        messages = {
            "invalid_registration": "That registration does not appear to be valid.",
            "key_missing": "The DVLA service has not been configured.",
            "key_rejected": "The DVLA API key was rejected.",
            "forbidden": "The DVLA service denied the request.",
            "not_found": "I could not find a vehicle with that registration.",
            "rate_limited": "The DVLA service is temporarily busy.",
            "service_unavailable": "The DVLA service is temporarily unavailable.",
            "invalid_response": "The DVLA service returned an invalid response.",
        }
        return jsonify(
            {
                "success": False,
                "reason": reason,
                "message": messages.get(reason, "The vehicle could not be looked up."),
            }
        ), 200

    vehicle = result["vehicle"]

    print(
        "VAPI VEHICLE LOOKUP:",
        {"business_id": business.business_id, "registration": registration},
    )

    return jsonify(
        {
            "success": True,
            "vehicle": {
                "registration": vehicle.get("registration"),
                "registration_compact": vehicle.get("registration_compact"),
                "make": vehicle.get("make"),
                "model": vehicle.get("model"),
                "make_model": vehicle.get("make_model"),
                "colour": vehicle.get("colour"),
                "year_of_manufacture": vehicle.get("year_of_manufacture"),
                "fuel_type": vehicle.get("fuel_type"),
                "engine_capacity": vehicle.get("engine_capacity"),
                "tax_status": vehicle.get("tax_status"),
                "tax_due_date": vehicle.get("tax_due_date"),
                "mot_status": vehicle.get("mot_status"),
                "mot_expiry_date": vehicle.get("mot_expiry_date"),
            },
            "message": vehicle_confirmation_question(vehicle),
        }
    ), 200


@vapi_bp.route("/check-availability", methods=["POST"])
def check_availability():
    data = _payload()

    try:
        business = _resolve_business(data)
    except Exception as error:
        return _business_error(error)

    try:
        return jsonify(_availability_result(data, business)), 200
    except Exception as error:
        print("VAPI AVAILABILITY ERROR:", business.business_id, repr(error))
        return jsonify(
            {
                "success": False,
                "message": f"{business.name}'s calendar is temporarily unavailable.",
            }
        ), 200


@vapi_bp.route("/book-appointment", methods=["POST"])
def book_appointment():
    data = _payload()

    try:
        business = _resolve_business(data)
    except Exception as error:
        return _business_error(error)

    phone = _caller_phone(data)
    service_key = _text(data.get("service_key")).lower()
    raw_datetime = _text(data.get("requested_datetime"))
    customer_name = _text(data.get("customer_name"))
    registration = _text(data.get("registration")).upper()
    make_model = _text(data.get("make_model"))
    notes = _text(data.get("notes"))

    try:
        service_definition(business, service_key)
    except ValueError:
        return jsonify(
            {"success": False, "message": "The garage service is missing or invalid."}
        ), 200

    if not raw_datetime:
        return jsonify(
            {"success": False, "message": "The appointment date and time are missing."}
        ), 200

    if not customer_name:
        return jsonify(
            {"success": False, "message": "The customer's full name is required."}
        ), 200

    if not registration:
        return jsonify(
            {"success": False, "message": "The vehicle registration is required."}
        ), 200

    try:
        requested_datetime = _parse_datetime(
            business,
            raw_datetime,
            require_future=True,
        )
    except ValueError as error:
        messages = {
            "missing_datetime": "The appointment date and time are missing.",
            "invalid_datetime": "The appointment date and time could not be understood.",
            "past_datetime": (
                "That appointment date is in the past. Please confirm a future date and time."
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

    from trimtech.integrations.dvla import safely_lookup_vehicle

    vehicle_lookup = safely_lookup_vehicle(registration)

    if vehicle_lookup.get("success"):
        vehicle_data = vehicle_lookup.get("vehicle") or {}
    else:
        vehicle_data = {
            "reg": registration,
            "registration": registration,
            "make_model": make_model or "Vehicle confirmed by customer",
        }

    try:
        booking = create_booking(
            business,
            phone=phone,
            service_key=service_key,
            start_dt=requested_datetime,
            customer_name=customer_name,
            vehicle=vehicle_data,
            notes=notes,
            source="Vapi Voice AI",
        )
    except ValueError as error:
        if str(error) == "slot_taken":
            return jsonify(
                {
                    "success": False,
                    "message": (
                        "That appointment time has just become unavailable. "
                        "Please check availability again."
                    ),
                }
            ), 200

        print("VAPI BOOKING VALUE ERROR:", business.business_id, repr(error))
        return jsonify(
            {"success": False, "message": "The appointment could not be booked."}
        ), 200
    except Exception as error:
        print("VAPI BOOKING ERROR:", business.business_id, repr(error))
        return jsonify(
            {
                "success": False,
                "message": f"{business.name}'s booking system is temporarily unavailable.",
            }
        ), 200

    label = _service_label(business, service_key)

    # Send the approved WhatsApp confirmation only after the booking succeeds.
    # If WhatsApp fails, keep the calendar booking successful and log the error.
    if phone:
        local_start = requested_datetime.astimezone(timezone(business))
        date_text = (
            f"{local_start.strftime('%A')} "
            f"{local_start.day} "
            f"{local_start.strftime('%B')}"
        )
        time_text = (
            local_start.strftime("%I:%M %p")
            .lstrip("0")
            .replace(":00 ", " ")
            .lower()
        )

        try:
            send_booking_confirmation(
                phone=phone,
                customer_name=customer_name,
                service_label=label,
                registration=registration,
                date_text=date_text,
                time_text=time_text,
            )
            print(
                "VAPI BOOKING WHATSAPP CONFIRMATION SENT:",
                {
                    "business_id": business.business_id,
                    "phone": phone,
                    "service": label,
                    "registration": registration,
                    "datetime": requested_datetime.isoformat(),
                },
            )
        except Exception as error:
            print(
                "VAPI BOOKING WHATSAPP CONFIRMATION ERROR:",
                {
                    "business_id": business.business_id,
                    "phone": phone,
                    "error": repr(error),
                },
            )
    else:
        print(
            "VAPI BOOKING WHATSAPP CONFIRMATION SKIPPED:",
            {
                "business_id": business.business_id,
                "reason": "missing_customer_phone",
            },
        )

    return jsonify(
        {
            "success": True,
            "booking_id": booking.get("id"),
            "calendar_link": booking.get("link"),
            "business_id": business.business_id,
            "service_key": service_key,
            "service": label,
            "requested_datetime": requested_datetime.isoformat(),
            "message": (
                f"The {label} appointment is now booked for {customer_name} on "
                f"{_spoken_datetime(business, requested_datetime)}."
            ),
        }
    ), 200


@vapi_bp.route("/list-bookings", methods=["POST"])
def list_customer_bookings():
    data = _payload()

    try:
        business = _resolve_business(data)
    except Exception as error:
        return _business_error(error)

    phone = _caller_phone(data)

    if not phone:
        return jsonify(
            {
                "success": False,
                "bookings": [],
                "message": (
                    "The caller's phone number is required to find their appointments."
                ),
            }
        ), 200

    try:
        bookings = list_bookings(business, phone)
    except Exception as error:
        print("VAPI LIST BOOKINGS ERROR:", business.business_id, repr(error))
        return jsonify(
            {
                "success": False,
                "bookings": [],
                "message": f"{business.name}'s calendar is temporarily unavailable.",
            }
        ), 200

    public_bookings = [
        _public_booking(business, booking)
        for booking in bookings
    ]

    if not public_bookings:
        return jsonify(
            {
                "success": True,
                "bookings": [],
                "message": (
                    "I could not find any upcoming appointments for this phone number."
                ),
            }
        ), 200

    if len(public_bookings) == 1:
        booking = public_bookings[0]
        service = booking.get("service_key") or "garage"
        registration = booking.get("registration") or "the vehicle"

        return jsonify(
            {
                "success": True,
                "bookings": public_bookings,
                "message": (
                    f"I found one upcoming {service} appointment for {registration} "
                    f"on {booking['spoken_datetime']}."
                ),
            }
        ), 200

    labels = []
    for index, booking in enumerate(public_bookings, start=1):
        service = booking.get("service_key") or "garage"
        registration = booking.get("registration") or "the vehicle"
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

def _business_prompt_variables(
    business: BusinessConfig,
    *,
    called_number: str = "",
) -> dict[str, str]:
    tz = timezone(business)
    now = datetime.now(tz)

    service_lines: list[str] = []

    for service in business.services:
        if not getattr(service, "enabled", True):
            continue

        name = _text(
            getattr(service, "name", "")
            or getattr(service, "key", "").replace("_", " ").title()
        )

        price = getattr(service, "price", None)
        duration = getattr(service, "duration_minutes", None)

        parts = [name]

        if price is not None:
            try:
                parts.append(f"£{float(price):.2f}")
            except (TypeError, ValueError):
                parts.append(_text(price))

        if duration:
            try:
                parts.append(f"{int(duration)} minutes")
            except (TypeError, ValueError):
                pass

        service_lines.append(" - ".join(parts))

    metadata = getattr(business, "metadata", {})

    if not isinstance(metadata, dict):
        metadata = {}

    opening_hours = _text(
        metadata.get("opening_hours")
    )

    business_notes = _text(
        metadata.get("business_notes")
    )

    business_timezone = _text(
        getattr(business, "timezone_name", "")
    ) or "Europe/London"

    return {
        "business_name": _text(
            getattr(business, "business_name", "")
        ),
        "timezone": business_timezone,
        "business_phone": _phone(called_number),
        "opening_hours": (
            opening_hours
            or "Opening hours have not been configured."
        ),
        "services": (
            "\n".join(service_lines)
            if service_lines
            else "No services are currently configured."
        ),
        "business_notes": business_notes,
        "current_local_datetime": now.strftime(
            "%A %d %B %Y %I:%M %p"
        ),
    }

@vapi_bp.route("/assistant-config", methods=["POST"])
def assistant_config():
    data = _payload()
    message_type = _message_type(data)

    # This endpoint is intended to be used as the Vapi phone-number
    # Server URL for dynamic inbound assistant selection.
    if message_type and message_type != "assistant-request":
        return "", 204

    try:
        business = _resolve_business(data)
    except Exception as error:
        reason = str(error)
        print(
            "VAPI ASSISTANT REQUEST BUSINESS ERROR:",
            {
                "reason": reason,
                "called_number": _called_number(data),
            },
        )

        messages = {
            "missing_called_number": (
                "Sorry, I could not identify which garage you called. "
                "Please try again shortly."
            ),
            "business_not_configured": (
                "Sorry, this garage phone line is not configured yet. "
                "Please try again shortly."
            ),
            "duplicate_vapi_phone_mapping": (
                "Sorry, this garage phone line is temporarily unavailable. "
                "Please try again shortly."
            ),
        }

        return jsonify(
            {
                "error": messages.get(
                    reason,
                    "Sorry, the garage assistant is temporarily unavailable. "
                    "Please try again shortly.",
                )
            }
        ), 200

    assistant_id = os.getenv(
        "VAPI_GARAGE_MASTER_ASSISTANT_ID",
        "",
    ).strip()

    if not assistant_id:
        print(
            "VAPI ASSISTANT REQUEST ERROR:",
            {
                "business_id": business.business_id,
                "reason": "missing_master_assistant_id",
            },
        )
        return jsonify(
            {
                "error": (
                    "Sorry, the garage assistant is temporarily unavailable. "
                    "Please try again shortly."
                )
            }
        ), 200

    called_number = _called_number(data)
    variables = _business_prompt_variables(
        business,
        called_number=called_number,
    )

    print(
        "VAPI ASSISTANT REQUEST:",
        {
            "business_id": business.business_id,
            "called_number": called_number,
            "assistant_id": assistant_id,
        },
    )

    # Vapi requires camelCase `assistantId` here.
    # assistantOverrides.variableValues fills the {{...}} values
    # in the saved shared master assistant for this call.
    return jsonify(
        {
            "assistantId": assistant_id,
            "assistantOverrides": {
                "variableValues": variables,
            },
        }
    ), 200

@vapi_bp.route("/cancel-appointment", methods=["POST"])
def cancel_appointment():
    data = _payload()

    try:
        business = _resolve_business(data)
    except Exception as error:
        return _business_error(error)

    phone = _caller_phone(data)
    booking_id = _text(data.get("booking_id"))

    if not phone:
        return jsonify(
            {
                "success": False,
                "message": (
                    "The caller's phone number is required before an appointment can be cancelled."
                ),
            }
        ), 200

    if not booking_id:
        return jsonify(
            {
                "success": False,
                "message": (
                    "The booking must be found and confirmed before it can be cancelled."
                ),
            }
        ), 200

    try:
        bookings = list_bookings(business, phone)
    except Exception as error:
        print("VAPI CANCEL LOOKUP ERROR:", business.business_id, repr(error))
        return jsonify(
            {
                "success": False,
                "message": f"{business.name}'s calendar is temporarily unavailable.",
            }
        ), 200

    booking = next(
        (
            item
            for item in bookings
            if _text(item.get("id")) == booking_id
        ),
        None,
    )

    if not booking:
        return jsonify(
            {
                "success": False,
                "message": (
                    "That upcoming appointment could not be found for this caller. "
                    "Please search again."
                ),
            }
        ), 200

    try:
        cancel_booking(business, booking_id)
    except Exception as error:
        print("VAPI CANCEL ERROR:", business.business_id, repr(error))
        return jsonify(
            {
                "success": False,
                "message": "The appointment could not be cancelled right now.",
            }
        ), 200

    service = booking.get("service") or "garage"
    registration = booking.get("reg") or "the vehicle"

    return jsonify(
        {
            "success": True,
            "booking_id": booking_id,
            "message": (
                f"The {service} appointment for {registration} on "
                f"{_spoken_datetime(business, booking.get('start'))} has been cancelled."
            ),
        }
    ), 200


@vapi_bp.route("/reschedule-appointment", methods=["POST"])
def reschedule_appointment():
    data = _payload()

    try:
        business = _resolve_business(data)
    except Exception as error:
        return _business_error(error)

    phone = _caller_phone(data)
    booking_id = _text(data.get("booking_id"))
    raw_datetime = _text(
        data.get("new_requested_datetime")
        or data.get("requested_datetime")
    )

    if not phone:
        return jsonify(
            {
                "success": False,
                "message": (
                    "The caller's phone number is required before an appointment can be rescheduled."
                ),
            }
        ), 200

    if not booking_id:
        return jsonify(
            {
                "success": False,
                "message": (
                    "The existing booking must be found and confirmed before it can be rescheduled."
                ),
            }
        ), 200

    try:
        new_start = _parse_datetime(
            business,
            raw_datetime,
            require_future=True,
        )
    except ValueError as error:
        messages = {
            "missing_datetime": "The new appointment date and time are missing.",
            "invalid_datetime": (
                "The new appointment date and time could not be understood."
            ),
            "past_datetime": "The new appointment must be in the future.",
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
        bookings = list_bookings(business, phone)
    except Exception as error:
        print("VAPI RESCHEDULE LOOKUP ERROR:", business.business_id, repr(error))
        return jsonify(
            {
                "success": False,
                "message": f"{business.name}'s calendar is temporarily unavailable.",
            }
        ), 200

    existing_booking = next(
        (
            item
            for item in bookings
            if _text(item.get("id")) == booking_id
        ),
        None,
    )

    if not existing_booking:
        return jsonify(
            {
                "success": False,
                "message": (
                    "That upcoming appointment could not be found for this caller. "
                    "Please search again."
                ),
            }
        ), 200

    try:
        updated = reschedule_booking(
            business,
            event_id=booking_id,
            new_start=new_start,
        )
    except ValueError as error:
        if str(error) == "slot_taken":
            return jsonify(
                {
                    "success": False,
                    "message": (
                        "That new appointment time is no longer available. "
                        "Please check availability again."
                    ),
                }
            ), 200

        print("VAPI RESCHEDULE VALUE ERROR:", business.business_id, repr(error))
        return jsonify(
            {
                "success": False,
                "message": "The appointment could not be rescheduled.",
            }
        ), 200
    except Exception as error:
        print("VAPI RESCHEDULE ERROR:", business.business_id, repr(error))
        return jsonify(
            {
                "success": False,
                "message": f"{business.name}'s calendar is temporarily unavailable.",
            }
        ), 200

    service = existing_booking.get("service") or "garage"
    registration = existing_booking.get("reg") or "the vehicle"
    old_spoken = _spoken_datetime(business, existing_booking.get("start"))
    new_spoken = _spoken_datetime(business, new_start)

    return jsonify(
        {
            "success": True,
            "booking_id": updated.get("id"),
            "calendar_link": updated.get("link"),
            "business_id": business.business_id,
            "service_key": updated.get("service"),
            "old_requested_datetime": existing_booking.get("start"),
            "new_requested_datetime": updated.get("start"),
            "message": (
                f"The {service} appointment for {registration} has been moved "
                f"from {old_spoken} to {new_spoken}."
            ),
        }
    ), 200