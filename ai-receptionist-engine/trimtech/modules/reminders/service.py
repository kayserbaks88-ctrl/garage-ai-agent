from __future__ import annotations

"""
TrimTech reminder dashboard state service.

Save as:
    trimtech/modules/reminders/service.py

This module keeps cumulative reminder statistics and recent reminder activity
for the dashboard. State is stored in a hidden Google Calendar system event so
it survives Render restarts without adding a database.
"""

import json
from datetime import datetime
from typing import Any

from integrations.garage_calendar import _calendar_id, _get_calendar_service
from integrations.garage_config import TIMEZONE


MARKER_KEY = "trimtech_system_record"
MARKER_VALUE = "reminder_dashboard_state"
EVENT_SUMMARY = "[TrimTech System] Reminder Dashboard State"
EVENT_START_DATE = "2099-01-03"
EVENT_END_DATE = "2099-01-04"
MAX_RECENT_ITEMS = 50


def _text(value: Any) -> str:
    return str(value or "").strip()


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _private(event: dict[str, Any]) -> dict[str, Any]:
    extended = event.get("extendedProperties") or {}
    private = extended.get("private") or {}
    return private if isinstance(private, dict) else {}


def _json_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]

    raw = _text(value)
    if not raw:
        return []

    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return []

    if not isinstance(parsed, list):
        return []

    return [item for item in parsed if isinstance(item, dict)]


def _find_event() -> dict[str, Any] | None:
    result = (
        _get_calendar_service()
        .events()
        .list(
            calendarId=_calendar_id(),
            privateExtendedProperty=f"{MARKER_KEY}={MARKER_VALUE}",
            singleEvents=True,
            showDeleted=False,
            maxResults=1,
        )
        .execute()
    )

    items = result.get("items") or []
    return items[0] if items else None


def _create_event() -> dict[str, Any]:
    body = {
        "summary": EVENT_SUMMARY,
        "description": (
            "System record used by the TrimTech dashboard. Do not delete."
        ),
        "start": {"date": EVENT_START_DATE},
        "end": {"date": EVENT_END_DATE},
        "transparency": "transparent",
        "visibility": "private",
        "extendedProperties": {
            "private": {
                MARKER_KEY: MARKER_VALUE,
                "status": "ready",
                "last_run": "",
                "last_successful_run": "",
                "events_checked_last_run": "0",
                "waiting": "0",
                "sent_total": "0",
                "sent_this_month": "0",
                "failed_total": "0",
                "failed_this_month": "0",
                "month_key": "",
                "recent_items_json": "[]",
            }
        },
    }

    return (
        _get_calendar_service()
        .events()
        .insert(
            calendarId=_calendar_id(),
            body=body,
        )
        .execute()
    )


def _get_or_create_event() -> dict[str, Any]:
    return _find_event() or _create_event()


def _month_key(value: datetime | None = None) -> str:
    current = (
        value.astimezone(TIMEZONE)
        if value is not None
        else datetime.now(TIMEZONE)
    )
    return current.strftime("%Y-%m")


def _normalise_item(
    item: dict[str, Any],
    *,
    fallback_status: str,
    recorded_at: str,
    source: str,
) -> dict[str, Any]:
    return {
        "type": _text(
            item.get("type")
            or item.get("reminder_type")
            or source
            or "reminder"
        ),
        "source": source,
        "status": _text(
            item.get("status") or fallback_status
        ).lower(),
        "customer_name": _text(
            item.get("customer_name")
            or item.get("name")
            or "Customer"
        ),
        "phone": _text(item.get("phone")),
        "registration": _text(
            item.get("registration")
            or item.get("vehicle_reg")
        ),
        "service": _text(
            item.get("service")
            or item.get("service_label")
        ),
        "event_id": _text(item.get("event_id")),
        "message_sid": _text(
            item.get("message_sid")
            or item.get("sid")
        ),
        "recorded_at": _text(
            item.get("recorded_at") or recorded_at
        ),
        "error": _text(item.get("error")),
    }


