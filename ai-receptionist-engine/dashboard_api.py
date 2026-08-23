from __future__ import annotations

"""
TrimTech shared business dashboard API.

This version supports both:

1. The existing legacy /dashboard
2. Individual onboarded business dashboards such as:

       /platform/businesses/elite-auto-centre/dashboard

Each API request resolves its business from the secure Flask session.

Important isolation rule:

An onboarded business must use its own business-specific Calendar ID.
It will NOT silently fall back to GARAGE_CALENDAR_ID or another
business's Calendar ID.

Example:

    ELITE_AUTO_CENTRE_CALENDAR_ID=...

The legacy dashboard continues to support the existing environment
variables so the current TrimTech Garage deployment remains compatible.
"""

import json
import os
from collections import Counter
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from flask import (
    Blueprint,
    g,
    jsonify,
    session,
)

from google.oauth2 import service_account
from googleapiclient.discovery import build

from dashboard_auth import (
    is_dashboard_authenticated,
)

from trimtech.modules.auth.routes import (
    BUSINESS_ID_SESSION_KEY,
    BUSINESS_USER_SESSION_KEY,
    PLATFORM_ADMIN_SESSION_KEY,
)

from trimtech.core.business import BusinessConfig
from trimtech.core.registry import (
    get_active_business,
    load_business_instance,
)

from trimtech.modules.reminders.reminder_scheduler import (
    process_reminders,
)

from trimtech.modules.crm.customer_service import (
    build_customer_records,
    customer_summary,
)

from trimtech.modules.crm.vehicle_service import (
    build_vehicle_records,
    format_registration,
    normalise_registration,
)

from trimtech.modules.reminders.reminder_scheduler import (
    get_reminder_health,
)

dashboard_api = Blueprint(
    "dashboard_api",
    __name__,
)


GOOGLE_CALENDAR_SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly"
]


# =========================================================
# Business context
# =========================================================


def normalise_text(
    value: Any,
) -> str:
    return str(
        value or ""
    ).strip()


def normalise_env_key(
    value: Any,
) -> str:
    text = normalise_text(
        value
    ).upper()

    return (
        text
        .replace("-", "_")
        .replace(" ", "_")
    )


def selected_business_id() -> str:
    return normalise_text(
        session.get(
            "dashboard_business_id"
        )
    )


def is_business_instance_request() -> bool:
    return bool(
        selected_business_id()
    )


def resolve_dashboard_business() -> BusinessConfig:
    """
    Resolve the correct business for this dashboard request.

    Individual platform dashboards use the business ID stored
    in the secure Flask session.

    The original /dashboard continues to use the active
    environment-selected business.
    """

    business_id = (
        selected_business_id()
    )

    if business_id:
        return load_business_instance(
            business_id
        )

    return get_active_business()


@dashboard_api.before_request
def load_dashboard_business_context():
    """
    Load the dashboard business once per request.

    Flask g is request-local, so one user's business context
    cannot overwrite another request's business context.
    """

    g.dashboard_business = (
        resolve_dashboard_business()
    )


def current_business() -> BusinessConfig:
    business = getattr(
        g,
        "dashboard_business",
        None,
    )

    if isinstance(
        business,
        BusinessConfig,
    ):
        return business

    return resolve_dashboard_business()


def current_timezone_name() -> str:
    return (
        current_business()
        .timezone_name
    )


def current_timezone() -> ZoneInfo:
    return (
        current_business()
        .timezone
    )


def business_instance_env_prefix() -> str:
    return normalise_env_key(
        current_business()
        .business_id
    )


def business_type_env_prefix() -> str:
    return normalise_env_key(
        current_business()
        .business_type
    )


def enabled_service_keys() -> list[str]:
    business = current_business()

    return [
        service.key
        for service
        in business.enabled_services()
    ]


# =========================================================
# Dashboard API access control
# =========================================================


def dashboard_api_access_allowed() -> bool:
    """
    Allow the correct authentication mode for each dashboard.

    Legacy /dashboard:
        Uses the original dashboard login.

    Platform admin:
        May open any onboarded business dashboard.

    Business customer:
        May only load API data for the business ID stored in
        their authenticated customer session.

    This keeps the existing Garage dashboard compatible while
    allowing secure customer dashboards to use the same API.
    """

    if is_dashboard_authenticated():
        return True

    if bool(
        session.get(
            PLATFORM_ADMIN_SESSION_KEY
        )
    ):
        return True

    if not bool(
        session.get(
            BUSINESS_USER_SESSION_KEY
        )
    ):
        return False

    customer_business_id = normalise_text(
        session.get(
            BUSINESS_ID_SESSION_KEY
        )
    )

    dashboard_business_id = (
        selected_business_id()
    )

    return bool(
        customer_business_id
        and dashboard_business_id
        and customer_business_id
        == dashboard_business_id
    )


def dashboard_api_access_required(
    view_function,
):
    """
    Protect dashboard API routes without forcing customer
    sessions through the legacy dashboard authentication.
    """

    from functools import wraps

    @wraps(view_function)
    def wrapped(*args, **kwargs):
        if dashboard_api_access_allowed():
            return view_function(
                *args,
                **kwargs,
            )

        return (
            jsonify(
                {
                    "success": False,
                    "error": (
                        "dashboard_access_denied"
                    ),
                    "message": (
                        "You do not have access "
                        "to this dashboard."
                    ),
                }
            ),
            403,
        )

    return wrapped


