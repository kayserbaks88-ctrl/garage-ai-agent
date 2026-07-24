from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from typing import Any, Iterable

from integrations.customer_history import list_all_customers
from integrations.garage_calendar import (
    _calendar_id,
    _get_calendar_service,
    normalise_phone,
)
from integrations.garage_config import TIMEZONE
from integrations.reminder_sender import send_whatsapp_template


CAMPAIGN_LOOKBACK_DAYS = 730

WIN_BACK_6_MONTH_DAYS = 180
WIN_BACK_12_MONTH_DAYS = 365
WIN_BACK_18_MONTH_DAYS = 548

DEFAULT_CAMPAIGN_COOLDOWN_DAYS = 90
MAX_CAMPAIGN_BATCH_SIZE = 250

TRUE_VALUES = {
    "1",
    "true",
    "yes",
    "done",
    "completed",
}

COMPLETED_VALUES = {
    "1",
    "true",
    "yes",
    "done",
    "complete",
    "completed",
}

OPT_OUT_WORDS = {
    "cancel",
    "do not contact",
    "dont contact",
    "don't contact",
    "no more",
    "opt out",
    "remove me",
    "stop",
    "stop messages",
    "unsubscribe",
}


CAMPAIGN_TYPES = {
    "win_back_6_month": {
        "label": "6 Month Win-back",
        "content_sid_env": (
            "TWILIO_CAMPAIGN_WIN_BACK_6M_CONTENT_SID"
        ),
        "inactive_days": WIN_BACK_6_MONTH_DAYS,
        "variables": (
            "customer_name",
            "last_service",
            "offer_text",
        ),
    },
    "win_back_12_month": {
        "label": "12 Month Win-back",
        "content_sid_env": (
            "TWILIO_CAMPAIGN_WIN_BACK_12M_CONTENT_SID"
        ),
        "inactive_days": WIN_BACK_12_MONTH_DAYS,
        "variables": (
            "customer_name",
            "last_service",
            "offer_text",
        ),
    },
    "win_back_18_month": {
        "label": "18 Month Win-back",
        "content_sid_env": (
            "TWILIO_CAMPAIGN_WIN_BACK_18M_CONTENT_SID"
        ),
        "inactive_days": WIN_BACK_18_MONTH_DAYS,
        "variables": (
            "customer_name",
            "last_service",
            "offer_text",
        ),
    },
    "winter_check": {
        "label": "Winter Vehicle Check",
        "content_sid_env": (
            "TWILIO_CAMPAIGN_WINTER_CHECK_CONTENT_SID"
        ),
        "variables": (
            "customer_name",
            "vehicle",
            "offer_text",
        ),
    },
    "summer_check": {
        "label": "Summer Vehicle Check",
        "content_sid_env": (
            "TWILIO_CAMPAIGN_SUMMER_CHECK_CONTENT_SID"
        ),
        "variables": (
            "customer_name",
            "vehicle",
            "offer_text",
        ),
    },
    "air_conditioning": {
        "label": "Air Conditioning Campaign",
        "content_sid_env": (
            "TWILIO_CAMPAIGN_AIR_CON_CONTENT_SID"
        ),
        "variables": (
            "customer_name",
            "vehicle",
            "offer_text",
        ),
    },
    "battery_check": {
        "label": "Battery Check Campaign",
        "content_sid_env": (
            "TWILIO_CAMPAIGN_BATTERY_CHECK_CONTENT_SID"
        ),
        "variables": (
            "customer_name",
            "vehicle",
            "offer_text",
        ),
    },
    "tyre_check": {
        "label": "Tyre Safety Campaign",
        "content_sid_env": (
            "TWILIO_CAMPAIGN_TYRE_CHECK_CONTENT_SID"
        ),
        "variables": (
            "customer_name",
            "vehicle",
            "offer_text",
        ),
    },
    "vip_loyalty": {
        "label": "VIP Loyalty Campaign",
        "content_sid_env": (
            "TWILIO_CAMPAIGN_VIP_LOYALTY_CONTENT_SID"
        ),
        "variables": (
            "customer_name",
            "completed_visits",
            "offer_text",
        ),
    },
    "custom": {
        "label": "Custom Campaign",
        "content_sid_env": (
            "TWILIO_CAMPAIGN_CUSTOM_CONTENT_SID"
        ),
        "variables": (
            "customer_name",
            "message_title",
            "offer_text",
        ),
    },
}


def _now() -> datetime:
    return datetime.now(TIMEZONE)


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()

    if not value:
        raise ValueError(f"Missing {name}")

    return value