def _merge_recent(
    old_items: list[dict[str, Any]],
    new_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()

    for item in [*new_items, *old_items]:
        key = "|".join(
            [
                _text(item.get("message_sid")),
                _text(item.get("event_id")),
                _text(item.get("type")),
                _text(item.get("recorded_at")),
                _text(item.get("status")),
            ]
        )

        if key in seen:
            continue

        seen.add(key)
        result.append(item)

        if len(result) >= MAX_RECENT_ITEMS:
            break

    return result


def record_reminder_run(
    summary: dict[str, Any],
    *,
    source: str = "appointment",
    waiting: int | None = None,
) -> dict[str, Any]:
    """
    Add one appointment/MOT reminder run to cumulative dashboard statistics.
    """
    event = _get_or_create_event()
    private = _private(event)

    checked_at = _text(summary.get("checked_at"))
    if not checked_at:
        checked_at = datetime.now(TIMEZONE).isoformat()

    try:
        checked_dt = datetime.fromisoformat(
            checked_at.replace("Z", "+00:00")
        )
        if checked_dt.tzinfo is None:
            checked_dt = checked_dt.replace(tzinfo=TIMEZONE)
        checked_dt = checked_dt.astimezone(TIMEZONE)
    except ValueError:
        checked_dt = datetime.now(TIMEZONE)
        checked_at = checked_dt.isoformat()

    current_month = _month_key(checked_dt)

    if _text(private.get("month_key")) != current_month:
        private["sent_this_month"] = "0"
        private["failed_this_month"] = "0"

    sent_rows = summary.get("sent")
    sent_rows = sent_rows if isinstance(sent_rows, list) else []

    error_rows = summary.get("errors")
    error_rows = error_rows if isinstance(error_rows, list) else []

    sent_items = [
        _normalise_item(
            item,
            fallback_status="sent",
            recorded_at=checked_at,
            source=source,
        )
        for item in sent_rows
        if isinstance(item, dict)
    ]

    failed_items = [
        _normalise_item(
            item,
            fallback_status="failed",
            recorded_at=checked_at,
            source=source,
        )
        for item in error_rows
        if isinstance(item, dict)
    ]

    sent_count = _int(summary.get("sent_count"))
    error_count = _int(summary.get("error_count"))

    events_checked = _int(
        summary.get("events_checked")
        or summary.get("vehicles_checked")
    )

    recent = _merge_recent(
        _json_list(private.get("recent_items_json")),
        [*sent_items, *failed_items],
    )

    private.update(
        {
            MARKER_KEY: MARKER_VALUE,
            "status": "healthy" if error_count == 0 else "error",
            "last_run": checked_at,
            "events_checked_last_run": str(events_checked),
            "waiting": str(
                max(0, _int(waiting))
                if waiting is not None
                else _int(private.get("waiting"))
            ),
            "sent_total": str(
                _int(private.get("sent_total")) + sent_count
            ),
            "sent_this_month": str(
                _int(private.get("sent_this_month")) + sent_count
            ),
            "failed_total": str(
                _int(private.get("failed_total")) + error_count
            ),
            "failed_this_month": str(
                _int(private.get("failed_this_month")) + error_count
            ),
            "month_key": current_month,
            "recent_items_json": json.dumps(
                recent,
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        }
    )

    if error_count == 0:
        private["last_successful_run"] = checked_at

    (
        _get_calendar_service()
        .events()
        .patch(
            calendarId=_calendar_id(),
            eventId=event["id"],
            body={"extendedProperties": {"private": private}},
        )
        .execute()
    )

    return get_reminder_health()


def set_waiting_count(waiting: int) -> dict[str, Any]:
    event = _get_or_create_event()
    private = _private(event)

    private.update(
        {
            MARKER_KEY: MARKER_VALUE,
            "waiting": str(max(0, _int(waiting))),
        }
    )

    (
        _get_calendar_service()
        .events()
        .patch(
            calendarId=_calendar_id(),
            eventId=event["id"],
            body={"extendedProperties": {"private": private}},
        )
        .execute()
    )

    return get_reminder_health()


def get_reminder_health() -> dict[str, Any]:
    default = {
        "enabled": True,
        "due": 0,
        "waiting": 0,
        "sent_this_month": 0,
        "sent_total": 0,
        "failed": 0,
        "failed_this_month": 0,
        "last_run": None,
        "last_successful_run": None,
        "events_checked": 0,
        "status": "ready",
        "period": "this month",
        "queue": [],
        "recent": [],
    }

    try:
        event = _find_event()
        if not event:
            return default

        private = _private(event)
        waiting = _int(private.get("waiting"))
        recent = _json_list(private.get("recent_items_json"))

        return {
            **default,
            "due": waiting,
            "waiting": waiting,
            "sent_this_month": _int(
                private.get("sent_this_month")
            ),
            "sent_total": _int(private.get("sent_total")),
            "failed": _int(private.get("failed_total")),
            "failed_this_month": _int(
                private.get("failed_this_month")
            ),
            "last_run": _text(private.get("last_run")) or None,
            "last_successful_run": (
                _text(private.get("last_successful_run")) or None
            ),
            "events_checked": _int(
                private.get("events_checked_last_run")
            ),
            "status": _text(private.get("status")) or "ready",
            "queue": [
                item
                for item in recent
                if _text(item.get("status")).lower()
                in {"pending", "waiting", "scheduled"}
            ],
            "recent": recent,
        }

    except Exception as error:
        print(
            "REMINDER DASHBOARD STATE READ ERROR:",
            repr(error),
        )
        return {**default, "status": "error"}