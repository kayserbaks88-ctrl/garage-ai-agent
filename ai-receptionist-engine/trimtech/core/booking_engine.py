from __future__ import annotations

"""
Shared TrimTech booking engine.

This module is business-aware and uses the shared Google Calendar service.

It no longer imports:

    integrations.garage_calendar
    integrations.garage_config

All booking and availability operations can receive an explicit
BusinessConfig. For legacy callers that do not yet pass one, the current
active business is used as a compatibility fallback.

Multi-business Vapi routes should always pass the resolved business
explicitly so one garage can never accidentally use another garage's
calendar or services.
"""

from datetime import datetime, timedelta
from typing import Any

from trimtech.core.business import BusinessConfig
from trimtech.core.registry import get_active_business
from trimtech.integrations.google_calendar.service import (
    create_booking,
    get_available_slots,
    is_free,
    service_definition,
    timezone,
)


# =========================================================
# Business helpers
# =========================================================


def _business(
    business: BusinessConfig | None,
) -> BusinessConfig:
    if isinstance(
        business,
        BusinessConfig,
    ):
        return business

    return get_active_business()


def service_label(
    service_key: str,
    business: BusinessConfig | None = None,
) -> str:
    resolved_business = _business(
        business
    )

    try:
        service = service_definition(
            resolved_business,
            service_key,
        )

        return service.name

    except ValueError:
        return (
            str(
                service_key
                or "Garage Appointment"
            )
            .replace(
                "_",
                " ",
            )
            .title()
        )


# =========================================================
# Formatting
# =========================================================


def format_slot(
    slot: datetime,
    business: BusinessConfig | None = None,
) -> str:
    resolved_business = _business(
        business
    )

    local_slot = slot.astimezone(
        timezone(
            resolved_business
        )
    )

    time_label = (
        local_slot
        .strftime(
            "%I:%M %p"
        )
        .lstrip("0")
        .replace(
            ":00 ",
            " ",
        )
        .lower()
    )

    return (
        f"{local_slot.strftime('%A')} "
        f"{local_slot.day} "
        f"{local_slot.strftime('%B')} "
        f"at {time_label}"
    )


# =========================================================
# Availability
# =========================================================


def check_requested_slot(
    session: dict[str, Any],
    business: BusinessConfig | None = None,
) -> dict[str, Any]:
    resolved_business = _business(
        business
    )

    slot = session.get(
        "requested_datetime"
    )

    service_key = str(
        session.get(
            "service_key"
        )
        or ""
    ).strip()

    if not isinstance(
        slot,
        datetime,
    ):
        return {
            "available": False,
            "slots": [],
            "error": "missing_details",
        }

    try:
        service = service_definition(
            resolved_business,
            service_key,
        )

    except ValueError:
        return {
            "available": False,
            "slots": [],
            "error": "missing_details",
        }

    business_timezone = timezone(
        resolved_business
    )

    if slot.tzinfo is None:
        slot = slot.replace(
            tzinfo=business_timezone
        )
    else:
        slot = slot.astimezone(
            business_timezone
        )

    if slot <= datetime.now(
        business_timezone
    ):
        return {
            "available": False,
            "slots": [],
            "error": "past_datetime",
        }

    duration = int(
        service.duration_minutes
    )

    try:
        available = is_free(
            resolved_business,
            slot,
            slot
            + timedelta(
                minutes=duration
            ),
        )

    except Exception as error:
        print(
            "CALENDAR CHECK ERROR:",
            {
                "business_id": (
                    resolved_business
                    .business_id
                ),
                "error": repr(
                    error
                ),
            },
        )

        return {
            "available": False,
            "slots": [],
            "error": "calendar_unavailable",
        }

    if available:
        return {
            "available": True,
            "slots": [slot],
            "error": "",
        }

    try:
        alternatives = get_available_slots(
            resolved_business,
            requested_date=(
                slot.date()
            ),
            service_key=(
                service.key
            ),
            preferred_period=str(
                session.get(
                    "preferred_period"
                )
                or ""
            ).strip(),
            limit=4,
        )

    except Exception as error:
        print(
            "SLOT LOOKUP ERROR:",
            {
                "business_id": (
                    resolved_business
                    .business_id
                ),
                "error": repr(
                    error
                ),
            },
        )

        return {
            "available": False,
            "slots": [],
            "error": "calendar_unavailable",
        }

    return {
        "available": False,
        "slots": alternatives,
        "error": "slot_taken",
    }


