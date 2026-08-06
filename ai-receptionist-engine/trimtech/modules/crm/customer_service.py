from __future__ import annotations

"""
TrimTech CRM customer grouping service.

File:
    trimtech/modules/crm/customer_service.py

Purpose:
    Build one customer profile from all related bookings and attach every
    vehicle, booking, service and revenue record to that customer.

Primary matching rule:
    1. Normalised phone number
    2. Email address
    3. Name + registration fallback

This prevents repeat customers from being shown as separate CRM records when
their name is entered slightly differently.
"""

import re
from collections import Counter
from collections.abc import Callable, Iterable
from datetime import datetime
from typing import Any

from trimtech.modules.crm.vehicle_service import (
    booking_datetime_value,
    booking_history_item,
    booking_is_cancelled,
    booking_is_completed,
    booking_is_upcoming,
    customer_email_from_booking,
    customer_name_from_booking,
    customer_phone_from_booking,
    format_registration,
    normalise_registration,
    normalise_text,
    parse_datetime,
    registration_from_booking,
    safe_price,
    service_from_booking,
    status_from_booking,
)


def normalise_phone(value: Any) -> str:
    phone = normalise_text(value)

    if phone.lower().startswith("whatsapp:"):
        phone = phone.split(":", 1)[1]

    digits = re.sub(r"\D", "", phone)

    if not digits:
        return ""

    if digits.startswith("0044"):
        digits = digits[4:]

    if digits.startswith("44"):
        digits = digits[2:]

    if digits.startswith("0"):
        return digits

    if len(digits) == 10:
        return f"0{digits}"

    return digits


def display_phone(value: Any) -> str:
    phone = normalise_phone(value)

    return phone or "Phone not recorded"


def normalise_email(value: Any) -> str:
    return normalise_text(value).lower()


def normalise_name(value: Any) -> str:
    name = normalise_text(value)

    return re.sub(
        r"\s+",
        " ",
        name,
    ).strip()


def customer_identity_key(
    booking: dict[str, Any],
) -> str:
    phone = normalise_phone(
        customer_phone_from_booking(booking)
    )

    if phone:
        return f"phone:{phone}"

    email = normalise_email(
        customer_email_from_booking(booking)
    )

    if email:
        return f"email:{email}"

    name = normalise_name(
        customer_name_from_booking(booking)
    ).lower()

    registration = registration_from_booking(
        booking
    )

    return (
        f"name:{name}|reg:{registration}"
        if name or registration
        else "customer:unknown"
    )


def latest_non_empty(
    bookings: Iterable[dict[str, Any]],
    extractor: Callable[[dict[str, Any]], Any],
) -> Any:
    booking_list = list(bookings)

    for booking in reversed(booking_list):
        value = extractor(booking)

        if value not in (None, "", "—"):
            return value

    return None


def booking_sort_key(
    booking: dict[str, Any],
) -> tuple[int, str]:
    value = booking_datetime_value(booking)
    parsed = parse_datetime(value)

    if parsed is not None:
        return (0, parsed.isoformat())

    return (1, normalise_text(value))

def booking_is_cancelled(
    booking: dict[str, Any],
) -> bool:
    status = normalise_text(
        booking.get("status")
        or booking.get("booking_status")
        or "confirmed"
    ).lower()

    return "cancel" in status


def booking_is_completed(
    booking: dict[str, Any],
    now: datetime,
) -> bool:
    if booking_is_cancelled(booking):
        return False

    status = normalise_text(
        booking.get("status")
        or booking.get("booking_status")
        or "confirmed"
    ).lower()

    if any(
        word in status
        for word in (
            "completed",
            "complete",
            "done",
            "finished",
            "attended",
        )
    ):
        return True

    booking_time = parse_datetime(
        booking_datetime_value(booking)
    )

    if booking_time is None:
        return False

    try:
        return booking_time < now
    except TypeError:
        return False


def booking_is_upcoming(
    booking: dict[str, Any],
    now: datetime,
) -> bool:
    if booking_is_cancelled(booking):
        return False

    booking_time = parse_datetime(
        booking_datetime_value(booking)
    )

    if booking_time is None:
        return False

    try:
        return booking_time >= now
    except TypeError:
        return False

