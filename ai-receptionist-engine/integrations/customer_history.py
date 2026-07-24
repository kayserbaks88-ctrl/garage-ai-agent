from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from typing import Any

from integrations.garage_calendar import (
    _calendar_id,
    _get_calendar_service,
    normalise_phone,
)
from integrations.garage_config import SERVICES, TIMEZONE
from integrations.service_history import (
    get_customer_service_summary,
    list_service_history,
)


CUSTOMER_LOOKBACK_YEARS = 10
DEFAULT_CUSTOMER_LIMIT = 100

VIP_VISIT_THRESHOLD = 5
VIP_SPEND_THRESHOLD = 750.00
INACTIVE_CUSTOMER_DAYS = 365


def _parse_datetime(value: str) -> datetime | None:
    """
    Convert a Google Calendar datetime value into Europe/London time.
    """
    raw_value = str(value or "").strip()

    if not raw_value:
        return None

    try:
        parsed = datetime.fromisoformat(
            raw_value.replace("Z", "+00:00")
        )
    except ValueError:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=TIMEZONE)

    return parsed.astimezone(TIMEZONE)


def _clean_registration(registration: str) -> str:
    """
    Convert a registration into a reliable comparison key.

    Example:
    ab12 cde -> AB12CDE
    """
    return "".join(
        character
        for character in str(registration or "").upper()
        if character.isalnum()
    )


def _display_registration(registration: str) -> str:
    """
    Convert a registration key into a readable UK format.

    Example:
    AB12CDE -> AB12 CDE
    """
    cleaned = _clean_registration(registration)

    if len(cleaned) > 3:
        return f"{cleaned[:-3]} {cleaned[-3:]}"

    return cleaned


def _private_data(event: dict) -> dict:
    return (
        (event.get("extendedProperties") or {})
        .get("private")
        or {}
    )


def _event_start(event: dict) -> datetime | None:
    return _parse_datetime(
        (event.get("start") or {}).get("dateTime", "")
    )


def _event_end(event: dict) -> datetime | None:
    return _parse_datetime(
        (event.get("end") or {}).get("dateTime", "")
    )


def _service_label(service_key: str) -> str:
    key = str(service_key or "").strip().lower()
    service = SERVICES.get(key) or {}

    return str(
        service.get("label")
        or key.replace("_", " ").title()
        or "Garage Appointment"
    )


def _event_phone(event: dict) -> str:
    private = _private_data(event)

    return normalise_phone(
        private.get("phone") or ""
    )


def _event_customer_name(event: dict) -> str:
    private = _private_data(event)

    return str(
        private.get("customer_name")
        or private.get("name")
        or ""
    ).strip()


def _event_registration(event: dict) -> str:
    private = _private_data(event)

    return _display_registration(
        private.get("registration")
        or private.get("reg")
        or private.get("vehicle_reg")
        or ""
    )


def _event_service_key(event: dict) -> str:
    private = _private_data(event)

    return str(
        private.get("service") or ""
    ).strip().lower()


def _event_status(event: dict) -> str:
    """
    Return a simplified appointment status.

    Possible values:
    - completed
    - upcoming
    - cancelled
    - no_show
    - past
    """
    if event.get("status") == "cancelled":
        return "cancelled"

    private = _private_data(event)

    no_show_value = str(
        private.get("no_show") or ""
    ).strip().lower()

    if no_show_value in {
        "true",
        "yes",
        "1",
        "no_show",
    }:
        return "no_show"

    completed_value = str(
        private.get("service_completed") or ""
    ).strip().lower()

    if completed_value in {
        "true",
        "yes",
        "1",
        "completed",
    }:
        return "completed"

    now = datetime.now(TIMEZONE)
    end_time = _event_end(event)
    start_time = _event_start(event)

    if start_time and start_time > now:
        return "upcoming"

    if end_time and end_time <= now:
        return "past"

    return "upcoming"


def _safe_float(value: Any) -> float | None:
    raw_value = str(value or "").strip()

    if not raw_value:
        return None

    cleaned = (
        raw_value.replace("£", "")
        .replace(",", "")
        .strip()
    )

    try:
        return float(cleaned)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    raw_value = str(value or "").strip()

    if not raw_value:
        return None

    cleaned = raw_value.replace(",", "").strip()

    try:
        return int(cleaned)
    except (TypeError, ValueError):
        return None


