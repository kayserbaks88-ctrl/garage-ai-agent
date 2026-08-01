from __future__ import annotations

"""
TrimTech CRM vehicle grouping service.

File:
    trimtech/modules/crm/vehicle_service.py

Purpose:
    Build one canonical vehicle profile for every registration plate and attach
    all matching booking/service history to that profile.

Important:
    Registrations such as:

        MC65 XON
        mc65xon
        MC65-XON
        MC65_XON

    are all grouped under the canonical key:

        MC65XON
"""

import re
from collections.abc import Callable, Iterable
from datetime import datetime
from typing import Any


UNKNOWN_REGISTRATIONS = {
    "",
    "-",
    "—",
    "UNKNOWN",
    "NOT RECORDED",
    "N/A",
    "NA",
    "NONE",
    "NULL",
}


def normalise_text(value: Any) -> str:
    return str(value or "").strip()


def normalise_registration(value: Any) -> str:
    """
    Return a canonical registration key containing uppercase letters and digits.

    This key is used for grouping and comparisons. It is intentionally stored
    without spaces so formatting differences never create duplicate vehicles.
    """
    registration = re.sub(
        r"[^A-Z0-9]",
        "",
        normalise_text(value).upper(),
    )

    if registration in UNKNOWN_REGISTRATIONS:
        return ""

    return registration


def format_registration(value: Any) -> str:
    """
    Return a readable UK-style registration where possible.

    Examples:
        MC65XON -> MC65 XON
        AB12CDE -> AB12 CDE

    Unknown and non-standard registrations remain safely readable.
    """
    registration = normalise_registration(value)

    if not registration:
        return "—"

    if len(registration) == 7:
        return f"{registration[:4]} {registration[4:]}"

    return registration


def registration_from_booking(booking: dict[str, Any]) -> str:
    for field_name in (
        "vehicle_reg",
        "registration",
        "reg",
        "vehicle_registration",
        "number_plate",
        "plate",
    ):
        registration = normalise_registration(
            booking.get(field_name)
        )

        if registration:
            return registration

    return ""


def customer_name_from_booking(booking: dict[str, Any]) -> str:
    for field_name in (
        "customer_name",
        "name",
        "customer",
    ):
        value = normalise_text(booking.get(field_name))

        if value:
            return value

    return "Customer"


def customer_phone_from_booking(booking: dict[str, Any]) -> str:
    for field_name in (
        "phone",
        "customer_phone",
        "telephone",
        "mobile",
    ):
        value = normalise_text(booking.get(field_name))

        if value:
            return value

    return ""


def customer_email_from_booking(booking: dict[str, Any]) -> str:
    for field_name in (
        "email",
        "customer_email",
    ):
        value = normalise_text(booking.get(field_name))

        if value:
            return value

    return ""


def service_from_booking(booking: dict[str, Any]) -> str:
    for field_name in (
        "service",
        "service_name",
        "service_key",
    ):
        value = normalise_text(booking.get(field_name))

        if value:
            return value

    return "Garage appointment"


def status_from_booking(booking: dict[str, Any]) -> str:
    return (
        normalise_text(
            booking.get("status")
            or booking.get("booking_status")
            or "confirmed"
        ).lower()
        or "confirmed"
    )


def booking_datetime_value(booking: dict[str, Any]) -> Any:
    for field_name in (
        "start",
        "datetime",
        "date_time",
        "appointment_datetime",
        "date",
    ):
        value = booking.get(field_name)

        if value:
            return value

    return None


def parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value

    text = normalise_text(value)

    if not text:
        return None

    try:
        return datetime.fromisoformat(
            text.replace("Z", "+00:00")
        )
    except ValueError:
        return None


def first_available(
    bookings: Iterable[dict[str, Any]],
    *field_names: str,
) -> Any:
    for booking in bookings:
        for field_name in field_names:
            value = booking.get(field_name)

            if value not in (None, "", "—"):
                return value

    return None


def latest_available(
    bookings: Iterable[dict[str, Any]],
    *field_names: str,
) -> Any:
    booking_list = list(bookings)

    for booking in reversed(booking_list):
        for field_name in field_names:
            value = booking.get(field_name)

            if value not in (None, "", "—"):
                return value

    return None


def booking_sort_key(booking: dict[str, Any]) -> str:
    parsed = parse_datetime(
        booking_datetime_value(booking)
    )

    return parsed.isoformat() if parsed else ""


