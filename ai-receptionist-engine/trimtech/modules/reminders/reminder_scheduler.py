from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from google.oauth2 import service_account
from googleapiclient.discovery import build

from trimtech.core.business import BusinessConfig
from trimtech.core.registry import get_active_business, load_business_instance
from trimtech.modules.onboarding.service import list_onboarding_businesses
from trimtech.modules.reminders.sender import (
    send_24_hour_reminder,
    send_2_hour_reminder,
    send_follow_up,
)
from trimtech.modules.reminders.service import record_reminder_run


REMINDER_WINDOW_MINUTES = 10
FOLLOW_UP_DELAY_HOURS = 2
GOOGLE_CALENDAR_SCOPES = ["https://www.googleapis.com/auth/calendar"]

HEALTH_MARKER_KEY = "trimtech_system_record"
HEALTH_MARKER_VALUE = "reminder_health"
HEALTH_EVENT_SUMMARY = "[TrimTech System] Reminder Health"
HEALTH_EVENT_DATE = "2099-01-01"
HEALTH_EVENT_END_DATE = "2099-01-02"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _env_prefix(value: Any) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", _text(value)).strip("_").upper()


def _normalise_phone(phone: Any) -> str:
    value = _text(phone).lower().replace("whatsapp:", "")
    digits = "".join(ch for ch in value if ch.isdigit())

    if not digits:
        return ""
    if digits.startswith("0044"):
        return "+44" + digits[4:]
    if digits.startswith("44"):
        return "+" + digits
    if digits.startswith("0"):
        return "+44" + digits[1:]
    return "+" + digits


def _is_legacy_garage(business: BusinessConfig) -> bool:
    return _text(business.business_id).lower() in {"trimtech-garage", "garage"}


def _business_candidates() -> list[BusinessConfig]:
    businesses: list[BusinessConfig] = []
    seen: set[str] = set()

    try:
        active = get_active_business()
        if active.feature_enabled("reminders"):
            businesses.append(active)
            seen.add(_text(active.business_id))
    except Exception as error:
        print("REMINDER ACTIVE BUSINESS ERROR:", repr(error))

    try:
        records = list_onboarding_businesses()
    except Exception as error:
        print("REMINDER ONBOARDING LIST ERROR:", repr(error))
        records = []

    for record in records:
        slug = _text(getattr(record, "business_slug", ""))
        if not slug:
            continue

        try:
            business = load_business_instance(slug, refresh=True)
        except Exception as error:
            print("REMINDER BUSINESS LOAD ERROR:", slug, repr(error))
            continue

        business_id = _text(business.business_id)

        if (
            not business_id
            or business_id in seen
            or not business.feature_enabled("reminders")
        ):
            continue

        businesses.append(business)
        seen.add(business_id)

    return businesses


def _resolve_business(
    business: BusinessConfig | None = None,
    business_id: str | None = None,
) -> BusinessConfig:
    if isinstance(business, BusinessConfig):
        return business

    wanted = _text(business_id)
    if wanted:
        return load_business_instance(wanted, refresh=True)

    return get_active_business()


def _business_timezone(business: BusinessConfig) -> ZoneInfo:
    try:
        timezone = business.timezone
        if isinstance(timezone, ZoneInfo):
            return timezone
    except Exception:
        pass

    return ZoneInfo(_text(getattr(business, "timezone_name", "")) or "Europe/London")


def _business_calendar_id(business: BusinessConfig) -> str:
    metadata_calendar_id = _text(business.metadata.get("calendar_id"))
    if metadata_calendar_id:
        return metadata_calendar_id

    prefix = _env_prefix(business.business_id)
    instance_calendar_id = _text(os.getenv(f"{prefix}_CALENDAR_ID"))
    if instance_calendar_id:
        return instance_calendar_id

    if not _is_legacy_garage(business):
        return ""

    for value in (
        os.getenv("GARAGE_CALENDAR_ID"),
        os.getenv("GARAGE_GOOGLE_CALENDAR_ID"),
        os.getenv("TRIMTECH_GARAGE_CALENDAR_ID"),
        os.getenv("TRIMTECH_CALENDAR_ID"),
        os.getenv("GOOGLE_CALENDAR_ID"),
        os.getenv("CALENDAR_ID"),
    ):
        calendar_id = _text(value)
        if calendar_id:
            return calendar_id

    return ""


