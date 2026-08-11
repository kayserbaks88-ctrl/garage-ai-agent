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

from trimtech.modules.auth.repository import (
    AuthRepositoryError,
    authenticate_business_user,
    create_business_user,
    create_customer_invite,
    get_customer_invite_by_token,
    mark_customer_invite_used,
)
from trimtech.modules.onboarding.service import (
    OnboardingStorageError,
    load_onboarding_business,
)


auth_blueprint = Blueprint(
    "auth",
    __name__,
)


# =========================================================
# Session keys
# =========================================================

PLATFORM_ADMIN_SESSION_KEY = (
    "platform_admin_authenticated"
)

BUSINESS_USER_SESSION_KEY = (
    "business_user_authenticated"
)

BUSINESS_USER_ID_SESSION_KEY = (
    "business_user_id"
)

BUSINESS_ID_SESSION_KEY = (
    "business_id"
)

BUSINESS_USERNAME_SESSION_KEY = (
    "business_username"
)


# =========================================================
# Login protection
# =========================================================

MAX_FAILED_ATTEMPTS = 5
ATTEMPT_WINDOW_SECONDS = 15 * 60
LOCKOUT_SECONDS = 15 * 60

_failed_attempts: dict[
    str,
    dict[str, float | int],
] = {}

_attempt_lock = threading.Lock()


# =========================================================
# General helpers
# =========================================================


def clean_text(
    value,
) -> str:
    return str(
        value or ""
    ).strip()


def _client_ip() -> str:
    forwarded_for = request.headers.get(
        "X-Forwarded-For",
        "",
    )

    if forwarded_for:
        return (
            forwarded_for
            .split(",")[0]
            .strip()
        )

    return (
        request.remote_addr
        or "unknown"
    )


def _clean_old_attempts() -> None:
    now = time.time()

    with _attempt_lock:
        expired_ips: list[str] = []

        for ip_address, data in (
            _failed_attempts.items()
        ):
            last_attempt = float(
                data.get(
                    "last_attempt",
                    0,
                )
            )

            locked_until = float(
                data.get(
                    "locked_until",
                    0,
                )
            )

            if (
                now > locked_until
                and (
                    now - last_attempt
                    > ATTEMPT_WINDOW_SECONDS
                )
            ):
                expired_ips.append(
                    ip_address
                )

        for ip_address in expired_ips:
            _failed_attempts.pop(
                ip_address,
                None,
            )


def _is_locked_out(
    ip_address: str,
) -> tuple[bool, int]:
    _clean_old_attempts()

    now = time.time()

    with _attempt_lock:
        data = _failed_attempts.get(
            ip_address
        )

        if not data:
            return False, 0

        locked_until = float(
            data.get(
                "locked_until",
                0,
            )
        )

        if locked_until > now:
            seconds_remaining = int(
                locked_until - now
            )

            return (
                True,
                max(
                    seconds_remaining,
                    1,
                ),
            )

    return False, 0


def _record_failed_attempt(
    ip_address: str,
) -> None:
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

        first_attempt = float(
            data.get(
                "first_attempt",
                now,
            )
        )

        if (
            now - first_attempt
            > ATTEMPT_WINDOW_SECONDS
        ):
            data = {
                "count": 0,
                "first_attempt": now,
                "last_attempt": now,
                "locked_until": 0,
            }

        data["count"] = (
            int(
                data.get(
                    "count",
                    0,
                )
            )
            + 1
        )

        data["last_attempt"] = now

        if (
            int(
                data["count"]
            )
            >= MAX_FAILED_ATTEMPTS
        ):
            data["locked_until"] = (
                now
                + LOCKOUT_SECONDS
            )

        _failed_attempts[
            ip_address
        ] = data


def _clear_failed_attempts(
    ip_address: str,
) -> None:
    with _attempt_lock:
        _failed_attempts.pop(
            ip_address,
            None,
        )


