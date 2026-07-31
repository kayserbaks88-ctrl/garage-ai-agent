from __future__ import annotations

import os
import re
from typing import Any

import requests


DEFAULT_DVLA_API_URL = (
    "https://driver-vehicle-licensing.api.gov.uk/"
    "vehicle-enquiry/v1/vehicles"
)


def _dvla_api_url() -> str:
    return (
        os.getenv("DVLA_API_URL", DEFAULT_DVLA_API_URL).strip()
        or DEFAULT_DVLA_API_URL
    )


def _dvla_api_key() -> str:
    return os.getenv("DVLA_API_KEY", "").strip()


def clean_registration(value: Any) -> str:
    """
    Convert a spoken or typed UK registration into the compact format
    expected by the DVLA API.

    Example:
        "AB12 CDE" -> "AB12CDE"
    """
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def format_registration(value: Any) -> str:
    """
    Format common seven-character UK registrations for display.

    Example:
        "AB12CDE" -> "AB12 CDE"
    """
    compact = clean_registration(value)

    if len(compact) == 7:
        return f"{compact[:4]} {compact[4:]}"

    return compact


def is_plausible_registration(value: Any) -> bool:
    """
    Perform a broad validation before contacting DVLA.

    This intentionally supports modern, older and personalised UK
    registrations rather than accepting only the AB12 CDE format.
    """
    compact = clean_registration(value)

    if not re.fullmatch(r"[A-Z0-9]{1,7}", compact):
        return False

    # A UK registration should contain at least one letter.
    if not re.search(r"[A-Z]", compact):
        return False

    return True


def _failure(reason: str) -> dict[str, Any]:
    return {
        "success": False,
        "reason": reason,
        "vehicle": None,
    }


def safely_lookup_vehicle(registration: Any) -> dict[str, Any]:
    """
    Look up a vehicle through the DVLA Vehicle Enquiry API.

    The function always returns a predictable dictionary and does not
    allow network errors or invalid DVLA responses to crash the caller.
    """
    compact = clean_registration(registration)

    if not is_plausible_registration(compact):
        return _failure("invalid_registration")

    api_key = _dvla_api_key()

    if not api_key:
        print("DVLA CONFIG ERROR: DVLA_API_KEY is missing")
        return _failure("key_missing")

    try:
        response = requests.post(
            _dvla_api_url(),
            headers={
                "x-api-key": api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            json={
                "registrationNumber": compact,
            },
            timeout=12,
        )
    except requests.Timeout:
        print("DVLA REQUEST ERROR: request timed out")
        return _failure("service_unavailable")
    except requests.RequestException as error:
        print("DVLA REQUEST ERROR:", repr(error))
        return _failure("service_unavailable")

    if response.status_code != 200:
        print(
            "DVLA RESPONSE ERROR:",
            response.status_code,
            response.text[:300],
        )

        reason = {
            400: "invalid_registration",
            401: "key_rejected",
            403: "forbidden",
            404: "not_found",
            409: "not_found",
            429: "rate_limited",
        }.get(response.status_code, "service_unavailable")

        return _failure(reason)

    try:
        data = response.json()
    except ValueError:
        print("DVLA RESPONSE ERROR: invalid JSON response")
        return _failure("invalid_response")

    if not isinstance(data, dict):
        print("DVLA RESPONSE ERROR: unexpected response type")
        return _failure("invalid_response")

    make = str(data.get("make") or "").strip().title()
    model = str(data.get("model") or "").strip().title()
    colour = str(data.get("colour") or "").strip().title()

    make_model = " ".join(
        part for part in (make, model) if part
    ).strip()

    displayed_registration = format_registration(compact)

    vehicle = {
        "reg": displayed_registration,
        "registration": displayed_registration,
        "registration_compact": compact,
        "make": make,
        "model": model,
        "make_model": make_model or make or "Vehicle",
        "colour": colour,
        "year_of_manufacture": data.get("yearOfManufacture"),
        "fuel_type": str(data.get("fuelType") or "").strip().title(),
        "engine_capacity": data.get("engineCapacity"),
        "co2_emissions": data.get("co2Emissions"),
        "tax_status": str(data.get("taxStatus") or "").strip().title(),
        "tax_due_date": str(data.get("taxDueDate") or "").strip(),
        "mot_status": str(data.get("motStatus") or "").strip().title(),
        "mot_expiry_date": str(data.get("motExpiryDate") or "").strip(),
        "month_of_first_registration": str(
            data.get("monthOfFirstRegistration") or ""
        ).strip(),
        "marked_for_export": bool(data.get("markedForExport", False)),
        "raw": data,
    }

    return {
        "success": True,
        "reason": "",
        "vehicle": vehicle,
    }


def lookup_vehicle(registration: Any) -> dict[str, Any]:
    """
    Public alias used by voice-agent and API integrations.
    """
    return safely_lookup_vehicle(registration)


def vehicle_confirmation_question(vehicle: dict[str, Any]) -> str:
    """
    Build the natural confirmation spoken by the voice receptionist.
    """
    parts: list[str] = []

    year = vehicle.get("year_of_manufacture")
    colour = str(vehicle.get("colour") or "").strip()
    make_model = str(vehicle.get("make_model") or "").strip()

    if year:
        parts.append(str(year))

    if colour:
        parts.append(colour.lower())

    if make_model:
        parts.append(make_model)

    description = " ".join(parts).strip() or "vehicle"

    registration = str(
        vehicle.get("registration")
        or vehicle.get("reg")
        or ""
    ).strip()

    if registration:
        return (
            f"I found a {description}, registration "
            f"{registration}. Is that the correct vehicle?"
        )

    return f"I found a {description}. Is that the correct vehicle?"