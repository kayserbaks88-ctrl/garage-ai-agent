from __future__ import annotations

import json
import os
from collections import Counter
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from flask import Blueprint, jsonify
from dashboard_auth import dashboard_api_login_required
from integrations.reminder_scheduler import run_reminder_job
from google.oauth2 import service_account
from googleapiclient.discovery import build


dashboard_api = Blueprint("dashboard_api", __name__)

TIMEZONE_NAME = os.getenv("GARAGE_TIMEZONE", "Europe/London")
TIMEZONE = ZoneInfo(TIMEZONE_NAME)

GOOGLE_CALENDAR_SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly"
]

SERVICE_PRICES = {
    "mot": 54.85,
    "full service": 180.00,
    "diagnostic": 65.00,
    "oil change": 75.00,
}

SERVICE_LABELS = {
    "mot": "MOT",
    "full service": "Full Service",
    "diagnostic": "Diagnostic",
    "oil change": "Oil Change",
}

SERVICE_ORDER = [
    "mot",
    "full service",
    "diagnostic",
    "oil change",
]


def normalise_text(value: Any) -> str:
    return str(value or "").strip()


def normalise_phone(value: Any) -> str:
    phone = normalise_text(value)

    if phone.startswith("whatsapp:"):
        phone = phone.removeprefix("whatsapp:")

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
    service = normalise_text(value).lower()

    aliases = {
        "mot test": "mot",
        "m.o.t": "mot",
        "m.o.t.": "mot",
        "service": "full service",
        "full car service": "full service",
        "car service": "full service",
        "diagnostics": "diagnostic",
        "vehicle diagnostic": "diagnostic",
        "oil": "oil change",
        "oil and filter": "oil change",
        "oil & filter": "oil change",
    }

    if service in aliases:
        return aliases[service]

    for known_service in SERVICE_ORDER:
        if known_service in service:
            return known_service

    return service or "garage appointment"


def service_label(value: Any) -> str:
    key = normalise_service(value)
    return SERVICE_LABELS.get(key, normalise_text(value) or "Garage Appointment")


def service_price(value: Any) -> float:
    key = normalise_service(value)
    return float(SERVICE_PRICES.get(key, 0.0))


