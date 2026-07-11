from __future__ import annotations

from typing import Any

from integrations.garage_leads import (
    find_customer_by_phone,
    get_customer_history,
)


def clean(value: Any) -> str:
    return str(value or "").strip()


def first_name(full_name: str) -> str:
    name = clean(full_name)

    if not name:
        return ""

    return name.split()[0].capitalize()


def normalise_phone(phone: str) -> str:
    return (
        clean(phone)
        .replace("whatsapp:", "")
        .replace(" ", "")
        .replace("-", "")
        .replace("(", "")
        .replace(")", "")
    )


def load_customer_memory(phone: str) -> dict:
    """
    Look up a caller using their Twilio phone number.

    This function never raises an error into the voice call.
    If Google Sheets is unavailable, it safely returns an empty result.
    """
    phone = normalise_phone(phone)

    if not phone:
        return {
            "found": False,
            "phone": "",
            "name": "",
            "first_name": "",
            "vehicle_reg": "",
            "service_needed": "",
            "issue": "",
            "preferred_time": "",
            "notes": "",
            "status": "",
            "previous_visits": 0,
            "history": [],
        }

    try:
        customer = find_customer_by_phone(phone)
        history = get_customer_history(phone, limit=5)

    except Exception as error:
        print(
            "CUSTOMER MEMORY LOOKUP ERROR:",
            repr(error),
        )

        return {
            "found": False,
            "phone": phone,
            "name": "",
            "first_name": "",
            "vehicle_reg": "",
            "service_needed": "",
            "issue": "",
            "preferred_time": "",
            "notes": "",
            "status": "",
            "previous_visits": 0,
            "history": [],
        }

    if not customer:
        return {
            "found": False,
            "phone": phone,
            "name": "",
            "first_name": "",
            "vehicle_reg": "",
            "service_needed": "",
            "issue": "",
            "preferred_time": "",
            "notes": "",
            "status": "",
            "previous_visits": 0,
            "history": history or [],
        }

    name = clean(customer.get("name"))
    vehicle_reg = clean(
        customer.get("vehicle_reg")
    ).upper()

    return {
        "found": True,
        "phone": phone,
        "name": name,
        "first_name": first_name(name),
        "vehicle_reg": vehicle_reg,
        "service_needed": clean(
            customer.get("service_needed")
        ),
        "issue": clean(customer.get("issue")),
        "preferred_time": clean(
            customer.get("preferred_time")
        ),
        "notes": clean(customer.get("notes")),
        "status": clean(customer.get("status")),
        "previous_visits": int(
            customer.get("previous_visits") or 0
        ),
        "history": history or [],
    }


def build_returning_customer_greeting(
    customer_memory: dict,
    business_name: str,
) -> str:
    """
    Create a warm greeting for a returning caller.

    We keep the wording simple because the full conversation engine
    will decide whether to ask about the previous vehicle next.
    """
    first = clean(
        customer_memory.get("first_name")
    )

    visits = int(
        customer_memory.get("previous_visits") or 0
    )

    if not first:
        return (
            f"Thanks for calling {business_name}. "
            "How can I help today?"
        )

    if visits > 1:
        return (
            f"Welcome back, {first}. "
            f"Thanks for calling {business_name} again. "
            "How can I help today?"
        )

    return (
        f"Welcome back, {first}. "
        f"Thanks for calling {business_name}. "
        "How can I help today?"
    )


def build_new_customer_greeting(
    business_name: str,
) -> str:
    return (
        f"Thanks for calling {business_name}. "
        "The team are busy helping customers at the moment, "
        "but I can take your details and help arrange an appointment. "
        "How can I help today?"
    )


def build_same_vehicle_question(
    customer_memory: dict,
) -> str:
    registration = clean(
        customer_memory.get("vehicle_reg")
    ).upper()

    first = clean(
        customer_memory.get("first_name")
    )

    if registration and first:
        return (
            f"{first}, is this call about the same vehicle, "
            f"registration {registration}?"
        )

    if registration:
        return (
            "Is this call about the same vehicle as last time, "
            f"registration {registration}?"
        )

    return ""


def get_last_registration(
    customer_memory: dict,
) -> str:
    return clean(
        customer_memory.get("vehicle_reg")
    ).upper()


def get_last_service(
    customer_memory: dict,
) -> str:
    return clean(
        customer_memory.get("service_needed")
    )


def get_previous_issue(
    customer_memory: dict,
) -> str:
    return clean(
        customer_memory.get("issue")
    )


def get_distinct_registrations(
    customer_memory: dict,
) -> list[str]:
    """
    Return unique registrations found in recent history,
    newest first.
    """
    history = list(
        customer_memory.get("history") or []
    )

    registrations = []

    for item in reversed(history):
        registration = clean(
            item.get("vehicle_reg")
        ).upper()

        if not registration:
            continue

        if registration not in registrations:
            registrations.append(registration)

    latest = get_last_registration(customer_memory)

    if latest and latest not in registrations:
        registrations.insert(0, latest)

    return registrations


def customer_has_multiple_vehicles(
    customer_memory: dict,
) -> bool:
    return len(
        get_distinct_registrations(customer_memory)
    ) > 1


def build_multiple_vehicle_question(
    customer_memory: dict,
) -> str:
    registrations = get_distinct_registrations(
        customer_memory
    )

    if len(registrations) < 2:
        return build_same_vehicle_question(
            customer_memory
        )

    spoken = registrations[:3]

    if len(spoken) == 2:
        options = (
            f"{spoken[0]} or {spoken[1]}"
        )
    else:
        options = (
            f"{spoken[0]}, {spoken[1]}, "
            f"or {spoken[2]}"
        )

    first = clean(
        customer_memory.get("first_name")
    )

    if first:
        return (
            f"{first}, which vehicle is this about today: "
            f"{options}?"
        )

    return (
        "Which vehicle is this about today: "
        f"{options}?"
    )


def memory_snapshot(
    customer_memory: dict,
) -> dict:
    """
    Small safe diagnostic view for Render logs.
    """
    return {
        "found": bool(
            customer_memory.get("found")
        ),
        "name": clean(
            customer_memory.get("name")
        ),
        "first_name": clean(
            customer_memory.get("first_name")
        ),
        "vehicle_reg": clean(
            customer_memory.get("vehicle_reg")
        ),
        "previous_visits": int(
            customer_memory.get(
                "previous_visits"
            )
            or 0
        ),
        "history_count": len(
            customer_memory.get("history")
            or []
        ),
    }