def _optional_env(
    name: str,
    default: str = "",
) -> str:
    return os.getenv(name, default).strip()


def _is_true(value: Any) -> bool:
    return str(value or "").strip().lower() in TRUE_VALUES


def _is_completed(value: Any) -> bool:
    return (
        str(value or "").strip().lower()
        in COMPLETED_VALUES
    )


def _parse_datetime(
    value: Any,
) -> datetime | None:
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
        parsed = parsed.replace(
            tzinfo=TIMEZONE
        )

    return parsed.astimezone(TIMEZONE)


def _parse_date(
    value: Any,
) -> date | None:
    raw_value = str(value or "").strip()

    if not raw_value:
        return None

    try:
        return date.fromisoformat(
            raw_value[:10]
        )
    except ValueError:
        parsed = _parse_datetime(
            raw_value
        )

        return (
            parsed.date()
            if parsed
            else None
        )


def _private_data(
    event: dict[str, Any],
) -> dict[str, Any]:
    return (
        (event.get("extendedProperties") or {})
        .get("private")
        or {}
    )


def _event_start(
    event: dict[str, Any],
) -> datetime | None:
    start = event.get("start") or {}

    return _parse_datetime(
        start.get("dateTime")
        or start.get("date")
        or ""
    )


def _event_end(
    event: dict[str, Any],
) -> datetime | None:
    end = event.get("end") or {}

    return _parse_datetime(
        end.get("dateTime")
        or end.get("date")
        or ""
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


def _money_value(
    value: Any,
) -> float:
    cleaned = (
        str(value or "")
        .replace("£", "")
        .replace(",", "")
        .strip()
    )

    if not cleaned:
        return 0.0

    try:
        return round(
            float(cleaned),
            2,
        )
    except (
        TypeError,
        ValueError,
    ):
        return 0.0


def _normalise_customer(
    customer: dict[str, Any],
) -> dict[str, Any]:
    phone = normalise_phone(
        customer.get("phone")
        or customer.get(
            "customer_phone"
        )
        or ""
    )

    vehicles = customer.get(
        "vehicles"
    ) or []

    if not isinstance(vehicles, list):
        vehicles = []

    first_vehicle = (
        vehicles[0]
        if vehicles
        and isinstance(
            vehicles[0],
            dict,
        )
        else {}
    )

    registration = (
        customer.get("registration")
        or customer.get("vehicle_reg")
        or first_vehicle.get(
            "registration"
        )
        or first_vehicle.get(
            "vehicle_reg"
        )
        or ""
    )

    make = (
        customer.get("vehicle_make")
        or first_vehicle.get("make")
        or ""
    )

    model = (
        customer.get("vehicle_model")
        or first_vehicle.get("model")
        or ""
    )

    vehicle_description = " ".join(
        part
        for part in (
            str(make).strip(),
            str(model).strip(),
        )
        if part
    ).strip()

    if not vehicle_description:
        vehicle_description = (
            _display_registration(
                registration
            )
            or "your vehicle"
        )

    last_visit = (
        customer.get("last_visit")
        or customer.get(
            "latest_visit"
        )
        or customer.get(
            "last_service_date"
        )
        or ""
    )

    return {
        **customer,
        "phone": phone,
        "customer_name": str(
            customer.get(
                "customer_name"
            )
            or customer.get("name")
            or "Customer"
        ).strip(),
        "registration": (
            _display_registration(
                registration
            )
        ),
        "vehicle": (
            vehicle_description
        ),
        "last_visit": (
            _parse_datetime(last_visit)
        ),
        "last_service": str(
            customer.get(
                "last_service"
            )
            or customer.get(
                "last_service_label"
            )
            or "your previous visit"
        ).strip(),
        "completed_visits": int(
            customer.get(
                "completed_visits",
                0,
            )
            or 0
        ),
        "cancelled_visits": int(
            customer.get(
                "cancelled_visits",
                0,
            )
            or 0
        ),
        "no_show_visits": int(
            customer.get(
                "no_show_visits",
                0,
            )
            or 0
        ),
        "total_spent": _money_value(
            customer.get(
                "total_spent",
                0,
            )
        ),
        "vip_customer": bool(
            customer.get(
                "vip_customer"
            )
        ),
        "marketing_opt_out": bool(
            customer.get(
                "marketing_opt_out"
            )
            or customer.get(
                "do_not_contact"
            )
        ),
    }


def _customer_key(
    customer: dict[str, Any],
) -> str:
    phone = str(
        customer.get("phone")
        or ""
    ).strip()

    if phone:
        return phone

    registration = (
        _clean_registration(
            customer.get(
                "registration"
            )
            or ""
        )
    )

    name = str(
        customer.get(
            "customer_name"
        )
        or ""
    ).strip().lower()

    return f"{name}|{registration}"


def _campaign_config(
    campaign_type: str,
) -> dict[str, Any]:
    cleaned_type = str(
        campaign_type or ""
    ).strip().lower()

    config = CAMPAIGN_TYPES.get(
        cleaned_type
    )

    if not config:
        valid_types = ", ".join(
            sorted(
                CAMPAIGN_TYPES.keys()
            )
        )

        raise ValueError(
            "Unknown campaign type "
            f"'{campaign_type}'. "
            f"Valid types: {valid_types}"
        )

    return {
        **config,
        "campaign_type": cleaned_type,
    }


def _campaign_metadata_key(
    campaign_type: str,
    suffix: str,
) -> str:
    cleaned_campaign = "".join(
        character
        if character.isalnum()
        else "_"
        for character in str(
            campaign_type or ""
        ).lower()
    ).strip("_")

    cleaned_suffix = "".join(
        character
        if character.isalnum()
        else "_"
        for character in str(
            suffix or ""
        ).lower()
    ).strip("_")

    return (
        f"campaign_"
        f"{cleaned_campaign}_"
        f"{cleaned_suffix}"
    )


def _fetch_customer_events(
    phone: str,
    current_time: datetime,
) -> list[dict[str, Any]]:
    normalised_phone = (
        normalise_phone(phone)
    )

    if not normalised_phone:
        return []

    time_min = (
        current_time
        - timedelta(
            days=CAMPAIGN_LOOKBACK_DAYS
        )
    )

    time_max = (
        current_time
        + timedelta(days=365)
    )

    service = (
        _get_calendar_service()
    )

    events: list[dict[str, Any]] = []
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
                showDeleted=False,
                maxResults=2500,
                pageToken=page_token,
            )
            .execute()
        )

        for event in result.get(
            "items",
            [],
        ):
            private = _private_data(
                event
            )

            event_phone = (
                normalise_phone(
                    private.get("phone")
                    or private.get(
                        "customer_phone"
                    )
                    or ""
                )
            )

            if (
                event_phone
                == normalised_phone
            ):
                events.append(event)

        page_token = result.get(
            "nextPageToken"
        )

        if not page_token:
            break

    return events