def _load_google_credentials(business: BusinessConfig):
    prefix = _env_prefix(business.business_id)

    raw_credentials = (
        _text(os.getenv(f"{prefix}_GOOGLE_SERVICE_ACCOUNT_JSON"))
        or _text(os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON"))
    )

    if raw_credentials:
        return service_account.Credentials.from_service_account_info(
            json.loads(raw_credentials),
            scopes=GOOGLE_CALENDAR_SCOPES,
        )

    credentials_path = (
        _text(os.getenv(f"{prefix}_GOOGLE_APPLICATION_CREDENTIALS"))
        or _text(os.getenv("GOOGLE_APPLICATION_CREDENTIALS"))
    )

    if credentials_path and os.path.exists(credentials_path):
        return service_account.Credentials.from_service_account_file(
            credentials_path,
            scopes=GOOGLE_CALENDAR_SCOPES,
        )

    project_root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..")
    )

    for name in ("credential.json", "credentials.json"):
        path = os.path.join(project_root, name)
        if os.path.exists(path):
            return service_account.Credentials.from_service_account_file(
                path,
                scopes=GOOGLE_CALENDAR_SCOPES,
            )

    raise RuntimeError("Google Calendar credentials were not found.")


def _calendar_service(business: BusinessConfig):
    return build(
        "calendar",
        "v3",
        credentials=_load_google_credentials(business),
        cache_discovery=False,
    )


def _service_label(business: BusinessConfig, service_key: str) -> str:
    key = _text(service_key).lower()

    try:
        label = _text(business.service_label(key))
        if label:
            return label
    except Exception:
        pass

    try:
        service = business.resolve_service(key)
    except Exception:
        service = None

    if service:
        return _text(getattr(service, "name", "")) or key.replace("_", " ").title()

    return key.replace("_", " ").title() or "Garage Appointment"


def _parse_calendar_datetime(
    raw_value: str,
    timezone: ZoneInfo,
) -> datetime | None:
    value = _text(raw_value)
    if not value:
        return None

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone)

    return parsed.astimezone(timezone)


def _event_private_data(event: dict) -> dict:
    return ((event.get("extendedProperties") or {}).get("private") or {})


def _within_due_window(target_time: datetime, current_time: datetime) -> bool:
    window_start = current_time - timedelta(minutes=REMINDER_WINDOW_MINUTES)
    return window_start <= target_time <= current_time


def _format_reminder_date(start_dt: datetime) -> str:
    try:
        return start_dt.strftime("%A %-d %B")
    except ValueError:
        return start_dt.strftime("%A %d %B").replace(" 0", " ")


def _format_reminder_time(start_dt: datetime) -> str:
    try:
        return start_dt.strftime("%-I:%M %p").lower()
    except ValueError:
        return start_dt.strftime("%I:%M %p").lstrip("0").lower()


def _get_relevant_events(
    business: BusinessConfig,
    current_time: datetime,
) -> list[dict]:
    calendar_id = _business_calendar_id(business)

    if not calendar_id:
        raise RuntimeError(
            f"{_env_prefix(business.business_id)}_CALENDAR_ID is not configured."
        )

    result = (
        _calendar_service(business)
        .events()
        .list(
            calendarId=calendar_id,
            timeMin=(current_time - timedelta(hours=FOLLOW_UP_DELAY_HOURS + 1)).isoformat(),
            timeMax=(current_time + timedelta(hours=25)).isoformat(),
            singleEvents=True,
            orderBy="startTime",
            maxResults=100,
        )
        .execute()
    )

    items = result.get("items", [])
    return items if isinstance(items, list) else []


