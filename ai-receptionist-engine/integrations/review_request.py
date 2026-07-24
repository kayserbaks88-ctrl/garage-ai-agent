from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Any

from integrations.garage_calendar import (
    _calendar_id,
    _get_calendar_service,
    normalise_phone,
)
from integrations.garage_config import SERVICES, TIMEZONE
from integrations.reminder_sender import send_whatsapp_template


REVIEW_LOOKBACK_DAYS = 60
REVIEW_REMINDER_DELAY_DAYS = 7

POSITIVE_WORDS = {
    "amazing",
    "brilliant",
    "excellent",
    "fantastic",
    "fine",
    "fixed",
    "good",
    "great",
    "happy",
    "lovely",
    "perfect",
    "pleased",
    "sorted",
    "thank you",
    "thanks",
    "very good",
    "working well",
    "yes",
}

NEGATIVE_WORDS = {
    "angry",
    "awful",
    "bad",
    "broken",
    "complaint",
    "disappointed",
    "issue",
    "not fixed",
    "not good",
    "not happy",
    "noise",
    "problem",
    "refund",
    "rubbish",
    "still",
    "unhappy",
    "worse",
}


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()

    if not value:
        raise ValueError(f"Missing {name}")

    return value


def _optional_env(name: str) -> str:
    return os.getenv(name, "").strip()


def _parse_datetime(value: str) -> datetime | None:
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


def _is_true(value: Any) -> bool:
    return str(value or "").strip().lower() in {
        "1",
        "completed",
        "done",
        "true",
        "yes",
    }


def _service_label(service_key: str) -> str:
    key = str(service_key or "").strip().lower()
    service = SERVICES.get(key) or {}

    return str(
        service.get("label")
        or key.replace("_", " ").title()
        or "Garage Appointment"
    )


def _clean_registration(registration: str) -> str:
    return "".join(
        character
        for character in str(registration or "").upper()
        if character.isalnum()
    )


def _display_registration(registration: str) -> str:
    cleaned = _clean_registration(registration)

    if len(cleaned) > 3:
        return f"{cleaned[:-3]} {cleaned[-3:]}"

    return cleaned


def _event_to_record(
    event: dict,
) -> dict[str, Any] | None:
    if event.get("status") == "cancelled":
        return None

    private = _private_data(event)

    start_time = _event_start(event)
    end_time = _event_end(event)

    if not start_time or not end_time:
        return None

    phone = normalise_phone(
        private.get("phone") or ""
    )

    if not phone:
        return None

    service_key = str(
        private.get("service") or ""
    ).strip().lower()

    registration = (
        private.get("registration")
        or private.get("vehicle_reg")
        or private.get("reg")
        or ""
    )

    return {
        "event_id": str(event.get("id") or ""),
        "event": event,
        "private": private,
        "phone": phone,
        "customer_name": str(
            private.get("customer_name")
            or private.get("name")
            or "Customer"
        ).strip(),
        "registration": _display_registration(
            registration
        ),
        "service_key": service_key,
        "service_label": _service_label(service_key),
        "start": start_time,
        "end": end_time,
        "service_completed": _is_true(
            private.get("service_completed")
        ),
        "no_show": _is_true(
            private.get("no_show")
        ),
    }


def _update_event_private_data(
    event: dict,
    updates: dict[str, Any],
) -> dict:
    event_id = str(event.get("id") or "").strip()

    if not event_id:
        raise ValueError(
            "Missing Google Calendar event ID"
        )

    extended_properties = (
        event.get("extendedProperties")
        or {}
    )

    private = (
        extended_properties.get("private")
        or {}
    )

    for key, value in updates.items():
        private[str(key)] = str(value)

    extended_properties["private"] = private
    event["extendedProperties"] = extended_properties

    return (
        _get_calendar_service()
        .events()
        .update(
            calendarId=_calendar_id(),
            eventId=event_id,
            body=event,
        )
        .execute()
    )


def _get_event(event_id: str) -> dict:
    cleaned_event_id = str(event_id or "").strip()

    if not cleaned_event_id:
        raise ValueError("Missing event_id")

    return (
        _get_calendar_service()
        .events()
        .get(
            calendarId=_calendar_id(),
            eventId=cleaned_event_id,
        )
        .execute()
    )


def _fetch_events(
    time_min: datetime,
    time_max: datetime,
) -> list[dict]:
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

        events.extend(result.get("items", []))

        page_token = result.get("nextPageToken")

        if not page_token:
            break

    return events


