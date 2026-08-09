from __future__ import annotations

"""
TrimTech onboarding web routes.

Flow:
    Step 1 - Business details
    Review
    Step 2 - Services and opening hours
    Step 3 - Integrations
    Step 4 - Launch

The onboarding record is saved after every step so the owner can
return to the setup without losing completed information.
"""

from typing import Any

from flask import (
    Blueprint,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)

from trimtech.modules.onboarding.models import (
    OnboardingBusiness,
)
from trimtech.modules.onboarding.service import (
    OnboardingStorageError,
    load_onboarding_business,
    save_onboarding_business,
)


onboarding_blueprint = Blueprint(
    "onboarding",
    __name__,
    url_prefix="/onboarding",
)


DAYS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)


# =========================================================
# Helpers
# =========================================================


def clean_form_text(value: Any) -> str:
    return str(value or "").strip()


def safe_duration(value: Any) -> int:
    try:
        duration = int(value)
    except (TypeError, ValueError):
        return 0

    return max(
        duration,
        0,
    )


def safe_price(value: Any) -> float:
    try:
        price = float(value)
    except (TypeError, ValueError):
        return 0.0

    return round(
        max(price, 0.0),
        2,
    )


def load_business_or_redirect(
    business_slug: str,
) -> OnboardingBusiness | None:
    try:
        business = load_onboarding_business(
            business_slug
        )

    except OnboardingStorageError as error:
        flash(
            str(error),
            "error",
        )
        return None

    if business is None:
        flash(
            "That onboarding record could not be found.",
            "error",
        )
        return None

    return business


def services_from_form() -> list[dict[str, Any]]:
    names = request.form.getlist(
        "service_name"
    )

    durations = request.form.getlist(
        "service_duration"
    )

    prices = request.form.getlist(
        "service_price"
    )

    services: list[dict[str, Any]] = []

    row_count = max(
        len(names),
        len(durations),
        len(prices),
    )

    for index in range(row_count):
        name = clean_form_text(
            names[index]
            if index < len(names)
            else ""
        )

        duration = safe_duration(
            durations[index]
            if index < len(durations)
            else 0
        )

        price = safe_price(
            prices[index]
            if index < len(prices)
            else 0
        )

        if not name:
            continue

        services.append(
            {
                "name": name,
                "duration_minutes": duration,
                "price": price,
                "enabled": True,
            }
        )

    return services


def opening_hours_from_form() -> dict[str, Any]:
    opening_hours: dict[str, Any] = {}

    for day in DAYS:
        is_closed = (
            request.form.get(
                f"{day}_closed"
            )
            == "on"
        )

        opening_hours[day] = {
            "closed": is_closed,
            "open": clean_form_text(
                request.form.get(
                    f"{day}_open",
                    "",
                )
            ),
            "close": clean_form_text(
                request.form.get(
                    f"{day}_close",
                    "",
                )
            ),
        }

    return opening_hours


# =========================================================
# Step 1 - Business details
# =========================================================


@onboarding_blueprint.get("/")
def onboarding_start():
    return render_template(
        "onboarding/business_details.html",
        business=None,
        form_data={},
    )


@onboarding_blueprint.post("/")
def onboarding_create():
    form_data = {
        "business_name": clean_form_text(
            request.form.get(
                "business_name"
            )
        ),
        "owner_name": clean_form_text(
            request.form.get(
                "owner_name"
            )
        ),
        "email": clean_form_text(
            request.form.get(
                "email"
            )
        ),
        "phone": clean_form_text(
            request.form.get(
                "phone"
            )
        ),
        "business_type": clean_form_text(
            request.form.get(
                "business_type",
                "other",
            )
        ),
        "address": clean_form_text(
            request.form.get(
                "address"
            )
        ),
        "postcode": clean_form_text(
            request.form.get(
                "postcode"
            )
        ),
        "website": clean_form_text(
            request.form.get(
                "website"
            )
        ),
    }

    business = OnboardingBusiness(
        **form_data,
    )

    errors = business.validate()

    if errors:
        for error in errors:
            flash(
                error,
                "error",
            )

        return render_template(
            "onboarding/business_details.html",
            business=None,
            form_data=form_data,
        ), 400

    try:
        save_onboarding_business(
            business
        )

    except OnboardingStorageError as error:
        flash(
            str(error),
            "error",
        )

        return render_template(
            "onboarding/business_details.html",
            business=None,
            form_data=form_data,
        ), 500

    flash(
        "Business details saved.",
        "success",
    )

    return redirect(
        url_for(
            "onboarding.onboarding_review",
            business_slug=business.business_slug,
        )
    )


# =========================================================
# Review
# =========================================================


@onboarding_blueprint.get(
    "/<business_slug>/review"
)
def onboarding_review(
    business_slug: str,
):
    business = load_business_or_redirect(
        business_slug
    )

    if business is None:
        return redirect(
            url_for(
                "onboarding.onboarding_start"
            )
        )

    return render_template(
        "onboarding/review.html",
        business=business,
    )