def _find_health_event(business: BusinessConfig) -> dict | None:
    calendar_id = _business_calendar_id(business)
    if not calendar_id:
        return None

    result = (
        _calendar_service(business)
        .events()
        .list(
            calendarId=calendar_id,
            privateExtendedProperty=f"{HEALTH_MARKER_KEY}={HEALTH_MARKER_VALUE}",
            singleEvents=True,
            maxResults=1,
            showDeleted=False,
        )
        .execute()
    )

    items = result.get("items") or []
    return items[0] if items else None


def _create_health_event(business: BusinessConfig) -> dict:
    calendar_id = _business_calendar_id(business)

    if not calendar_id:
        raise RuntimeError(
            f"{_env_prefix(business.business_id)}_CALENDAR_ID is not configured."
        )

    body = {
        "summary": HEALTH_EVENT_SUMMARY,
        "description": (
            f"System record used by the TrimTech dashboard for "
            f"{business.business_name}. Do not delete."
        ),
        "start": {"date": HEALTH_EVENT_DATE},
        "end": {"date": HEALTH_EVENT_END_DATE},
        "transparency": "transparent",
        "visibility": "private",
        "extendedProperties": {
            "private": {
                HEALTH_MARKER_KEY: HEALTH_MARKER_VALUE,
                "business_id": business.business_id,
                "status": "ready",
                "last_run": "",
                "last_successful_run": "",
                "events_checked": "0",
                "sent_count": "0",
                "error_count": "0",
            }
        },
    }

    return (
        _calendar_service(business)
        .events()
        .insert(calendarId=calendar_id, body=body)
        .execute()
    )


def _get_or_create_health_event(business: BusinessConfig) -> dict:
    return _find_health_event(business) or _create_health_event(business)


def _save_reminder_health(
    business: BusinessConfig,
    summary: dict[str, Any],
    *,
    successful: bool,
) -> None:
    try:
        calendar_id = _business_calendar_id(business)
        if not calendar_id:
            return

        service = _calendar_service(business)
        event = _get_or_create_health_event(business)

        private = {
            **_event_private_data(event),
            HEALTH_MARKER_KEY: HEALTH_MARKER_VALUE,
            "business_id": business.business_id,
            "status": "healthy" if successful else "error",
            "last_run": _text(summary.get("checked_at")),
            "events_checked": str(int(summary.get("events_checked") or 0)),
            "sent_count": str(int(summary.get("sent_count") or 0)),
            "error_count": str(int(summary.get("error_count") or 0)),
        }

        if successful:
            private["last_successful_run"] = _text(summary.get("checked_at"))

        (
            service.events()
            .patch(
                calendarId=calendar_id,
                eventId=event["id"],
                body={"extendedProperties": {"private": private}},
            )
            .execute()
        )

    except Exception as error:
        print(
            "REMINDER HEALTH SAVE ERROR:",
            {"business_id": business.business_id, "error": repr(error)},
        )


def get_reminder_health(
    business: BusinessConfig | None = None,
    business_id: str | None = None,
) -> dict[str, Any]:
    selected = _resolve_business(business=business, business_id=business_id)

    configured = bool(_business_calendar_id(selected))

    default_result = {
        "enabled": bool(selected.feature_enabled("reminders")),
        "configured": configured,
        "business_id": selected.business_id,
        "business_name": selected.business_name,
        "due": 0,
        "waiting": 0,
        "sent_this_month": 0,
        "last_run": None,
        "last_successful_run": None,
        "events_checked": 0,
        "sent_count": 0,
        "error_count": 0,
        "failed": 0,
        "status": "ready" if configured else "not_configured",
        "period": "this month",
        "queue": [],
    }

    if not selected.feature_enabled("reminders"):
        return {**default_result, "enabled": False, "status": "disabled"}

    if not configured:
        return default_result

    try:
        event = _find_health_event(selected)

        if not event:
            return default_result

        private = _event_private_data(event)

        return {
            **default_result,
            "last_run": private.get("last_run") or None,
            "last_successful_run": private.get("last_successful_run") or None,
            "events_checked": int(private.get("events_checked") or 0),
            "sent_count": int(private.get("sent_count") or 0),
            "sent_this_month": int(private.get("sent_count") or 0),
            "error_count": int(private.get("error_count") or 0),
            "failed": int(private.get("error_count") or 0),
            "status": private.get("status") or "ready",
        }

    except Exception as error:
        print(
            "REMINDER HEALTH READ ERROR:",
            {"business_id": selected.business_id, "error": repr(error)},
        )
        return {**default_result, "status": "error"}