def _latest_customer_event(
    phone: str,
    current_time: datetime,
) -> dict[str, Any] | None:
    events = _fetch_customer_events(
        phone=phone,
        current_time=current_time,
    )

    if not events:
        return None

    dated_events = [
        event
        for event in events
        if _event_start(event)
    ]

    if not dated_events:
        return events[-1]

    dated_events.sort(
        key=lambda event: (
            _event_start(event)
            or datetime.min.replace(
                tzinfo=TIMEZONE
            )
        ),
        reverse=True,
    )

    return dated_events[0]


def _update_event_private_data(
    event: dict[str, Any],
    updates: dict[str, Any],
) -> dict[str, Any]:
    event_id = str(
        event.get("id") or ""
    ).strip()

    if not event_id:
        raise ValueError(
            "Missing Google Calendar event ID"
        )

    extended_properties = (
        event.get(
            "extendedProperties"
        )
        or {}
    )

    private = (
        extended_properties.get(
            "private"
        )
        or {}
    )

    for key, value in updates.items():
        private[str(key)] = str(value)

    extended_properties[
        "private"
    ] = private

    event[
        "extendedProperties"
    ] = extended_properties

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


def _last_campaign_sent_at(
    event: dict[str, Any] | None,
    campaign_type: str,
) -> datetime | None:
    if not event:
        return None

    private = _private_data(
        event
    )

    metadata_key = (
        _campaign_metadata_key(
            campaign_type,
            "sent_at",
        )
    )

    return _parse_datetime(
        private.get(metadata_key)
        or ""
    )