def _safe_next_url(
    target: str | None,
) -> str | None:
    if not target:
        return None

    host_url = request.host_url

    resolved_url = urljoin(
        host_url,
        target,
    )

    host_parts = urlparse(
        host_url
    )

    target_parts = urlparse(
        resolved_url
    )

    if (
        host_parts.scheme
        == target_parts.scheme
        and host_parts.netloc
        == target_parts.netloc
    ):
        return resolved_url

    return None


# =========================================================
# Platform admin credentials
# =========================================================


def _platform_admin_credentials(
) -> tuple[str, str]:
    """
    Dedicated Platform credentials are preferred.

    Existing dashboard credentials remain as a development
    fallback only.
    """

    username = (
        os.getenv(
            "PLATFORM_ADMIN_USERNAME",
            "",
        ).strip()
        or os.getenv(
            "DASHBOARD_USERNAME",
            "",
        ).strip()
    )

    password = (
        os.getenv(
            "PLATFORM_ADMIN_PASSWORD",
            "",
        )
        or os.getenv(
            "DASHBOARD_PASSWORD",
            "",
        )
    )

    return (
        username,
        password,
    )


# =========================================================
# Authentication state
# =========================================================


def is_platform_admin_authenticated(
) -> bool:
    return bool(
        session.get(
            PLATFORM_ADMIN_SESSION_KEY
        )
    )


def is_business_user_authenticated(
) -> bool:
    return bool(
        session.get(
            BUSINESS_USER_SESSION_KEY
        )
        and session.get(
            BUSINESS_ID_SESSION_KEY
        )
    )


def current_business_user_id(
) -> str:
    return clean_text(
        session.get(
            BUSINESS_USER_ID_SESSION_KEY
        )
    )


def current_business_user_business_id(
) -> str:
    return clean_text(
        session.get(
            BUSINESS_ID_SESSION_KEY
        )
    )


# =========================================================
# Route decorators
# =========================================================


def platform_admin_required(
    view_function,
):
    """
    Protect TrimTech master Platform pages.
    """

    @wraps(
        view_function
    )
    def protected_view(
        *args,
        **kwargs,
    ):
        if not (
            is_platform_admin_authenticated()
        ):
            next_url = request.full_path

            if next_url.endswith("?"):
                next_url = (
                    next_url[:-1]
                )

            return redirect(
                url_for(
                    "auth.platform_login",
                    next=next_url,
                )
            )

        return view_function(
            *args,
            **kwargs,
        )

    return protected_view


def business_user_required(
    view_function,
):
    """
    Protect customer business pages.
    """

    @wraps(
        view_function
    )
    def protected_view(
        *args,
        **kwargs,
    ):
        if not (
            is_business_user_authenticated()
        ):
            next_url = request.full_path

            if next_url.endswith("?"):
                next_url = (
                    next_url[:-1]
                )

            return redirect(
                url_for(
                    "auth.customer_login",
                    next=next_url,
                )
            )

        return view_function(
            *args,
            **kwargs,
        )

    return protected_view


def business_access_required(
    view_function,
):
    """
    Protect a URL containing <business_slug>.

    Platform admins can access any business.

    Customers may only access the business permanently
    linked to their account.
    """

    @wraps(
        view_function
    )
    def protected_view(
        business_slug: str,
        *args,
        **kwargs,
    ):
        clean_slug = clean_text(
            business_slug
        ).lower()

        if (
            is_platform_admin_authenticated()
        ):
            return view_function(
                business_slug,
                *args,
                **kwargs,
            )

        if not (
            is_business_user_authenticated()
        ):
            return redirect(
                url_for(
                    "auth.customer_login",
                    next=request.path,
                )
            )

        allowed_business_id = (
            current_business_user_business_id()
            .lower()
        )

        if (
            clean_slug
            != allowed_business_id
        ):
            return (
                jsonify(
                    {
                        "success": False,
                        "error": (
                            "business_access_denied"
                        ),
                        "message": (
                            "You do not have access "
                            "to this business."
                        ),
                    }
                ),
                403,
            )

        return view_function(
            business_slug,
            *args,
            **kwargs,
        )

    return protected_view


