from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta
from typing import Any

from integrations.garage_calendar import (
    _calendar_id,
    _get_calendar_service,
    normalise_phone,
)
from integrations.garage_config import SERVICES, TIMEZONE


DEFAULT_REPORT_DAYS = 30
MAX_REPORT_DAYS = 366

COMPLETED_VALUES = {
    "1",
    "complete",
    "completed",
    "done",
    "true",
    "yes",
}

TRUE_VALUES = {
    "1",
    "true",
    "yes",
    "done",
    "completed",
}

CANCELLED_VALUES = {
    "1",
    "cancelled",
    "canceled",
    "true",
    "yes",
}

NO_SHOW_VALUES = {
    "1",
    "no show",
    "no-show",
    "no_show",
    "true",
    "yes",
}

REVENUE_KEYS = (
    "amount_paid",
    "total_paid",
    "price",
    "service_price",
    "booking_value",
    "revenue",
    "amount",
)

REGISTRATION_KEYS = (
    "registration",
    "vehicle_reg",
    "reg",
)

PHONE_KEYS = (
    "phone",
    "customer_phone",
    "telephone",
)

CUSTOMER_NAME_KEYS = (
    "customer_name",
    "name",
)

SERVICE_KEYS = (
    "service",
    "service_key",
    "appointment_type",
)


def _now() -> datetime:
    return datetime.now(TIMEZONE)


def _is_true(value: Any) -> bool:
    return str(value or "").strip().lower() in TRUE_VALUES


def _is_completed(value: Any) -> bool:
    return str(value or "").strip().lower() in COMPLETED_VALUES


def _is_cancelled(value: Any) -> bool:
    return str(value or "").strip().lower() in CANCELLED_VALUES


def _is_no_show(value: Any) -> bool:
    return str(value or "").strip().lower() in NO_SHOW_VALUES


def _first_value(
    data: dict[str, Any],
    keys: tuple[str, ...],
    default: str = "",
) -> str:
    for key in keys:
        value = data.get(key)

        if value is not None and str(value).strip():
            return str(value).strip()

    return default


def _private_data(event: dict[str, Any]) -> dict[str, Any]:
    return (
        (event.get("extendedProperties") or {})
        .get("private")
        or {}
    )


def _parse_datetime(value: Any) -> datetime | None:
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


def _event_datetime(
    event: dict[str, Any],
    field: str,
) -> datetime | None:
    event_time = event.get(field) or {}

    date_time_value = event_time.get("dateTime")

    if date_time_value:
        return _parse_datetime(date_time_value)

    date_value = str(
        event_time.get("date") or ""
    ).strip()

    if not date_value:
        return None

    try:
        parsed_date = date.fromisoformat(date_value)
    except ValueError:
        return None

    return datetime.combine(
        parsed_date,
        time.min,
        tzinfo=TIMEZONE,
    )


def _service_label(service_key: str) -> str:
    cleaned_key = str(
        service_key or ""
    ).strip().lower()

    service = SERVICES.get(cleaned_key) or {}

    return str(
        service.get("label")
        or cleaned_key.replace("_", " ").title()
        or "Garage Appointment"
    )


def _clean_registration(
    registration: str,
) -> str:
    return "".join(
        character
        for character in str(
            registration or ""
        ).upper()
        if character.isalnum()
    )


def _display_registration(
    registration: str,
) -> str:
    cleaned = _clean_registration(
        registration
    )

    if len(cleaned) > 3:
        return (
            f"{cleaned[:-3]} "
            f"{cleaned[-3:]}"
        )

    return cleaned


def _money_value(value: Any) -> float:
    if value is None:
        return 0.0

    cleaned = (
        str(value)
        .strip()
        .replace("£", "")
        .replace(",", "")
    )

    if not cleaned:
        return 0.0

    try:
        return round(float(cleaned), 2)
    except (TypeError, ValueError):
        return 0.0


def _event_revenue(
    private: dict[str, Any],
) -> float:
    for key in REVENUE_KEYS:
        if key in private:
            amount = _money_value(
                private.get(key)
            )

            if amount:
                return amount

    service_key = _first_value(
        private,
        SERVICE_KEYS,
    ).lower()

    service = SERVICES.get(service_key) or {}

    for key in (
        "price",
        "amount",
        "default_price",
    ):
        amount = _money_value(
            service.get(key)
        )

        if amount:
            return amount

    return 0.0


