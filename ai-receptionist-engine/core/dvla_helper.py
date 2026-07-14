from __future__ import annotations

import os
import re
from typing import Any

import requests


DVLA_API_URL = os.getenv(
    "DVLA_API_URL",
    "https://driver-vehicle-licensing.api.gov.uk/vehicle-enquiry/v1/vehicles",
).strip()
DVLA_API_KEY = os.getenv("DVLA_API_KEY", "").strip()


def clean_registration(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def safely_lookup_vehicle(registration: str) -> dict:
    compact = clean_registration(registration)

    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z]{3}", compact):
        return {"success": False, "reason": "invalid_registration", "vehicle": None}

    if not DVLA_API_KEY:
        return {"success": False, "reason": "key_missing", "vehicle": None}

    try:
        response = requests.post(
            DVLA_API_URL,
            headers={
                "x-api-key": DVLA_API_KEY,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            json={"registrationNumber": compact},
            timeout=12,
        )
    except requests.RequestException as error:
        print("DVLA REQUEST ERROR:", repr(error))
        return {"success": False, "reason": "service_unavailable", "vehicle": None}

    if response.status_code != 200:
        print("DVLA RESPONSE:", response.status_code, response.text[:300])
        reason = {
            400: "invalid_registration",
            401: "key_rejected",
            403: "forbidden",
            404: "not_found",
            429: "rate_limited",
        }.get(response.status_code, "service_unavailable")
        return {"success": False, "reason": reason, "vehicle": None}

    try:
        data = response.json()
    except ValueError:
        return {"success": False, "reason": "invalid_response", "vehicle": None}

    make = str(data.get("make") or "").title()
    model = str(data.get("model") or "").title()
    make_model = " ".join(part for part in (make, model) if part)

    vehicle = {
        "reg": f"{compact[:4]} {compact[4:]}",
        "registration": f"{compact[:4]} {compact[4:]}",
        "make": make,
        "model": model,
        "make_model": make_model or "Vehicle",
        "colour": str(data.get("colour") or "").title(),
        "year_of_manufacture": data.get("yearOfManufacture"),
        "mot_status": str(data.get("motStatus") or "").title(),
        "mot_expiry_date": str(data.get("motExpiryDate") or ""),
        "raw": data,
    }
    return {"success": True, "reason": "", "vehicle": vehicle}


def vehicle_confirmation_question(vehicle: dict) -> str:
    parts = []
    if vehicle.get("year_of_manufacture"):
        parts.append(str(vehicle["year_of_manufacture"]))
    if vehicle.get("colour"):
        parts.append(str(vehicle["colour"]).lower())
    if vehicle.get("make_model"):
        parts.append(str(vehicle["make_model"]))

    description = " ".join(parts) or "vehicle"
    reg = str(vehicle.get("registration") or vehicle.get("reg") or "")
    return f"I found a {description}, registration {reg}. Is that the correct vehicle?"