def analyse_customer_sentiment(
    message: str,
) -> dict[str, Any]:
    cleaned = " ".join(
        str(message or "").strip().lower().split()
    )

    if not cleaned:
        return {
            "sentiment": "unknown",
            "positive_matches": [],
            "negative_matches": [],
            "confidence": 0.0,
        }

    positive_matches = sorted(
        word
        for word in POSITIVE_WORDS
        if word in cleaned
    )

    negative_matches = sorted(
        word
        for word in NEGATIVE_WORDS
        if word in cleaned
    )

    positive_score = len(positive_matches)
    negative_score = len(negative_matches)

    if negative_score > 0:
        sentiment = "negative"
    elif positive_score > 0:
        sentiment = "positive"
    else:
        sentiment = "unknown"

    total_matches = positive_score + negative_score

    confidence = (
        min(1.0, total_matches / 2)
        if total_matches
        else 0.0
    )

    return {
        "sentiment": sentiment,
        "positive_matches": positive_matches,
        "negative_matches": negative_matches,
        "confidence": confidence,
    }


def send_review_request(
    event_id: str,
    current_time: datetime | None = None,
    force: bool = False,
) -> dict[str, Any] | None:
    now = (
        current_time.astimezone(TIMEZONE)
        if current_time
        else datetime.now(TIMEZONE)
    )

    event = _get_event(event_id)
    record = _event_to_record(event)

    if not record:
        raise ValueError(
            "The event cannot be used for a review request"
        )

    private = record["private"]

    if not force:
        if not record["service_completed"]:
            return None

        if record["no_show"]:
            return None

        if private.get("review_request_sent"):
            return None

        sentiment = str(
            private.get("customer_sentiment") or ""
        ).strip().lower()

        if sentiment == "negative":
            return None

        if _is_true(private.get("complaint_open")):
            return None

    review_url = _required_env(
        "GOOGLE_REVIEW_URL"
    )

    result = send_whatsapp_template(
        phone=record["phone"],
        content_sid=_required_env(
            "TWILIO_REVIEW_REQUEST_CONTENT_SID"
        ),
        variables={
            "1": record["customer_name"],
            "2": record["service_label"],
            "3": review_url,
        },
    )

    sent_at = now.isoformat()
    message_sid = str(
        result.get("sid") or ""
    )

    _update_event_private_data(
        event=event,
        updates={
            "review_request_sent": sent_at,
            "review_request_sent_sid": message_sid,
            "review_link_sent": review_url,
            "review_status": "requested",
        },
    )

    return {
        "type": "review_request",
        "event_id": record["event_id"],
        "phone": record["phone"],
        "customer_name": record["customer_name"],
        "service_label": record["service_label"],
        "message_sid": message_sid,
        "review_url": review_url,
        "sent_at": sent_at,
    }


def send_review_reminder(
    event_id: str,
    current_time: datetime | None = None,
    force: bool = False,
) -> dict[str, Any] | None:
    now = (
        current_time.astimezone(TIMEZONE)
        if current_time
        else datetime.now(TIMEZONE)
    )

    event = _get_event(event_id)
    record = _event_to_record(event)

    if not record:
        raise ValueError(
            "The event cannot be used for a review reminder"
        )

    private = record["private"]

    request_sent_at = _parse_datetime(
        private.get("review_request_sent") or ""
    )

    if not force:
        if not request_sent_at:
            return None

        if private.get("review_reminder_sent"):
            return None

        if _is_true(private.get("review_received")):
            return None

        if str(
            private.get("review_status") or ""
        ).strip().lower() == "received":
            return None

        if str(
            private.get("customer_sentiment") or ""
        ).strip().lower() == "negative":
            return None

        reminder_due_at = (
            request_sent_at
            + timedelta(
                days=REVIEW_REMINDER_DELAY_DAYS
            )
        )

        if now < reminder_due_at:
            return None

    review_url = (
        str(private.get("review_link_sent") or "").strip()
        or _required_env("GOOGLE_REVIEW_URL")
    )

    result = send_whatsapp_template(
        phone=record["phone"],
        content_sid=_required_env(
            "TWILIO_REVIEW_REMINDER_CONTENT_SID"
        ),
        variables={
            "1": record["customer_name"],
            "2": review_url,
        },
    )

    sent_at = now.isoformat()
    message_sid = str(
        result.get("sid") or ""
    )

    _update_event_private_data(
        event=event,
        updates={
            "review_reminder_sent": sent_at,
            "review_reminder_sent_sid": message_sid,
            "review_status": "reminded",
        },
    )

    return {
        "type": "review_reminder",
        "event_id": record["event_id"],
        "phone": record["phone"],
        "customer_name": record["customer_name"],
        "message_sid": message_sid,
        "review_url": review_url,
        "sent_at": sent_at,
    }