# =========================================================
# Step 2 - Services and opening hours
# =========================================================


@onboarding_blueprint.get(
    "/<business_slug>/services"
)
def onboarding_services(
    business_slug: str,
):
    business = load_business_or_redirect(
        business_slug
    )

    if business is None:
        return redirect(
            url_for(
                "onboarding.onboarding_start"
            )
        )

    return render_template(
        "onboarding/services.html",
        business=business,
        days=DAYS,
    )


@onboarding_blueprint.post(
    "/<business_slug>/services"
)
def onboarding_services_save(
    business_slug: str,
):
    business = load_business_or_redirect(
        business_slug
    )

    if business is None:
        return redirect(
            url_for(
                "onboarding.onboarding_start"
            )
        )

    services = services_from_form()
    opening_hours = opening_hours_from_form()

    business.services = services
    business.opening_hours = opening_hours

    business.timezone = (
        clean_form_text(
            request.form.get(
                "timezone",
                business.timezone,
            )
        )
        or "Europe/London"
    )

    business.currency = (
        clean_form_text(
            request.form.get(
                "currency",
                business.currency,
            )
        ).upper()
        or "GBP"
    )

    if not services:
        flash(
            "Add at least one service.",
            "error",
        )

        return render_template(
            "onboarding/services.html",
            business=business,
            days=DAYS,
        ), 400

    invalid_services = [
        service
        for service in services
        if (
            service["duration_minutes"] <= 0
            or service["price"] < 0
        )
    ]

    if invalid_services:
        flash(
            "Every service needs a valid duration.",
            "error",
        )

        return render_template(
            "onboarding/services.html",
            business=business,
            days=DAYS,
        ), 400

    try:
        save_onboarding_business(
            business
        )

    except OnboardingStorageError as error:
        flash(
            str(error),
            "error",
        )

        return render_template(
            "onboarding/services.html",
            business=business,
            days=DAYS,
        ), 500

    flash(
        "Services and opening hours saved.",
        "success",
    )

    return redirect(
        url_for(
            "onboarding.onboarding_integrations",
            business_slug=business.business_slug,
        )
    )


# =========================================================
# Step 3 - Integrations
# =========================================================


@onboarding_blueprint.get(
    "/<business_slug>/integrations"
)
def onboarding_integrations(
    business_slug: str,
):
    business = load_business_or_redirect(
        business_slug
    )

    if business is None:
        return redirect(
            url_for(
                "onboarding.onboarding_start"
            )
        )

    return render_template(
        "onboarding/integrations.html",
        business=business,
    )


@onboarding_blueprint.post(
    "/<business_slug>/integrations"
)
def onboarding_integrations_save(
    business_slug: str,
):
    business = load_business_or_redirect(
        business_slug
    )

    if business is None:
        return redirect(
            url_for(
                "onboarding.onboarding_start"
            )
        )

    business.integrations = {
        "google_calendar": (
            request.form.get(
                "google_calendar"
            )
            == "on"
        ),
        "vapi_voice": (
            request.form.get(
                "vapi_voice"
            )
            == "on"
        ),
        "whatsapp": (
            request.form.get(
                "whatsapp"
            )
            == "on"
        ),
        "email": (
            request.form.get(
                "email"
            )
            == "on"
        ),
    }

    try:
        save_onboarding_business(
            business
        )

    except OnboardingStorageError as error:
        flash(
            str(error),
            "error",
        )

        return render_template(
            "onboarding/integrations.html",
            business=business,
        ), 500

    flash(
        "Integrations saved.",
        "success",
    )

    return redirect(
        url_for(
            "onboarding.onboarding_launch",
            business_slug=business.business_slug,
        )
    )


# =========================================================
# Step 4 - Launch
# =========================================================


@onboarding_blueprint.get(
    "/<business_slug>/launch"
)
def onboarding_launch(
    business_slug: str,
):
    business = load_business_or_redirect(
        business_slug
    )

    if business is None:
        return redirect(
            url_for(
                "onboarding.onboarding_start"
            )
        )

    return render_template(
        "onboarding/launch.html",
        business=business,
    )


@onboarding_blueprint.post(
    "/<business_slug>/launch"
)
def onboarding_launch_complete(
    business_slug: str,
):
    business = load_business_or_redirect(
        business_slug
    )

    if business is None:
        return redirect(
            url_for(
                "onboarding.onboarding_start"
            )
        )

    if not business.services:
        flash(
            "Add at least one service before launching.",
            "error",
        )

        return redirect(
            url_for(
                "onboarding.onboarding_services",
                business_slug=business.business_slug,
            )
        )

    business.onboarding_complete = True

    try:
        save_onboarding_business(
            business
        )

    except OnboardingStorageError as error:
        flash(
            str(error),
            "error",
        )

        return render_template(
            "onboarding/launch.html",
            business=business,
        ), 500

    flash(
        "Your TrimTech business setup is complete.",
        "success",
    )

    return redirect(
        url_for(
            "onboarding.onboarding_launch",
            business_slug=business.business_slug,
            complete="1",
        )
    )