# =========================================================
# Business labels / services
# =========================================================


def normalise_phone(
    value: Any,
) -> str:
    phone = normalise_text(
        value
    )

    if phone.lower().startswith(
        "whatsapp:"
    ):
        phone = phone.split(
            ":",
            1,
        )[1]

    phone = (
        phone
        .replace(" ", "")
        .replace("-", "")
        .replace("(", "")
        .replace(")", "")
    )

    if phone.startswith("+44"):
        return "0" + phone[3:]

    if (
        phone.startswith("44")
        and len(phone) >= 12
    ):
        return "0" + phone[2:]

    return phone


def normalise_service(
    value: Any,
) -> str:
    business = current_business()

    service = (
        business.resolve_service(
            value
        )
    )

    if service:
        return service.key

    fallback = (
        normalise_text(
            value
        )
        .lower()
    )

    return (
        fallback
        or "appointment"
    )


def service_label(
    value: Any,
) -> str:
    return (
        current_business()
        .service_label(value)
    )


def service_price(
    value: Any,
) -> float:
    try:
        return float(
            current_business()
            .service_price(value)
        )

    except (
        TypeError,
        ValueError,
        KeyError,
    ):
        return 0.0


def default_booking_label() -> str:
    business = current_business()

    value = normalise_text(
        business.metadata.get(
            "booking_label"
        )
    )

    if value:
        return value

    return "Appointment"


def default_customer_label() -> str:
    business = current_business()

    value = normalise_text(
        business.metadata.get(
            "customer_label"
        )
    )

    if value:
        return value

    return "Customer"


def default_vehicle_label() -> str:
    business = current_business()

    value = normalise_text(
        business.metadata.get(
            "vehicle_label"
        )
    )

    if value:
        return value

    return "Vehicle"


# =========================================================
# Business-specific environment configuration
# =========================================================


def get_calendar_id() -> str:
    """
    Resolve the Calendar ID safely.

    For an onboarded business:

        ELITE_AUTO_CENTRE_CALENDAR_ID

    is required.

    We deliberately do not fall back to GARAGE_CALENDAR_ID,
    GOOGLE_CALENDAR_ID, etc. for an individual business,
    because doing so could expose another customer's data.

    The original /dashboard keeps the old fallback behaviour.
    """

    business = current_business()

    metadata_calendar_id = (
        normalise_text(
            business.metadata.get(
                "calendar_id"
            )
        )
    )

    if metadata_calendar_id:
        return metadata_calendar_id

    instance_prefix = (
        business_instance_env_prefix()
    )

    instance_calendar_id = (
        normalise_text(
            os.getenv(
                f"{instance_prefix}_CALENDAR_ID"
            )
        )
    )

    if instance_calendar_id:
        return instance_calendar_id

    if is_business_instance_request():
        return ""

    type_prefix = (
        business_type_env_prefix()
    )

    possible_values = [
        os.getenv(
            f"{type_prefix}_CALENDAR_ID"
        ),
        os.getenv(
            "TRIMTECH_CALENDAR_ID"
        ),
        os.getenv(
            "GOOGLE_CALENDAR_ID"
        ),
        os.getenv(
            "CALENDAR_ID"
        ),
    ]

    for value in possible_values:
        calendar_id = (
            normalise_text(
                value
            )
        )

        if calendar_id:
            return calendar_id

    return ""


def load_google_credentials():
    """
    Service-account credentials may be shared across businesses.

    Data separation is controlled primarily by each business's
    unique Calendar ID.

    A business-specific service account can also be supplied:

        ELITE_AUTO_CENTRE_GOOGLE_SERVICE_ACCOUNT_JSON

    Otherwise the existing shared Google credentials are used.
    """

    instance_prefix = (
        business_instance_env_prefix()
    )

    business_credentials = (
        normalise_text(
            os.getenv(
                (
                    f"{instance_prefix}_"
                    "GOOGLE_SERVICE_ACCOUNT_JSON"
                )
            )
        )
    )

    raw_credentials = (
        business_credentials
        or normalise_text(
            os.getenv(
                "GOOGLE_SERVICE_ACCOUNT_JSON"
            )
        )
    )

    if raw_credentials:
        credentials_info = (
            json.loads(
                raw_credentials
            )
        )

        return (
            service_account
            .Credentials
            .from_service_account_info(
                credentials_info,
                scopes=(
                    GOOGLE_CALENDAR_SCOPES
                ),
            )
        )

    business_credentials_path = (
        normalise_text(
            os.getenv(
                (
                    f"{instance_prefix}_"
                    "GOOGLE_APPLICATION_CREDENTIALS"
                )
            )
        )
    )

    credentials_path = (
        business_credentials_path
        or normalise_text(
            os.getenv(
                "GOOGLE_APPLICATION_CREDENTIALS"
            )
        )
    )

    if not credentials_path:
        local_credentials_path = (
            os.path.join(
                os.path.dirname(
                    os.path.abspath(
                        __file__
                    )
                ),
                "credential.json",
            )
        )

        if os.path.exists(
            local_credentials_path
        ):
            credentials_path = (
                local_credentials_path
            )

    if (
        credentials_path
        and os.path.exists(
            credentials_path
        )
    ):
        return (
            service_account
            .Credentials
            .from_service_account_file(
                credentials_path,
                scopes=(
                    GOOGLE_CALENDAR_SCOPES
                ),
            )
        )

    raise RuntimeError(
        "Google Calendar credentials were not found."
    )