def _fetch_customer_events(
    time_min: datetime,
    time_max: datetime,
) -> list[dict]:
    """
    Retrieve calendar events with pagination.
    """
    service = _get_calendar_service()

    events: list[dict] = []
    page_token: str | None = None

    while True:
        result = (
            service.events()
            .list(
                calendarId=_calendar_id(),
                timeMin=time_min.isoformat(),
                timeMax=time_max.isoformat(),
                singleEvents=True,
                orderBy="startTime",
                maxResults=2500,
                pageToken=page_token,
            )
            .execute()
        )

        events.extend(
            result.get("items", [])
        )

        page_token = result.get(
            "nextPageToken"
        )

        if not page_token:
            break

    return events


def _vehicle_from_event(event: dict) -> dict[str, Any] | None:
    private = _private_data(event)

    registration = _event_registration(event)

    if not registration:
        return None

    mileage = _safe_int(
        private.get("mileage")
    )

    return {
        "registration": registration,
        "registration_key": _clean_registration(
            registration
        ),
        "make": str(
            private.get("vehicle_make")
            or private.get("make")
            or ""
        ).strip(),
        "model": str(
            private.get("vehicle_model")
            or private.get("model")
            or ""
        ).strip(),
        "colour": str(
            private.get("vehicle_colour")
            or private.get("colour")
            or ""
        ).strip(),
        "fuel_type": str(
            private.get("fuel_type") or ""
        ).strip(),
        "year": str(
            private.get("vehicle_year") or ""
        ).strip(),
        "mileage": mileage,
        "mot_expiry": str(
            private.get("mot_expiry") or ""
        ).strip(),
        "service_due_date": str(
            private.get("service_due_date") or ""
        ).strip(),
    }