# =========================================================
# Platform admin login
# =========================================================


@auth_blueprint.route(
    "/platform/login",
    methods=[
        "GET",
        "POST",
    ],
)
def platform_login():
    if (
        is_platform_admin_authenticated()
    ):
        return redirect(
            url_for(
                "platform.platform_businesses"
            )
        )

    error_message = ""
    username_value = ""

    next_url = (
        request.args.get(
            "next"
        )
        or request.form.get(
            "next"
        )
        or ""
    )

    (
        expected_username,
        expected_password,
    ) = _platform_admin_credentials()

    if (
        not expected_username
        or not expected_password
    ):
        current_app.logger.error(
            "TrimTech Platform admin login "
            "is not configured."
        )

        return render_template(
            "auth/platform_login.html",
            error_message=(
                "Platform login has not been "
                "configured yet."
            ),
            username_value="",
            next_url=next_url,
            configuration_error=True,
        ), 503

    if request.method == "POST":
        ip_address = (
            _client_ip()
        )

        (
            locked_out,
            seconds_remaining,
        ) = _is_locked_out(
            ip_address
        )

        if locked_out:
            minutes_remaining = max(
                1,
                (
                    seconds_remaining
                    + 59
                )
                // 60,
            )

            error_message = (
                "Too many failed attempts. "
                "Please try again in about "
                f"{minutes_remaining} minute"
                f"{'s' if minutes_remaining != 1 else ''}."
            )

        else:
            username_value = (
                request.form.get(
                    "username",
                    "",
                )
                .strip()
            )

            submitted_password = (
                request.form.get(
                    "password",
                    "",
                )
            )

            username_matches = (
                hmac.compare_digest(
                    username_value,
                    expected_username,
                )
            )

            password_matches = (
                hmac.compare_digest(
                    submitted_password,
                    expected_password,
                )
            )

            if (
                username_matches
                and password_matches
            ):
                _clear_failed_attempts(
                    ip_address
                )

                session.clear()
                session.permanent = True

                session[
                    PLATFORM_ADMIN_SESSION_KEY
                ] = True

                session[
                    "auth_role"
                ] = "platform_admin"

                session[
                    "platform_admin_username"
                ] = expected_username

                session[
                    "platform_login_time"
                ] = int(
                    time.time()
                )

                safe_next = (
                    _safe_next_url(
                        next_url
                    )
                )

                if safe_next:
                    return redirect(
                        safe_next
                    )

                return redirect(
                    url_for(
                        "platform.platform_businesses"
                    )
                )

            _record_failed_attempt(
                ip_address
            )

            error_message = (
                "Incorrect username "
                "or password."
            )

    return render_template(
        "auth/platform_login.html",
        error_message=error_message,
        username_value=username_value,
        next_url=next_url,
        configuration_error=False,
    )


# =========================================================
# Platform logout
# =========================================================


@auth_blueprint.route(
    "/platform/logout",
    methods=[
        "GET",
        "POST",
    ],
)
def platform_logout():
    session.clear()

    return redirect(
        url_for(
            "auth.platform_login"
        )
    )


# =========================================================
# Create customer invite
# =========================================================