def get_calendar_service():
    credentials = (
        load_google_credentials()
    )

    return build(
        "calendar",
        "v3",
        credentials=credentials,
        cache_discovery=False,
    )


# =========================================================
# Calendar helpers
# =========================================================


def iso_utc(
    value: datetime,
) -> str:
    return (
        value
        .astimezone(
            ZoneInfo("UTC")
        )
        .isoformat()
        .replace(
            "+00:00",
            "Z",
        )
    )


def parse_event_datetime(
    event_value: (
        dict[str, Any]
        | None
    ),
) -> datetime | None:
    if not event_value:
        return None

    timezone = (
        current_timezone()
    )

    date_time_value = (
        normalise_text(
            event_value.get(
                "dateTime"
            )
        )
    )

    if date_time_value:
        try:
            parsed = (
                datetime
                .fromisoformat(
                    date_time_value
                    .replace(
                        "Z",
                        "+00:00",
                    )
                )
            )

            if parsed.tzinfo is None:
                parsed = (
                    parsed.replace(
                        tzinfo=timezone
                    )
                )

            return (
                parsed.astimezone(
                    timezone
                )
            )

        except ValueError:
            return None

    date_value = (
        normalise_text(
            event_value.get(
                "date"
            )
        )
    )

    if date_value:
        try:
            parsed_date = (
                datetime.strptime(
                    date_value,
                    "%Y-%m-%d",
                )
            )

            return (
                parsed_date.replace(
                    tzinfo=timezone
                )
            )

        except ValueError:
            return None

    return None


def event_private_properties(
    event: dict[str, Any],
) -> dict[str, Any]:
    extended_properties = (
        event.get(
            "extendedProperties"
        )
        or {}
    )

    private_properties = (
        extended_properties.get(
            "private"
        )
        or {}
    )

    return (
        private_properties
        if isinstance(
            private_properties,
            dict,
        )
        else {}
    )


def read_event_field(
    event: dict[str, Any],
    private_properties: (
        dict[str, Any]
    ),
    *field_names: str,
) -> str:
    for field_name in field_names:
        value = (
            normalise_text(
                private_properties.get(
                    field_name
                )
            )
        )

        if value:
            return value

    description = (
        normalise_text(
            event.get(
                "description"
            )
        )
    )

    wanted = {
        field_name
        .strip()
        .lower()
        .replace(" ", "_")
        .replace("-", "_")
        for field_name
        in field_names
    }

    for line in (
        description.splitlines()
    ):
        (
            line_key,
            separator,
            line_value,
        ) = line.partition(":")

        if not separator:
            continue

        normalised_line_key = (
            line_key
            .strip()
            .lower()
            .replace(" ", "_")
            .replace("-", "_")
        )

        if (
            normalised_line_key
            in wanted
        ):
            value = (
                normalise_text(
                    line_value
                )
            )

            if value:
                return value

    return ""


def parse_summary_fallback(
    summary: str,
) -> dict[str, str]:
    business = current_business()

    result = {
        "customer_name": "",
        "service": "",
        "vehicle_reg": "",
    }

    clean_summary = (
        normalise_text(
            summary
        )
    )

    if not clean_summary:
        return result

    separators = [
        " - ",
        " | ",
        " – ",
    ]

    parts = [
        clean_summary
    ]

    for separator in separators:
        if separator in clean_summary:
            parts = [
                part.strip()
                for part
                in clean_summary.split(
                    separator
                )
                if part.strip()
            ]
            break

    for part in parts:
        part_lower = (
            part.lower()
        )

        if business.resolve_service(
            part_lower
        ):
            result[
                "service"
            ] = part
            continue

        if business.feature_enabled(
            "vehicles"
        ):
            registration = (
                normalise_registration(
                    part
                )
            )

            if (
                5 <= len(
                    registration
                ) <= 8
                and any(
                    character.isdigit()
                    for character
                    in registration
                )
                and any(
                    character.isalpha()
                    for character
                    in registration
                )
            ):
                result[
                    "vehicle_reg"
                ] = registration
                continue

        if not result[
            "customer_name"
        ]:
            result[
                "customer_name"
            ] = part

    return result


# =========================================================
# Calendar event → booking
# =========================================================