def booking_is_cancelled(booking: dict[str, Any]) -> bool:
    return "cancel" in status_from_booking(booking)


def booking_is_completed(
    booking: dict[str, Any],
    now: datetime,
) -> bool:
    status = status_from_booking(booking)

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
        return (
            booking_time < now
            and not booking_is_cancelled(booking)
        )
    except TypeError:
        # Aware/naive mismatch should not break the dashboard.
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


def safe_price(
    booking: dict[str, Any],
    service_price_resolver: Callable[[Any], float] | None,
) -> float:
    for field_name in (
        "price",
        "service_price",
        "amount",
        "revenue",
        "total",
    ):
        raw_value = booking.get(field_name)

        if raw_value in (None, ""):
            continue

        try:
            return max(0.0, float(raw_value))
        except (TypeError, ValueError):
            continue

    if service_price_resolver is None:
        return 0.0

    try:
        return max(
            0.0,
            float(
                service_price_resolver(
                    booking.get("service_key")
                    or booking.get("service")
                    or booking.get("service_name")
                )
            ),
        )
    except (TypeError, ValueError, KeyError):
        return 0.0


def booking_history_item(
    booking: dict[str, Any],
    service_price_resolver: Callable[[Any], float] | None,
) -> dict[str, Any]:
    return {
        "event_id": normalise_text(
            booking.get("event_id")
            or booking.get("id")
        ),
        "service": service_from_booking(booking),
        "service_key": normalise_text(
            booking.get("service_key")
        ),
        "start": booking_datetime_value(booking),
        "end": booking.get("end"),
        "status": status_from_booking(booking),
        "price": round(
            safe_price(
                booking,
                service_price_resolver,
            ),
            2,
        ),
        "customer_name": customer_name_from_booking(
            booking
        ),
        "customer_phone": customer_phone_from_booking(
            booking
        ),
        "customer_email": customer_email_from_booking(
            booking
        ),
        "notes": normalise_text(
            booking.get("notes")
            or booking.get("description")
        ),
        "calendar_link": normalise_text(
            booking.get("calendar_link")
            or booking.get("htmlLink")
        ),
        "created_at": booking.get("created_at"),
        "updated_at": booking.get("updated_at"),
    }


