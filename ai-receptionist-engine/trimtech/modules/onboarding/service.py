from __future__ import annotations

"""
TrimTech onboarding storage service.

This module is the stable storage interface used by:

- onboarding routes
- TrimTech Platform
- business registry
- business dashboards

The storage implementation now uses the persistent onboarding
repository instead of individual JSON files.

Because the public functions in this module stay the same, the rest
of the application does not need to know whether records are stored
in JSON, SQLite, Postgres, or another database later.
"""

from trimtech.modules.onboarding.models import (
    OnboardingBusiness,
    create_business_slug,
)
from trimtech.modules.onboarding.repository import (
    OnboardingRepositoryError,
    business_record_exists,
    delete_business_record,
    list_business_records,
    load_business_record,
    repository_health,
    save_business_record,
)


class OnboardingStorageError(RuntimeError):
    """
    Raised when onboarding data cannot be saved or loaded.
    """


def _clean_business_slug(
    business_slug: str,
) -> str:
    """
    Convert a supplied business slug into the same safe format
    used throughout TrimTech onboarding.
    """

    safe_slug = create_business_slug(
        business_slug
    )

    if not safe_slug:
        raise OnboardingStorageError(
            "A valid business slug is required."
        )

    return safe_slug


def save_onboarding_business(
    business: OnboardingBusiness,
) -> OnboardingBusiness:
    """
    Save or update one onboarding business.

    The business is validated before it is written to persistent
    storage.
    """

    if not isinstance(
        business,
        OnboardingBusiness,
    ):
        raise OnboardingStorageError(
            "A valid onboarding business is required."
        )

    errors = business.validate()

    if errors:
        raise OnboardingStorageError(
            " ".join(errors)
        )

    safe_slug = _clean_business_slug(
        business.business_slug
    )

    business.business_slug = safe_slug

    payload = business.to_dict()

    payload[
        "business_slug"
    ] = safe_slug

    try:
        save_business_record(
            payload
        )

    except OnboardingRepositoryError as error:
        raise OnboardingStorageError(
            "Unable to save onboarding progress."
        ) from error

    return business


def load_onboarding_business(
    business_slug: str,
) -> OnboardingBusiness | None:
    """
    Load one onboarding business by slug.
    """

    safe_slug = _clean_business_slug(
        business_slug
    )

    try:
        raw_data = load_business_record(
            safe_slug
        )

    except OnboardingRepositoryError as error:
        raise OnboardingStorageError(
            "Unable to load onboarding progress."
        ) from error

    if raw_data is None:
        return None

    if not isinstance(
        raw_data,
        dict,
    ):
        raise OnboardingStorageError(
            "The onboarding record is invalid."
        )

    try:
        business = (
            OnboardingBusiness.from_dict(
                raw_data
            )
        )

    except (
        TypeError,
        ValueError,
    ) as error:
        raise OnboardingStorageError(
            "The onboarding record is invalid."
        ) from error

    return business


def onboarding_business_exists(
    business_slug: str,
) -> bool:
    """
    Return True when a business exists in persistent storage.
    """

    safe_slug = _clean_business_slug(
        business_slug
    )

    try:
        return business_record_exists(
            safe_slug
        )

    except OnboardingRepositoryError as error:
        raise OnboardingStorageError(
            "Unable to check onboarding progress."
        ) from error


def delete_onboarding_business(
    business_slug: str,
) -> bool:
    """
    Delete one onboarding business.
    """

    safe_slug = _clean_business_slug(
        business_slug
    )

    try:
        return delete_business_record(
            safe_slug
        )

    except OnboardingRepositoryError as error:
        raise OnboardingStorageError(
            "Unable to delete onboarding progress."
        ) from error


def list_onboarding_businesses() -> list[
    OnboardingBusiness
]:
    """
    Return every valid onboarding business from persistent storage.
    """

    try:
        raw_records = (
            list_business_records()
        )

    except OnboardingRepositoryError as error:
        raise OnboardingStorageError(
            "Unable to list onboarding records."
        ) from error

    businesses: list[
        OnboardingBusiness
    ] = []

    for raw_data in raw_records:
        if not isinstance(
            raw_data,
            dict,
        ):
            continue

        try:
            business = (
                OnboardingBusiness.from_dict(
                    raw_data
                )
            )

        except (
            TypeError,
            ValueError,
        ):
            continue

        businesses.append(
            business
        )

    return businesses


def onboarding_storage_health() -> dict:
    """
    Return basic persistent-storage health information.

    Useful for local testing and deployment diagnostics.
    """

    try:
        return repository_health()

    except OnboardingRepositoryError as error:
        raise OnboardingStorageError(
            "Unable to check onboarding storage."
        ) from error