def _customer_is_eligible(
    customer: dict[str, Any],
    campaign_type: str,
    current_time: datetime,
    cooldown_days: int,
    force: bool = False,
) -> tuple[bool, str]:
    if not customer.get("phone"):
        return (
            False,
            "missing_phone",
        )

    if (
        customer.get(
            "marketing_opt_out"
        )
        and not force
    ):
        return (
            False,
            "marketing_opt_out",
        )

    config = _campaign_config(
        campaign_type
    )

    inactive_days = config.get(
        "inactive_days"
    )

    if (
        inactive_days is not None
        and not force
    ):
        last_visit = customer.get(
            "last_visit"
        )

        if not last_visit:
            return (
                False,
                "missing_last_visit",
            )

        days_inactive = (
            current_time.date()
            - last_visit.date()
        ).days

        if (
            days_inactive
            < int(inactive_days)
        ):
            return (
                False,
                "not_inactive_long_enough",
            )

    if (
        campaign_type == "vip_loyalty"
        and not force
    ):
        is_vip = bool(
            customer.get(
                "vip_customer"
            )
            or customer.get(
                "completed_visits",
                0,
            )
            >= 5
            or customer.get(
                "total_spent",
                0.0,
            )
            >= 750.0
        )

        if not is_vip:
            return (
                False,
                "not_vip",
            )

    latest_event = (
        _latest_customer_event(
            phone=customer["phone"],
            current_time=current_time,
        )
    )

    last_sent = (
        _last_campaign_sent_at(
            event=latest_event,
            campaign_type=campaign_type,
        )
    )

    if last_sent and not force:
        next_allowed = (
            last_sent
            + timedelta(
                days=cooldown_days
            )
        )

        if current_time < next_allowed:
            return (
                False,
                "campaign_cooldown",
            )

    return True, "eligible"


def _build_template_variables(
    customer: dict[str, Any],
    campaign_type: str,
    offer_text: str,
    message_title: str,
) -> dict[str, str]:
    config = _campaign_config(
        campaign_type
    )

    values = {
        "customer_name": (
            customer.get(
                "customer_name"
            )
            or "Customer"
        ),
        "last_service": (
            customer.get(
                "last_service"
            )
            or "your previous visit"
        ),
        "vehicle": (
            customer.get("vehicle")
            or "your vehicle"
        ),
        "registration": (
            customer.get(
                "registration"
            )
            or ""
        ),
        "completed_visits": str(
            customer.get(
                "completed_visits",
                0,
            )
        ),
        "offer_text": (
            offer_text
            or "Contact us to book."
        ),
        "message_title": (
            message_title
            or config["label"]
        ),
    }

    variable_names = config.get(
        "variables",
        (),
    )

    return {
        str(index): str(
            values.get(
                variable_name,
                "",
            )
        )
        for index, variable_name
        in enumerate(
            variable_names,
            start=1,
        )
    }


def send_campaign_message(
    customer: dict[str, Any],
    campaign_type: str,
    offer_text: str = "",
    message_title: str = "",
    current_time: datetime | None = None,
    force: bool = False,
    cooldown_days: int = (
        DEFAULT_CAMPAIGN_COOLDOWN_DAYS
    ),
) -> dict[str, Any] | None:
    now = (
        current_time.astimezone(
            TIMEZONE
        )
        if current_time
        else _now()
    )

    normalised_customer = (
        _normalise_customer(
            customer
        )
    )

    eligible, reason = (
        _customer_is_eligible(
            customer=normalised_customer,
            campaign_type=campaign_type,
            current_time=now,
            cooldown_days=int(
                cooldown_days
            ),
            force=force,
        )
    )

    if not eligible:
        return None

    config = _campaign_config(
        campaign_type
    )

    content_sid = _required_env(
        config[
            "content_sid_env"
        ]
    )

    variables = (
        _build_template_variables(
            customer=normalised_customer,
            campaign_type=campaign_type,
            offer_text=offer_text,
            message_title=message_title,
        )
    )

    result = send_whatsapp_template(
        phone=normalised_customer[
            "phone"
        ],
        content_sid=content_sid,
        variables=variables,
    )

    sent_at = now.isoformat()
    message_sid = str(
        result.get("sid") or ""
    )

    latest_event = (
        _latest_customer_event(
            phone=normalised_customer[
                "phone"
            ],
            current_time=now,
        )
    )

    metadata_saved = False

    if latest_event:
        _update_event_private_data(
            event=latest_event,
            updates={
                _campaign_metadata_key(
                    campaign_type,
                    "sent_at",
                ): sent_at,
                _campaign_metadata_key(
                    campaign_type,
                    "message_sid",
                ): message_sid,
                _campaign_metadata_key(
                    campaign_type,
                    "offer",
                ): offer_text,
                "last_campaign_type": (
                    campaign_type
                ),
                "last_campaign_sent_at": (
                    sent_at
                ),
                "last_campaign_message_sid": (
                    message_sid
                ),
            },
        )

        metadata_saved = True

    return {
        "success": True,
        "type": "campaign",
        "campaign_type": (
            campaign_type
        ),
        "campaign_label": (
            config["label"]
        ),
        "customer_key": (
            _customer_key(
                normalised_customer
            )
        ),
        "customer_name": (
            normalised_customer[
                "customer_name"
            ]
        ),
        "phone": (
            normalised_customer[
                "phone"
            ]
        ),
        "registration": (
            normalised_customer[
                "registration"
            ]
        ),
        "vehicle": (
            normalised_customer[
                "vehicle"
            ]
        ),
        "message_sid": (
            message_sid
        ),
        "offer_text": (
            offer_text
        ),
        "sent_at": (
            sent_at
        ),
        "metadata_saved": (
            metadata_saved
        ),
        "eligibility_reason": (
            reason
        ),
    }


