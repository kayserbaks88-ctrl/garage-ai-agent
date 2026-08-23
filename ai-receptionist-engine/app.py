from __future__ import annotations

import hmac
import importlib
import json
import os
from datetime import datetime, timedelta

from dotenv import load_dotenv
from flask import Flask, jsonify, request, render_template, session
from twilio.twiml.messaging_response import MessagingResponse
from trimtech.integrations.vapi import vapi_bp
from trimtech.modules.onboarding import onboarding_blueprint
from trimtech.modules.platform import platform_blueprint
from trimtech.core.registry import load_business_instance
from trimtech.modules.auth import auth_blueprint
from trimtech.modules.auth.routes import (
    business_access_required,
)

load_dotenv()

from engine import BUSINESS
from integrations.garage_config import TIMEZONE
from integrations.garage_voice_agent import (
    handle_voice_process,
    handle_voice_start,
)

from dashboard_api import dashboard_api
from dashboard_auth import (
    dashboard_auth,
    dashboard_login_required,
)

app = Flask(__name__)

# =========================================================
# Secure dashboard session configuration
# =========================================================

_flask_secret_key = (
    os.getenv("FLASK_SECRET_KEY", "").strip()
    or os.getenv("SECRET_KEY", "").strip()
)

if not _flask_secret_key:
    raise RuntimeError(
        "FLASK_SECRET_KEY is missing. Add a long random value in Render "
        "before starting the service."
    )

app.config.update(
    SECRET_KEY=_flask_secret_key,
    PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_SAMESITE="Lax",
)

app.register_blueprint(dashboard_auth)
app.register_blueprint(dashboard_api)
app.register_blueprint(vapi_bp)
app.register_blueprint(auth_blueprint)
app.register_blueprint(onboarding_blueprint)
app.register_blueprint(platform_blueprint)

# =========================================================
# Health check
# =========================================================

@app.route("/", methods=["GET"])
def home():
    return jsonify(
        {
            "ok": True,
            "service": "TrimTech AI Receptionist",
            "business": BUSINESS,
        }
    )


# =========================================================
# WhatsApp
# =========================================================

@app.route("/whatsapp", methods=["POST"])
def whatsapp():
    incoming = request.values.get("Body", "")
    phone = request.values.get("From", "")
    profile_name = request.values.get("ProfileName", "")

    if BUSINESS == "garage":
        from integrations.garage_agent import handle_message

        reply = handle_message(incoming, phone, profile_name)

    elif BUSINESS == "barber":
        from integrations.barber_agent import handle_message

        reply = handle_message(incoming, phone, profile_name)

    elif BUSINESS == "lead_gen":
        from integrations.lead_gen_agent import handle_message

        reply = handle_message(incoming, phone, profile_name)

    elif BUSINESS == "quote_builder":
        from integrations.quote_builder_agent import handle_message

        num_media = int(request.values.get("NumMedia", 0))
        media_urls = []

        for index in range(num_media):
            media_url = request.values.get(f"MediaUrl{index}")
            if media_url:
                media_urls.append(media_url)

        reply = handle_message(
            phone=phone,
            text=incoming,
            profile_name=profile_name,
            media_urls=media_urls,
        )

    elif BUSINESS == "staff_manager":
        from integrations.staff_manager_agent import handle_message

        num_media = int(request.values.get("NumMedia", 0))
        media_urls = []

        for index in range(num_media):
            media_url = request.values.get(f"MediaUrl{index}")
            if media_url:
                media_urls.append(media_url)

        reply = handle_message(
            phone=phone,
            text=incoming.strip(),
            profile_name=profile_name,
            media_urls=media_urls,
            location={
                "latitude": request.values.get("Latitude", ""),
                "longitude": request.values.get("Longitude", ""),
            },
        )

    else:
        reply = "Sorry, this service is not currently available."

    response = MessagingResponse()
    response.message(reply)

    return str(response)


# =========================================================
# Existing Twilio voice routes
# =========================================================

@app.route("/voice", methods=["POST"])
def voice():
    call_sid = request.values.get("CallSid", "")
    caller_number = request.values.get("From", "")

    return handle_voice_start(call_sid, caller_number)


@app.route("/voice/process", methods=["POST"])
def voice_process():
    call_sid = request.values.get("CallSid", "")
    caller_number = request.values.get("From", "")
    speech_text = request.values.get("SpeechResult", "")

    return handle_voice_process(
        call_sid=call_sid,
        caller_number=caller_number,
        speech_text=speech_text,
    )


def _configured_secret(*names: str) -> str:
    """Return the first configured secret from the supplied environment names."""
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


def _request_secret() -> str:
    """Read a private API token from a bearer header or X-Internal-Token."""
    authorization = request.headers.get("Authorization", "").strip()

    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()

    return request.headers.get("X-Internal-Token", "").strip()