def customer_vehicle_summaries(
    bookings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}

    for booking in bookings:
        registration_key = registration_from_booking(
            booking
        )

        if not registration_key:
            continue

        grouped.setdefault(
            registration_key,
            [],
        ).append(booking)

    vehicles = []

    for registration_key, vehicle_bookings in grouped.items():
        ordered = sorted(
            vehicle_bookings,
            key=booking_sort_key,
        )

        latest = ordered[-1]

        next_booking = next(
            (
                booking
                for booking in ordered
                if status_from_booking(booking) != "cancelled"
                and parse_datetime(
                    booking_datetime_value(booking)
                )
            ),
            None,
        )

        vehicles.append(
            {
                "registration_key": registration_key,
                "registration": format_registration(
                    registration_key
                ),
                "make": normalise_text(
                    latest.get("make")
                    or latest.get("vehicle_make")
                ),
                "model": normalise_text(
                    latest.get("model")
                    or latest.get("vehicle_model")
                ),
                "colour": normalise_text(
                    latest.get("colour")
                    or latest.get("color")
                    or latest.get("vehicle_colour")
                ),
                "year": (
                    latest.get("year")
                    or latest.get("manufacture_year")
                    or latest.get("year_of_manufacture")
                ),
                "booking_count": len(
                    ordered
                ),
                "latest_booking": booking_history_item(
                    latest,
                    None,
                ),
                "next_booking": (
                    booking_history_item(
                        next_booking,
                        None,
                    )
                    if next_booking
                    else None
                ),
            }
        )

    vehicles.sort(
        key=lambda item: str(
            item.get("registration")
            or ""
        )
    )

    return vehicles


def build_customer_record(
    identity_key: str,
    bookings: list[dict[str, Any]],
    *,
    now: datetime,
    service_price_resolver: Callable[[Any], float] | None = None,
) -> dict[str, Any]:
    ordered_bookings = sorted(
        bookings,
        key=booking_sort_key,
    )

    name = (
        latest_non_empty(
            ordered_bookings,
            customer_name_from_booking,
        )
        or "Customer"
    )

    phone = latest_non_empty(
        ordered_bookings,
        customer_phone_from_booking,
    )

    email = latest_non_empty(
        ordered_bookings,
        customer_email_from_booking,
    )

    completed = [
        booking
        for booking in ordered_bookings
        if booking_is_completed(
            booking,
            now,
        )
    ]

    upcoming = [
        booking
        for booking in ordered_bookings
        if booking_is_upcoming(
            booking,
            now,
        )
    ]

    cancelled = [
        booking
        for booking in ordered_bookings
        if booking_is_cancelled(
            booking
        )
    ]

    total_spend = round(
        sum(
            safe_price(
                booking,
                service_price_resolver,
            )
            for booking in completed
        ),
        2,
    )

    upcoming_value = round(
        sum(
            safe_price(
                booking,
                service_price_resolver,
            )
            for booking in upcoming
        ),
        2,
    )

    service_counter: Counter[str] = Counter(
        service_from_booking(booking)
        for booking in ordered_bookings
        if not booking_is_cancelled(booking)
    )

    favourite_service = (
        service_counter.most_common(1)[0][0]
        if service_counter
        else ""
    )

    first_booking = (
        ordered_bookings[0]
        if ordered_bookings
        else None
    )

    latest_booking = (
        ordered_bookings[-1]
        if ordered_bookings
        else None
    )

    last_completed = (
        completed[-1]
        if completed
        else None
    )

    next_booking = (
        upcoming[0]
        if upcoming
        else None
    )

    vehicles = customer_vehicle_summaries(
        ordered_bookings
    )

    history = [
        booking_history_item(
            booking,
            service_price_resolver,
        )
        for booking in reversed(
            ordered_bookings
        )
    ]

    return {
        "customer_key": identity_key,
        "name": normalise_name(name),
        "phone": normalise_phone(phone),
        "phone_display": display_phone(phone),
        "email": normalise_email(email),
        "vehicle_count": len(vehicles),
        "vehicles": vehicles,
        "booking_count": len(
            ordered_bookings
        ),
        "completed_visit_count": len(
            completed
        ),
        "cancelled_booking_count": len(
            cancelled
        ),
        "upcoming_booking_count": len(
            upcoming
        ),
        "total_spend": total_spend,
        "upcoming_value": upcoming_value,
        "average_completed_visit_value": round(
            (
                total_spend
                / len(completed)
            )
            if completed
            else 0.0,
            2,
        ),
        "favourite_service": favourite_service,
        "first_booking": (
            booking_history_item(
                first_booking,
                service_price_resolver,
            )
            if first_booking
            else None
        ),
        "latest_booking": (
            booking_history_item(
                latest_booking,
                service_price_resolver,
            )
            if latest_booking
            else None
        ),
        "last_completed_visit": (
            booking_history_item(
                last_completed,
                service_price_resolver,
            )
            if last_completed
            else None
        ),
        "next_booking": (
            booking_history_item(
                next_booking,
                service_price_resolver,
            )
            if next_booking
            else None
        ),
        "booking_history": history,
    }


