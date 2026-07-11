from __future__ import annotations

import os
import re
from typing import Any

import requests


DVLA_API_KEY = os.getenv("DVLA_API_KEY", "").strip()

DVLA_API_URL = os.getenv(
    "DVLA_API_URL",
    (
        "https://driver-vehicle-licensing.api.gov.uk/"
        "vehicle-enquiry/v1/vehicles"
    ),
).strip()

REQUEST_TIMEOUT_SECONDS = 12


class DVLAError(Exception):
    """Base error for DVLA vehicle lookup failures."""


class DVLAKeyMissingError(DVLAError):
    """Raised when DVLA_API_KEY has not been configured."""


class DVLAVehicleNotFoundError(DVLAError):
    """Raised when the registration cannot be found."""


class DVLAInvalidRegistrationError(DVLAError):
    """Raised when the supplied registration is invalid."""


class DVLARateLimitError(DVLAError):
    """Raised when the DVLA rate limit has been reached."""


class DVLAServiceUnavailableError(DVLAError):
    """Raised when the DVLA service cannot currently respond."""


def clean(value: Any) -> str:
    return str(value or "").strip()


def clean_registration(registration: str) -> str:
    """
    Return the compact uppercase form expected by the DVLA API.

    Example:
        "ab12 cde" -> "AB12CDE"
    """
    return re.sub(
        r"[^A-Z0-9]",
        "",
        clean(registration).upper(),
    )


def format_registration(registration: str) -> str:
    """
    Format a modern seven-character UK registration for speech/display.

    Example:
        "AB12CDE" -> "AB12 CDE"
    """
    compact = clean_registration(registration)

    if len(compact) == 7:
        return f"{compact[:4]} {compact[4:]}"

    return compact


def has_api_key() -> bool:
    return bool(DVLA_API_KEY)