def _require_private_access():
    """
    Protect internal automation, dashboard and campaign routes.

    Configure either:
      INTERNAL_API_TOKEN
      SCHEDULER_SECRET
      DASHBOARD_API_KEY
    """
    expected = _configured_secret(
        "REMINDER_CRON_SECRET",
        "INTERNAL_API_TOKEN",
        "SCHEDULER_SECRET",
        "DASHBOARD_API_KEY",
    )

    if not expected:
        return jsonify(
            {
                "success": False,
                "error": "private_api_not_configured",
                "message": (
                    "Set INTERNAL_API_TOKEN in Render before using "
                    "private TrimTech routes."
                ),
            }
        ), 503

    supplied = _request_secret()

    if not supplied or not hmac.compare_digest(supplied, expected):
        return jsonify(
            {
                "success": False,
                "error": "unauthorised",
            }
        ), 401

    return None


def _json_payload() -> dict:
    payload = request.get_json(silent=True)
    return payload if isinstance(payload, dict) else {}


def _load_callable(module_name: str, function_names: tuple[str, ...]):
    """
    Load the first available function from a module.

    This keeps app.py compatible with the exact function naming used in the
    saved automation modules while still failing clearly when a module is
    incomplete.
    """
    module = importlib.import_module(module_name)

    for function_name in function_names:
        function = getattr(module, function_name, None)
        if callable(function):
            return function

    raise AttributeError(
        f"{module_name} does not provide any of: {', '.join(function_names)}"
    )


def _run_automation(
    label: str,
    module_name: str,
    function_names: tuple[str, ...],
) -> dict:
    try:
        function = _load_callable(module_name, function_names)
        result = function()

        return {
            "success": True,
            "automation": label,
            "result": result,
        }

    except Exception as error:
        print(
            "AUTOMATION ERROR:",
            {
                "automation": label,
                "module": module_name,
                "error": repr(error),
            },
        )

        return {
            "success": False,
            "automation": label,
            "error": repr(error),
        }


def _register_optional_reminder_blueprint() -> None:
    """
    Register reminder_scheduler_bp when the saved reminder module exposes it.

    The manual/private scheduler endpoints below remain available even when
    the module does not use a Flask Blueprint.
    """
    try:
        module = importlib.import_module("trimtech.modules.reminders.reminder_scheduler")
        blueprint = getattr(module, "reminder_scheduler_bp", None)

        if blueprint is not None and blueprint.name not in app.blueprints:
            app.register_blueprint(blueprint)
            

    except Exception as error:
        print("REMINDER BLUEPRINT NOT REGISTERED:", repr(error))


_register_optional_reminder_blueprint()


# =========================================================
# Private automation routes
# =========================================================

@app.route("/internal/run/automations", methods=["POST"])
def run_all_automations():
    denied = _require_private_access()
    if denied:
        return denied

    jobs = (
        (
            "appointment_reminders",
            "trimtech.modules.reminders.reminder_scheduler",
            (
                "process_appointment_reminders",
                "process_reminders",
                "run_reminders",
                "process_due_reminders",
            ),
        ),
        (
            "customer_care",
            "integrations.customer_care",
            (
                "process_customer_care",
            ),
        ),
        (
            "review_reminders",
            "integrations.review_request",
            (
                "process_review_reminders",
            ),
        ),
        (
            "mot_reminders",
            "trimtech.integrations.mot_reminders",
            (
                "process_mot_reminders",
                "process_due_mot_reminders",
            ),
        ),
        (
            "vehicle_reminders",
            "integrations.vehicle_reminders",
            (
                "process_vehicle_reminders",
                "process_service_reminders",
                "process_due_vehicle_reminders",
            ),
        ),
    )

    results = [
        _run_automation(label, module_name, function_names)
        for label, module_name, function_names in jobs
    ]

    return jsonify(
        {
            "success": all(item["success"] for item in results),
            "results": results,
            "ran_at": datetime.now(TIMEZONE).isoformat(),
        }
    ), 200


@app.route("/internal/run/reminders", methods=["POST"])
@app.route("/internal/run-reminders", methods=["POST"])
def run_appointment_reminders():
    denied = _require_private_access()
    if denied:
        return denied

    result = _run_automation(
        "appointment_reminders",
        "trimtech.integrations.reminder_scheduler",
        (
            "process_appointment_reminders",
            "process_reminders",
            "run_reminders",
            "process_due_reminders",
        ),
    )

    return jsonify(result), 200 if result["success"] else 500


@app.route("/internal/run/customer-care", methods=["POST"])
def run_customer_care():
    denied = _require_private_access()
    if denied:
        return denied

    result = _run_automation(
        "customer_care",
        "integrations.customer_care",
        ("process_customer_care",),
    )

    return jsonify(result), 200 if result["success"] else 500


