from __future__ import annotations

"""
TrimTech Garage dashboard API.

This version keeps the existing working dashboard routes and adds:

- One CRM record per customer.
- One vehicle record per normalised registration.
- Full booking/service history for each vehicle.
- Customer revenue and repeat-customer summaries.
- Revenue totals for today, week, month and year.
- Analytics suitable for the dashboard.
"""

import json
import os
from collections import Counter
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from flask import Blueprint, jsonify
from google.oauth2 import service_account
from googleapiclient.discovery import build
from trimtech.modules.reminders.service import get_reminder_health

from dashboard_auth import dashboard_api_login_required
from trimtech.integrations.reminder_scheduler import process_reminders
from trimtech.core.registry import get_active_business
from trimtech.modules.crm.customer_service import (
    build_customer_records,
    customer_summary,
)
from trimtech.modules.crm.vehicle_service import (
    build_vehicle_records,
    format_registration,
    normalise_registration,
)


dashboard_api = Blueprint("dashboard_api", __name__)

BUSINESS = get_active_business()
TIMEZONE_NAME = BUSINESS.timezone_name
TIMEZONE = BUSINESS.timezone

GOOGLE_CALENDAR_SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly"
]


def business_env_prefix() -> str:
    return BUSINESS.business_type.upper().replace("-", "_")


def enabled_service_keys() -> list[str]:
    return [
        service.key
        for service in BUSINESS.enabled_services()
    ]


def normalise_text(value: Any) -> str:
    return str(value or "").strip()


def normalise_phone(value: Any) -> str:
    phone = normalise_text(value)

    if phone.lower().startswith("whatsapp:"):
        phone = phone.split(":", 1)[1]

    phone = (
        phone.replace(" ", "")
        .replace("-", "")
        .replace("(", "")
        .replace(")", "")
    )

    if phone.startswith("+44"):
        return "0" + phone[3:]

    if phone.startswith("44") and len(phone) >= 12:
        return "0" + phone[2:]

    return phone


def normalise_service(value: Any) -> str:
    service = BUSINESS.resolve_service(value)

    if service:
        return service.key

    fallback = normalise_text(value).lower()

    return fallback or "appointment"


def service_label(value: Any) -> str:
    return BUSINESS.service_label(value)


def service_price(value: Any) -> float:
    try:
        return float(BUSINESS.service_price(value))
    except (TypeError, ValueError, KeyError):
        return 0.0


def get_calendar_id() -> str:
    prefix = business_env_prefix()

    possible_values = [
        os.getenv(f"{prefix}_CALENDAR_ID"),
        os.getenv("TRIMTECH_CALENDAR_ID"),
        os.getenv("GOOGLE_CALENDAR_ID"),
        os.getenv("CALENDAR_ID"),
    ]

    for value in possible_values:
        calendar_id = normalise_text(value)

        if calendar_id:
            return calendar_id

    return ""


def load_google_credentials():
    raw_credentials = normalise_text(
        os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    )

    if raw_credentials:
        credentials_info = json.loads(raw_credentials)

        return service_account.Credentials.from_service_account_info(
            credentials_info,
            scopes=GOOGLE_CALENDAR_SCOPES,
        )

    credentials_path = normalise_text(
        os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    )

    if not credentials_path:
        local_credentials_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "credential.json",
        )

        if os.path.exists(local_credentials_path):
            credentials_path = local_credentials_path

    if credentials_path and os.path.exists(credentials_path):
        return service_account.Credentials.from_service_account_file(
            credentials_path,
            scopes=GOOGLE_CALENDAR_SCOPES,
        )

    raise RuntimeError(
        "Google Calendar credentials were not found."
    )


def get_calendar_service():
    credentials = load_google_credentials()

    return build(
        "calendar",
        "v3",
        credentials=credentials,
        cache_discovery=False,
    )


def iso_utc(value: datetime) -> str:
    return (
        value.astimezone(ZoneInfo("UTC"))
        .isoformat()
        .replace("+00:00", "Z")
    )