def _event_status(
    event: dict[str, Any],
    private: dict[str, Any],
    start_time: datetime,
    end_time: datetime,
    current_time: datetime,
) -> str:
    google_status = str(
        event.get("status") or ""
    ).strip().lower()

    custom_status = str(
        private.get("booking_status")
        or private.get("appointment_status")
        or private.get("status")
        or ""
    ).strip().lower()

    if (
        google_status == "cancelled"
        or _is_cancelled(
            private.get("cancelled")
        )
        or custom_status
        in {
            "cancelled",
            "canceled",
        }
    ):
        return "cancelled"

    if (
        _is_no_show(
            private.get("no_show")
        )
        or custom_status
        in {
            "no show",
            "no-show",
            "no_show",
        }
    ):
        return "no_show"

    if (
        _is_completed(
            private.get(
                "service_completed"
            )
        )
        or custom_status
        in {
            "complete",
            "completed",
            "done",
        }
    ):
        return "completed"

    if start_time <= current_time < end_time:
        return "in_progress"

    if end_time < current_time:
        return "past_unconfirmed"

    return "upcoming"


def _event_to_record(
    event: dict[str, Any],
    current_time: datetime,
) -> dict[str, Any] | None:
    private = _private_data(event)

    start_time = _event_datetime(
        event,
        "start",
    )

    end_time = _event_datetime(
        event,
        "end",
    )

    if not start_time or not end_time:
        return None

    phone = normalise_phone(
        _first_value(
            private,
            PHONE_KEYS,
        )
    )

    customer_name = _first_value(
        private,
        CUSTOMER_NAME_KEYS,
        "Customer",
    )

    service_key = _first_value(
        private,
        SERVICE_KEYS,
    ).lower()

    registration = _display_registration(
        _first_value(
            private,
            REGISTRATION_KEYS,
        )
    )

    status = _event_status(
        event=event,
        private=private,
        start_time=start_time,
        end_time=end_time,
        current_time=current_time,
    )

    revenue = _event_revenue(
        private
    )

    return {
        "event_id": str(
            event.get("id") or ""
        ),
        "summary": str(
            event.get("summary") or ""
        ).strip(),
        "phone": phone,
        "customer_name": customer_name,
        "registration": registration,
        "service_key": service_key,
        "service_label": _service_label(
            service_key
        ),
        "start": start_time,
        "end": end_time,
        "status": status,
        "revenue": revenue,
        "private": private,
    }


def _normalise_period(
    start: datetime,
    end: datetime,
) -> tuple[datetime, datetime]:
    start_time = start

    if start_time.tzinfo is None:
        start_time = start_time.replace(
            tzinfo=TIMEZONE
        )
    else:
        start_time = start_time.astimezone(
            TIMEZONE
        )

    end_time = end

    if end_time.tzinfo is None:
        end_time = end_time.replace(
            tzinfo=TIMEZONE
        )
    else:
        end_time = end_time.astimezone(
            TIMEZONE
        )

    if end_time <= start_time:
        raise ValueError(
            "Report end must be after report start"
        )

    maximum_end = (
        start_time
        + timedelta(days=MAX_REPORT_DAYS)
    )

    if end_time > maximum_end:
        raise ValueError(
            f"Reports cannot exceed "
            f"{MAX_REPORT_DAYS} days"
        )

    return start_time, end_time