@app.route("/internal/run/review-reminders", methods=["POST"])
def run_review_reminders():
    denied = _require_private_access()
    if denied:
        return denied

    result = _run_automation(
        "review_reminders",
        "integrations.review_request",
        ("process_review_reminders",),
    )

    return jsonify(result), 200 if result["success"] else 500


@app.route("/internal/run/mot-reminders", methods=["POST"])
def run_mot_reminders():
    denied = _require_private_access()
    if denied:
        return denied

    result = _run_automation(
        "mot_reminders",
        "trimtech.integrations.mot_reminders",
        (
            "process_mot_reminders",
            "process_due_mot_reminders",
        ),
    )

    return jsonify(result), 200 if result["success"] else 500


@app.route("/internal/run/vehicle-reminders", methods=["POST"])
def run_vehicle_reminders():
    denied = _require_private_access()
    if denied:
        return denied

    result = _run_automation(
        "vehicle_reminders",
        "integrations.vehicle_reminders",
        (
            "process_vehicle_reminders",
            "process_service_reminders",
            "process_due_vehicle_reminders",
        ),
    )

    return jsonify(result), 200 if result["success"] else 500


# =========================================================
# Private dashboard and reporting API
# =========================================================

@app.route("/api/dashboard/summary", methods=["GET"])
def dashboard_summary():
    denied = _require_private_access()
    if denied:
        return denied

    try:
        from integrations.garage_reports import get_dashboard_summary

        return jsonify(get_dashboard_summary()), 200

    except Exception as error:
        print("DASHBOARD SUMMARY ERROR:", repr(error))
        return jsonify(
            {
                "success": False,
                "error": "dashboard_summary_failed",
            }
        ), 500


@app.route("/api/dashboard/morning-briefing", methods=["GET"])
def dashboard_morning_briefing():
    denied = _require_private_access()
    if denied:
        return denied

    try:
        from integrations.garage_reports import get_owner_morning_briefing

        return jsonify(get_owner_morning_briefing()), 200

    except Exception as error:
        print("MORNING BRIEFING ERROR:", repr(error))
        return jsonify(
            {
                "success": False,
                "error": "morning_briefing_failed",
            }
        ), 500


@app.route("/api/reports/today", methods=["GET"])
def report_today():
    denied = _require_private_access()
    if denied:
        return denied

    try:
        from integrations.garage_reports import get_today_report

        return jsonify(get_today_report()), 200

    except Exception as error:
        print("TODAY REPORT ERROR:", repr(error))
        return jsonify(
            {
                "success": False,
                "error": "today_report_failed",
            }
        ), 500


@app.route("/api/reports/week", methods=["GET"])
def report_week():
    denied = _require_private_access()
    if denied:
        return denied

    try:
        from integrations.garage_reports import get_week_report

        return jsonify(get_week_report()), 200

    except Exception as error:
        print("WEEK REPORT ERROR:", repr(error))
        return jsonify(
            {
                "success": False,
                "error": "week_report_failed",
            }
        ), 500


@app.route("/api/reports/month", methods=["GET"])
def report_month():
    denied = _require_private_access()
    if denied:
        return denied

    try:
        from integrations.garage_reports import get_month_report

        year = request.args.get("year", type=int)
        month = request.args.get("month", type=int)

        return jsonify(
            get_month_report(
                year=year,
                month=month,
            )
        ), 200

    except ValueError as error:
        return jsonify(
            {
                "success": False,
                "error": str(error),
            }
        ), 400

    except Exception as error:
        print("MONTH REPORT ERROR:", repr(error))
        return jsonify(
            {
                "success": False,
                "error": "month_report_failed",
            }
        ), 500


@app.route("/api/reports/today-schedule", methods=["GET"])
def report_today_schedule():
    denied = _require_private_access()
    if denied:
        return denied

    try:
        from integrations.garage_reports import get_today_schedule

        return jsonify(
            {
                "success": True,
                "schedule": get_today_schedule(),
            }
        ), 200

    except Exception as error:
        print("TODAY SCHEDULE ERROR:", repr(error))
        return jsonify(
            {
                "success": False,
                "error": "today_schedule_failed",
            }
        ), 500


# =========================================================
# Private campaign API
# =========================================================

@app.route("/api/campaigns/summary", methods=["GET"])
def campaign_summary():
    denied = _require_private_access()
    if denied:
        return denied

    try:
        from integrations.campaigns import get_campaign_dashboard_summary

        return jsonify(get_campaign_dashboard_summary()), 200

    except Exception as error:
        print("CAMPAIGN SUMMARY ERROR:", repr(error))
        return jsonify(
            {
                "success": False,
                "error": "campaign_summary_failed",
            }
        ), 500


