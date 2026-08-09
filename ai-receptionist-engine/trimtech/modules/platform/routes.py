from __future__ import annotations

"""
TrimTech platform dashboard routes.

This module provides the central business management dashboard
for all businesses created through TrimTech onboarding.
"""

from flask import (
    Blueprint,
    flash,
    redirect,
    render_template,
    url_for,
)

from trimtech.modules.onboarding.service import (
    OnboardingStorageError,
    list_onboarding_businesses,
)


platform_blueprint = Blueprint(
    "platform",
    __name__,
    url_prefix="/platform",
)


def enabled_integrations(
    integrations: dict,
) -> list[str]:
    labels = {
        "google_calendar": "Google Calendar",
        "vapi_voice": "Vapi Voice",
        "whatsapp": "WhatsApp",
        "email": "Email",
    }

    return [
        labels.get(
            key,
            key.replace("_", " ").title(),
        )
        for key, enabled in integrations.items()
        if enabled
    ]


def get_business_by_slug(
    business_slug: str,
):
    try:
        businesses = list_onboarding_businesses()

    except OnboardingStorageError as error:
        flash(
            str(error),
            "error",
        )
        return None

    return next(
        (
            business
            for business in businesses
            if business.business_slug == business_slug
        ),
        None,
    )


@platform_blueprint.get("/")
def platform_home():
    return redirect(
        url_for(
            "platform.platform_businesses"
        )
    )


@platform_blueprint.get(
    "/businesses"
)
def platform_businesses():
    try:
        onboarding_businesses = (
            list_onboarding_businesses()
        )

    except OnboardingStorageError as error:
        flash(
            str(error),
            "error",
        )

        onboarding_businesses = []

    businesses = []

    for business in onboarding_businesses:
        integrations = enabled_integrations(
            business.integrations
        )

        businesses.append(
            {
                "business_name": (
                    business.business_name
                ),
                "business_slug": (
                    business.business_slug
                ),
                "business_type": (
                    business.business_type
                ),
                "owner_name": (
                    business.owner_name
                ),
                "email": (
                    business.email
                ),
                "phone": (
                    business.phone
                ),
                "timezone": (
                    business.timezone
                ),
                "currency": (
                    business.currency
                ),
                "service_count": len(
                    business.services
                ),
                "integration_count": len(
                    integrations
                ),
                "integrations": integrations,
                "onboarding_complete": (
                    business.onboarding_complete
                ),
                "status": (
                    "Live"
                    if business.onboarding_complete
                    else "Setup in progress"
                ),
            }
        )

    businesses.sort(
        key=lambda item: (
            not item["onboarding_complete"],
            item["business_name"].lower(),
        )
    )

    completed_count = sum(
        1
        for business in businesses
        if business["onboarding_complete"]
    )

    setup_count = (
        len(businesses)
        - completed_count
    )

    summary = {
        "total_businesses": len(
            businesses
        ),
        "live_businesses": (
            completed_count
        ),
        "setup_businesses": (
            setup_count
        ),
        "total_services": sum(
            business["service_count"]
            for business in businesses
        ),
    }

    return render_template(
        "platform/businesses.html",
        businesses=businesses,
        summary=summary,
    )


@platform_blueprint.get(
    "/businesses/<business_slug>"
)
def platform_business_detail(
    business_slug: str,
):
    business = get_business_by_slug(
        business_slug
    )

    if business is None:
        flash(
            "That business could not be found.",
            "error",
        )

        return redirect(
            url_for(
                "platform.platform_businesses"
            )
        )

    integrations = enabled_integrations(
        business.integrations
    )

    return render_template(
        "platform/business_detail.html",
        business=business,
        integrations=integrations,
        service_count=len(
            business.services
        ),
        integration_count=len(
            integrations
        ),
    )