def record_customer_feedback(
    event_id: str,
    message: str,
    current_time: datetime | None = None,
    automatically_request_review: bool = True,
) -> dict[str, Any]:
    now = (
        current_time.astimezone(TIMEZONE)
        if current_time
        else datetime.now(TIMEZONE)
    )

    event = _get_event(event_id)
    record = _event_to_record(event)

    if not record:
        raise ValueError(
            "The event cannot be used for customer feedback"
        )

    sentiment_result = analyse_customer_sentiment(
        message
    )

    sentiment = sentiment_result["sentiment"]

    updates: dict[str, Any] = {
        "customer_feedback": str(message or "").strip(),
        "customer_feedback_received_at": now.isoformat(),
        "customer_sentiment": sentiment,
    }

    if sentiment == "negative":
        updates.update(
            {
                "complaint_open": "true",
                "complaint_opened_at": now.isoformat(),
                "review_status": "blocked",
            }
        )

    elif sentiment == "positive":
        updates.update(
            {
                "complaint_open": "false",
                "customer_happy": "true",
            }
        )

    _update_event_private_data(
        event=event,
        updates=updates,
    )

    review_result = None

    if (
        sentiment == "positive"
        and automatically_request_review
    ):
        review_result = send_review_request(
            event_id=event_id,
            current_time=now,
        )

    return {
        "success": True,
        "event_id": event_id,
        "phone": record["phone"],
        "customer_name": record["customer_name"],
        "feedback": str(message or "").strip(),
        "sentiment": sentiment,
        "confidence": sentiment_result["confidence"],
        "positive_matches": sentiment_result[
            "positive_matches"
        ],
        "negative_matches": sentiment_result[
            "negative_matches"
        ],
        "complaint_opened": sentiment == "negative",
        "review_request_sent": bool(review_result),
        "review_request": review_result,
        "recorded_at": now.isoformat(),
    }


def mark_review_received(
    event_id: str,
    rating: int | None = None,
    review_text: str = "",
    reviewer_name: str = "",
    current_time: datetime | None = None,
) -> dict[str, Any]:
    now = (
        current_time.astimezone(TIMEZONE)
        if current_time
        else datetime.now(TIMEZONE)
    )

    if rating is not None:
        rating = int(rating)

        if rating < 1 or rating > 5:
            raise ValueError(
                "rating must be between 1 and 5"
            )

    event = _get_event(event_id)

    updates: dict[str, Any] = {
        "review_received": "true",
        "review_received_at": now.isoformat(),
        "review_status": "received",
    }

    if rating is not None:
        updates["review_rating"] = str(rating)

    if str(review_text or "").strip():
        updates["review_text"] = str(
            review_text
        ).strip()

    if str(reviewer_name or "").strip():
        updates["reviewer_name"] = str(
            reviewer_name
        ).strip()

    _update_event_private_data(
        event=event,
        updates=updates,
    )

    return {
        "success": True,
        "event_id": event_id,
        "rating": rating,
        "review_text": str(review_text or "").strip(),
        "reviewer_name": str(
            reviewer_name or ""
        ).strip(),
        "received_at": now.isoformat(),
    }


def close_customer_complaint(
    event_id: str,
    resolution_notes: str = "",
    current_time: datetime | None = None,
) -> dict[str, Any]:
    now = (
        current_time.astimezone(TIMEZONE)
        if current_time
        else datetime.now(TIMEZONE)
    )

    event = _get_event(event_id)

    _update_event_private_data(
        event=event,
        updates={
            "complaint_open": "false",
            "complaint_closed_at": now.isoformat(),
            "complaint_resolution_notes": str(
                resolution_notes or ""
            ).strip(),
        },
    )

    return {
        "success": True,
        "event_id": event_id,
        "complaint_closed_at": now.isoformat(),
        "resolution_notes": str(
            resolution_notes or ""
        ).strip(),
    }


def find_latest_completed_event_by_phone(
    phone: str,
    lookback_days: int = REVIEW_LOOKBACK_DAYS,
    current_time: datetime | None = None,
) -> dict[str, Any] | None:
    now = (
        current_time.astimezone(TIMEZONE)
        if current_time
        else datetime.now(TIMEZONE)
    )

    normalised_phone = normalise_phone(phone)

    if not normalised_phone:
        return None

    events = _fetch_events(
        time_min=now - timedelta(days=lookback_days),
        time_max=now + timedelta(days=1),
    )

    matches: list[dict[str, Any]] = []

    for event in events:
        record = _event_to_record(event)

        if not record:
            continue

        if record["phone"] != normalised_phone:
            continue

        if not record["service_completed"]:
            continue

        if record["no_show"]:
            continue

        if record["end"] > now:
            continue

        matches.append(record)

    if not matches:
        return None

    matches.sort(
        key=lambda item: item["end"],
        reverse=True,
    )

    return matches[0]