@auth_blueprint.post(
    "/platform/businesses/"
    "<business_slug>/invite"
)
@platform_admin_required
def create_business_invite(
    business_slug: str,
):
    """
    Create a one-time customer registration link.

    Only the Platform administrator can create invitations.
    """

    try:
        business = (
            load_onboarding_business(
                business_slug
            )
        )

    except OnboardingStorageError as error:
        return (
            jsonify(
                {
                    "success": False,
                    "error": (
                        "business_load_failed"
                    ),
                    "message": str(
                        error
                    ),
                }
            ),
            500,
        )

    if business is None:
        return (
            jsonify(
                {
                    "success": False,
                    "error": (
                        "business_not_found"
                    ),
                }
            ),
            404,
        )

    email = clean_text(
        request.form.get(
            "email"
        )
        or (
            request.get_json(
                silent=True
            )
            or {}
        ).get(
            "email"
        )
        or business.email
    ).lower()

    if not email:
        return (
            jsonify(
                {
                    "success": False,
                    "error": (
                        "email_required"
                    ),
                }
            ),
            400,
        )

    try:
        invite, raw_token = (
            create_customer_invite(
                business_id=(
                    business.business_slug
                ),
                business_name=(
                    business.business_name
                ),
                business_type=(
                    business.business_type
                ),
                email=email,
                created_by=clean_text(
                    session.get(
                        "platform_admin_username"
                    )
                )
                or "platform_admin",
                expires_hours=72,
            )
        )

    except (
        AuthRepositoryError,
        ValueError,
    ) as error:
        return (
            jsonify(
                {
                    "success": False,
                    "error": (
                        "invite_creation_failed"
                    ),
                    "message": str(
                        error
                    ),
                }
            ),
            400,
        )

    registration_url = url_for(
        "auth.customer_register",
        token=raw_token,
        _external=True,
    )

    return jsonify(
        {
            "success": True,
            "invite": (
                invite.to_dict()
            ),
            "registration_url": (
                registration_url
            ),
            "expires_at": (
                invite.expires_at
            ),
        }
    )


# =========================================================
# Customer registration
# =========================================================


@auth_blueprint.route(
    "/register/<token>",
    methods=[
        "GET",
        "POST",
    ],
)
def customer_register(
    token: str,
):
    error_message = ""
    success_message = ""

    username_value = ""
    full_name_value = ""

    try:
        invite = (
            get_customer_invite_by_token(
                token
            )
        )

    except AuthRepositoryError as error:
        current_app.logger.error(
            "Customer invite lookup failed: %s",
            error,
        )

        invite = None

        error_message = (
            "This registration link "
            "could not be checked."
        )

    if (
        invite is None
        or not invite.usable
    ):
        return render_template(
            "auth/customer_register.html",
            invite=invite,
            error_message=(
                error_message
                or (
                    "This registration link "
                    "is invalid, expired or "
                    "has already been used."
                )
            ),
            success_message="",
            username_value="",
            full_name_value="",
        ), 400

    if request.method == "POST":
        username_value = (
            clean_text(
                request.form.get(
                    "username"
                )
            )
            .lower()
        )

        full_name_value = (
            clean_text(
                request.form.get(
                    "full_name"
                )
            )
        )

        password = request.form.get(
            "password",
            "",
        )

        confirm_password = (
            request.form.get(
                "confirm_password",
                "",
            )
        )

        if not full_name_value:
            error_message = (
                "Please enter your name."
            )

        elif not username_value:
            error_message = (
                "Please choose a username."
            )

        elif len(
            password
        ) < 10:
            error_message = (
                "Password must be at "
                "least 10 characters."
            )

        elif (
            password
            != confirm_password
        ):
            error_message = (
                "The passwords do not match."
            )

        else:
            try:
                user = (
                    create_business_user(
                        username=(
                            username_value
                        ),
                        password=password,
                        business_id=(
                            invite.business_id
                        ),
                        email=(
                            invite.email
                        ),
                        full_name=(
                            full_name_value
                        ),
                    )
                )

                mark_customer_invite_used(
                    invite.invite_id
                )

            except (
                AuthRepositoryError,
                ValueError,
            ) as error:
                error_message = str(
                    error
                )

            else:
                session.clear()
                session.permanent = True

                session[
                    BUSINESS_USER_SESSION_KEY
                ] = True

                session[
                    BUSINESS_USER_ID_SESSION_KEY
                ] = user.user_id

                session[
                    BUSINESS_ID_SESSION_KEY
                ] = user.business_id

                session[
                    BUSINESS_USERNAME_SESSION_KEY
                ] = user.username

                session[
                    "dashboard_business_id"
                ] = user.business_id

                session[
                    "auth_role"
                ] = "business_user"

                session[
                    "business_login_time"
                ] = int(
                    time.time()
                )

                return redirect(
                    url_for(
                        "business_dashboard",
                        business_slug=(
                            user.business_id
                        ),
                    )
                )

    return render_template(
        "auth/customer_register.html",
        invite=invite,
        error_message=error_message,
        success_message=success_message,
        username_value=username_value,
        full_name_value=full_name_value,
    )