def event_to_booking(
    event: dict[str, Any],
) -> dict[str, Any] | None:
    business = current_business()

    if (
        normalise_text(
            event.get(
                "status"
            )
        ).lower()
        == "cancelled"
    ):
        return None

    start = (
        parse_event_datetime(
            event.get(
                "start"
            )
        )
    )

    end = (
        parse_event_datetime(
            event.get(
                "end"
            )
        )
    )

    if not start:
        return None

    private_properties = (
        event_private_properties(
            event
        )
    )

    summary_fallback = (
        parse_summary_fallback(
            normalise_text(
                event.get(
                    "summary"
                )
            )
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
        or summary_fallback[
            "customer_name"
        ]
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

    raw_registration = ""

    if business.feature_enabled(
        "vehicles"
    ):
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
            or summary_fallback[
                "vehicle_reg"
            ]
        )

    registration_key = ""

    if raw_registration:
        registration_key = (
            normalise_registration(
                raw_registration
            )
        )

    service = (
        read_event_field(
            event,
            private_properties,
            "service",
            "service_key",
            "service_name",
        )
        or summary_fallback[
            "service"
        ]
    )

    service_key = (
        normalise_service(
            service
        )
    )

    status = (
        read_event_field(
            event,
            private_properties,
            "booking_status",
            "status",
        )
        or "confirmed"
    )

    make = ""
    model = ""
    colour = ""
    year = ""
    fuel_type = ""
    mot_status = ""
    mot_expiry_date = ""

    if business.feature_enabled(
        "vehicles"
    ):
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

        mot_expiry_date = (
            read_event_field(
                event,
                private_properties,
                "mot_expiry_date",
                "mot_expiry",
            )
        )

    return {
        "event_id": (
            normalise_text(
                event.get(
                    "id"
                )
            )
        ),
        "customer_name": (
            customer_name
            or default_customer_label()
        ),
        "phone": (
            normalise_phone(
                phone
            )
        ),
        "email": email,
        "vehicle_reg": (
            format_registration(
                registration_key
            )
            if registration_key
            else "—"
        ),
        "registration_key": (
            registration_key
        ),
        "make": make,
        "model": model,
        "colour": colour,
        "year": year,
        "fuel_type": fuel_type,
        "mot_status": mot_status,
        "mot_expiry_date": (
            mot_expiry_date
        ),
        "service": (
            service_label(
                service_key
            )
        ),
        "service_key": (
            service_key
        ),
        "price": (
            service_price(
                service_key
            )
        ),
        "start": (
            start.isoformat()
        ),
        "end": (
            end.isoformat()
            if end
            else None
        ),
        "status": (
            status.lower()
        ),
        "notes": (
            normalise_text(
                event.get(
                    "description"
                )
            )
        ),
        "calendar_link": (
            normalise_text(
                event.get(
                    "htmlLink"
                )
            )
        ),
        "created_at": (
            normalise_text(
                event.get(
                    "created"
                )
            )
        ),
        "updated_at": (
            normalise_text(
                event.get(
                    "updated"
                )
            )
        ),
    }


def fetch_calendar_events(
    time_min: datetime,
    time_max: datetime,
) -> list[dict[str, Any]]:
    calendar_id = (
        get_calendar_id()
    )

    if not calendar_id:
        if is_business_instance_request():
            required_name = (
                f"{business_instance_env_prefix()}"
                "_CALENDAR_ID"
            )

            raise RuntimeError(
                f"{required_name} is not configured."
            )

        raise RuntimeError(
            "Calendar ID is not configured."
        )

    calendar_service = (
        get_calendar_service()
    )

    events: list[
        dict[str, Any]
    ] = []

    page_token: str | None = None

    while True:
        response = (
            calendar_service
            .events()
            .list(
                calendarId=(
                    calendar_id
                ),
                timeMin=(
                    iso_utc(
                        time_min
                    )
                ),
                timeMax=(
                    iso_utc(
                        time_max
                    )
                ),
                singleEvents=True,
                orderBy="startTime",
                maxResults=2500,
                pageToken=(
                    page_token
                ),
            )
            .execute()
        )

        page_events = (
            response.get(
                "items"
            )
            or []
        )

        if isinstance(
            page_events,
            list,
        ):
            events.extend(
                page_events
            )

        page_token = (
            response.get(
                "nextPageToken"
            )
        )

        if not page_token:
            break

    return events


def load_bookings() -> tuple[
    list[dict[str, Any]],
    str | None,
]:
    timezone = (
        current_timezone()
    )

    now = datetime.now(
        timezone
    )

    try:
        history_days = int(
            os.getenv(
                "DASHBOARD_HISTORY_DAYS",
                "730",
            )
        )
    except ValueError:
        history_days = 730

    try:
        future_days = int(
            os.getenv(
                "DASHBOARD_FUTURE_DAYS",
                "365",
            )
        )
    except ValueError:
        future_days = 365

    range_start = (
        now
        - timedelta(
            days=history_days
        )
    ).replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )

    range_end = (
        now
        + timedelta(
            days=future_days
        )
    ).replace(
        hour=23,
        minute=59,
        second=59,
        microsecond=999999,
    )

    try:
        raw_events = (
            fetch_calendar_events(
                range_start,
                range_end,
            )
        )

        bookings: list[
            dict[str, Any]
        ] = []

        for event in raw_events:
            booking = (
                event_to_booking(
                    event
                )
            )

            if booking:
                bookings.append(
                    booking
                )

        bookings.sort(
            key=lambda item: (
                item.get(
                    "start"
                )
                or ""
            )
        )

        return bookings, None

    except Exception as error:
        print(
            "DASHBOARD CALENDAR ERROR:",
            {
                "business_id": (
                    current_business()
                    .business_id
                ),
                "error": repr(
                    error
                ),
            },
        )

        return [], str(error)