def record_feedback_by_phone(
    phone: str,
    message: str,
    automatically_request_review: bool = True,
) -> dict[str, Any]:
    record = find_latest_completed_event_by_phone(
        phone
    )

    if not record:
        return {
            "success": False,
            "error": "completed_service_not_found",
            "phone": normalise_phone(phone),
            "review_request_sent": False,
        }

    return record_customer_feedback(
        event_id=record["event_id"],
        message=message,
        automatically_request_review=(
            automatically_request_review
        ),
    )


def process_review_reminders(
    now: datetime | None = None,
) -> dict[str, Any]:
    current_time = (
        now.astimezone(TIMEZONE)
        if now
        else datetime.now(TIMEZONE)
    )

    events = _fetch_events(
        time_min=(
            current_time
            - timedelta(days=REVIEW_LOOKBACK_DAYS)
        ),
        time_max=current_time + timedelta(days=1),
    )

    sent: list[dict[str, Any]] = []
    skipped = 0
    errors: list[dict[str, Any]] = []

    for event in events:
        record = _event_to_record(event)

        if not record:
            skipped += 1
            continue

        private = record["private"]

        if not private.get("review_request_sent"):
            skipped += 1
            continue

        try:
            result = send_review_reminder(
                event_id=record["event_id"],
                current_time=current_time,
            )

            if result:
                sent.append(result)
            else:
                skipped += 1

        except Exception as error:
            error_record = {
                "event_id": record["event_id"],
                "phone": record["phone"],
                "customer_name": record[
                    "customer_name"
                ],
                "error": repr(error),
            }

            errors.append(error_record)

            print(
                "REVIEW REMINDER ERROR:",
                error_record,
            )

    summary = {
        "success": len(errors) == 0,
        "checked_at": current_time.isoformat(),
        "events_checked": len(events),
        "sent_count": len(sent),
        "sent": sent,
        "skipped_count": skipped,
        "error_count": len(errors),
        "errors": errors,
    }

    print(
        "REVIEW REMINDERS COMPLETE:",
        summary,
    )

    return summary


def get_review_statistics(
    days: int = 30,
    now: datetime | None = None,
) -> dict[str, Any]:
    current_time = (
        now.astimezone(TIMEZONE)
        if now
        else datetime.now(TIMEZONE)
    )

    events = _fetch_events(
        time_min=current_time - timedelta(days=days),
        time_max=current_time + timedelta(days=1),
    )

    requested = 0
    reminded = 0
    received = 0
    blocked = 0
    ratings: list[int] = []

    for event in events:
        private = _private_data(event)

        if private.get("review_request_sent"):
            requested += 1

        if private.get("review_reminder_sent"):
            reminded += 1

        if (
            _is_true(private.get("review_received"))
            or str(
                private.get("review_status") or ""
            ).strip().lower()
            == "received"
        ):
            received += 1

        if (
            _is_true(private.get("complaint_open"))
            or str(
                private.get("review_status") or ""
            ).strip().lower()
            == "blocked"
        ):
            blocked += 1

        rating_value = str(
            private.get("review_rating") or ""
        ).strip()

        if rating_value.isdigit():
            rating = int(rating_value)

            if 1 <= rating <= 5:
                ratings.append(rating)

    conversion_rate = (
        round((received / requested) * 100, 1)
        if requested
        else 0.0
    )

    average_rating = (
        round(sum(ratings) / len(ratings), 2)
        if ratings
        else 0.0
    )

    rating_breakdown = {
        str(stars): ratings.count(stars)
        for stars in range(1, 6)
    }

    return {
        "period_days": int(days),
        "review_requests_sent": requested,
        "review_reminders_sent": reminded,
        "reviews_received": received,
        "review_requests_blocked": blocked,
        "conversion_rate": conversion_rate,
        "average_rating": average_rating,
        "rating_breakdown": rating_breakdown,
        "generated_at": current_time.isoformat(),
    }


def format_review_statistics_for_ai(
    days: int = 30,
) -> str:
    statistics = get_review_statistics(days=days)

    return "\n".join(
        [
            f"Review report for the last {days} days:",
            (
                "Review requests sent: "
                f"{statistics['review_requests_sent']}."
            ),
            (
                "Review reminders sent: "
                f"{statistics['review_reminders_sent']}."
            ),
            (
                "Reviews received: "
                f"{statistics['reviews_received']}."
            ),
            (
                "Review conversion rate: "
                f"{statistics['conversion_rate']}%."
            ),
            (
                "Average recorded rating: "
                f"{statistics['average_rating']} out of 5."
            ),
            (
                "Requests blocked because of complaints or "
                f"negative feedback: "
                f"{statistics['review_requests_blocked']}."
            ),
        ]
    )