def parse_event_datetime(
    event_value: dict[str, Any] | None,
) -> datetime | None:
    if not event_value:
        return None

    date_time_value = normalise_text(
        event_value.get("dateTime")
    )

    if date_time_value:
        try:
            parsed = datetime.fromisoformat(
                date_time_value.replace("Z", "+00:00")
            )

            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=TIMEZONE)

            return parsed.astimezone(TIMEZONE)

        except ValueError:
            return None

    date_value = normalise_text(
        event_value.get("date")
    )

    if date_value:
        try:
            parsed_date = datetime.strptime(
                date_value,
                "%Y-%m-%d",
            )

            return parsed_date.replace(tzinfo=TIMEZONE)

        except ValueError:
            return None

    return None


def event_private_properties(
    event: dict[str, Any],
) -> dict[str, Any]:
    extended_properties = (
        event.get("extendedProperties") or {}
    )

    private_properties = (
        extended_properties.get("private") or {}
    )

    return (
        private_properties
        if isinstance(private_properties, dict)
        else {}
    )


def read_event_field(
    event: dict[str, Any],
    private_properties: dict[str, Any],
    *field_names: str,
) -> str:
    for field_name in field_names:
        value = normalise_text(
            private_properties.get(field_name)
        )

        if value:
            return value

    description = normalise_text(
        event.get("description")
    )

    wanted = {
        field_name
        .strip()
        .lower()
        .replace(" ", "_")
        .replace("-", "_")
        for field_name in field_names
    }

    for line in description.splitlines():
        line_key, separator, line_value = (
            line.partition(":")
        )

        if not separator:
            continue

        normalised_line_key = (
            line_key.strip()
            .lower()
            .replace(" ", "_")
            .replace("-", "_")
        )

        if normalised_line_key in wanted:
            value = normalise_text(line_value)

            if value:
                return value

    return ""


def parse_summary_fallback(
    summary: str,
) -> dict[str, str]:
    result = {
        "customer_name": "",
        "service": "",
        "vehicle_reg": "",
    }

    clean_summary = normalise_text(summary)

    if not clean_summary:
        return result

    separators = [
        " - ",
        " | ",
        " – ",
    ]

    parts = [clean_summary]

    for separator in separators:
        if separator in clean_summary:
            parts = [
                part.strip()
                for part in clean_summary.split(separator)
                if part.strip()
            ]
            break

    for part in parts:
        part_lower = part.lower()

        if BUSINESS.resolve_service(part_lower):
            result["service"] = part
            continue

        registration = normalise_registration(part)

        if (
            5 <= len(registration) <= 8
            and any(
                character.isdigit()
                for character in registration
            )
            and any(
                character.isalpha()
                for character in registration
            )
        ):
            result["vehicle_reg"] = registration
            continue

        if not result["customer_name"]:
            result["customer_name"] = part

    return result