@app.route("/api/campaigns/preview", methods=["POST"])
def campaign_preview():
    denied = _require_private_access()
    if denied:
        return denied

    data = _json_payload()
    campaign_type = str(data.get("campaign_type") or "").strip()
    offer_text = str(data.get("offer_text") or "").strip()
    message_title = str(data.get("message_title") or "").strip()
    limit = data.get("limit", 250)
    force = bool(data.get("force", False))

    if not campaign_type:
        return jsonify(
            {
                "success": False,
                "error": "campaign_type_required",
            }
        ), 400

    try:
        from integrations.campaigns import run_campaign

        result = run_campaign(
            campaign_type=campaign_type,
            offer_text=offer_text,
            message_title=message_title,
            limit=int(limit),
            dry_run=True,
            force=force,
        )

        return jsonify(result), 200

    except (TypeError, ValueError) as error:
        return jsonify(
            {
                "success": False,
                "error": str(error),
            }
        ), 400

    except Exception as error:
        print("CAMPAIGN PREVIEW ERROR:", repr(error))
        return jsonify(
            {
                "success": False,
                "error": "campaign_preview_failed",
            }
        ), 500


@app.route("/api/campaigns/run", methods=["POST"])
def campaign_run():
    denied = _require_private_access()
    if denied:
        return denied

    data = _json_payload()
    campaign_type = str(data.get("campaign_type") or "").strip()
    offer_text = str(data.get("offer_text") or "").strip()
    message_title = str(data.get("message_title") or "").strip()
    limit = data.get("limit", 250)

    # Deliberately require a second explicit confirmation in the JSON body.
    confirmed = data.get("confirm_send") is True
    force = data.get("force") is True

    if not campaign_type:
        return jsonify(
            {
                "success": False,
                "error": "campaign_type_required",
            }
        ), 400

    if not confirmed:
        return jsonify(
            {
                "success": False,
                "error": "campaign_send_not_confirmed",
                "message": (
                    "Preview the audience first, then send again with "
                    '"confirm_send": true.'
                ),
            }
        ), 400

    try:
        from integrations.campaigns import run_campaign

        result = run_campaign(
            campaign_type=campaign_type,
            offer_text=offer_text,
            message_title=message_title,
            limit=int(limit),
            dry_run=False,
            force=force,
        )

        return jsonify(result), 200

    except (TypeError, ValueError) as error:
        return jsonify(
            {
                "success": False,
                "error": str(error),
            }
        ), 400

    except Exception as error:
        print("CAMPAIGN RUN ERROR:", repr(error))
        return jsonify(
            {
                "success": False,
                "error": "campaign_run_failed",
            }
        ), 500


@app.route("/api/campaigns/opt-out", methods=["POST"])
def campaign_opt_out():
    denied = _require_private_access()
    if denied:
        return denied

    data = _json_payload()
    phone = str(data.get("phone") or "").strip()
    reason = str(data.get("reason") or "").strip()

    if not phone:
        return jsonify(
            {
                "success": False,
                "error": "phone_required",
            }
        ), 400

    try:
        from integrations.campaigns import record_marketing_opt_out

        return jsonify(
            record_marketing_opt_out(
                phone=phone,
                reason=reason,
            )
        ), 200

    except ValueError as error:
        return jsonify(
            {
                "success": False,
                "error": str(error),
            }
        ), 400

    except Exception as error:
        print("CAMPAIGN OPT-OUT ERROR:", repr(error))
        return jsonify(
            {
                "success": False,
                "error": "campaign_opt_out_failed",
            }
        ), 500
@app.route("/dashboard")
@dashboard_login_required
def dashboard():
    # Legacy/current dashboard.
    # Remove any previously selected platform business.
    session.pop("dashboard_business_id", None)

    return render_template(
        "dashboard.html",
        business=None,
        business_slug="",
    )


@app.route(
    "/platform/businesses/<business_slug>/dashboard"
)
@business_access_required
def business_dashboard(
    business_slug: str,
):
    try:
        business = load_business_instance(
            business_slug,
            refresh=True,
        )

    except LookupError:
        return jsonify(
            {
                "success": False,
                "error": "business_not_found",
                "business_slug": business_slug,
            }
        ), 404

    session["dashboard_business_id"] = (
        business.business_id
    )

    return render_template(
        "dashboard.html",
        business=business,
        business_slug=business.business_id,
    )
    try:
        business = load_business_instance(
            business_slug,
            refresh=True,
        )

    except LookupError:
        return jsonify(
            {
                "success": False,
                "error": "business_not_found",
                "business_slug": business_slug,
            }
        ), 404

    # This becomes the business context used by the
    # dashboard API for this logged-in session.
    session["dashboard_business_id"] = (
        business.business_id
    )

    return render_template(
        "dashboard.html",
        business=business,
        business_slug=business.business_id,
    )

if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)