def merge_customer_groups(
    grouped: dict[str, list[dict[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    """
    Merge weaker fallback groups into a strong phone/email group where possible.

    Example:
        An older booking has only a name and registration.
        A newer booking has the same registration and a phone number.
        Both bookings are attached to the phone-based customer profile.
    """
    registration_to_strong_key: dict[str, str] = {}

    for key, bookings in grouped.items():
        if not (
            key.startswith("phone:")
            or key.startswith("email:")
        ):
            continue

        for booking in bookings:
            registration = registration_from_booking(
                booking
            )

            if registration:
                registration_to_strong_key[
                    registration
                ] = key

    merged: dict[str, list[dict[str, Any]]] = {}

    for key, bookings in grouped.items():
        destination_key = key

        if key.startswith("name:"):
            registrations = {
                registration_from_booking(
                    booking
                )
                for booking in bookings
            }

            registrations.discard("")

            strong_matches = {
                registration_to_strong_key[
                    registration
                ]
                for registration in registrations
                if registration
                in registration_to_strong_key
            }

            if len(strong_matches) == 1:
                destination_key = next(
                    iter(strong_matches)
                )

        merged.setdefault(
            destination_key,
            [],
        ).extend(bookings)

    return merged


def build_customer_records(
    bookings: Iterable[dict[str, Any]],
    *,
    now: datetime,
    service_price_resolver: Callable[[Any], float] | None = None,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}

    for booking in bookings:
        if not isinstance(booking, dict):
            continue

        key = customer_identity_key(
            booking
        )

        grouped.setdefault(
            key,
            [],
        ).append(booking)

    grouped = merge_customer_groups(
        grouped
    )

    customers = [
        build_customer_record(
            identity_key,
            customer_bookings,
            now=now,
            service_price_resolver=service_price_resolver,
        )
        for identity_key, customer_bookings
        in grouped.items()
    ]

    customers.sort(
        key=lambda customer: (
            -int(
                customer.get(
                    "upcoming_booking_count"
                )
                or 0
            ),
            -float(
                customer.get(
                    "total_spend"
                )
                or 0
            ),
            str(
                customer.get("name")
                or ""
            ).lower(),
        )
    )

    return customers


def customer_lookup(
    customers: Iterable[dict[str, Any]],
    *,
    phone: Any = None,
    email: Any = None,
    customer_key: Any = None,
) -> dict[str, Any] | None:
    target_key = normalise_text(
        customer_key
    )

    target_phone = normalise_phone(
        phone
    )

    target_email = normalise_email(
        email
    )

    for customer in customers:
        if (
            target_key
            and normalise_text(
                customer.get(
                    "customer_key"
                )
            )
            == target_key
        ):
            return customer

        if (
            target_phone
            and normalise_phone(
                customer.get("phone")
            )
            == target_phone
        ):
            return customer

        if (
            target_email
            and normalise_email(
                customer.get("email")
            )
            == target_email
        ):
            return customer

    return None


def customer_summary(
    customers: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    customer_list = list(customers)

    repeat_customers = sum(
        1
        for customer in customer_list
        if int(
            customer.get(
                "completed_visit_count"
            )
            or 0
        )
        >= 2
    )

    total_spend = round(
        sum(
            float(
                customer.get(
                    "total_spend"
                )
                or 0
            )
            for customer in customer_list
        ),
        2,
    )

    return {
        "total_customers": len(
            customer_list
        ),
        "repeat_customers": repeat_customers,
        "repeat_customer_rate": round(
            (
                repeat_customers
                / len(customer_list)
                * 100
            )
            if customer_list
            else 0.0,
            1,
        ),
        "total_customer_value": total_spend,
        "average_customer_value": round(
            (
                total_spend
                / len(customer_list)
            )
            if customer_list
            else 0.0,
            2,
        ),
        "customers_with_multiple_vehicles": sum(
            1
            for customer in customer_list
            if int(
                customer.get(
                    "vehicle_count"
                )
                or 0
            )
            > 1
        ),
    }