def vehicle_customer_records(
    bookings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    customers: dict[str, dict[str, Any]] = {}

    for booking in bookings:
        name = customer_name_from_booking(booking)
        phone = customer_phone_from_booking(booking)
        email = customer_email_from_booking(booking)

        key = (
            f"phone:{phone}"
            if phone
            else f"name:{name.lower()}|email:{email.lower()}"
        )

        current = customers.setdefault(
            key,
            {
                "key": key,
                "name": name,
                "phone": phone,
                "email": email,
                "booking_count": 0,
            },
        )

        current["booking_count"] += 1

        if not current.get("name") and name:
            current["name"] = name

        if not current.get("phone") and phone:
            current["phone"] = phone

        if not current.get("email") and email:
            current["email"] = email

    return sorted(
        customers.values(),
        key=lambda item: (
            -int(item.get("booking_count") or 0),
            str(item.get("name") or "").lower(),
        ),
    )


def build_vehicle_record(
    registration_key: str,
    bookings: list[dict[str, Any]],
    *,
    now: datetime,
    service_price_resolver: Callable[[Any], float] | None = None,
) -> dict[str, Any]:
    ordered_bookings = sorted(
        bookings,
        key=booking_sort_key,
    )

    completed_bookings = [
        booking
        for booking in ordered_bookings
        if booking_is_completed(booking, now)
    ]

    upcoming_bookings = [
        booking
        for booking in ordered_bookings
        if booking_is_upcoming(booking, now)
    ]

    active_bookings = [
        booking
        for booking in ordered_bookings
        if not booking_is_cancelled(booking)
    ]

    total_spend = round(
        sum(
            safe_price(
                booking,
                service_price_resolver,
            )
            for booking in completed_bookings
        ),
        2,
    )

    estimated_pipeline_value = round(
        sum(
            safe_price(
                booking,
                service_price_resolver,
            )
            for booking in upcoming_bookings
        ),
        2,
    )

    history = [
        booking_history_item(
            booking,
            service_price_resolver,
        )
        for booking in reversed(ordered_bookings)
    ]

    service_counter: dict[str, int] = {}

    for item in history:
        service_name = normalise_text(
            item.get("service")
        ) or "Garage appointment"

        service_counter[service_name] = (
            service_counter.get(service_name, 0)
            + 1
        )

    most_used_service = ""

    if service_counter:
        most_used_service = max(
            service_counter,
            key=lambda key: (
                service_counter[key],
                key,
            ),
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
        completed_bookings[-1]
        if completed_bookings
        else None
    )

    next_booking = (
        upcoming_bookings[0]
        if upcoming_bookings
        else None
    )

    return {
        "registration_key": registration_key,
        "registration": format_registration(
            registration_key
        ),
        "make": normalise_text(
            latest_available(
                ordered_bookings,
                "make",
                "vehicle_make",
            )
        ),
        "model": normalise_text(
            latest_available(
                ordered_bookings,
                "model",
                "vehicle_model",
            )
        ),
        "colour": normalise_text(
            latest_available(
                ordered_bookings,
                "colour",
                "color",
                "vehicle_colour",
            )
        ),
        "year": latest_available(
            ordered_bookings,
            "year",
            "manufacture_year",
            "year_of_manufacture",
        ),
        "fuel_type": normalise_text(
            latest_available(
                ordered_bookings,
                "fuel_type",
                "fuel",
            )
        ),
        "mot_status": normalise_text(
            latest_available(
                ordered_bookings,
                "mot_status",
                "motStatus",
            )
        ),
        "mot_expiry_date": latest_available(
            ordered_bookings,
            "mot_expiry_date",
            "mot_expiry",
            "motExpiryDate",
        ),
        "tax_status": normalise_text(
            latest_available(
                ordered_bookings,
                "tax_status",
                "taxStatus",
            )
        ),
        "customers": vehicle_customer_records(
            ordered_bookings
        ),
        "customer_count": len(
            vehicle_customer_records(
                ordered_bookings
            )
        ),
        "booking_count": len(
            ordered_bookings
        ),
        "active_booking_count": len(
            active_bookings
        ),
        "completed_visit_count": len(
            completed_bookings
        ),
        "cancelled_booking_count": sum(
            1
            for booking in ordered_bookings
            if booking_is_cancelled(booking)
        ),
        "upcoming_booking_count": len(
            upcoming_bookings
        ),
        "total_spend": total_spend,
        "estimated_pipeline_value": estimated_pipeline_value,
        "average_completed_visit_value": round(
            (
                total_spend
                / len(completed_bookings)
            )
            if completed_bookings
            else 0.0,
            2,
        ),
        "most_used_service": most_used_service,
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
        "service_history": history,
    }


def build_vehicle_records(
    bookings: Iterable[dict[str, Any]],
    *,
    now: datetime,
    service_price_resolver: Callable[[Any], float] | None = None,
) -> list[dict[str, Any]]:
    """
    Group every booking by canonical registration and return vehicle profiles.

    Bookings without a usable registration are deliberately excluded from the
    vehicle directory, but they can still remain in customer and booking views.
    """
    grouped: dict[str, list[dict[str, Any]]] = {}

    for booking in bookings:
        if not isinstance(booking, dict):
            continue

        registration_key = registration_from_booking(
            booking
        )

        if not registration_key:
            continue

        enriched_booking = {
            **booking,
            "registration_key": registration_key,
            "vehicle_reg": format_registration(
                registration_key
            ),
        }

        grouped.setdefault(
            registration_key,
            [],
        ).append(enriched_booking)

    vehicles = [
        build_vehicle_record(
            registration_key,
            vehicle_bookings,
            now=now,
            service_price_resolver=service_price_resolver,
        )
        for registration_key, vehicle_bookings
        in grouped.items()
    ]

    vehicles.sort(
    key=lambda vehicle: (
        (
            parse_datetime(
                (
                    vehicle.get("next_booking")
                    or {}
                ).get("start")
            ).isoformat()
            if parse_datetime(
                (
                    vehicle.get("next_booking")
                    or {}
                ).get("start")
            )
            else "9999-12-31T23:59:59+00:00"
        ),
        str(
            vehicle.get("registration")
            or ""
        ),
    )
)

    return vehicles


def vehicle_lookup(
    vehicles: Iterable[dict[str, Any]],
    registration: Any,
) -> dict[str, Any] | None:
    target = normalise_registration(
        registration
    )

    if not target:
        return None

    return next(
        (
            vehicle
            for vehicle in vehicles
            if normalise_registration(
                vehicle.get("registration_key")
                or vehicle.get("registration")
            )
            == target
        ),
        None,
    )