def get_campaign_audience(
    campaign_type: str,
    current_time: datetime | None = None,
    cooldown_days: int = (
        DEFAULT_CAMPAIGN_COOLDOWN_DAYS
    ),
    limit: int = (
        MAX_CAMPAIGN_BATCH_SIZE
    ),
    force: bool = False,
) -> list[dict[str, Any]]:
    now = (
        current_time.astimezone(
            TIMEZONE
        )
        if current_time
        else _now()
    )

    _campaign_config(
        campaign_type
    )

    raw_customers = (
        list_all_customers()
    )

    customers = [
        _normalise_customer(
            customer
        )
        for customer in raw_customers
        if isinstance(
            customer,
            dict,
        )
    ]

    audience: list[
        dict[str, Any]
    ] = []

    seen_keys: set[str] = set()

    for customer in customers:
        customer_key = (
            _customer_key(customer)
        )

        if (
            not customer_key
            or customer_key
            in seen_keys
        ):
            continue

        seen_keys.add(
            customer_key
        )

        eligible, reason = (
            _customer_is_eligible(
                customer=customer,
                campaign_type=(
                    campaign_type
                ),
                current_time=now,
                cooldown_days=int(
                    cooldown_days
                ),
                force=force,
            )
        )

        if not eligible:
            continue

        last_visit = customer.get(
            "last_visit"
        )

        days_inactive = (
            (
                now.date()
                - last_visit.date()
            ).days
            if last_visit
            else None
        )

        audience.append(
            {
                **customer,
                "customer_key": (
                    customer_key
                ),
                "campaign_type": (
                    campaign_type
                ),
                "eligibility_reason": (
                    reason
                ),
                "days_inactive": (
                    days_inactive
                ),
            }
        )

    audience.sort(
        key=lambda customer: (
            customer.get(
                "days_inactive"
            )
            if customer.get(
                "days_inactive"
            )
            is not None
            else -1
        ),
        reverse=True,
    )

    batch_limit = max(
        1,
        min(
            int(limit),
            MAX_CAMPAIGN_BATCH_SIZE,
        ),
    )

    return audience[
        :batch_limit
    ]


