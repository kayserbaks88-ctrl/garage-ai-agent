from __future__ import annotations

import hmac
import os
import threading
import time
from functools import wraps
from urllib.parse import urljoin, urlparse

from flask import (
    Blueprint,
    current_app,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)


dashboard_auth = Blueprint("dashboard_auth", __name__)


# ---------------------------------------------------------------------------
# Security settings
# ---------------------------------------------------------------------------

SESSION_KEY = "dashboard_authenticated"

MAX_FAILED_ATTEMPTS = 5
ATTEMPT_WINDOW_SECONDS = 15 * 60
LOCKOUT_SECONDS = 15 * 60

_failed_attempts: dict[str, dict[str, float | int]] = {}
_attempt_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _client_ip() -> str:
    forwarded_for = request.headers.get("X-Forwarded-For", "")

    if forwarded_for:
        return forwarded_for.split(",")[0].strip()

    return request.remote_addr or "unknown"


def _clean_old_attempts() -> None:
    now = time.time()

    with _attempt_lock:
        expired_ips = []

        for ip_address, data in _failed_attempts.items():
            last_attempt = float(data.get("last_attempt", 0))
            locked_until = float(data.get("locked_until", 0))

            if now > locked_until and now - last_attempt > ATTEMPT_WINDOW_SECONDS:
                expired_ips.append(ip_address)

        for ip_address in expired_ips:
            _failed_attempts.pop(ip_address, None)


def _is_locked_out(ip_address: str) -> tuple[bool, int]:
    _clean_old_attempts()

    now = time.time()

    with _attempt_lock:
        data = _failed_attempts.get(ip_address)

        if not data:
            return False, 0

        locked_until = float(data.get("locked_until", 0))

        if locked_until > now:
            seconds_remaining = int(locked_until - now)
            return True, max(seconds_remaining, 1)

    return False, 0


def _record_failed_attempt(ip_address: str) -> None:
    now = time.time()

    with _attempt_lock:
        data = _failed_attempts.get(
            ip_address,
            {
                "count": 0,
                "first_attempt": now,
                "last_attempt": now,
                "locked_until": 0,
            },
        )

        first_attempt = float(data.get("first_attempt", now))

        if now - first_attempt > ATTEMPT_WINDOW_SECONDS:
            data = {
                "count": 0,
                "first_attempt": now,
                "last_attempt": now,
                "locked_until": 0,
            }

        data["count"] = int(data.get("count", 0)) + 1
        data["last_attempt"] = now

        if int(data["count"]) >= MAX_FAILED_ATTEMPTS:
            data["locked_until"] = now + LOCKOUT_SECONDS

        _failed_attempts[ip_address] = data


def _clear_failed_attempts(ip_address: str) -> None:
    with _attempt_lock:
        _failed_attempts.pop(ip_address, None)


def _safe_next_url(target: str | None) -> str | None:
    if not target:
        return None

    host_url = request.host_url
    resolved_url = urljoin(host_url, target)

    host_parts = urlparse(host_url)
    target_parts = urlparse(resolved_url)

    if (
        host_parts.scheme == target_parts.scheme
        and host_parts.netloc == target_parts.netloc
    ):
        return resolved_url

    return None


def is_dashboard_authenticated() -> bool:
    return bool(session.get(SESSION_KEY))


# ---------------------------------------------------------------------------
# Route protection decorators
# ---------------------------------------------------------------------------

def dashboard_login_required(view_function):
    @wraps(view_function)
    def protected_view(*args, **kwargs):
        if not is_dashboard_authenticated():
            next_url = request.full_path

            if next_url.endswith("?"):
                next_url = next_url[:-1]

            return redirect(url_for("dashboard_auth.login", next=next_url))

        return view_function(*args, **kwargs)

    return protected_view


def dashboard_api_login_required(view_function):
    @wraps(view_function)
    def protected_api_view(*args, **kwargs):
        if not is_dashboard_authenticated():
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "authentication_required",
                        "message": "Please log in to access the dashboard.",
                    }
                ),
                401,
            )

        return view_function(*args, **kwargs)

    return protected_api_view


# ---------------------------------------------------------------------------
# Authentication routes
# ---------------------------------------------------------------------------

@dashboard_auth.before_app_request
def configure_dashboard_session() -> None:
    session.permanent = True


@dashboard_auth.route("/login", methods=["GET", "POST"])
def login():
    if is_dashboard_authenticated():
        return redirect(url_for("dashboard"))

    error_message = ""
    username_value = ""
    next_url = request.args.get("next") or request.form.get("next") or ""

    expected_username = os.getenv("DASHBOARD_USERNAME", "").strip()
    expected_password = os.getenv("DASHBOARD_PASSWORD", "")

    if not expected_username or not expected_password:
        current_app.logger.error(
            "Dashboard login is not configured. "
            "Set DASHBOARD_USERNAME and DASHBOARD_PASSWORD."
        )

        return render_template(
            "login.html",
            error_message=(
                "Dashboard login has not been configured yet. "
                "Please add the login details in Render."
            ),
            username_value="",
            next_url=next_url,
            configuration_error=True,
        ), 503

    if request.method == "POST":
        ip_address = _client_ip()
        locked_out, seconds_remaining = _is_locked_out(ip_address)

        if locked_out:
            minutes_remaining = max(1, (seconds_remaining + 59) // 60)

            error_message = (
                f"Too many failed attempts. "
                f"Please try again in about {minutes_remaining} minute"
                f"{'s' if minutes_remaining != 1 else ''}."
            )
        else:
            username_value = request.form.get("username", "").strip()
            submitted_password = request.form.get("password", "")

            username_matches = hmac.compare_digest(
                username_value,
                expected_username,
            )

            password_matches = hmac.compare_digest(
                submitted_password,
                expected_password,
            )

            if username_matches and password_matches:
                _clear_failed_attempts(ip_address)

                session.clear()
                session.permanent = True
                session[SESSION_KEY] = True
                session["dashboard_username"] = expected_username
                session["login_time"] = int(time.time())

                safe_next = _safe_next_url(next_url)

                if safe_next:
                    return redirect(safe_next)

                return redirect(url_for("dashboard"))

            _record_failed_attempt(ip_address)
            error_message = "Incorrect username or password."

    return render_template(
        "login.html",
        error_message=error_message,
        username_value=username_value,
        next_url=next_url,
        configuration_error=False,
    )


@dashboard_auth.route("/logout", methods=["GET", "POST"])
def logout():
    session.clear()
    return redirect(url_for("dashboard_auth.login"))