from __future__ import annotations

"""
TrimTech onboarding storage service.

This module saves and loads onboarding records as JSON files.
It gives us a simple working foundation now and can later be
replaced with a database without changing the onboarding pages.
"""

import json
import os
from pathlib import Path
from typing import Any

from trimtech.modules.onboarding.models import (
    OnboardingBusiness,
    create_business_slug,
)


DEFAULT_STORAGE_DIRECTORY = Path(
    os.getenv(
        "ONBOARDING_STORAGE_DIR",
        "data/onboarding",
    )
)


class OnboardingStorageError(RuntimeError):
    """Raised when onboarding data cannot be saved or loaded."""


def storage_directory() -> Path:
    directory = DEFAULT_STORAGE_DIRECTORY
    directory.mkdir(
        parents=True,
        exist_ok=True,
    )
    return directory


def business_file_path(
    business_slug: str,
) -> Path:
    safe_slug = create_business_slug(
        business_slug
    )

    if not safe_slug:
        raise OnboardingStorageError(
            "A valid business slug is required."
        )

    return storage_directory() / (
        f"{safe_slug}.json"
    )


def save_onboarding_business(
    business: OnboardingBusiness,
) -> Path:
    errors = business.validate()

    if errors:
        raise OnboardingStorageError(
            " ".join(errors)
        )

    path = business_file_path(
        business.business_slug
    )

    temporary_path = path.with_suffix(
        ".json.tmp"
    )

    payload = business.to_dict()

    try:
        temporary_path.write_text(
            json.dumps(
                payload,
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        temporary_path.replace(path)

    except OSError as error:
        raise OnboardingStorageError(
            "Unable to save onboarding progress."
        ) from error

    return path


def load_onboarding_business(
    business_slug: str,
) -> OnboardingBusiness | None:
    path = business_file_path(
        business_slug
    )

    if not path.exists():
        return None

    try:
        raw_data = json.loads(
            path.read_text(
                encoding="utf-8",
            )
        )

    except (
        OSError,
        json.JSONDecodeError,
    ) as error:
        raise OnboardingStorageError(
            "Unable to load onboarding progress."
        ) from error

    if not isinstance(raw_data, dict):
        raise OnboardingStorageError(
            "The onboarding record is invalid."
        )

    return OnboardingBusiness.from_dict(
        raw_data
    )


def onboarding_business_exists(
    business_slug: str,
) -> bool:
    return business_file_path(
        business_slug
    ).exists()


def delete_onboarding_business(
    business_slug: str,
) -> bool:
    path = business_file_path(
        business_slug
    )

    if not path.exists():
        return False

    try:
        path.unlink()
    except OSError as error:
        raise OnboardingStorageError(
            "Unable to delete onboarding progress."
        ) from error

    return True


def list_onboarding_businesses() -> list[
    OnboardingBusiness
]:
    businesses: list[OnboardingBusiness] = []

    try:
        files = sorted(
            storage_directory().glob(
                "*.json"
            )
        )
    except OSError as error:
        raise OnboardingStorageError(
            "Unable to list onboarding records."
        ) from error

    for path in files:
        try:
            raw_data: Any = json.loads(
                path.read_text(
                    encoding="utf-8",
                )
            )

            if not isinstance(raw_data, dict):
                continue

            businesses.append(
                OnboardingBusiness.from_dict(
                    raw_data
                )
            )

        except (
            OSError,
            json.JSONDecodeError,
            TypeError,
            ValueError,
        ):
            continue

    return businesses