def get_calendar_id() -> str:
    possible_values = [
        os.getenv("GARAGE_CALENDAR_ID"),
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


def parse_event_datetime(event_value: dict[str, Any] | None) -> datetime | None:
    if not event_value:
        return None

    date_time_value = normalise_text(event_value.get("dateTime"))

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

    date_value = normalise_text(event_value.get("date"))

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


def event_private_properties(event: dict[str, Any]) -> dict[str, Any]:
    extended_properties = event.get("extendedProperties") or {}
    private_properties = extended_properties.get("private") or {}

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
        value = normalise_text(private_properties.get(field_name))

        if value:
            return value

    description = normalise_text(event.get("description"))

    for line in description.splitlines():
        line_key, separator, line_value = line.partition(":")

        if not separator:
            continue

        normalised_line_key = (
            line_key.strip()
            .lower()
            .replace(" ", "_")
            .replace("-", "_")
        )

        if normalised_line_key in field_names:
            value = normalise_text(line_value)

            if value:
                return value

    return ""


def parse_summary_fallback(summary: str) -> dict[str, str]:
    result = {
        "customer_name": "",
        "service": "",
        "vehicle_reg": "",
    }

    clean_summary = normalise_text(summary)

    if not clean_summary:
        return result

    separators = [" - ", " | ", " – "]
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

        if any(
            service_key in part_lower
            for service_key in SERVICE_ORDER
        ):
            result["service"] = part
            continue

        compact_part = part.replace(" ", "")

        if (
            5 <= len(compact_part) <= 8
            and compact_part.isalnum()
            and any(character.isdigit() for character in compact_part)
            and any(character.isalpha() for character in compact_part)
        ):
            result["vehicle_reg"] = compact_part.upper()
            continue

        if not result["customer_name"]:
            result["customer_name"] = part

    return result


def event_to_booking(event: dict[str, Any]) -> dict[str, Any] | None:
    if normalise_text(event.get("status")).lower() == "cancelled":
        return None

    start = parse_event_datetime(event.get("start"))
    end = parse_event_datetime(event.get("end"))

    if not start:
        return None

    private_properties = event_private_properties(event)
    summary_fallback = parse_summary_fallback(
        normalise_text(event.get("summary"))
    )

    customer_name = read_event_field(
        event,
        private_properties,
        "customer_name",
        "name",
        "customer",
    ) or summary_fallback["customer_name"]

    phone = read_event_field(
        event,
        private_properties,
        "phone",
        "customer_phone",
        "telephone",
        "mobile",
    )

    vehicle_reg = read_event_field(
        event,
        private_properties,
        "vehicle_reg",
        "registration",
        "reg",
        "vehicle_registration",
    ) or summary_fallback["vehicle_reg"]

    service = read_event_field(
        event,
        private_properties,
        "service",
        "service_key",
        "service_name",
    ) or summary_fallback["service"]

    service_key = normalise_service(service)

    status = read_event_field(
        event,
        private_properties,
        "booking_status",
        "status",
    ) or "confirmed"

    return {
        "event_id": normalise_text(event.get("id")),
        "customer_name": customer_name or "Customer",
        "phone": normalise_phone(phone),
        "vehicle_reg": vehicle_reg.upper() if vehicle_reg else "—",
        "service": service_label(service_key),
        "service_key": service_key,
        "start": start.isoformat(),
        "end": end.isoformat() if end else None,
        "status": status.lower(),
        "calendar_link": normalise_text(event.get("htmlLink")),
        "created_at": normalise_text(event.get("created")),
        "updated_at": normalise_text(event.get("updated")),
    }


def fetch_calendar_events(
    time_min: datetime,
    time_max: datetime,
) -> list[dict[str, Any]]:
    calendar_id = get_calendar_id()

    if not calendar_id:
        raise RuntimeError(
            "GARAGE_CALENDAR_ID is not configured."
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

        page_events = response.get("items") or []

        if isinstance(page_events, list):
            events.extend(page_events)

        page_token = response.get("nextPageToken")

        if not page_token:
            break

    return events


def load_bookings() -> tuple[list[dict[str, Any]], str | None]:
    now = datetime.now(TIMEZONE)

    range_start = (
        now - timedelta(days=7)
    ).replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )

    range_end = (
        now + timedelta(days=90)
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

        bookings = []

        for event in raw_events:
            booking = event_to_booking(event)

            if booking:
                bookings.append(booking)

        bookings.sort(
            key=lambda item: item.get("start") or ""
        )

        return bookings, None

    except Exception as error:
        print(
            "DASHBOARD CALENDAR ERROR:",
            repr(error),
        )

        return [], str(error)


def parse_booking_start(booking: dict[str, Any]) -> datetime | None:
    value = normalise_text(booking.get("start"))

    if not value:
        return None

    try:
        parsed = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=TIMEZONE)

        return parsed.astimezone(TIMEZONE)

    except ValueError:
        return None


def booking_activity(
    bookings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    now = datetime.now(TIMEZONE)
    today = now.date()

    activity = []

    for offset in range(6, -1, -1):
        target_date = today - timedelta(days=offset)

        count = sum(
            1
            for booking in bookings
            if (
                parse_booking_start(booking)
                and parse_booking_start(booking).date()
                == target_date
            )
        )

        activity.append(
            {
                "date": target_date.isoformat(),
                "count": count,
            }
        )

    return activity


def service_performance(
    bookings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    now = datetime.now(TIMEZONE)
    thirty_days_ago = now - timedelta(days=30)

    counter: Counter[str] = Counter()

    for booking in bookings:
        start = parse_booking_start(booking)

        if not start or start < thirty_days_ago:
            continue

        service_key = normalise_service(
            booking.get("service_key")
            or booking.get("service")
        )

        counter[service_key] += 1

    performance = []

    for service_key in SERVICE_ORDER:
        performance.append(
            {
                "name": SERVICE_LABELS[service_key],
                "bookings": counter.get(service_key, 0),
            }
        )

    extra_services = sorted(
        service_key
        for service_key in counter
        if service_key not in SERVICE_ORDER
    )

    for service_key in extra_services:
        performance.append(
            {
                "name": service_label(service_key),
                "bookings": counter[service_key],
            }
        )

    return performance


def estimated_monthly_revenue(
    bookings: list[dict[str, Any]],
) -> float:
    now = datetime.now(TIMEZONE)

    total = 0.0

    for booking in bookings:
        start = parse_booking_start(booking)

        if not start:
            continue

        if (
            start.year != now.year
            or start.month != now.month
        ):
            continue

        if normalise_text(
            booking.get("status")
        ).lower() == "cancelled":
            continue

        total += service_price(
            booking.get("service_key")
            or booking.get("service")
        )

    return round(total, 2)


def unique_customer_count(
    bookings: list[dict[str, Any]],
) -> int:
    customer_keys: set[str] = set()

    for booking in bookings:
        phone = normalise_phone(booking.get("phone"))

        if phone:
            customer_keys.add(f"phone:{phone}")
            continue

        customer_name = normalise_text(
            booking.get("customer_name")
        ).lower()

        vehicle_reg = normalise_text(
            booking.get("vehicle_reg")
        ).replace(" ", "").upper()

        if customer_name or vehicle_reg:
            customer_keys.add(
                f"name:{customer_name}|reg:{vehicle_reg}"
            )

    return len(customer_keys)


def reminder_health() -> dict[str, Any]:
    default_result = {
        "enabled": True,
        "due": 0,
        "sent_this_month": 0,
        "last_run": None,
        "status": "ready",
        "period": "this month",
    }

    try:
        from integrations.reminder_service import get_reminder_health

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

    try:
        from integrations.mot_reminders import get_reminder_summary

        summary = get_reminder_summary()

        if isinstance(summary, dict):
            return {
                **default_result,
                "due": int(
                    summary.get("due")
                    or summary.get("reminders_due")
                    or 0
                ),
                "sent_this_month": int(
                    summary.get("sent_this_month")
                    or summary.get("sent")
                    or 0
                ),
                "last_run": summary.get("last_run"),
                "status": summary.get("status") or "ready",
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

    for booking in recent_bookings[:6]:
        customer_name = (
            normalise_text(
                booking.get("customer_name")
            )
            or "Customer"
        )

        service = (
            normalise_text(
                booking.get("service")
            )
            or "garage appointment"
        )

        vehicle_reg = normalise_text(
            booking.get("vehicle_reg")
        )

        detail_parts = [service]

        if vehicle_reg and vehicle_reg != "—":
            detail_parts.append(vehicle_reg)

        activity.append(
            {
                "type": "booking",
                "title": f"Booking recorded for {customer_name}",
                "detail": " · ".join(detail_parts),
                "created_at": (
                    booking.get("created_at")
                    or booking.get("updated_at")
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
        if normalise_text(os.getenv("DVLA_API_KEY"))
        else "not configured"
    )

    vapi_status = (
        "connected"
        if (
            normalise_text(os.getenv("VAPI_API_KEY"))
            or normalise_text(os.getenv("VAPI_PRIVATE_KEY"))
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

    bookings, calendar_error = load_bookings()

    today_bookings = []

    upcoming_bookings = []

    for booking in bookings:
        start = parse_booking_start(booking)

        if not start:
            continue

        if start.date() == today:
            today_bookings.append(booking)

        if start >= now:
            upcoming_bookings.append(booking)

    upcoming_bookings.sort(
        key=lambda item: item.get("start") or ""
    )

    reminders = reminder_health()

    next_appointment = (
        upcoming_bookings[0]
        if upcoming_bookings
        else None
    )

    return {
        "summary": {
            "today_bookings": len(today_bookings),
            "upcoming_bookings": len(upcoming_bookings),
            "reminders_due": int(
                reminders.get("due") or 0
            ),
            "estimated_revenue": estimated_monthly_revenue(
                bookings
            ),
            "total_customers": unique_customer_count(
                bookings
            ),
        },
        "next_appointment": next_appointment,
        "booking_activity": booking_activity(bookings),
        "service_performance": service_performance(bookings),
        "upcoming_appointments": upcoming_bookings[:20],
        "reminders": reminders,
        "ai_activity": recent_ai_activity(bookings),
        "systems": system_health(calendar_error),
        "meta": {
            "generated_at": now.isoformat(),
            "timezone": TIMEZONE_NAME,
            "calendar_error": calendar_error,
        },
    }


@dashboard_api.get("/api/dashboard-data")
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
                    "error": "dashboard_data_failed",
                    "message": str(error),
                }
            ),
            500,
        )


@dashboard_api.get("/api/dashboard-health")
@dashboard_api_login_required
def dashboard_health():
    calendar_id = get_calendar_id()

    return jsonify(
        {
            "success": True,
            "service": "TrimTech Garage Dashboard",
            "status": "online",
            "timezone": TIMEZONE_NAME,
            "calendar_configured": bool(calendar_id),
            "generated_at": datetime.now(
                TIMEZONE
            ).isoformat(),
        }
    )

@dashboard_api.post("/api/run-reminders")
@dashboard_api_login_required
def dashboard_run_reminders():
    """
    Allow a logged-in garage owner to run the existing reminder job
    without exposing REMINDER_CRON_SECRET to browser JavaScript.

    The protected /internal/run-reminders endpoint remains available
    for the automatic external scheduler.
    """
    result = run_reminder_job()

    status_code = 200 if result.get("success") else 500

    return jsonify(result), status_code