# =========================================================
# Booking helpers
# =========================================================


def parse_booking_start(
    booking: dict[str, Any],
) -> datetime | None:
    timezone = (
        current_timezone()
    )

    value = (
        normalise_text(
            booking.get(
                "start"
            )
        )
    )

    if not value:
        return None

    try:
        parsed = (
            datetime.fromisoformat(
                value.replace(
                    "Z",
                    "+00:00",
                )
            )
        )

        if parsed.tzinfo is None:
            parsed = (
                parsed.replace(
                    tzinfo=timezone
                )
            )

        return (
            parsed.astimezone(
                timezone
            )
        )

    except ValueError:
        return None


def is_cancelled(
    booking: dict[str, Any],
) -> bool:
    return (
        "cancel"
        in normalise_text(
            booking.get(
                "status"
            )
        ).lower()
    )


def booking_value(
    booking: dict[str, Any],
) -> float:
    try:
        return float(
            booking.get(
                "price"
            )
            or service_price(
                booking.get(
                    "service_key"
                )
                or booking.get(
                    "service"
                )
            )
        )

    except (
        TypeError,
        ValueError,
    ):
        return 0.0


# =========================================================
# Dashboard analytics
# =========================================================


def booking_activity(
    bookings: list[
        dict[str, Any]
    ],
) -> list[dict[str, Any]]:
    timezone = (
        current_timezone()
    )

    now = datetime.now(
        timezone
    )

    today = now.date()

    activity = []

    for offset in range(
        6,
        -1,
        -1,
    ):
        target_date = (
            today
            - timedelta(
                days=offset
            )
        )

        count = 0

        for booking in bookings:
            start = (
                parse_booking_start(
                    booking
                )
            )

            if (
                start
                and start.date()
                == target_date
                and not is_cancelled(
                    booking
                )
            ):
                count += 1

        activity.append(
            {
                "date": (
                    target_date
                    .isoformat()
                ),
                "count": count,
            }
        )

    return activity


def service_performance(
    bookings: list[
        dict[str, Any]
    ],
) -> list[dict[str, Any]]:
    business = (
        current_business()
    )

    timezone = (
        current_timezone()
    )

    now = datetime.now(
        timezone
    )

    thirty_days_ago = (
        now
        - timedelta(
            days=30
        )
    )

    counter: Counter[str] = (
        Counter()
    )

    for booking in bookings:
        start = (
            parse_booking_start(
                booking
            )
        )

        if (
            not start
            or start
            < thirty_days_ago
            or is_cancelled(
                booking
            )
        ):
            continue

        service_key = (
            normalise_service(
                booking.get(
                    "service_key"
                )
                or booking.get(
                    "service"
                )
            )
        )

        counter[
            service_key
        ] += 1

    performance = []

    configured_service_keys = (
        enabled_service_keys()
    )

    for service in (
        business.enabled_services()
    ):
        performance.append(
            {
                "name": (
                    service.name
                ),
                "bookings": (
                    counter.get(
                        service.key,
                        0,
                    )
                ),
            }
        )

    extra_services = sorted(
        service_key
        for service_key
        in counter
        if (
            service_key
            not in configured_service_keys
        )
    )

    for service_key in (
        extra_services
    ):
        performance.append(
            {
                "name": (
                    service_label(
                        service_key
                    )
                ),
                "bookings": (
                    counter[
                        service_key
                    ]
                ),
            }
        )

    return performance