# =========================================================
# Customer login
# =========================================================


@auth_blueprint.route(
    "/customer/login",
    methods=[
        "GET",
        "POST",
    ],
)
def customer_login():
    if (
        is_business_user_authenticated()
    ):
        return redirect(
            url_for(
                "business_dashboard",
                business_slug=(
                    current_business_user_business_id()
                ),
            )
        )

    error_message = ""
    success_message = ""

    username_value = ""

    next_url = (
        request.args.get(
            "next"
        )
        or request.form.get(
            "next"
        )
        or ""
    )

    if request.method == "POST":
        ip_address = (
            _client_ip()
        )

        (
            locked_out,
            seconds_remaining,
        ) = _is_locked_out(
            ip_address
        )

        if locked_out:
            minutes_remaining = max(
                1,
                (
                    seconds_remaining
                    + 59
                )
                // 60,
            )

            error_message = (
                "Too many failed attempts. "
                "Please try again in about "
                f"{minutes_remaining} minute"
                f"{'s' if minutes_remaining != 1 else ''}."
            )

        else:
            username_value = (
                clean_text(
                    request.form.get(
                        "username"
                    )
                )
                .lower()
            )

            password = (
                request.form.get(
                    "password",
                    "",
                )
            )

            try:
                user = (
                    authenticate_business_user(
                        username_value,
                        password,
                    )
                )

            except AuthRepositoryError as error:
                current_app.logger.error(
                    "Business login failed: %s",
                    error,
                )

                user = None

                error_message = (
                    "Unable to sign in "
                    "right now."
                )

            if (
                user is not None
            ):
                _clear_failed_attempts(
                    ip_address
                )

                session.clear()
                session.permanent = True

                session[
                    BUSINESS_USER_SESSION_KEY
                ] = True

                session[
                    BUSINESS_USER_ID_SESSION_KEY
                ] = user.user_id

                session[
                    BUSINESS_ID_SESSION_KEY
                ] = user.business_id

                session[
                    BUSINESS_USERNAME_SESSION_KEY
                ] = user.username

                session[
                    "dashboard_business_id"
                ] = user.business_id

                session[
                    "auth_role"
                ] = "business_user"

                session[
                    "business_login_time"
                ] = int(
                    time.time()
                )

                safe_next = (
                    _safe_next_url(
                        next_url
                    )
                )

                if safe_next:
                    return redirect(
                        safe_next
                    )

                return redirect(
                    url_for(
                        "business_dashboard",
                        business_slug=(
                            user.business_id
                        ),
                    )
                )

            if not error_message:
                _record_failed_attempt(
                    ip_address
                )

                error_message = (
                    "Incorrect username "
                    "or password."
                )

    return render_template(
        "auth/customer_login.html",
        error_message=error_message,
        success_message=success_message,
        username_value=username_value,
        next_url=next_url,
    )


# =========================================================
# Customer logout
# =========================================================


@auth_blueprint.route(
    "/customer/logout",
    methods=[
        "GET",
        "POST",
    ],
)
def customer_logout():
    session.clear()

    return redirect(
        url_for(
            "auth.customer_login"
        )
    )


# =========================================================
# Customer session information
# =========================================================


@auth_blueprint.get(
    "/customer/session"
)
def customer_session():
    if not (
        is_business_user_authenticated()
    ):
        return (
            jsonify(
                {
                    "success": False,
                    "authenticated": False,
                }
            ),
            401,
        )

    return jsonify(
        {
            "success": True,
            "authenticated": True,
            "role": "business_user",
            "user_id": (
                current_business_user_id()
            ),
            "username": clean_text(
                session.get(
                    BUSINESS_USERNAME_SESSION_KEY
                )
            ),
            "business_id": (
                current_business_user_business_id()
            ),
        }
    )