def event_to_booking(
    event: dict[str, Any],
) -> dict[str, Any] | None:
    if (
        normalise_text(
            event.get("status")
        ).lower()
        == "cancelled"
    ):
        return None

    start = parse_event_datetime(
        event.get("start")
    )

    end = parse_event_datetime(
        event.get("end")
    )

    if not start:
        return None

    private_properties = event_private_properties(
        event
    )

    summary_fallback = parse_summary_fallback(
        normalise_text(
            event.get("summary")
        )
    )

    customer_name = (
        read_event_field(
            event,
            private_properties,
            "customer_name",
            "name",
            "customer",
        )
        or summary_fallback["customer_name"]
    )

    phone = read_event_field(
        event,
        private_properties,
        "phone",
        "customer_phone",
        "telephone",
        "mobile",
    )

    email = read_event_field(
        event,
        private_properties,
        "email",
        "customer_email",
    )

    raw_registration = (
        read_event_field(
            event,
            private_properties,
            "vehicle_reg",
            "registration",
            "reg",
            "vehicle_registration",
            "number_plate",
            "plate",
        )
        or summary_fallback["vehicle_reg"]
    )

    registration_key = normalise_registration(
        raw_registration
    )

    service = (
        read_event_field(
            event,
            private_properties,
            "service",
            "service_key",
            "service_name",
        )
        or summary_fallback["service"]
    )

    service_key = normalise_service(service)

    status = (
        read_event_field(
            event,
            private_properties,
            "booking_status",
            "status",
        )
        or "confirmed"
    )

    make = read_event_field(
        event,
        private_properties,
        "make",
        "vehicle_make",
    )

    model = read_event_field(
        event,
        private_properties,
        "model",
        "vehicle_model",
    )

    colour = read_event_field(
        event,
        private_properties,
        "colour",
        "color",
        "vehicle_colour",
    )

    year = read_event_field(
        event,
        private_properties,
        "year",
        "manufacture_year",
        "year_of_manufacture",
    )

    fuel_type = read_event_field(
        event,
        private_properties,
        "fuel_type",
        "fuel",
    )

    mot_status = read_event_field(
        event,
        private_properties,
        "mot_status",
    )

    mot_expiry_date = read_event_field(
        event,
        private_properties,
        "mot_expiry_date",
        "mot_expiry",
    )

    return {
        "event_id": normalise_text(
            event.get("id")
        ),
        "customer_name": (
            customer_name or "Customer"
        ),
        "phone": normalise_phone(phone),
        "email": email,
        "vehicle_reg": (
            format_registration(
                registration_key
            )
            if registration_key
            else "—"
        ),
        "registration_key": registration_key,
        "make": make,
        "model": model,
        "colour": colour,
        "year": year,
        "fuel_type": fuel_type,
        "mot_status": mot_status,
        "mot_expiry_date": mot_expiry_date,
        "service": service_label(
            service_key
        ),
        "service_key": service_key,
        "price": service_price(
            service_key
        ),
        "start": start.isoformat(),
        "end": (
            end.isoformat()
            if end
            else None
        ),
        "status": status.lower(),
        "notes": normalise_text(
            event.get("description")
        ),
        "calendar_link": normalise_text(
            event.get("htmlLink")
        ),
        "created_at": normalise_text(
            event.get("created")
        ),
        "updated_at": normalise_text(
            event.get("updated")
        ),
    }


def fetch_calendar_events(
    time_min: datetime,
    time_max: datetime,
) -> list[dict[str, Any]]:
    calendar_id = get_calendar_id()

    if not calendar_id:
        raise RuntimeError(
            f"{business_env_prefix()}_CALENDAR_ID is not configured."
        )

    calendar_service = get_calendar_service()

    events: list[dict[str, Any]] = []
    page_token: str | None = None

    while True:
        response = (
            calendar_service.events()
            .list(
                calendarId=calendar_id,
                timeMin=iso_utc(time_min),
                timeMax=iso_utc(time_max),
                singleEvents=True,
                orderBy="startTime",
                maxResults=2500,
                pageToken=page_token,
            )
            .execute()
        )

        page_events = (
            response.get("items") or []
        )

        if isinstance(page_events, list):
            events.extend(page_events)

        page_token = response.get(
            "nextPageToken"
        )

        if not page_token:
            break

    return events


def load_bookings() -> tuple[
    list[dict[str, Any]],
    str | None,
]:
    now = datetime.now(TIMEZONE)

    history_days = int(
        os.getenv(
            "DASHBOARD_HISTORY_DAYS",
            "730",
        )
    )

    future_days = int(
        os.getenv(
            "DASHBOARD_FUTURE_DAYS",
            "365",
        )
    )

    range_start = (
        now - timedelta(days=history_days)
    ).replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )

    range_end = (
        now + timedelta(days=future_days)
    ).replace(
        hour=23,
        minute=59,
        second=59,
        microsecond=999999,
    )

    try:
        raw_events = fetch_calendar_events(
            range_start,
            range_end,
        )

        bookings: list[
            dict[str, Any]
        ] = []

        for event in raw_events:
            booking = event_to_booking(event)

            if booking:
                bookings.append(booking)

        bookings.sort(
            key=lambda item: (
                item.get("start") or ""
            )
        )

        return bookings, None

    except Exception as error:
        print(
            "DASHBOARD CALENDAR ERROR:",
            repr(error),
        )

        return [], str(error)