def _mark_reminder_sent(
    business: BusinessConfig,
    event: dict,
    reminder_key: str,
    sent_at: datetime,
    message_sid: str = "",
) -> None:
    calendar_id = _business_calendar_id(business)

    if not calendar_id:
        raise RuntimeError("Business calendar is not configured.")

    service = _calendar_service(business)

    extended_properties = event.get("extendedProperties") or {}
    private = extended_properties.get("private") or {}

    private[reminder_key] = sent_at.isoformat()

    if message_sid:
        private[f"{reminder_key}_sid"] = message_sid

    private["reminder_business_id"] = business.business_id
    extended_properties["private"] = private
    event["extendedProperties"] = extended_properties

    (
        service.events()
        .update(
            calendarId=calendar_id,
            eventId=event["id"],
            body=event,
        )
        .execute()
    )


def _appointment_details(
    business: BusinessConfig,
    event: dict,
) -> dict | None:
    private = _event_private_data(event)

    phone = _normalise_phone(
        private.get("phone", "")
        or private.get("customer_phone", "")
    )

    if not phone:
        print(
            "REMINDER SKIPPED — MISSING PHONE:",
            business.business_id,
            event.get("id"),
            event.get("summary"),
        )
        return None

    timezone = _business_timezone(business)

    start_dt = _parse_calendar_datetime(
        (event.get("start") or {}).get("dateTime", ""),
        timezone,
    )

    end_dt = _parse_calendar_datetime(
        (event.get("end") or {}).get("dateTime", ""),
        timezone,
    )

    if not start_dt or not end_dt:
        print(
            "REMINDER SKIPPED — INVALID EVENT TIME:",
            business.business_id,
            event.get("id"),
        )
        return None

    service_key = _text(
        private.get("service")
        or private.get("service_key")
        or private.get("service_name")
    ).lower()

    return {
        "phone": phone,
        "customer_name": _text(
            private.get("customer_name") or private.get("name")
        ) or "Customer",
        "service_key": service_key,
        "service_label": _service_label(business, service_key),
        "registration": _text(
            private.get("reg")
            or private.get("vehicle_reg")
            or private.get("registration")
            or "your vehicle"
        ).upper(),
        "start": start_dt,
        "end": end_dt,
        "private": private,
    }


def _send_due_24_hour_reminder(
    business: BusinessConfig,
    event: dict,
    details: dict,
    current_time: datetime,
) -> dict | None:
    private = details["private"]

    if private.get("reminder_24h_sent"):
        return None

    target_time = details["start"] - timedelta(hours=24)

    if not _within_due_window(target_time, current_time):
        return None

    result = send_24_hour_reminder(
        phone=details["phone"],
        customer_name=details["customer_name"],
        service_label=details["service_label"],
        registration=details["registration"],
        date_text=_format_reminder_date(details["start"]),
        time_text=_format_reminder_time(details["start"]),
    )

    _mark_reminder_sent(
        business=business,
        event=event,
        reminder_key="reminder_24h_sent",
        sent_at=current_time,
        message_sid=_text(result.get("sid")),
    )

    return {
        "type": "24_hour",
        "business_id": business.business_id,
        "business_name": business.business_name,
        "event_id": event.get("id"),
        "phone": details["phone"],
        "customer_name": details["customer_name"],
        "registration": details["registration"],
        "service": details["service_label"],
        "message_sid": result.get("sid"),
    }