def _merge_vehicle_records(
    vehicles: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Merge repeated vehicle records from multiple appointments.
    """
    merged: dict[str, dict[str, Any]] = {}

    for vehicle in vehicles:
        registration_key = vehicle.get(
            "registration_key",
            "",
        )

        if not registration_key:
            continue

        existing = merged.get(
            registration_key
        )

        if not existing:
            merged[registration_key] = {
                **vehicle,
                "visit_count": 1,
            }
            continue

        existing["visit_count"] += 1

        for field in (
            "make",
            "model",
            "colour",
            "fuel_type",
            "year",
            "mot_expiry",
            "service_due_date",
        ):
            if (
                not existing.get(field)
                and vehicle.get(field)
            ):
                existing[field] = vehicle[field]

        new_mileage = vehicle.get("mileage")
        old_mileage = existing.get("mileage")

        if (
            new_mileage is not None
            and (
                old_mileage is None
                or new_mileage > old_mileage
            )
        ):
            existing["mileage"] = new_mileage

    return list(merged.values())


def get_customer_events(
    phone: str,
    include_cancelled: bool = True,
    include_future: bool = True,
    limit: int = DEFAULT_CUSTOMER_LIMIT,
) -> list[dict[str, Any]]:
    """
    Return all known appointments for one customer.
    """
    normalised_phone = normalise_phone(phone)

    if not normalised_phone:
        return []

    now = datetime.now(TIMEZONE)

    time_min = now - timedelta(
        days=365 * CUSTOMER_LOOKBACK_YEARS
    )

    time_max = (
        now + timedelta(days=365 * 2)
        if include_future
        else now + timedelta(minutes=1)
    )

    events = _fetch_customer_events(
        time_min=time_min,
        time_max=time_max,
    )

    customer_events: list[dict[str, Any]] = []

    for event in events:
        if _event_phone(event) != normalised_phone:
            continue

        status = _event_status(event)

        if (
            not include_cancelled
            and status == "cancelled"
        ):
            continue

        start_time = _event_start(event)
        end_time = _event_end(event)

        if not start_time:
            continue

        private = _private_data(event)

        service_key = _event_service_key(event)

        customer_events.append(
            {
                "event_id": event.get("id", ""),
                "calendar_link": event.get(
                    "htmlLink",
                    "",
                ),
                "customer_name": _event_customer_name(
                    event
                ),
                "phone": normalised_phone,
                "registration": _event_registration(
                    event
                ),
                "service_key": service_key,
                "service_label": _service_label(
                    service_key
                ),
                "status": status,
                "start": start_time,
                "end": end_time,
                "date": start_time.strftime(
                    "%Y-%m-%d"
                ),
                "date_text": start_time.strftime(
                    "%A %-d %B %Y"
                ),
                "time_text": start_time.strftime(
                    "%-I:%M %p"
                ).lower(),
                "amount_paid": _safe_float(
                    private.get("amount_paid")
                    or private.get("price")
                ),
                "mileage": _safe_int(
                    private.get("mileage")
                ),
                "vehicle": _vehicle_from_event(
                    event
                ),
                "notes": str(
                    private.get("work_notes")
                    or private.get("notes")
                    or ""
                ).strip(),
                "recommendations": str(
                    private.get("recommendations")
                    or ""
                ).strip(),
            }
        )

    customer_events.sort(
        key=lambda item: item["start"],
        reverse=True,
    )

    safe_limit = max(
        1,
        min(
            int(limit or DEFAULT_CUSTOMER_LIMIT),
            500,
        ),
    )

    return customer_events[:safe_limit]


def get_customer_profile(
    phone: str,
) -> dict[str, Any]:
    """
    Build the complete customer profile used by the garage AI.
    """
    normalised_phone = normalise_phone(phone)

    if not normalised_phone:
        return {
            "found": False,
            "phone": "",
            "customer_name": "",
            "returning_customer": False,
            "vip_customer": False,
            "total_visits": 0,
            "completed_visits": 0,
            "cancelled_visits": 0,
            "no_show_visits": 0,
            "upcoming_bookings": 0,
            "vehicles": [],
            "vehicle_count": 0,
            "total_spent": 0.0,
            "average_spend": 0.0,
            "first_visit": "",
            "last_visit": "",
            "last_service": "",
            "most_popular_service": "",
            "inactive_customer": False,
            "events": [],
        }

    events = get_customer_events(
        phone=normalised_phone,
        include_cancelled=True,
        include_future=True,
        limit=500,
    )

    service_summary = get_customer_service_summary(
        normalised_phone
    )

    if not events and not service_summary.get("found"):
        return {
            "found": False,
            "phone": normalised_phone,
            "customer_name": "",
            "returning_customer": False,
            "vip_customer": False,
            "total_visits": 0,
            "completed_visits": 0,
            "cancelled_visits": 0,
            "no_show_visits": 0,
            "upcoming_bookings": 0,
            "vehicles": [],
            "vehicle_count": 0,
            "total_spent": 0.0,
            "average_spend": 0.0,
            "first_visit": "",
            "last_visit": "",
            "last_service": "",
            "most_popular_service": "",
            "inactive_customer": False,
            "events": [],
        }

    completed_events = [
        event
        for event in events
        if event["status"] in {
            "completed",
            "past",
        }
    ]

    cancelled_events = [
        event
        for event in events
        if event["status"] == "cancelled"
    ]

    no_show_events = [
        event
        for event in events
        if event["status"] == "no_show"
    ]

    upcoming_events = [
        event
        for event in events
        if event["status"] == "upcoming"
    ]

    historical_events = sorted(
        completed_events,
        key=lambda item: item["start"],
    )

    customer_name = ""

    for event in events:
        if event.get("customer_name"):
            customer_name = event[
                "customer_name"
            ]
            break

    if not customer_name:
        customer_name = str(
            service_summary.get(
                "customer_name",
                "",
            )
        ).strip()

    vehicle_records = [
        event["vehicle"]
        for event in events
        if event.get("vehicle")
    ]

    vehicles = _merge_vehicle_records(
        vehicle_records
    )

    service_labels = [
        event["service_label"]
        for event in completed_events
        if event.get("service_label")
    ]

    service_counter = Counter(
        service_labels
    )

    most_popular_service = ""

    if service_counter:
        most_popular_service = (
            service_counter.most_common(1)[0][0]
        )

    recorded_amounts = [
        event["amount_paid"]
        for event in completed_events
        if event.get("amount_paid") is not None
    ]

    total_spent = round(
        sum(recorded_amounts),
        2,
    )

    average_spend = round(
        total_spent / len(recorded_amounts),
        2,
    ) if recorded_amounts else 0.0

    first_visit_event = (
        historical_events[0]
        if historical_events
        else None
    )

    last_visit_event = (
        historical_events[-1]
        if historical_events
        else None
    )

    completed_visit_count = max(
        len(completed_events),
        int(
            service_summary.get(
                "total_visits",
                0,
            )
            or 0
        ),
    )

    returning_customer = (
        completed_visit_count > 0
    )

    vip_customer = (
        completed_visit_count
        >= VIP_VISIT_THRESHOLD
        or total_spent
        >= VIP_SPEND_THRESHOLD
    )

    inactive_customer = False

    if last_visit_event:
        days_since_last_visit = (
            datetime.now(TIMEZONE)
            - last_visit_event["start"]
        ).days

        inactive_customer = (
            days_since_last_visit
            >= INACTIVE_CUSTOMER_DAYS
        )
    else:
        days_since_last_visit = None

    latest_service = (
        last_visit_event.get(
            "service_label",
            "",
        )
        if last_visit_event
        else str(
            service_summary.get(
                "last_service",
                "",
            )
        )
    )

    review_requested_count = sum(
        1
        for record in service_summary.get(
            "history",
            []
        )
        if record.get("review_requested")
    )

    return {
        "found": True,
        "phone": normalised_phone,
        "customer_name": customer_name,
        "returning_customer": returning_customer,
        "vip_customer": vip_customer,
        "total_visits": len(events),
        "completed_visits": completed_visit_count,
        "cancelled_visits": len(
            cancelled_events
        ),
        "no_show_visits": len(
            no_show_events
        ),
        "upcoming_bookings": len(
            upcoming_events
        ),
        "vehicles": vehicles,
        "vehicle_count": len(vehicles),
        "current_vehicle": (
            vehicles[0]
            if vehicles
            else None
        ),
        "total_spent": total_spent,
        "average_spend": average_spend,
        "first_visit": (
            first_visit_event["date"]
            if first_visit_event
            else ""
        ),
        "first_visit_text": (
            first_visit_event["date_text"]
            if first_visit_event
            else ""
        ),
        "last_visit": (
            last_visit_event["date"]
            if last_visit_event
            else ""
        ),
        "last_visit_text": (
            last_visit_event["date_text"]
            if last_visit_event
            else ""
        ),
        "last_service": latest_service,
        "last_registration": (
            last_visit_event.get(
                "registration",
                "",
            )
            if last_visit_event
            else str(
                service_summary.get(
                    "last_registration",
                    "",
                )
            )
        ),
        "most_popular_service": (
            most_popular_service
        ),
        "inactive_customer": (
            inactive_customer
        ),
        "days_since_last_visit": (
            days_since_last_visit
        ),
        "review_requested_count": (
            review_requested_count
        ),
        "upcoming": upcoming_events,
        "completed": completed_events,
        "cancelled": cancelled_events,
        "no_shows": no_show_events,
        "events": events,
    }


def find_customer_by_phone(
    phone: str,
) -> dict[str, Any] | None:
    """
    Compatibility helper for the existing customer-memory flow.
    """
    profile = get_customer_profile(phone)

    if not profile.get("found"):
        return None

    vehicles = profile.get("vehicles") or []

    latest_vehicle = (
        vehicles[0]
        if vehicles
        else {}
    )

    return {
        "name": profile.get(
            "customer_name",
            "",
        ),
        "phone": profile.get(
            "phone",
            "",
        ),
        "vehicle_reg": (
            profile.get("last_registration")
            or latest_vehicle.get(
                "registration",
                "",
            )
        ),
        "previous_visits": profile.get(
            "completed_visits",
            0,
        ),
        "returning_customer": profile.get(
            "returning_customer",
            False,
        ),
        "vip_customer": profile.get(
            "vip_customer",
            False,
        ),
        "last_service": profile.get(
            "last_service",
            "",
        ),
        "last_visit": profile.get(
            "last_visit",
            "",
        ),
        "vehicles": vehicles,
    }


def list_all_customers(
    limit: int = DEFAULT_CUSTOMER_LIMIT,
    include_upcoming_only: bool = False,
) -> list[dict[str, Any]]:
    """
    Build a deduplicated customer list from calendar bookings.
    """
    now = datetime.now(TIMEZONE)

    events = _fetch_customer_events(
        time_min=now - timedelta(
            days=365 * CUSTOMER_LOOKBACK_YEARS
        ),
        time_max=now + timedelta(
            days=365 * 2
        ),
    )

    phones: list[str] = []

    for event in events:
        phone = _event_phone(event)

        if (
            phone
            and phone not in phones
        ):
            phones.append(phone)

    customers: list[dict[str, Any]] = []

    for phone in phones:
        profile = get_customer_profile(
            phone
        )

        if not profile.get("found"):
            continue

        if (
            include_upcoming_only
            and profile.get(
                "upcoming_bookings",
                0,
            ) < 1
        ):
            continue

        customers.append(profile)

    customers.sort(
        key=lambda customer: (
            customer.get("last_visit", ""),
            customer.get("customer_name", ""),
        ),
        reverse=True,
    )

    safe_limit = max(
        1,
        min(
            int(limit or DEFAULT_CUSTOMER_LIMIT),
            1000,
        ),
    )

    return customers[:safe_limit]


def find_customers_by_registration(
    registration: str,
) -> list[dict[str, Any]]:
    """
    Find customers connected to a vehicle registration.
    """
    registration_key = _clean_registration(
        registration
    )

    if not registration_key:
        return []

    customers = list_all_customers(
        limit=1000
    )

    matches: list[dict[str, Any]] = []

    for customer in customers:
        vehicles = customer.get(
            "vehicles",
            [],
        )

        if any(
            vehicle.get(
                "registration_key"
            ) == registration_key
            for vehicle in vehicles
        ):
            matches.append(customer)

    return matches


def get_inactive_customers(
    inactive_days: int = INACTIVE_CUSTOMER_DAYS,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """
    Return customers who have not completed a visit recently.

    This will later be used by campaigns.py.
    """
    customers = list_all_customers(
        limit=1000
    )

    inactive: list[dict[str, Any]] = []

    for customer in customers:
        days_since_last_visit = customer.get(
            "days_since_last_visit"
        )

        if days_since_last_visit is None:
            continue

        if (
            days_since_last_visit
            >= int(inactive_days)
        ):
            inactive.append(customer)

    inactive.sort(
        key=lambda customer: (
            customer.get(
                "days_since_last_visit",
                0,
            )
        ),
        reverse=True,
    )

    return inactive[: max(1, int(limit))]


def get_vip_customers(
    limit: int = 100,
) -> list[dict[str, Any]]:
    """
    Return customers who meet the loyalty threshold.
    """
    customers = list_all_customers(
        limit=1000
    )

    vip_customers = [
        customer
        for customer in customers
        if customer.get("vip_customer")
    ]

    vip_customers.sort(
        key=lambda customer: (
            customer.get(
                "total_spent",
                0,
            ),
            customer.get(
                "completed_visits",
                0,
            ),
        ),
        reverse=True,
    )

    return vip_customers[: max(1, int(limit))]


def mark_customer_no_show(
    event_id: str,
    reason: str = "",
) -> dict[str, Any]:
    """
    Mark an appointment as a no-show.
    """
    event_id = str(event_id or "").strip()

    if not event_id:
        raise ValueError(
            "Missing Google Calendar event ID"
        )

    service = _get_calendar_service()

    event = (
        service.events()
        .get(
            calendarId=_calendar_id(),
            eventId=event_id,
        )
        .execute()
    )

    extended_properties = (
        event.get("extendedProperties")
        or {}
    )

    private = (
        extended_properties.get("private")
        or {}
    )

    marked_at = datetime.now(
        TIMEZONE
    ).isoformat()

    private["no_show"] = "true"
    private["no_show_marked_at"] = (
        marked_at
    )

    if reason.strip():
        private["no_show_reason"] = (
            reason.strip()
        )

    extended_properties["private"] = private
    event["extendedProperties"] = (
        extended_properties
    )

    updated_event = (
        service.events()
        .update(
            calendarId=_calendar_id(),
            eventId=event_id,
            body=event,
        )
        .execute()
    )

    print(
        "CUSTOMER MARKED NO-SHOW:",
        event_id,
        marked_at,
    )

    return {
        "success": True,
        "event_id": event_id,
        "marked_at": marked_at,
        "customer_name": _event_customer_name(
            updated_event
        ),
        "phone": _event_phone(
            updated_event
        ),
    }


def update_customer_name(
    phone: str,
    new_name: str,
) -> dict[str, Any]:
    """
    Update the customer's name across their calendar events.

    This helps fix incorrectly captured voice names.
    """
    normalised_phone = normalise_phone(
        phone
    )

    cleaned_name = str(
        new_name or ""
    ).strip()

    if not normalised_phone:
        raise ValueError(
            "Missing customer phone number"
        )

    if not cleaned_name:
        raise ValueError(
            "Missing customer name"
        )

    now = datetime.now(TIMEZONE)

    events = _fetch_customer_events(
        time_min=now - timedelta(
            days=365 * CUSTOMER_LOOKBACK_YEARS
        ),
        time_max=now + timedelta(
            days=365 * 2
        ),
    )

    service = _get_calendar_service()

    updated_count = 0
    updated_event_ids: list[str] = []

    for event in events:
        if _event_phone(event) != normalised_phone:
            continue

        event_id = event.get("id")

        if not event_id:
            continue

        extended_properties = (
            event.get("extendedProperties")
            or {}
        )

        private = (
            extended_properties.get("private")
            or {}
        )

        private["customer_name"] = cleaned_name
        private["name_updated_at"] = (
            datetime.now(TIMEZONE).isoformat()
        )

        extended_properties["private"] = (
            private
        )

        event["extendedProperties"] = (
            extended_properties
        )

        (
            service.events()
            .update(
                calendarId=_calendar_id(),
                eventId=event_id,
                body=event,
            )
            .execute()
        )

        updated_count += 1
        updated_event_ids.append(event_id)

    print(
        "CUSTOMER NAME UPDATED:",
        normalised_phone,
        cleaned_name,
        updated_count,
    )

    return {
        "success": True,
        "phone": normalised_phone,
        "customer_name": cleaned_name,
        "updated_events": updated_count,
        "event_ids": updated_event_ids,
    }


def format_customer_profile_for_ai(
    phone: str,
) -> str:
    """
    Return a short customer-memory summary for the voice agent.
    """
    profile = get_customer_profile(
        phone
    )

    if not profile.get("found"):
        return (
            "No previous customer history was found."
        )

    name = (
        profile.get("customer_name")
        or "Customer"
    )

    completed_visits = profile.get(
        "completed_visits",
        0,
    )

    vehicle_descriptions: list[str] = []

    for vehicle in profile.get(
        "vehicles",
        [],
    ):
        parts = []

        if vehicle.get("make"):
            parts.append(vehicle["make"])

        if vehicle.get("model"):
            parts.append(vehicle["model"])

        description = " ".join(parts).strip()

        if not description:
            description = "vehicle"

        registration = vehicle.get(
            "registration",
            "",
        )

        if registration:
            description += (
                f" registration {registration}"
            )

        vehicle_descriptions.append(
            description
        )

    vehicles_text = (
        ", ".join(vehicle_descriptions)
        if vehicle_descriptions
        else "no saved vehicles"
    )

    lines = [
        f"Customer name: {name}.",
        (
            f"Previous completed visits: "
            f"{completed_visits}."
        ),
        f"Saved vehicles: {vehicles_text}.",
    ]

    if profile.get("last_visit_text"):
        lines.append(
            (
                f"Last visit: "
                f"{profile['last_visit_text']} "
                f"for {profile.get('last_service') or 'a garage service'}."
            )
        )

    if profile.get("upcoming_bookings"):
        lines.append(
            (
                f"Upcoming bookings: "
                f"{profile['upcoming_bookings']}."
            )
        )

    if profile.get("vip_customer"):
        lines.append(
            "This customer is marked as a VIP customer."
        )

    if profile.get("inactive_customer"):
        lines.append(
            (
                "This customer has not visited for "
                f"{profile.get('days_since_last_visit')} days."
            )
        )

    return "\n".join(lines)