def parse_booking_start(
    booking: dict[str, Any],
) -> datetime | None:
    value = normalise_text(
        booking.get("start")
    )

    if not value:
        return None

    try:
        parsed = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )

        if parsed.tzinfo is None:
            parsed = parsed.replace(
                tzinfo=TIMEZONE
            )

        return parsed.astimezone(
            TIMEZONE
        )

    except ValueError:
        return None


def is_cancelled(
    booking: dict[str, Any],
) -> bool:
    return "cancel" in normalise_text(
        booking.get("status")
    ).lower()


def booking_value(
    booking: dict[str, Any],
) -> float:
    try:
        return float(
            booking.get("price")
            or service_price(
                booking.get("service_key")
                or booking.get("service")
            )
        )
    except (TypeError, ValueError):
        return 0.0


def booking_activity(
    bookings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    now = datetime.now(TIMEZONE)
    today = now.date()

    activity = []

    for offset in range(6, -1, -1):
        target_date = (
            today - timedelta(days=offset)
        )

        count = sum(
            1
            for booking in bookings
            if (
                parse_booking_start(booking)
                and parse_booking_start(
                    booking
                ).date()
                == target_date
                and not is_cancelled(booking)
            )
        )

        activity.append(
            {
                "date": (
                    target_date.isoformat()
                ),
                "count": count,
            }
        )

    return activity


def service_performance(
    bookings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    now = datetime.now(TIMEZONE)

    thirty_days_ago = (
        now - timedelta(days=30)
    )

    counter: Counter[str] = Counter()

    for booking in bookings:
        start = parse_booking_start(
            booking
        )

        if (
            not start
            or start < thirty_days_ago
            or is_cancelled(booking)
        ):
            continue

        service_key = normalise_service(
            booking.get("service_key")
            or booking.get("service")
        )

        counter[service_key] += 1

    performance = []

    configured_service_keys = (
        enabled_service_keys()
    )

    for service in BUSINESS.enabled_services():
        performance.append(
            {
                "name": service.name,
                "bookings": counter.get(
                    service.key,
                    0,
                ),
            }
        )

    extra_services = sorted(
        service_key
        for service_key in counter
        if service_key
        not in configured_service_keys
    )

    for service_key in extra_services:
        performance.append(
            {
                "name": service_label(
                    service_key
                ),
                "bookings": counter[
                    service_key
                ],
            }
        )

    return performance


def revenue_summary(
    bookings: list[dict[str, Any]],
) -> dict[str, Any]:
    now = datetime.now(TIMEZONE)
    today = now.date()
    week_start = (
        today
        - timedelta(
            days=today.weekday()
        )
    )

    year_start = datetime(
        now.year,
        1,
        1,
        tzinfo=TIMEZONE,
    )

    active = [
        booking
        for booking in bookings
        if not is_cancelled(booking)
    ]

    def total_for(
        predicate,
    ) -> float:
        total = 0.0

        for booking in active:
            start = parse_booking_start(
                booking
            )

            if (
                start
                and predicate(start)
            ):
                total += booking_value(
                    booking
                )

        return round(total, 2)

    today_total = total_for(
        lambda value: (
            value.date() == today
        )
    )

    week_total = total_for(
        lambda value: (
            week_start
            <= value.date()
            <= today
        )
    )

    month_total = total_for(
        lambda value: (
            value.year == now.year
            and value.month == now.month
        )
    )

    year_total = total_for(
        lambda value: (
            value >= year_start
            and value <= now
        )
    )

    lifetime_total = round(
        sum(
            booking_value(booking)
            for booking in active
            if (
                parse_booking_start(
                    booking
                )
                and parse_booking_start(
                    booking
                )
                <= now
            )
        ),
        2,
    )

    completed_count = sum(
        1
        for booking in active
        if (
            parse_booking_start(
                booking
            )
            and parse_booking_start(
                booking
            )
            <= now
        )
    )

    future_pipeline = round(
        sum(
            booking_value(booking)
            for booking in active
            if (
                parse_booking_start(
                    booking
                )
                and parse_booking_start(
                    booking
                )
                > now
            )
        ),
        2,
    )

    monthly_breakdown = []

    for month_offset in range(5, -1, -1):
        target_month = (
            now.month - month_offset
        )

        target_year = now.year

        while target_month <= 0:
            target_month += 12
            target_year -= 1

        total = total_for(
            lambda value,
            target_year=target_year,
            target_month=target_month: (
                value.year == target_year
                and value.month == target_month
            )
        )

        label = datetime(
            target_year,
            target_month,
            1,
            tzinfo=TIMEZONE,
        ).strftime("%b")

        monthly_breakdown.append(
            {
                "year": target_year,
                "month": target_month,
                "label": label,
                "revenue": total,
            }
        )

    return {
        "today": today_total,
        "this_week": week_total,
        "this_month": month_total,
        "this_year": year_total,
        "lifetime": lifetime_total,
        "future_pipeline": future_pipeline,
        "average_booking_value": round(
            (
                lifetime_total
                / completed_count
            )
            if completed_count
            else 0.0,
            2,
        ),
        "completed_booking_count": (
            completed_count
        ),
        "monthly_breakdown": (
            monthly_breakdown
        ),
    }


def analytics_summary(
    bookings: list[dict[str, Any]],
    customers: list[dict[str, Any]],
    vehicles: list[dict[str, Any]],
) -> dict[str, Any]:
    total_bookings = len(bookings)

    cancelled = sum(
        1
        for booking in bookings
        if is_cancelled(booking)
    )

    active_bookings = (
        total_bookings - cancelled
    )

    service_counter = Counter(
        normalise_text(
            booking.get("service")
        )
        for booking in bookings
        if not is_cancelled(booking)
    )

    popular_service = (
        service_counter.most_common(1)[0][0]
        if service_counter
        else ""
    )

    vehicle_visit_leader = max(
        vehicles,
        key=lambda vehicle: int(
            vehicle.get(
                "booking_count"
            )
            or 0
        ),
        default=None,
    )

    repeat_customers = sum(
        1
        for customer in customers
        if int(
            customer.get(
                "completed_visit_count"
            )
            or 0
        )
        >= 2
    )

    return {
        "total_bookings": total_bookings,
        "active_bookings": active_bookings,
        "cancelled_bookings": cancelled,
        "cancellation_rate": round(
            (
                cancelled
                / total_bookings
                * 100
            )
            if total_bookings
            else 0.0,
            1,
        ),
        "total_customers": len(
            customers
        ),
        "repeat_customers": (
            repeat_customers
        ),
        "repeat_customer_rate": round(
            (
                repeat_customers
                / len(customers)
                * 100
            )
            if customers
            else 0.0,
            1,
        ),
        "total_vehicles": len(
            vehicles
        ),
        "popular_service": (
            popular_service
        ),
        "most_visited_vehicle": (
            {
                "registration": (
                    vehicle_visit_leader.get(
                        "registration"
                    )
                ),
                "booking_count": int(
                    vehicle_visit_leader.get(
                        "booking_count"
                    )
                    or 0
                ),
            }
            if vehicle_visit_leader
            else None
        ),
    }


def reminder_health() -> dict[str, Any]:
    default_result = {
        "enabled": True,
        "due": 0,
        "waiting": 0,
        "sent_this_month": 0,
        "failed": 0,
        "last_run": None,
        "status": "ready",
        "period": "this month",
        "queue": [],
    }

    try:
        health = get_reminder_health()

        if isinstance(health, dict):
            return {
               **default_result,
               **health,
            }

    except ImportError:
        pass

        health = get_reminder_health()

        if isinstance(health, dict):
            return {
                **default_result,
                **health,
            }

    except ImportError:
        pass

    except Exception as error:
        print(
            "DASHBOARD REMINDER HEALTH ERROR:",
            repr(error),
        )

        return {
            **default_result,
            "status": "error",
        }

    
    except ImportError:
        pass

    except Exception as error:
        print(
            "DASHBOARD VEHICLE REMINDER ERROR:",
            repr(error),
        )

    return default_result


def recent_ai_activity(
    bookings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    activity = []

    recent_bookings = sorted(
        bookings,
        key=lambda item: (
            item.get("created_at")
            or item.get("updated_at")
            or item.get("start")
            or ""
        ),
        reverse=True,
    )

    for booking in recent_bookings[:10]:
        customer_name = (
            normalise_text(
                booking.get(
                    "customer_name"
                )
            )
            or "Customer"
        )

        service = (
            normalise_text(
                booking.get("service")
            )
            or str(
                BUSINESS.metadata.get(
                    "booking_label"
                )
                or "appointment"
            ).lower()
        )

        vehicle_reg = normalise_text(
            booking.get("vehicle_reg")
        )

        detail_parts = [service]

        if (
            vehicle_reg
            and vehicle_reg != "—"
        ):
            detail_parts.append(
                vehicle_reg
            )

        activity.append(
            {
                "type": "booking",
                "title": (
                    f"Booking recorded for "
                    f"{customer_name}"
                ),
                "detail": " · ".join(
                    detail_parts
                ),
                "created_at": (
                    booking.get(
                        "created_at"
                    )
                    or booking.get(
                        "updated_at"
                    )
                    or booking.get("start")
                ),
            }
        )

    return activity


def system_health(
    calendar_error: str | None,
) -> dict[str, str]:
    calendar_status = (
        "connected"
        if not calendar_error
        else "error"
    )

    dvla_status = (
        "connected"
        if (
            not BUSINESS.feature_enabled(
                "dvla"
            )
            or normalise_text(
                os.getenv("DVLA_API_KEY")
            )
        )
        else "not configured"
    )

    vapi_status = (
        "connected"
        if (
            not BUSINESS.feature_enabled(
                "voice_agent"
            )
            or normalise_text(
                os.getenv("VAPI_API_KEY")
            )
            or normalise_text(
                os.getenv(
                    "VAPI_PRIVATE_KEY"
                )
            )
        )
        else "not configured"
    )

    overall = (
        "operational"
        if calendar_status == "connected"
        else "attention"
    )

    return {
        "overall": overall,
        "vapi": vapi_status,
        "calendar": calendar_status,
        "dvla": dvla_status,
        "backend": "connected",
    }


def build_dashboard_data() -> dict[str, Any]:
    now = datetime.now(TIMEZONE)
    today = now.date()

    bookings, calendar_error = (
        load_bookings()
    )

    today_bookings = []

    upcoming_bookings = []

    for booking in bookings:
        start = parse_booking_start(
            booking
        )

        if not start:
            continue

        if (
            start.date() == today
            and not is_cancelled(booking)
        ):
            today_bookings.append(
                booking
            )

        if (
            start >= now
            and not is_cancelled(booking)
        ):
            upcoming_bookings.append(
                booking
            )

    upcoming_bookings.sort(
        key=lambda item: (
            item.get("start") or ""
        )
    )

    customers = build_customer_records(
        bookings,
        now=now,
        service_price_resolver=service_price,
    )

    vehicles = build_vehicle_records(
        bookings,
        now=now,
        service_price_resolver=service_price,
    )

    customer_totals = customer_summary(
        customers
    )

    revenue = revenue_summary(
        bookings
    )

    analytics = analytics_summary(
        bookings,
        customers,
        vehicles,
    )

    reminders = reminder_health()

    next_appointment = (
        upcoming_bookings[0]
        if upcoming_bookings
        else None
    )

    return {
        "business": BUSINESS.to_dict(),
        "ui": {
            "dashboard_title": (
                BUSINESS.metadata.get(
                    "dashboard_title",
                    (
                        f"{BUSINESS.business_name} "
                        "Dashboard"
                    ),
                )
            ),
            "booking_label": (
                BUSINESS.metadata.get(
                    "booking_label",
                    "Appointment",
                )
            ),
            "customer_label": (
                BUSINESS.metadata.get(
                    "customer_label",
                    "Customer",
                )
            ),
            "vehicle_label": (
                BUSINESS.metadata.get(
                    "vehicle_label",
                    "Vehicle",
                )
            ),
            "currency_symbol": (
                BUSINESS.currency_symbol
            ),
        },
        "summary": {
            "today_bookings": len(
                today_bookings
            ),
            "upcoming_bookings": len(
                upcoming_bookings
            ),
            "reminders_due": int(
                reminders.get("due") or 0
            ),
            "estimated_revenue": (
                revenue["this_month"]
            ),
            "total_customers": len(
                customers
            ),
            "total_vehicles": len(
                vehicles
            ),
            "repeat_customers": (
                customer_totals[
                    "repeat_customers"
                ]
            ),
            "revenue_period": (
                "This month"
            ),
        },
        "next_appointment": (
            next_appointment
        ),
        "booking_activity": (
            booking_activity(bookings)
        ),
        "service_performance": (
            service_performance(bookings)
        ),
        "upcoming_appointments": (
            upcoming_bookings[:100]
        ),
        "customers": customers,
        "vehicles": vehicles,
        "customer_summary": (
            customer_totals
        ),
        "revenue": revenue,
        "analytics": analytics,
        "reminders": reminders,
        "ai_activity": (
            recent_ai_activity(bookings)
        ),
        "systems": (
            system_health(calendar_error)
        ),
        "meta": {
            "generated_at": (
                now.isoformat()
            ),
            "timezone": TIMEZONE_NAME,
            "business_id": (
                BUSINESS.business_id
            ),
            "business_type": (
                BUSINESS.business_type
            ),
            "calendar_error": (
                calendar_error
            ),
            "history_booking_count": len(
                bookings
            ),
        },
    }


@dashboard_api.get(
    "/api/dashboard-data"
)
@dashboard_api_login_required
def dashboard_data():
    try:
        data = build_dashboard_data()

        return jsonify(
            {
                "success": True,
                "data": data,
            }
        )

    except Exception as error:
        print(
            "DASHBOARD API ERROR:",
            repr(error),
        )

        return (
            jsonify(
                {
                    "success": False,
                    "error": (
                        "dashboard_data_failed"
                    ),
                    "message": str(error),
                }
            ),
            500,
        )


@dashboard_api.get(
    "/api/business"
)
@dashboard_api_login_required
def dashboard_business():
    return jsonify(
        {
            "success": True,
            "business": BUSINESS.to_dict(),
            "ui": {
                "dashboard_title": (
                    BUSINESS.metadata.get(
                        "dashboard_title",
                        BUSINESS.business_name,
                    )
                ),
                "booking_label": (
                    BUSINESS.metadata.get(
                        "booking_label",
                        "Appointment",
                    )
                ),
                "customer_label": (
                    BUSINESS.metadata.get(
                        "customer_label",
                        "Customer",
                    )
                ),
                "vehicle_label": (
                    BUSINESS.metadata.get(
                        "vehicle_label",
                        "Vehicle",
                    )
                ),
                "currency_symbol": (
                    BUSINESS.currency_symbol
                ),
            },
        }
    )


@dashboard_api.get(
    "/api/dashboard-health"
)
@dashboard_api_login_required
def dashboard_health():
    calendar_id = get_calendar_id()

    return jsonify(
        {
            "success": True,
            "service": (
                f"{BUSINESS.business_name} "
                "Dashboard"
            ),
            "business_id": (
                BUSINESS.business_id
            ),
            "business_type": (
                BUSINESS.business_type
            ),
            "status": "online",
            "timezone": TIMEZONE_NAME,
            "calendar_configured": bool(
                calendar_id
            ),
            "generated_at": (
                datetime.now(
                    TIMEZONE
                ).isoformat()
            ),
        }
    )


@dashboard_api.post(
    "/api/run-reminders"
)
@dashboard_api_login_required
def dashboard_run_reminders():
    result = process_reminders()

    status_code = (
        200
        if result.get("success")
        else 500
    )

    return jsonify(result), status_code