def _safe_int(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None

        return int(value)

    except (TypeError, ValueError):
        return None


def _safe_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value

    normalised = clean(value).lower()

    if normalised in {"true", "yes", "1"}:
        return True

    if normalised in {"false", "no", "0"}:
        return False

    return None


def _title_case(value: Any) -> str:
    text = clean(value)

    if not text:
        return ""

    return text.replace("_", " ").title()


def _build_make_model(data: dict) -> str:
    """
    VES commonly returns a make, but may not provide a model.

    Keep the result honest and never invent a model.
    """
    make = clean(data.get("make"))
    model = clean(data.get("model"))

    parts = []

    if make:
        parts.append(make.title())

    if model:
        parts.append(model.title())

    return " ".join(parts)


def normalise_vehicle_response(
    data: dict,
    fallback_registration: str = "",
) -> dict:
    """
    Convert the raw DVLA response into the consistent vehicle structure
    used by the receptionist and calendar modules.
    """
    registration = (
        clean(data.get("registrationNumber"))
        or clean(fallback_registration)
    )

    make_model = _build_make_model(data)

    return {
        "found": True,
        "reg": format_registration(registration),
        "registration": format_registration(registration),
        "make": clean(data.get("make")).title(),
        "model": clean(data.get("model")).title(),
        "make_model": make_model,
        "colour": clean(data.get("colour")).title(),
        "fuel_type": _title_case(data.get("fuelType")),
        "year_of_manufacture": _safe_int(
            data.get("yearOfManufacture")
        ),
        "engine_capacity": _safe_int(
            data.get("engineCapacity")
        ),
        "co2_emissions": _safe_int(
            data.get("co2Emissions")
        ),
        "tax_status": _title_case(
            data.get("taxStatus")
        ),
        "tax_due_date": clean(
            data.get("taxDueDate")
        ),
        "mot_status": _title_case(
            data.get("motStatus")
        ),
        "mot_expiry_date": clean(
            data.get("motExpiryDate")
        ),
        "marked_for_export": _safe_bool(
            data.get("markedForExport")
        ),
        "type_approval": clean(
            data.get("typeApproval")
        ),
        "wheelplan": _title_case(
            data.get("wheelplan")
        ),
        "month_of_first_registration": clean(
            data.get("monthOfFirstRegistration")
        ),
        "art_end_date": clean(
            data.get("artEndDate")
        ),
        "revenue_weight": _safe_int(
            data.get("revenueWeight")
        ),
        "real_driving_emissions": clean(
            data.get("realDrivingEmissions")
        ),
        "euro_status": clean(
            data.get("euroStatus")
        ),
        "date_of_last_v5c_issued": clean(
            data.get("dateOfLastV5CIssued")
        ),
        "raw": dict(data),
    }


def _extract_error_message(response: requests.Response) -> str:
    try:
        payload = response.json()

    except ValueError:
        return clean(response.text)

    if isinstance(payload, dict):
        for key in (
            "message",
            "error",
            "title",
            "detail",
        ):
            if payload.get(key):
                return clean(payload[key])

        errors = payload.get("errors")

        if isinstance(errors, list):
            messages = []

            for item in errors:
                if isinstance(item, dict):
                    message = (
                        item.get("message")
                        or item.get("detail")
                        or item.get("title")
                    )

                    if message:
                        messages.append(clean(message))

                elif item:
                    messages.append(clean(item))

            if messages:
                return "; ".join(messages)

    return clean(payload)


def lookup_vehicle(
    registration: str,
    timeout: int = REQUEST_TIMEOUT_SECONDS,
) -> dict:
    """
    Look up a UK vehicle using the DVLA Vehicle Enquiry Service.

    Raises a specific DVLAError subclass when lookup cannot be completed.
    The voice integration should catch these errors and continue without
    vehicle confirmation rather than terminating the call.
    """
    compact_registration = clean_registration(
        registration
    )

    if not compact_registration:
        raise DVLAInvalidRegistrationError(
            "Vehicle registration is missing."
        )

    if len(compact_registration) < 2:
        raise DVLAInvalidRegistrationError(
            "Vehicle registration is too short."
        )

    if not DVLA_API_KEY:
        raise DVLAKeyMissingError(
            "DVLA_API_KEY is missing."
        )

    headers = {
        "x-api-key": DVLA_API_KEY,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    payload = {
        "registrationNumber": compact_registration,
    }

    try:
        response = requests.post(
            DVLA_API_URL,
            headers=headers,
            json=payload,
            timeout=timeout,
        )

    except requests.Timeout as error:
        raise DVLAServiceUnavailableError(
            "The DVLA request timed out."
        ) from error

    except requests.RequestException as error:
        raise DVLAServiceUnavailableError(
            "The DVLA service could not be reached."
        ) from error

    if response.status_code == 200:
        try:
            data = response.json()

        except ValueError as error:
            raise DVLAServiceUnavailableError(
                "DVLA returned an invalid response."
            ) from error

        if not isinstance(data, dict):
            raise DVLAServiceUnavailableError(
                "DVLA returned an unexpected response."
            )

        return normalise_vehicle_response(
            data,
            fallback_registration=compact_registration,
        )

    error_message = _extract_error_message(
        response
    )

    if response.status_code == 400:
        raise DVLAInvalidRegistrationError(
            error_message
            or "The registration was not accepted by DVLA."
        )

    if response.status_code == 401:
        raise DVLAError(
            error_message
            or "The DVLA API key was not accepted."
        )

    if response.status_code == 403:
        raise DVLAError(
            error_message
            or "The DVLA API request was forbidden."
        )

    if response.status_code == 404:
        raise DVLAVehicleNotFoundError(
            error_message
            or "No vehicle was found for that registration."
        )

    if response.status_code == 429:
        raise DVLARateLimitError(
            error_message
            or "The DVLA request limit has been reached."
        )

    if response.status_code >= 500:
        raise DVLAServiceUnavailableError(
            error_message
            or "The DVLA service is temporarily unavailable."
        )

    raise DVLAError(
        error_message
        or (
            "DVLA lookup failed with status "
            f"{response.status_code}."
        )
    )


def safely_lookup_vehicle(
    registration: str,
) -> dict:
    """
    Safe wrapper for the voice receptionist.

    It always returns a dictionary and never allows a DVLA failure to
    crash or terminate the phone conversation.
    """
    compact_registration = clean_registration(
        registration
    )

    if not compact_registration:
        return {
            "success": False,
            "vehicle": None,
            "reason": "invalid_registration",
            "message": (
                "The registration was empty or invalid."
            ),
        }

    if not has_api_key():
        return {
            "success": False,
            "vehicle": None,
            "reason": "key_missing",
            "message": (
                "The DVLA API key is not configured."
            ),
        }

    try:
        vehicle = lookup_vehicle(
            compact_registration
        )

        return {
            "success": True,
            "vehicle": vehicle,
            "reason": "",
            "message": "",
        }

    except DVLAVehicleNotFoundError as error:
        return {
            "success": False,
            "vehicle": None,
            "reason": "not_found",
            "message": clean(error),
        }

    except DVLAInvalidRegistrationError as error:
        return {
            "success": False,
            "vehicle": None,
            "reason": "invalid_registration",
            "message": clean(error),
        }

    except DVLAKeyMissingError as error:
        return {
            "success": False,
            "vehicle": None,
            "reason": "key_missing",
            "message": clean(error),
        }

    except DVLARateLimitError as error:
        return {
            "success": False,
            "vehicle": None,
            "reason": "rate_limited",
            "message": clean(error),
        }

    except DVLAServiceUnavailableError as error:
        return {
            "success": False,
            "vehicle": None,
            "reason": "service_unavailable",
            "message": clean(error),
        }

    except DVLAError as error:
        return {
            "success": False,
            "vehicle": None,
            "reason": "api_error",
            "message": clean(error),
        }

    except Exception as error:
        print(
            "UNEXPECTED DVLA LOOKUP ERROR:",
            repr(error),
        )

        return {
            "success": False,
            "vehicle": None,
            "reason": "unexpected_error",
            "message": (
                "An unexpected vehicle lookup error occurred."
            ),
        }


def vehicle_description(vehicle: dict | None) -> str:
    """
    Return a natural description suitable for speech.

    Examples:
        "2018 Ford"
        "Ford"
        "the vehicle"
    """
    vehicle = vehicle or {}

    make_model = clean(
        vehicle.get("make_model")
    )

    year = vehicle.get(
        "year_of_manufacture"
    )

    colour = clean(vehicle.get("colour"))

    parts = []

    if year:
        parts.append(str(year))

    if colour:
        parts.append(colour.lower())

    if make_model:
        parts.append(make_model)

    if parts:
        return " ".join(parts)

    registration = clean(
        vehicle.get("registration")
        or vehicle.get("reg")
    )

    if registration:
        return (
            f"vehicle registration {registration}"
        )

    return "the vehicle"


def build_vehicle_confirmation_question(
    vehicle: dict,
) -> str:
    description = vehicle_description(vehicle)

    registration = clean(
        vehicle.get("registration")
        or vehicle.get("reg")
    )

    if registration:
        return (
            f"I found a {description}, registration "
            f"{registration}. Is that the correct vehicle?"
        )

    return (
        f"I found a {description}. "
        "Is that the correct vehicle?"
    )


def dvla_snapshot(result: dict) -> dict:
    """
    Small diagnostic view suitable for Render logs.
    """
    result = result or {}
    vehicle = result.get("vehicle") or {}

    return {
        "success": bool(result.get("success")),
        "reason": clean(result.get("reason")),
        "registration": clean(
            vehicle.get("registration")
            or vehicle.get("reg")
        ),
        "make_model": clean(
            vehicle.get("make_model")
        ),
        "mot_status": clean(
            vehicle.get("mot_status")
        ),
        "mot_expiry_date": clean(
            vehicle.get("mot_expiry_date")
        ),
    }