def _fetch_events(
    start: datetime,
    end: datetime,
) -> list[dict[str, Any]]:
    start_time, end_time = (
        _normalise_period(
            start,
            end,
        )
    )

    service = _get_calendar_service()

    events: list[dict[str, Any]] = []
    page_token: str | None = None

    while True:
        result = (
            service.events()
            .list(
                calendarId=_calendar_id(),
                timeMin=start_time.isoformat(),
                timeMax=end_time.isoformat(),
                singleEvents=True,
                orderBy="startTime",
                showDeleted=True,
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


def list_report_records(
    start: datetime,
    end: datetime,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    current_time = (
        now.astimezone(TIMEZONE)
        if now
        else _now()
    )

    events = _fetch_events(
        start=start,
        end=end,
    )

    records: list[dict[str, Any]] = []

    for event in events:
        record = _event_to_record(
            event=event,
            current_time=current_time,
        )

        if record:
            records.append(record)

    records.sort(
        key=lambda item: item["start"]
    )

    return records


def _customer_key(
    record: dict[str, Any],
) -> str:
    phone = str(
        record.get("phone") or ""
    ).strip()

    if phone:
        return phone

    name = str(
        record.get("customer_name")
        or ""
    ).strip().lower()

    registration = _clean_registration(
        record.get("registration") or ""
    )

    return f"{name}|{registration}"


def _customer_first_visit_dates(
    current_time: datetime,
) -> dict[str, datetime]:
    lookback_start = (
        current_time
        - timedelta(
            days=MAX_REPORT_DAYS
        )
    )

    records = list_report_records(
        start=lookback_start,
        end=current_time + timedelta(days=1),
        now=current_time,
    )

    first_visits: dict[str, datetime] = {}

    for record in records:
        if record["status"] not in {
            "completed",
            "past_unconfirmed",
        }:
            continue

        key = _customer_key(record)

        if not key:
            continue

        existing = first_visits.get(key)

        if (
            existing is None
            or record["start"] < existing
        ):
            first_visits[key] = (
                record["start"]
            )

    return first_visits


def _count_metadata(
    records: list[dict[str, Any]],
    key: str,
) -> int:
    return sum(
        1
        for record in records
        if str(
            record["private"].get(key)
            or ""
        ).strip()
    )


def _review_statistics(
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    requested = 0
    reminders = 0
    received = 0
    blocked = 0
    ratings: list[int] = []

    for record in records:
        private = record["private"]

        if private.get(
            "review_request_sent"
        ):
            requested += 1

        if private.get(
            "review_reminder_sent"
        ):
            reminders += 1

        review_status = str(
            private.get("review_status")
            or ""
        ).strip().lower()

        if (
            _is_true(
                private.get(
                    "review_received"
                )
            )
            or review_status == "received"
        ):
            received += 1

        if (
            _is_true(
                private.get(
                    "complaint_open"
                )
            )
            or review_status == "blocked"
        ):
            blocked += 1

        rating_text = str(
            private.get("review_rating")
            or ""
        ).strip()

        if rating_text.isdigit():
            rating = int(rating_text)

            if 1 <= rating <= 5:
                ratings.append(rating)

    conversion_rate = (
        round(
            received / requested * 100,
            1,
        )
        if requested
        else 0.0
    )

    average_rating = (
        round(
            sum(ratings) / len(ratings),
            2,
        )
        if ratings
        else 0.0
    )

    return {
        "requests_sent": requested,
        "reminders_sent": reminders,
        "reviews_received": received,
        "blocked_requests": blocked,
        "conversion_rate": conversion_rate,
        "average_rating": average_rating,
        "rating_breakdown": {
            str(stars): ratings.count(
                stars
            )
            for stars in range(1, 6)
        },
    }


def _reminder_statistics(
    records: list[dict[str, Any]],
) -> dict[str, int]:
    return {
        "appointment_24h_sent": (
            _count_metadata(
                records,
                "reminder_24h_sent",
            )
        ),
        "appointment_2h_sent": (
            _count_metadata(
                records,
                "reminder_2h_sent",
            )
        ),
        "follow_ups_sent": (
            _count_metadata(
                records,
                "follow_up_sent",
            )
        ),
        "thank_you_messages_sent": (
            _count_metadata(
                records,
                "customer_thank_you_sent",
            )
        ),
        "service_check_ins_sent": (
            _count_metadata(
                records,
                "service_check_in_sent",
            )
        ),
        "no_show_follow_ups_sent": (
            _count_metadata(
                records,
                "no_show_follow_up_sent",
            )
        ),
        "mot_30d_sent": (
            _count_metadata(
                records,
                "mot_reminder_30d_sent",
            )
        ),
        "mot_7d_sent": (
            _count_metadata(
                records,
                "mot_reminder_7d_sent",
            )
        ),
        "mot_due_sent": (
            _count_metadata(
                records,
                "mot_reminder_due_sent",
            )
        ),
        "service_30d_sent": (
            _count_metadata(
                records,
                "service_reminder_30d_sent",
            )
        ),
        "service_7d_sent": (
            _count_metadata(
                records,
                "service_reminder_7d_sent",
            )
        ),
        "service_due_sent": (
            _count_metadata(
                records,
                "service_reminder_due_sent",
            )
        ),
    }


def _daily_breakdown(
    records: list[dict[str, Any]],
    start: datetime,
    end: datetime,
) -> list[dict[str, Any]]:
    grouped: dict[
        date,
        list[dict[str, Any]],
    ] = defaultdict(list)

    for record in records:
        grouped[
            record["start"].date()
        ].append(record)

    days: list[dict[str, Any]] = []

    current_date = start.date()
    final_date = (
        end - timedelta(microseconds=1)
    ).date()

    while current_date <= final_date:
        day_records = grouped.get(
            current_date,
            [],
        )

        completed = [
            record
            for record in day_records
            if record["status"]
            == "completed"
        ]

        revenue = round(
            sum(
                record["revenue"]
                for record in completed
            ),
            2,
        )

        days.append(
            {
                "date": (
                    current_date.isoformat()
                ),
                "label": (
                    current_date.strftime(
                        "%a %-d %b"
                    )
                ),
                "bookings": len(
                    day_records
                ),
                "completed": len(
                    completed
                ),
                "cancelled": sum(
                    1
                    for record
                    in day_records
                    if record["status"]
                    == "cancelled"
                ),
                "no_shows": sum(
                    1
                    for record
                    in day_records
                    if record["status"]
                    == "no_show"
                ),
                "revenue": revenue,
            }
        )

        current_date += timedelta(
            days=1
        )

    return days


def build_garage_report(
    start: datetime,
    end: datetime,
    now: datetime | None = None,
) -> dict[str, Any]:
    current_time = (
        now.astimezone(TIMEZONE)
        if now
        else _now()
    )

    start_time, end_time = (
        _normalise_period(
            start,
            end,
        )
    )

    records = list_report_records(
        start=start_time,
        end=end_time,
        now=current_time,
    )

    completed_records = [
        record
        for record in records
        if record["status"] == "completed"
    ]

    cancelled_records = [
        record
        for record in records
        if record["status"] == "cancelled"
    ]

    no_show_records = [
        record
        for record in records
        if record["status"] == "no_show"
    ]

    upcoming_records = [
        record
        for record in records
        if record["status"] == "upcoming"
    ]

    in_progress_records = [
        record
        for record in records
        if record["status"] == "in_progress"
    ]

    past_unconfirmed_records = [
        record
        for record in records
        if record["status"]
        == "past_unconfirmed"
    ]

    active_records = [
        record
        for record in records
        if record["status"]
        not in {
            "cancelled",
            "no_show",
        }
    ]

    expected_revenue = round(
        sum(
            record["revenue"]
            for record in active_records
        ),
        2,
    )

    completed_revenue = round(
        sum(
            record["revenue"]
            for record
            in completed_records
        ),
        2,
    )

    outstanding_revenue = round(
        sum(
            record["revenue"]
            for record
            in upcoming_records
            + in_progress_records
        ),
        2,
    )

    service_counts = Counter(
        record["service_label"]
        for record in records
        if record["status"]
        != "cancelled"
    )

    service_revenue: dict[
        str,
        float,
    ] = defaultdict(float)

    for record in completed_records:
        service_revenue[
            record["service_label"]
        ] += record["revenue"]

    top_services = [
        {
            "service": service,
            "bookings": count,
            "completed_revenue": round(
                service_revenue.get(
                    service,
                    0.0,
                ),
                2,
            ),
        }
        for service, count
        in service_counts.most_common()
    ]

    unique_customers = {
        _customer_key(record)
        for record in records
        if _customer_key(record)
    }

    first_visit_dates = (
        _customer_first_visit_dates(
            current_time
        )
    )

    period_customer_keys = {
        _customer_key(record)
        for record in completed_records
        if _customer_key(record)
    }

    new_customer_keys: set[str] = set()
    returning_customer_keys: set[str] = set()

    for customer_key in period_customer_keys:
        first_visit = first_visit_dates.get(
            customer_key
        )

        if (
            first_visit
            and start_time
            <= first_visit
            < end_time
        ):
            new_customer_keys.add(
                customer_key
            )
        else:
            returning_customer_keys.add(
                customer_key
            )

    vip_customer_keys = {
        _customer_key(record)
        for record in records
        if (
            _customer_key(record)
            and _is_true(
                record["private"].get(
                    "vip_customer"
                )
            )
        )
    }

    total_bookings = len(records)

    attended_bookings = (
        len(completed_records)
        + len(past_unconfirmed_records)
    )

    attendance_opportunities = (
        attended_bookings
        + len(no_show_records)
    )

    completion_rate = (
        round(
            len(completed_records)
            / total_bookings
            * 100,
            1,
        )
        if total_bookings
        else 0.0
    )

    cancellation_rate = (
        round(
            len(cancelled_records)
            / total_bookings
            * 100,
            1,
        )
        if total_bookings
        else 0.0
    )

    no_show_rate = (
        round(
            len(no_show_records)
            / attendance_opportunities
            * 100,
            1,
        )
        if attendance_opportunities
        else 0.0
    )

    repeat_customer_rate = (
        round(
            len(returning_customer_keys)
            / len(period_customer_keys)
            * 100,
            1,
        )
        if period_customer_keys
        else 0.0
    )

    average_completed_job_value = (
        round(
            completed_revenue
            / len(completed_records),
            2,
        )
        if completed_records
        else 0.0
    )

    return {
        "success": True,
        "period": {
            "start": start_time.isoformat(),
            "end": end_time.isoformat(),
            "days": (
                end_time.date()
                - start_time.date()
            ).days,
        },
        "bookings": {
            "total": total_bookings,
            "completed": len(
                completed_records
            ),
            "upcoming": len(
                upcoming_records
            ),
            "in_progress": len(
                in_progress_records
            ),
            "cancelled": len(
                cancelled_records
            ),
            "no_shows": len(
                no_show_records
            ),
            "past_unconfirmed": len(
                past_unconfirmed_records
            ),
            "completion_rate": (
                completion_rate
            ),
            "cancellation_rate": (
                cancellation_rate
            ),
            "no_show_rate": (
                no_show_rate
            ),
        },
        "revenue": {
            "expected": expected_revenue,
            "completed": completed_revenue,
            "outstanding": (
                outstanding_revenue
            ),
            "average_completed_job": (
                average_completed_job_value
            ),
        },
        "customers": {
            "unique": len(
                unique_customers
            ),
            "new": len(
                new_customer_keys
            ),
            "returning": len(
                returning_customer_keys
            ),
            "vip": len(
                vip_customer_keys
            ),
            "repeat_customer_rate": (
                repeat_customer_rate
            ),
        },
        "services": {
            "top_services": top_services,
            "most_popular": (
                top_services[0]["service"]
                if top_services
                else ""
            ),
        },
        "reminders": (
            _reminder_statistics(
                records
            )
        ),
        "reviews": (
            _review_statistics(
                records
            )
        ),
        "daily_breakdown": (
            _daily_breakdown(
                records=records,
                start=start_time,
                end=end_time,
            )
        ),
        "generated_at": (
            current_time.isoformat()
        ),
    }


def get_today_report(
    now: datetime | None = None,
) -> dict[str, Any]:
    current_time = (
        now.astimezone(TIMEZONE)
        if now
        else _now()
    )

    start = current_time.replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )

    end = start + timedelta(
        days=1
    )

    report = build_garage_report(
        start=start,
        end=end,
        now=current_time,
    )

    report["report_type"] = "today"

    return report


def get_week_report(
    now: datetime | None = None,
) -> dict[str, Any]:
    current_time = (
        now.astimezone(TIMEZONE)
        if now
        else _now()
    )

    start_of_today = (
        current_time.replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
    )

    start = (
        start_of_today
        - timedelta(
            days=current_time.weekday()
        )
    )

    end = start + timedelta(
        days=7
    )

    report = build_garage_report(
        start=start,
        end=end,
        now=current_time,
    )

    report["report_type"] = "week"

    return report


def get_month_report(
    year: int | None = None,
    month: int | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    current_time = (
        now.astimezone(TIMEZONE)
        if now
        else _now()
    )

    selected_year = int(
        year or current_time.year
    )

    selected_month = int(
        month or current_time.month
    )

    if (
        selected_month < 1
        or selected_month > 12
    ):
        raise ValueError(
            "month must be between 1 and 12"
        )

    start = datetime(
        selected_year,
        selected_month,
        1,
        tzinfo=TIMEZONE,
    )

    if selected_month == 12:
        end = datetime(
            selected_year + 1,
            1,
            1,
            tzinfo=TIMEZONE,
        )
    else:
        end = datetime(
            selected_year,
            selected_month + 1,
            1,
            tzinfo=TIMEZONE,
        )

    report = build_garage_report(
        start=start,
        end=end,
        now=current_time,
    )

    report["report_type"] = "month"
    report["month"] = (
        start.strftime("%B %Y")
    )

    return report


def get_custom_report(
    start_date: date,
    end_date: date,
    now: datetime | None = None,
) -> dict[str, Any]:
    if end_date < start_date:
        raise ValueError(
            "end_date must not be before "
            "start_date"
        )

    start = datetime.combine(
        start_date,
        time.min,
        tzinfo=TIMEZONE,
    )

    end = datetime.combine(
        end_date + timedelta(days=1),
        time.min,
        tzinfo=TIMEZONE,
    )

    report = build_garage_report(
        start=start,
        end=end,
        now=now,
    )

    report["report_type"] = "custom"

    return report


def get_dashboard_summary(
    now: datetime | None = None,
) -> dict[str, Any]:
    current_time = (
        now.astimezone(TIMEZONE)
        if now
        else _now()
    )

    today = get_today_report(
        now=current_time
    )

    week = get_week_report(
        now=current_time
    )

    month = get_month_report(
        now=current_time
    )

    return {
        "success": True,
        "today": {
            "bookings": today[
                "bookings"
            ]["total"],
            "completed": today[
                "bookings"
            ]["completed"],
            "upcoming": today[
                "bookings"
            ]["upcoming"],
            "cancelled": today[
                "bookings"
            ]["cancelled"],
            "no_shows": today[
                "bookings"
            ]["no_shows"],
            "expected_revenue": today[
                "revenue"
            ]["expected"],
            "completed_revenue": today[
                "revenue"
            ]["completed"],
            "new_customers": today[
                "customers"
            ]["new"],
            "returning_customers": today[
                "customers"
            ]["returning"],
            "vip_customers": today[
                "customers"
            ]["vip"],
        },
        "week": {
            "bookings": week[
                "bookings"
            ]["total"],
            "completed": week[
                "bookings"
            ]["completed"],
            "expected_revenue": week[
                "revenue"
            ]["expected"],
            "completed_revenue": week[
                "revenue"
            ]["completed"],
            "new_customers": week[
                "customers"
            ]["new"],
            "returning_customers": week[
                "customers"
            ]["returning"],
        },
        "month": {
            "bookings": month[
                "bookings"
            ]["total"],
            "completed": month[
                "bookings"
            ]["completed"],
            "expected_revenue": month[
                "revenue"
            ]["expected"],
            "completed_revenue": month[
                "revenue"
            ]["completed"],
            "new_customers": month[
                "customers"
            ]["new"],
            "returning_customers": month[
                "customers"
            ]["returning"],
            "review_requests": month[
                "reviews"
            ]["requests_sent"],
            "reviews_received": month[
                "reviews"
            ]["reviews_received"],
            "review_conversion_rate": (
                month["reviews"][
                    "conversion_rate"
                ]
            ),
        },
        "daily_chart": week[
            "daily_breakdown"
        ],
        "top_services": month[
            "services"
        ]["top_services"][:5],
        "generated_at": (
            current_time.isoformat()
        ),
    }


def get_today_schedule(
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    current_time = (
        now.astimezone(TIMEZONE)
        if now
        else _now()
    )

    start = current_time.replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )

    end = start + timedelta(
        days=1
    )

    records = list_report_records(
        start=start,
        end=end,
        now=current_time,
    )

    return [
        {
            "event_id": record[
                "event_id"
            ],
            "time": record[
                "start"
            ].strftime("%H:%M"),
            "customer_name": record[
                "customer_name"
            ],
            "phone": record[
                "phone"
            ],
            "registration": record[
                "registration"
            ],
            "service": record[
                "service_label"
            ],
            "status": record[
                "status"
            ],
            "revenue": record[
                "revenue"
            ],
        }
        for record in records
    ]


def get_owner_morning_briefing(
    now: datetime | None = None,
) -> dict[str, Any]:
    current_time = (
        now.astimezone(TIMEZONE)
        if now
        else _now()
    )

    today = get_today_report(
        now=current_time
    )

    schedule = get_today_schedule(
        now=current_time
    )

    actions: list[str] = []

    if today["bookings"][
        "past_unconfirmed"
    ]:
        actions.append(
            f"{today['bookings']['past_unconfirmed']} "
            "past appointment(s) still need a "
            "completed, no-show or cancelled status."
        )

    if today["bookings"][
        "no_shows"
    ]:
        actions.append(
            f"Follow up with "
            f"{today['bookings']['no_shows']} "
            "no-show customer(s)."
        )

    open_complaints = (
        today["reviews"][
            "blocked_requests"
        ]
    )

    if open_complaints:
        actions.append(
            f"{open_complaints} customer "
            "complaint or negative feedback "
            "record(s) need attention."
        )

    if not actions:
        actions.append(
            "No urgent action is currently "
            "required."
        )

    return {
        "success": True,
        "date": (
            current_time.date().isoformat()
        ),
        "bookings_today": (
            today["bookings"]["total"]
        ),
        "completed_today": (
            today["bookings"][
                "completed"
            ]
        ),
        "upcoming_today": (
            today["bookings"][
                "upcoming"
            ]
        ),
        "expected_revenue": (
            today["revenue"][
                "expected"
            ]
        ),
        "vip_customers": (
            today["customers"]["vip"]
        ),
        "new_customers": (
            today["customers"]["new"]
        ),
        "returning_customers": (
            today["customers"][
                "returning"
            ]
        ),
        "schedule": schedule,
        "recommended_actions": actions,
        "generated_at": (
            current_time.isoformat()
        ),
    }


def format_report_for_ai(
    report: dict[str, Any],
) -> str:
    bookings = report.get(
        "bookings",
        {},
    )

    revenue = report.get(
        "revenue",
        {},
    )

    customers = report.get(
        "customers",
        {},
    )

    services = report.get(
        "services",
        {},
    )

    reviews = report.get(
        "reviews",
        {},
    )

    period = report.get(
        "period",
        {},
    )

    top_service = (
        services.get("most_popular")
        or "No service data"
    )

    return "\n".join(
        [
            (
                "Garage report from "
                f"{period.get('start', '')} "
                f"to {period.get('end', '')}."
            ),
            (
                "Total bookings: "
                f"{bookings.get('total', 0)}."
            ),
            (
                "Completed jobs: "
                f"{bookings.get('completed', 0)}."
            ),
            (
                "Upcoming bookings: "
                f"{bookings.get('upcoming', 0)}."
            ),
            (
                "Cancelled bookings: "
                f"{bookings.get('cancelled', 0)}."
            ),
            (
                "No-shows: "
                f"{bookings.get('no_shows', 0)}."
            ),
            (
                "Completed revenue: "
                f"£{revenue.get('completed', 0):,.2f}."
            ),
            (
                "Expected revenue: "
                f"£{revenue.get('expected', 0):,.2f}."
            ),
            (
                "Average completed job value: "
                f"£{revenue.get('average_completed_job', 0):,.2f}."
            ),
            (
                "New customers: "
                f"{customers.get('new', 0)}."
            ),
            (
                "Returning customers: "
                f"{customers.get('returning', 0)}."
            ),
            (
                "Repeat customer rate: "
                f"{customers.get('repeat_customer_rate', 0)}%."
            ),
            (
                "Most popular service: "
                f"{top_service}."
            ),
            (
                "Review requests sent: "
                f"{reviews.get('requests_sent', 0)}."
            ),
            (
                "Reviews received: "
                f"{reviews.get('reviews_received', 0)}."
            ),
            (
                "Review conversion rate: "
                f"{reviews.get('conversion_rate', 0)}%."
            ),
        ]
    )


def format_morning_briefing_for_ai(
    now: datetime | None = None,
) -> str:
    briefing = get_owner_morning_briefing(
        now=now
    )

    lines = [
        "Good morning. Here is your garage briefing.",
        (
            "Today's bookings: "
            f"{briefing['bookings_today']}."
        ),
        (
            "Expected revenue today: "
            f"£{briefing['expected_revenue']:,.2f}."
        ),
        (
            "Completed jobs so far: "
            f"{briefing['completed_today']}."
        ),
        (
            "Upcoming appointments: "
            f"{briefing['upcoming_today']}."
        ),
        (
            "New customers today: "
            f"{briefing['new_customers']}."
        ),
        (
            "Returning customers today: "
            f"{briefing['returning_customers']}."
        ),
        (
            "VIP customers today: "
            f"{briefing['vip_customers']}."
        ),
    ]

    actions = briefing.get(
        "recommended_actions",
        [],
    )

    if actions:
        lines.append(
            "Recommended actions:"
        )

        lines.extend(
            f"- {action}"
            for action in actions
        )

    return "\n".join(lines)