def _send_due_2_hour_reminder(
    business: BusinessConfig,
    event: dict,
    details: dict,
    current_time: datetime,
) -> dict | None:
    private = details["private"]

    if private.get("reminder_2h_sent"):
        return None

    target_time = details["start"] - timedelta(hours=2)

    if not _within_due_window(target_time, current_time):
        return None

    result = send_2_hour_reminder(
        phone=details["phone"],
        customer_name=details["customer_name"],
        service_label=details["service_label"],
        registration=details["registration"],
        time_text=_format_reminder_time(details["start"]),
    )

    _mark_reminder_sent(
        business=business,
        event=event,
        reminder_key="reminder_2h_sent",
        sent_at=current_time,
        message_sid=_text(result.get("sid")),
    )

    return {
        "type": "2_hour",
        "business_id": business.business_id,
        "business_name": business.business_name,
        "event_id": event.get("id"),
        "phone": details["phone"],
        "customer_name": details["customer_name"],
        "registration": details["registration"],
        "service": details["service_label"],
        "message_sid": result.get("sid"),
    }


def _send_due_follow_up(
    business: BusinessConfig,
    event: dict,
    details: dict,
    current_time: datetime,
) -> dict | None:
    private = details["private"]

    if private.get("follow_up_sent"):
        return None

    target_time = details["end"] + timedelta(hours=FOLLOW_UP_DELAY_HOURS)

    if not _within_due_window(target_time, current_time):
        return None

    result = send_follow_up(
        phone=details["phone"],
        customer_name=details["customer_name"],
        service_label=details["service_label"],
        registration=details["registration"],
    )

    _mark_reminder_sent(
        business=business,
        event=event,
        reminder_key="follow_up_sent",
        sent_at=current_time,
        message_sid=_text(result.get("sid")),
    )

    return {
        "type": "follow_up",
        "business_id": business.business_id,
        "business_name": business.business_name,
        "event_id": event.get("id"),
        "phone": details["phone"],
        "customer_name": details["customer_name"],
        "registration": details["registration"],
        "service": details["service_label"],
        "message_sid": result.get("sid"),
    }


def _process_business_reminders(
    business: BusinessConfig,
    now: datetime | None = None,
) -> dict[str, Any]:
    timezone = _business_timezone(business)

    current_time = (
        now.astimezone(timezone)
        if now is not None
        else datetime.now(timezone)
    )

    base_summary = {
        "success": True,
        "business_id": business.business_id,
        "business_name": business.business_name,
        "calendar_id_configured": bool(_business_calendar_id(business)),
        "checked_at": current_time.isoformat(),
        "events_checked": 0,
        "sent_count": 0,
        "sent": [],
        "skipped_count": 0,
        "error_count": 0,
        "errors": [],
    }

    if not business.feature_enabled("reminders"):
        return {**base_summary, "status": "disabled"}

    if not _business_calendar_id(business):
        error_record = {
            "business_id": business.business_id,
            "error": (
                f"{_env_prefix(business.business_id)}_CALENDAR_ID "
                "is not configured."
            ),
        }

        summary = {
            **base_summary,
            "success": False,
            "status": "not_configured",
            "error_count": 1,
            "errors": [error_record],
        }

        print("REMINDER BUSINESS NOT CONFIGURED:", error_record)
        return summary

    print(
        "REMINDER CHECK STARTED:",
        {
            "business_id": business.business_id,
            "business_name": business.business_name,
            "checked_at": current_time.isoformat(),
        },
    )

    sent: list[dict[str, Any]] = []
    skipped = 0
    errors: list[dict[str, Any]] = []

    try:
        events = _get_relevant_events(business, current_time)
    except Exception as error:
        error_record = {
            "business_id": business.business_id,
            "stage": "calendar_fetch",
            "error": repr(error),
        }

        summary = {
            **base_summary,
            "success": False,
            "status": "error",
            "error_count": 1,
            "errors": [error_record],
        }

        _save_reminder_health(business, summary, successful=False)
        print("REMINDER BUSINESS ERROR:", error_record)
        return summary

    for event in events:
        if event.get("status") == "cancelled":
            skipped += 1
            continue

        if not event.get("id"):
            skipped += 1
            continue

        details = _appointment_details(business, event)

        if not details:
            skipped += 1
            continue

        reminder_handlers = (
            _send_due_24_hour_reminder,
            _send_due_2_hour_reminder,
            _send_due_follow_up,
        )

        for handler in reminder_handlers:
            try:
                result = handler(
                    business,
                    event,
                    details,
                    current_time,
                )

                if result:
                    sent.append(result)

                    print(
                        "REMINDER SENT:",
                        result["business_id"],
                        result["type"],
                        result["phone"],
                        result.get("message_sid"),
                    )

                    details["private"][
                        {
                            "24_hour": "reminder_24h_sent",
                            "2_hour": "reminder_2h_sent",
                            "follow_up": "follow_up_sent",
                        }[result["type"]]
                    ] = current_time.isoformat()

            except Exception as error:
                error_record = {
                    "business_id": business.business_id,
                    "event_id": event.get("id"),
                    "reminder_handler": handler.__name__,
                    "error": repr(error),
                }

                errors.append(error_record)
                print("REMINDER ERROR:", error_record)

    summary = {
        **base_summary,
        "success": len(errors) == 0,
        "status": "healthy" if len(errors) == 0 else "error",
        "events_checked": len(events),
        "sent_count": len(sent),
        "sent": sent,
        "skipped_count": skipped,
        "error_count": len(errors),
        "errors": errors,
    }

    _save_reminder_health(
        business,
        summary,
        successful=(len(errors) == 0),
    )

    try:
        record_reminder_run(
            summary,
            source=f"appointment:{business.business_id}",
        )
    except Exception as error:
        print(
            "REMINDER DASHBOARD RECORD ERROR:",
            {"business_id": business.business_id, "error": repr(error)},
        )

    print("REMINDER CHECK COMPLETE:", summary)
    return summary


