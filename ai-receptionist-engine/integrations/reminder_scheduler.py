from __future__ import annotations

import os
from typing import Any

from flask import Blueprint, jsonify, request

from integrations.reminder_service import process_reminders


reminder_scheduler_bp = Blueprint(
    "reminder_scheduler",
    __name__,
)


def _cron_secret() -> str:
    """
    Secret used to protect the reminder endpoint.

    Add REMINDER_CRON_SECRET to Render before activating the scheduler.
    """
    return os.getenv("REMINDER_CRON_SECRET", "").strip()


def _request_is_authorised() -> bool:
    """
    Accept the secret in either:

    Authorization: Bearer YOUR_SECRET

    or:

    X-Cron-Secret: YOUR_SECRET
    """
    expected_secret = _cron_secret()

    if not expected_secret:
        print(
            "REMINDER SCHEDULER ERROR: "
            "REMINDER_CRON_SECRET is missing"
        )
        return False

    auth_header = request.headers.get(
        "Authorization",
        "",
    ).strip()

    custom_header = request.headers.get(
        "X-Cron-Secret",
        "",
    ).strip()

    bearer_secret = ""

    if auth_header.lower().startswith("bearer "):
        bearer_secret = auth_header[7:].strip()

    return (
        bearer_secret == expected_secret
        or custom_header == expected_secret
    )


def run_reminder_job() -> dict[str, Any]:
    """
    Run one complete reminder check.

    This can be called by:
    - the protected Flask endpoint
    - a manual test
    - a future background worker
    """
    try:
        result = process_reminders()

        return {
            "success": True,
            **result,
        }

    except Exception as error:
        print(
            "REMINDER SCHEDULER FAILED:",
            repr(error),
        )

        return {
            "success": False,
            "error": repr(error),
        }


@reminder_scheduler_bp.route(
    "/internal/run-reminders",
    methods=["GET", "POST"],
)
def run_reminders_endpoint():
    """
    Protected endpoint called by the scheduled job.
    """
    if not _request_is_authorised():
        return (
            jsonify(
                {
                    "success": False,
                    "error": "unauthorised",
                }
            ),
            401,
        )

    result = run_reminder_job()

    status_code = 200 if result["success"] else 500

    return jsonify(result), status_code


@reminder_scheduler_bp.route(
    "/internal/reminder-health",
    methods=["GET"],
)
def reminder_health_endpoint():
    """
    Simple health check.

    This does not send reminders.
    """
    return jsonify(
        {
            "success": True,
            "service": "garage-reminder-scheduler",
            "cron_secret_configured": bool(
                _cron_secret()
            ),
        }
    )