def run_campaign(
    campaign_type: str,
    offer_text: str = "",
    message_title: str = "",
    current_time: datetime | None = None,
    cooldown_days: int = (
        DEFAULT_CAMPAIGN_COOLDOWN_DAYS
    ),
    limit: int = (
        MAX_CAMPAIGN_BATCH_SIZE
    ),
    dry_run: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    now = (
        current_time.astimezone(
            TIMEZONE
        )
        if current_time
        else _now()
    )

    config = _campaign_config(
        campaign_type
    )

    audience = get_campaign_audience(
        campaign_type=campaign_type,
        current_time=now,
        cooldown_days=(
            cooldown_days
        ),
        limit=limit,
        force=force,
    )

    if dry_run:
        return {
            "success": True,
            "dry_run": True,
            "campaign_type": (
                campaign_type
            ),
            "campaign_label": (
                config["label"]
            ),
            "eligible_count": len(
                audience
            ),
            "audience": [
                {
                    "customer_name": (
                        customer[
                            "customer_name"
                        ]
                    ),
                    "phone": (
                        customer["phone"]
                    ),
                    "vehicle": (
                        customer["vehicle"]
                    ),
                    "registration": (
                        customer[
                            "registration"
                        ]
                    ),
                    "last_visit": (
                        customer[
                            "last_visit"
                        ].isoformat()
                        if customer.get(
                            "last_visit"
                        )
                        else ""
                    ),
                    "days_inactive": (
                        customer.get(
                            "days_inactive"
                        )
                    ),
                }
                for customer
                in audience
            ],
            "generated_at": (
                now.isoformat()
            ),
        }

    sent: list[
        dict[str, Any]
    ] = []

    skipped: list[
        dict[str, Any]
    ] = []

    errors: list[
        dict[str, Any]
    ] = []

    for customer in audience:
        try:
            result = (
                send_campaign_message(
                    customer=customer,
                    campaign_type=(
                        campaign_type
                    ),
                    offer_text=(
                        offer_text
                    ),
                    message_title=(
                        message_title
                    ),
                    current_time=now,
                    force=force,
                    cooldown_days=(
                        cooldown_days
                    ),
                )
            )

            if result:
                sent.append(result)
            else:
                skipped.append(
                    {
                        "customer_name": (
                            customer[
                                "customer_name"
                            ]
                        ),
                        "phone": (
                            customer["phone"]
                        ),
                        "reason": (
                            "not_sent"
                        ),
                    }
                )

        except Exception as error:
            error_record = {
                "customer_name": (
                    customer.get(
                        "customer_name",
                        "",
                    )
                ),
                "phone": (
                    customer.get(
                        "phone",
                        "",
                    )
                ),
                "error": repr(error),
            }

            errors.append(
                error_record
            )

            print(
                "CAMPAIGN SEND ERROR:",
                error_record,
            )

    summary = {
        "success": (
            len(errors) == 0
        ),
        "dry_run": False,
        "campaign_type": (
            campaign_type
        ),
        "campaign_label": (
            config["label"]
        ),
        "audience_count": len(
            audience
        ),
        "sent_count": len(
            sent
        ),
        "sent": sent,
        "skipped_count": len(
            skipped
        ),
        "skipped": skipped,
        "error_count": len(
            errors
        ),
        "errors": errors,
        "offer_text": (
            offer_text
        ),
        "completed_at": (
            now.isoformat()
        ),
    }

    print(
        "CAMPAIGN COMPLETE:",
        summary,
    )

    return summary


def run_win_back_campaign(
    months: int,
    offer_text: str = "",
    current_time: datetime | None = None,
    limit: int = (
        MAX_CAMPAIGN_BATCH_SIZE
    ),
    dry_run: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    campaign_map = {
        6: "win_back_6_month",
        12: "win_back_12_month",
        18: "win_back_18_month",
    }

    campaign_type = (
        campaign_map.get(
            int(months)
        )
    )

    if not campaign_type:
        raise ValueError(
            "months must be 6, 12 or 18"
        )

    default_offer = {
        6: (
            "Contact us to arrange your "
            "next vehicle check."
        ),
        12: (
            "Contact us to arrange your "
            "annual service."
        ),
        18: (
            "We would love to welcome "
            "you back. Contact us to book."
        ),
    }

    return run_campaign(
        campaign_type=campaign_type,
        offer_text=(
            offer_text
            or default_offer[
                int(months)
            ]
        ),
        current_time=current_time,
        limit=limit,
        dry_run=dry_run,
        force=force,
    )


def run_vip_loyalty_campaign(
    offer_text: str = "",
    current_time: datetime | None = None,
    limit: int = (
        MAX_CAMPAIGN_BATCH_SIZE
    ),
    dry_run: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    return run_campaign(
        campaign_type=(
            "vip_loyalty"
        ),
        offer_text=(
            offer_text
            or (
                "As a valued customer, "
                "contact us to arrange your "
                "complimentary vehicle check."
            )
        ),
        current_time=current_time,
        limit=limit,
        dry_run=dry_run,
        force=force,
    )


def run_seasonal_campaign(
    season: str,
    offer_text: str = "",
    current_time: datetime | None = None,
    limit: int = (
        MAX_CAMPAIGN_BATCH_SIZE
    ),
    dry_run: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    cleaned_season = str(
        season or ""
    ).strip().lower()

    campaign_map = {
        "winter": "winter_check",
        "summer": "summer_check",
        "air con": "air_conditioning",
        "air conditioning": (
            "air_conditioning"
        ),
        "battery": "battery_check",
        "tyre": "tyre_check",
        "tyres": "tyre_check",
    }

    campaign_type = (
        campaign_map.get(
            cleaned_season
        )
    )

    if not campaign_type:
        valid = ", ".join(
            sorted(
                campaign_map.keys()
            )
        )

        raise ValueError(
            "Unknown seasonal campaign. "
            f"Valid values: {valid}"
        )

    default_offers = {
        "winter_check": (
            "Book a winter vehicle health "
            "check with us."
        ),
        "summer_check": (
            "Book a summer vehicle health "
            "check with us."
        ),
        "air_conditioning": (
            "Contact us to arrange an air "
            "conditioning check."
        ),
        "battery_check": (
            "Contact us to arrange a battery "
            "and charging-system check."
        ),
        "tyre_check": (
            "Contact us to arrange a tyre "
            "safety check."
        ),
    }

    return run_campaign(
        campaign_type=campaign_type,
        offer_text=(
            offer_text
            or default_offers[
                campaign_type
            ]
        ),
        current_time=current_time,
        limit=limit,
        dry_run=dry_run,
        force=force,
    )


def record_marketing_opt_out(
    phone: str,
    reason: str = "",
    current_time: datetime | None = None,
) -> dict[str, Any]:
    now = (
        current_time.astimezone(
            TIMEZONE
        )
        if current_time
        else _now()
    )

    normalised_phone = (
        normalise_phone(phone)
    )

    if not normalised_phone:
        raise ValueError(
            "A valid phone number is required"
        )

    event = _latest_customer_event(
        phone=normalised_phone,
        current_time=now,
    )

    if not event:
        return {
            "success": False,
            "phone": normalised_phone,
            "error": (
                "customer_event_not_found"
            ),
        }

    _update_event_private_data(
        event=event,
        updates={
            "marketing_opt_out": (
                "true"
            ),
            "marketing_opt_out_at": (
                now.isoformat()
            ),
            "marketing_opt_out_reason": (
                str(reason or "").strip()
            ),
        },
    )

    return {
        "success": True,
        "phone": normalised_phone,
        "marketing_opt_out": True,
        "reason": str(
            reason or ""
        ).strip(),
        "recorded_at": (
            now.isoformat()
        ),
    }


def remove_marketing_opt_out(
    phone: str,
    current_time: datetime | None = None,
) -> dict[str, Any]:
    now = (
        current_time.astimezone(
            TIMEZONE
        )
        if current_time
        else _now()
    )

    normalised_phone = (
        normalise_phone(phone)
    )

    if not normalised_phone:
        raise ValueError(
            "A valid phone number is required"
        )

    event = _latest_customer_event(
        phone=normalised_phone,
        current_time=now,
    )

    if not event:
        return {
            "success": False,
            "phone": normalised_phone,
            "error": (
                "customer_event_not_found"
            ),
        }

    _update_event_private_data(
        event=event,
        updates={
            "marketing_opt_out": (
                "false"
            ),
            "marketing_opt_in_at": (
                now.isoformat()
            ),
        },
    )

    return {
        "success": True,
        "phone": normalised_phone,
        "marketing_opt_out": False,
        "recorded_at": (
            now.isoformat()
        ),
    }


def detect_marketing_opt_out(
    message: str,
) -> bool:
    cleaned = " ".join(
        str(message or "")
        .lower()
        .strip()
        .split()
    )

    if not cleaned:
        return False

    return any(
        phrase in cleaned
        for phrase in OPT_OUT_WORDS
    )


def process_marketing_reply(
    phone: str,
    message: str,
) -> dict[str, Any]:
    if detect_marketing_opt_out(
        message
    ):
        return record_marketing_opt_out(
            phone=phone,
            reason=(
                "Customer requested opt-out "
                f"by message: {message}"
            ),
        )

    return {
        "success": True,
        "phone": normalise_phone(
            phone
        ),
        "marketing_opt_out": False,
        "action": "no_change",
    }


def get_campaign_statistics(
    days: int = 30,
    current_time: datetime | None = None,
) -> dict[str, Any]:
    now = (
        current_time.astimezone(
            TIMEZONE
        )
        if current_time
        else _now()
    )

    selected_days = max(
        1,
        min(
            int(days),
            CAMPAIGN_LOOKBACK_DAYS,
        ),
    )

    start_time = (
        now
        - timedelta(
            days=selected_days
        )
    )

    service = (
        _get_calendar_service()
    )

    events: list[
        dict[str, Any]
    ] = []

    page_token: str | None = None

    while True:
        result = (
            service.events()
            .list(
                calendarId=_calendar_id(),
                timeMin=start_time.isoformat(),
                timeMax=(
                    now
                    + timedelta(days=1)
                ).isoformat(),
                singleEvents=True,
                orderBy="startTime",
                showDeleted=False,
                maxResults=2500,
                pageToken=page_token,
            )
            .execute()
        )

        events.extend(
            result.get(
                "items",
                [],
            )
        )

        page_token = result.get(
            "nextPageToken"
        )

        if not page_token:
            break

    sent_by_type: dict[
        str,
        int,
    ] = {
        campaign_type: 0
        for campaign_type
        in CAMPAIGN_TYPES
    }

    total_sent = 0
    opt_outs = 0
    customers_contacted: set[
        str
    ] = set()

    for event in events:
        private = _private_data(
            event
        )

        phone = normalise_phone(
            private.get("phone")
            or ""
        )

        if _is_true(
            private.get(
                "marketing_opt_out"
            )
        ):
            opt_out_at = (
                _parse_datetime(
                    private.get(
                        "marketing_opt_out_at"
                    )
                )
            )

            if (
                not opt_out_at
                or opt_out_at
                >= start_time
            ):
                opt_outs += 1

        for campaign_type in (
            CAMPAIGN_TYPES.keys()
        ):
            sent_key = (
                _campaign_metadata_key(
                    campaign_type,
                    "sent_at",
                )
            )

            sent_at = _parse_datetime(
                private.get(
                    sent_key
                )
                or ""
            )

            if (
                sent_at
                and sent_at
                >= start_time
            ):
                sent_by_type[
                    campaign_type
                ] += 1

                total_sent += 1

                if phone:
                    customers_contacted.add(
                        phone
                    )

    return {
        "success": True,
        "period_days": (
            selected_days
        ),
        "campaign_messages_sent": (
            total_sent
        ),
        "unique_customers_contacted": (
            len(
                customers_contacted
            )
        ),
        "marketing_opt_outs": (
            opt_outs
        ),
        "sent_by_type": (
            sent_by_type
        ),
        "generated_at": (
            now.isoformat()
        ),
    }


def get_campaign_dashboard_summary(
    current_time: datetime | None = None,
) -> dict[str, Any]:
    now = (
        current_time.astimezone(
            TIMEZONE
        )
        if current_time
        else _now()
    )

    win_back_6 = (
        get_campaign_audience(
            campaign_type=(
                "win_back_6_month"
            ),
            current_time=now,
            limit=(
                MAX_CAMPAIGN_BATCH_SIZE
            ),
        )
    )

    win_back_12 = (
        get_campaign_audience(
            campaign_type=(
                "win_back_12_month"
            ),
            current_time=now,
            limit=(
                MAX_CAMPAIGN_BATCH_SIZE
            ),
        )
    )

    win_back_18 = (
        get_campaign_audience(
            campaign_type=(
                "win_back_18_month"
            ),
            current_time=now,
            limit=(
                MAX_CAMPAIGN_BATCH_SIZE
            ),
        )
    )

    vip_audience = (
        get_campaign_audience(
            campaign_type=(
                "vip_loyalty"
            ),
            current_time=now,
            limit=(
                MAX_CAMPAIGN_BATCH_SIZE
            ),
        )
    )

    statistics = (
        get_campaign_statistics(
            days=30,
            current_time=now,
        )
    )

    return {
        "success": True,
        "eligible_audiences": {
            "win_back_6_month": len(
                win_back_6
            ),
            "win_back_12_month": len(
                win_back_12
            ),
            "win_back_18_month": len(
                win_back_18
            ),
            "vip_loyalty": len(
                vip_audience
            ),
        },
        "last_30_days": (
            statistics
        ),
        "generated_at": (
            now.isoformat()
        ),
    }


def format_campaign_summary_for_ai(
    current_time: datetime | None = None,
) -> str:
    summary = (
        get_campaign_dashboard_summary(
            current_time=current_time
        )
    )

    audiences = summary[
        "eligible_audiences"
    ]

    statistics = summary[
        "last_30_days"
    ]

    return "\n".join(
        [
            (
                "Garage marketing campaign "
                "summary:"
            ),
            (
                "Customers eligible for a "
                "6-month win-back campaign: "
                f"{audiences['win_back_6_month']}."
            ),
            (
                "Customers eligible for a "
                "12-month win-back campaign: "
                f"{audiences['win_back_12_month']}."
            ),
            (
                "Customers eligible for an "
                "18-month win-back campaign: "
                f"{audiences['win_back_18_month']}."
            ),
            (
                "VIP customers eligible for "
                "a loyalty campaign: "
                f"{audiences['vip_loyalty']}."
            ),
            (
                "Campaign messages sent in "
                "the last 30 days: "
                f"{statistics['campaign_messages_sent']}."
            ),
            (
                "Unique customers contacted "
                "in the last 30 days: "
                f"{statistics['unique_customers_contacted']}."
            ),
            (
                "Marketing opt-outs recorded "
                "in the last 30 days: "
                f"{statistics['marketing_opt_outs']}."
            ),
        ]
    )