def process_reminders(
    now: datetime | None = None,
    *,
    business: BusinessConfig | None = None,
    business_id: str | None = None,
) -> dict[str, Any]:
    """
    Shared reminder entry point.

    With a business/business_id:
        Process only that business.

    With no business supplied (normal Render cron):
        Process every reminder-enabled business independently.
    """

    if business is not None or _text(business_id):
        selected = _resolve_business(
            business=business,
            business_id=business_id,
        )
        return _process_business_reminders(selected, now=now)

    businesses = _business_candidates()

    started_at = (
        now
        if now is not None
        else datetime.now(ZoneInfo("Europe/London"))
    )

    results = [
        _process_business_reminders(selected, now=now)
        for selected in businesses
    ]

    sent: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    events_checked = 0
    skipped_count = 0

    for result in results:
        events_checked += int(result.get("events_checked") or 0)
        skipped_count += int(result.get("skipped_count") or 0)

        result_sent = result.get("sent") or []
        if isinstance(result_sent, list):
            sent.extend(result_sent)

        result_errors = result.get("errors") or []
        if isinstance(result_errors, list):
            errors.extend(result_errors)

    aggregate = {
        "success": (
            all(bool(result.get("success")) for result in results)
            if results
            else True
        ),
        "checked_at": started_at.isoformat(),
        "business_count": len(results),
        "businesses": results,
        "events_checked": events_checked,
        "sent_count": len(sent),
        "sent": sent,
        "skipped_count": skipped_count,
        "error_count": len(errors),
        "errors": errors,
    }

    print(
        "REMINDER MULTI-BUSINESS COMPLETE:",
        {
            "success": aggregate["success"],
            "business_count": aggregate["business_count"],
            "events_checked": aggregate["events_checked"],
            "sent_count": aggregate["sent_count"],
            "error_count": aggregate["error_count"],
        },
    )

    return aggregate


def process_appointment_reminders(
    now: datetime | None = None,
) -> dict[str, Any]:
    return process_reminders(now=now)


def run_reminders(
    now: datetime | None = None,
) -> dict[str, Any]:
    return process_reminders(now=now)


def process_due_reminders(
    now: datetime | None = None,
) -> dict[str, Any]:
    return process_reminders(now=now)