def build_slot_offer(
    slots: list[datetime],
    business: BusinessConfig | None = None,
) -> str:
    if not slots:
        return (
            "I couldn't find another available time that day. "
            "What other day would suit you?"
        )

    resolved_business = _business(
        business
    )

    labels = []

    for slot in slots:
        local_slot = slot.astimezone(
            timezone(
                resolved_business
            )
        )

        labels.append(
            local_slot
            .strftime(
                "%I:%M %p"
            )
            .lstrip("0")
            .replace(
                ":00 ",
                " ",
            )
            .lower()
        )

    if len(labels) == 1:
        options = labels[0]

    elif len(labels) == 2:
        options = (
            f"{labels[0]} or "
            f"{labels[1]}"
        )

    else:
        options = (
            ", ".join(
                labels[:-1]
            )
            + f", or {labels[-1]}"
        )

    return (
        "That time is unavailable. "
        f"I have {options}. "
        "Which one would suit you?"
    )


def match_slot(
    text: str,
    slots: list[datetime],
) -> datetime | None:
    normalised_text = str(
        text or ""
    ).lower()

    positions = {
        "first": 0,
        "one": 0,
        "option one": 0,
        "second": 1,
        "two": 1,
        "option two": 1,
        "third": 2,
        "three": 2,
        "option three": 2,
        "fourth": 3,
        "four": 3,
        "option four": 3,
    }

    for phrase, index in (
        positions.items()
    ):
        if (
            phrase
            in normalised_text
            and index
            < len(slots)
        ):
            return slots[index]

    from core.speech_parser import (
        parse_requested_time,
    )

    if slots:
        parsed = parse_requested_time(
            text,
            requested_date=(
                slots[0].date()
            ),
        )

        if parsed:
            for slot in slots:
                if (
                    slot.hour
                    == parsed.hour
                    and slot.minute
                    == parsed.minute
                ):
                    return slot

    return None


# =========================================================
# Booking creation from conversation/session state
# =========================================================


def create_from_session(
    session: dict[str, Any],
    business: BusinessConfig | None = None,
) -> dict[str, Any]:
    resolved_business = _business(
        business
    )

    vehicle = (
        session.get(
            "vehicle"
        )
        or {
            "reg": (
                session.get(
                    "registration",
                    "",
                )
            ),
            "make_model": (
                "Vehicle not confirmed"
            ),
        }
    )

    selected_slot = (
        session.get(
            "selected_slot"
        )
        or session.get(
            "requested_datetime"
        )
    )

    if not isinstance(
        selected_slot,
        datetime,
    ):
        raise ValueError(
            "missing_datetime"
        )

    service_key = str(
        session.get(
            "service_key"
        )
        or ""
    ).strip()

    # Validate against this business's configured services
    # before handing off to the calendar layer.
    service_definition(
        resolved_business,
        service_key,
    )

    customer_name = str(
        session.get(
            "name"
        )
        or session.get(
            "customer_name"
        )
        or ""
    ).strip()

    if not customer_name:
        raise ValueError(
            "missing_customer_name"
        )

    return create_booking(
        resolved_business,
        phone=str(
            session.get(
                "phone"
            )
            or ""
        ).strip(),
        service_key=(
            service_key
        ),
        start_dt=(
            selected_slot
        ),
        customer_name=(
            customer_name
        ),
        vehicle=vehicle,
        notes=str(
            session.get(
                "issue"
            )
            or session.get(
                "notes"
            )
            or ""
        ).strip(),
        source=str(
            session.get(
                "source"
            )
            or "Voice AI"
        ).strip(),
    )