def revenue_summary(
    bookings: list[
        dict[str, Any]
    ],
) -> dict[str, Any]:
    timezone = (
        current_timezone()
    )

    now = datetime.now(
        timezone
    )

    today = now.date()

    week_start = (
        today
        - timedelta(
            days=(
                today.weekday()
            )
        )
    )

    year_start = datetime(
        now.year,
        1,
        1,
        tzinfo=timezone,
    )

    active = [
        booking
        for booking
        in bookings
        if not is_cancelled(
            booking
        )
    ]

    def total_for(
        predicate,
    ) -> float:
        total = 0.0

        for booking in active:
            start = (
                parse_booking_start(
                    booking
                )
            )

            if (
                start
                and predicate(
                    start
                )
            ):
                total += (
                    booking_value(
                        booking
                    )
                )

        return round(
            total,
            2,
        )

    today_total = (
        total_for(
            lambda value: (
                value.date()
                == today
            )
        )
    )

    week_total = (
        total_for(
            lambda value: (
                week_start
                <= value.date()
                <= today
            )
        )
    )

    month_total = (
        total_for(
            lambda value: (
                value.year
                == now.year
                and value.month
                == now.month
            )
        )
    )

    year_total = (
        total_for(
            lambda value: (
                value
                >= year_start
                and value
                <= now
            )
        )
    )

    lifetime_total = round(
        sum(
            booking_value(
                booking
            )
            for booking
            in active
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
        for booking
        in active
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
            booking_value(
                booking
            )
            for booking
            in active
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

    for month_offset in range(
        5,
        -1,
        -1,
    ):
        target_month = (
            now.month
            - month_offset
        )

        target_year = now.year

        while target_month <= 0:
            target_month += 12
            target_year -= 1

        total = (
            total_for(
                lambda value,
                target_year=target_year,
                target_month=target_month: (
                    value.year
                    == target_year
                    and value.month
                    == target_month
                )
            )
        )

        label = (
            datetime(
                target_year,
                target_month,
                1,
                tzinfo=timezone,
            )
            .strftime("%b")
        )

        monthly_breakdown.append(
            {
                "year": (
                    target_year
                ),
                "month": (
                    target_month
                ),
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
        "future_pipeline": (
            future_pipeline
        ),
        "average_booking_value": (
            round(
                (
                    lifetime_total
                    / completed_count
                )
                if completed_count
                else 0.0,
                2,
            )
        ),
        "completed_booking_count": (
            completed_count
        ),
        "monthly_breakdown": (
            monthly_breakdown
        ),
    }


def analytics_summary(
    bookings: list[
        dict[str, Any]
    ],
    customers: list[
        dict[str, Any]
    ],
    vehicles: list[
        dict[str, Any]
    ],
) -> dict[str, Any]:
    business = (
        current_business()
    )

    total_bookings = len(
        bookings
    )

    cancelled = sum(
        1
        for booking
        in bookings
        if is_cancelled(
            booking
        )
    )

    active_bookings = (
        total_bookings
        - cancelled
    )

    service_counter = Counter(
        normalise_text(
            booking.get(
                "service"
            )
        )
        for booking
        in bookings
        if not is_cancelled(
            booking
        )
    )

    popular_service = (
        service_counter
        .most_common(1)[0][0]
        if service_counter
        else ""
    )

    vehicle_visit_leader = None

    if (
        business.feature_enabled(
            "vehicles"
        )
        and vehicles
    ):
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
        for customer
        in customers
        if int(
            customer.get(
                "completed_visit_count"
            )
            or 0
        )
        >= 2
    )

    return {
        "total_bookings": (
            total_bookings
        ),
        "active_bookings": (
            active_bookings
        ),
        "cancelled_bookings": (
            cancelled
        ),
        "cancellation_rate": (
            round(
                (
                    cancelled
                    / total_bookings
                    * 100
                )
                if total_bookings
                else 0.0,
                1,
            )
        ),
        "total_customers": len(
            customers
        ),
        "repeat_customers": (
            repeat_customers
        ),
        "repeat_customer_rate": (
            round(
                (
                    repeat_customers
                    / len(
                        customers
                    )
                    * 100
                )
                if customers
                else 0.0,
                1,
            )
        ),
        "total_vehicles": (
            len(vehicles)
        ),
        "popular_service": (
            popular_service
        ),
        "most_visited_vehicle": (
            {
                "registration": (
                    vehicle_visit_leader
                    .get(
                        "registration"
                    )
                ),
                "booking_count": (
                    int(
                        vehicle_visit_leader
                        .get(
                            "booking_count"
                        )
                        or 0
                    )
                ),
            }
            if vehicle_visit_leader
            else None
        ),
    }


# =========================================================
# Reminder health
# =========================================================


def default_reminder_health() -> dict[str, Any]:
    return {
        "enabled": (
            current_business()
            .feature_enabled(
                "reminders"
            )
        ),
        "due": 0,
        "waiting": 0,
        "sent_this_month": 0,
        "failed": 0,
        "last_run": None,
        "status": "ready",
        "period": "this month",
        "queue": [],
    }


def reminder_health() -> dict[str, Any]:
    """
    Return reminder health for the currently resolved business.

    Reminder scheduling is now business-aware, so both the legacy
    TrimTech Garage dashboard and onboarded business dashboards use
    the shared reminder health service with isolated business context.
    """

    default_result = default_reminder_health()

    if not current_business().feature_enabled(
        "reminders"
    ):
        return {
            **default_result,
            "enabled": False,
            "status": "disabled",
        }

    try:
        business = current_business()

        health = get_reminder_health(
            business_id=business.business_id,
        )

        if isinstance(
            health,
            dict,
        ):
            return {
                **default_result,
                **health,
                "enabled": True,
            }

    except Exception as error:
        print(
            "DASHBOARD REMINDER HEALTH ERROR:",
            {
                "business_id": (
                    current_business()
                    .business_id
                ),
                "error": repr(error),
            },
        )

        return {
            **default_result,
            "status": "error",
        }

    return default_result


# =========================================================
# AI activity
# =========================================================


def recent_ai_activity(
    bookings: list[
        dict[str, Any]
    ],
) -> list[dict[str, Any]]:
    activity = []

    recent_bookings = sorted(
        bookings,
        key=lambda item: (
            item.get(
                "created_at"
            )
            or item.get(
                "updated_at"
            )
            or item.get(
                "start"
            )
            or ""
        ),
        reverse=True,
    )

    for booking in (
        recent_bookings[:10]
    ):
        customer_name = (
            normalise_text(
                booking.get(
                    "customer_name"
                )
            )
            or default_customer_label()
        )

        service = (
            normalise_text(
                booking.get(
                    "service"
                )
            )
            or default_booking_label()
            .lower()
        )

        vehicle_reg = (
            normalise_text(
                booking.get(
                    "vehicle_reg"
                )
            )
        )

        detail_parts = [
            service
        ]

        if (
            current_business()
            .feature_enabled(
                "vehicles"
            )
            and vehicle_reg
            and vehicle_reg
            != "—"
        ):
            detail_parts.append(
                vehicle_reg
            )

        activity.append(
            {
                "type": "booking",
                "title": (
                    "Booking recorded for "
                    f"{customer_name}"
                ),
                "detail": (
                    " · ".join(
                        detail_parts
                    )
                ),
                "created_at": (
                    booking.get(
                        "created_at"
                    )
                    or booking.get(
                        "updated_at"
                    )
                    or booking.get(
                        "start"
                    )
                ),
            }
        )

    return activity


# =========================================================
# System health
# =========================================================


def business_specific_env(
    suffix: str,
) -> str:
    prefix = (
        business_instance_env_prefix()
    )

    return normalise_text(
        os.getenv(
            f"{prefix}_{suffix}"
        )
    )


def system_health(
    calendar_error: str | None,
) -> dict[str, str]:
    business = (
        current_business()
    )

    calendar_status = (
        "connected"
        if (
            get_calendar_id()
            and not calendar_error
        )
        else "not configured"
        if not get_calendar_id()
        else "error"
    )

    if not business.feature_enabled(
        "dvla"
    ):
        dvla_status = "disabled"

    elif (
        business_specific_env(
            "DVLA_API_KEY"
        )
        or normalise_text(
            os.getenv(
                "DVLA_API_KEY"
            )
        )
    ):
        dvla_status = "connected"

    else:
        dvla_status = (
            "not configured"
        )

    if not business.feature_enabled(
        "voice_agent"
    ):
        vapi_status = "disabled"

    elif (
        business_specific_env(
            "VAPI_API_KEY"
        )
        or business_specific_env(
            "VAPI_PRIVATE_KEY"
        )
        or (
            not is_business_instance_request()
            and (
                normalise_text(
                    os.getenv(
                        "VAPI_API_KEY"
                    )
                )
                or normalise_text(
                    os.getenv(
                        "VAPI_PRIVATE_KEY"
                    )
                )
            )
        )
    ):
        vapi_status = "connected"

    else:
        vapi_status = (
            "not configured"
        )

    important_statuses = [
        calendar_status,
        vapi_status,
        dvla_status,
    ]

    overall = (
        "operational"
        if all(
            status
            in {
                "connected",
                "disabled",
            }
            for status
            in important_statuses
        )
        else "attention"
    )

    return {
        "overall": overall,
        "vapi": vapi_status,
        "calendar": (
            calendar_status
        ),
        "dvla": dvla_status,
        "backend": "connected",
    }


# =========================================================
# Dashboard payload
# =========================================================


def dashboard_ui_config() -> dict[str, Any]:
    business = (
        current_business()
    )

    return {
        "dashboard_title": (
            business.metadata.get(
                "dashboard_title",
                (
                    f"{business.business_name} "
                    "Dashboard"
                ),
            )
        ),
        "booking_label": (
            default_booking_label()
        ),
        "customer_label": (
            default_customer_label()
        ),
        "vehicle_label": (
            default_vehicle_label()
        ),
        "currency_symbol": (
            business.currency_symbol
        ),
        "features": (
            business.features.to_dict()
        ),
    }


def build_dashboard_data() -> dict[str, Any]:
    business = (
        current_business()
    )

    timezone = (
        current_timezone()
    )

    now = datetime.now(
        timezone
    )

    today = now.date()

    bookings, calendar_error = (
        load_bookings()
    )

    today_bookings = []
    upcoming_bookings = []

    for booking in bookings:
        start = (
            parse_booking_start(
                booking
            )
        )

        if not start:
            continue

        if (
            start.date()
            == today
            and not is_cancelled(
                booking
            )
        ):
            today_bookings.append(
                booking
            )

        if (
            start >= now
            and not is_cancelled(
                booking
            )
        ):
            upcoming_bookings.append(
                booking
            )

    upcoming_bookings.sort(
        key=lambda item: (
            item.get(
                "start"
            )
            or ""
        )
    )

    customers = (
        build_customer_records(
            bookings,
            now=now,
            service_price_resolver=(
                service_price
            ),
        )
        if business.feature_enabled(
            "crm"
        )
        else []
    )

    vehicles = (
        build_vehicle_records(
            bookings,
            now=now,
            service_price_resolver=(
                service_price
            ),
        )
        if business.feature_enabled(
            "vehicles"
        )
        else []
    )

    customer_totals = (
        customer_summary(
            customers
        )
    )

    revenue = (
        revenue_summary(
            bookings
        )
    )

    analytics = (
        analytics_summary(
            bookings,
            customers,
            vehicles,
        )
    )

    reminders = (
        reminder_health()
    )

    next_appointment = (
        upcoming_bookings[0]
        if upcoming_bookings
        else None
    )

    return {
        "business": (
            business.to_dict()
        ),
        "ui": (
            dashboard_ui_config()
        ),
        "features": (
            business.features.to_dict()
        ),
        "summary": {
            "today_bookings": len(
                today_bookings
            ),
            "upcoming_bookings": len(
                upcoming_bookings
            ),
            "reminders_due": int(
                reminders.get(
                    "due"
                )
                or 0
            ),
            "estimated_revenue": (
                revenue[
                    "this_month"
                ]
            ),
            "total_customers": len(
                customers
            ),
            "total_vehicles": len(
                vehicles
            ),
            "repeat_customers": (
                customer_totals.get(
                    "repeat_customers",
                    0,
                )
            ),
            "revenue_period": (
                "This month"
            ),
        },
        "next_appointment": (
            next_appointment
        ),
        "booking_activity": (
            booking_activity(
                bookings
            )
        ),
        "service_performance": (
            service_performance(
                bookings
            )
        ),
        "upcoming_appointments": (
            upcoming_bookings[
                :100
            ]
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
            recent_ai_activity(
                bookings
            )
        ),
        "systems": (
            system_health(
                calendar_error
            )
        ),
        "meta": {
            "generated_at": (
                now.isoformat()
            ),
            "timezone": (
                business.timezone_name
            ),
            "business_id": (
                business.business_id
            ),
            "business_type": (
                business.business_type
            ),
            "business_name": (
                business.business_name
            ),
            "business_instance": (
                is_business_instance_request()
            ),
            "calendar_configured": bool(
                get_calendar_id()
            ),
            "calendar_error": (
                calendar_error
            ),
            "history_booking_count": (
                len(bookings)
            ),
        },
    }


# =========================================================
# API routes
# =========================================================


@dashboard_api.get(
    "/api/dashboard-data"
)
@dashboard_api_access_required
def dashboard_data():
    try:
        data = (
            build_dashboard_data()
        )

        return jsonify(
            {
                "success": True,
                "data": data,
            }
        )

    except Exception as error:
        print(
            "DASHBOARD API ERROR:",
            {
                "business_id": (
                    selected_business_id()
                    or "legacy"
                ),
                "error": repr(
                    error
                ),
            },
        )

        return (
            jsonify(
                {
                    "success": False,
                    "error": (
                        "dashboard_data_failed"
                    ),
                    "message": (
                        str(error)
                    ),
                }
            ),
            500,
        )


@dashboard_api.get(
    "/api/business"
)
@dashboard_api_access_required
def dashboard_business():
    business = (
        current_business()
    )

    return jsonify(
        {
            "success": True,
            "business": (
                business.to_dict()
            ),
            "ui": (
                dashboard_ui_config()
            ),
        }
    )


@dashboard_api.get(
    "/api/dashboard-health"
)
@dashboard_api_access_required
def dashboard_health():
    business = (
        current_business()
    )

    timezone = (
        current_timezone()
    )

    calendar_id = (
        get_calendar_id()
    )

    return jsonify(
        {
            "success": True,
            "service": (
                f"{business.business_name} "
                "Dashboard"
            ),
            "business_id": (
                business.business_id
            ),
            "business_type": (
                business.business_type
            ),
            "business_name": (
                business.business_name
            ),
            "business_instance": (
                is_business_instance_request()
            ),
            "status": "online",
            "timezone": (
                business.timezone_name
            ),
            "calendar_configured": bool(
                calendar_id
            ),
            "required_calendar_env": (
                (
                    f"{business_instance_env_prefix()}"
                    "_CALENDAR_ID"
                )
                if is_business_instance_request()
                else None
            ),
            "generated_at": (
                datetime.now(
                    timezone
                ).isoformat()
            ),
        }
    )


@dashboard_api.post(
    "/api/run-reminders"
)
@dashboard_api_access_required
def dashboard_run_reminders():
    """
    Keep the existing Garage reminder runner working.

    Individual onboarded businesses are blocked here until the
    reminder scheduler itself has business-scoped storage/calendar
    support. This prevents Elite Auto Centre from accidentally
    running TrimTech Garage reminders.
    """

    business = (
        current_business()
    )

    if not business.feature_enabled(
        "reminders"
    ):
        return (
            jsonify(
                {
                    "success": False,
                    "error": (
                        "reminders_disabled"
                    ),
                    "message": (
                        "Reminders are disabled "
                        "for this business."
                    ),
                }
            ),
            409,
        )

    if is_business_instance_request():
        return (
            jsonify(
                {
                    "success": False,
                    "error": (
                        "business_reminders_"
                        "not_configured"
                    ),
                    "business_id": (
                        business.business_id
                    ),
                    "message": (
                        "Business-specific reminder "
                        "processing has not been "
                        "configured yet."
                    ),
                }
            ),
            409,
        )

    try:
        result = (
            process_reminders()
        )

    except Exception as error:
        print(
            "DASHBOARD REMINDER RUN ERROR:",
            repr(error),
        )

        return (
            jsonify(
                {
                    "success": False,
                    "error": (
                        "reminder_run_failed"
                    ),
                    "message": (
                        str(error)
                    ),
                }
            ),
            500,
        )

    status_code = (
        200
        if result.get(
            "success"
        )
        else 500
    )

    return (
        jsonify(result),
        status_code,
    )