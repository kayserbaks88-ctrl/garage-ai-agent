from __future__ import annotations

import os
from typing import Any

from trimtech.core.business import BusinessConfig
from trimtech.core.registry import get_active_business


def _normalise_business_type(value: str | None) -> str:
    return (
        str(value or "")
        .strip()
        .lower()
        .replace("-", "_")
        .replace(" ", "_")
    )


# ---------------------------------------------------------------------
# Active business
# ---------------------------------------------------------------------

ACTIVE_BUSINESS: BusinessConfig = get_active_business()

BUSINESS = _normalise_business_type(
    ACTIVE_BUSINESS.business_type
)

if not BUSINESS:
    BUSINESS = "garage"


# ---------------------------------------------------------------------
# Backwards-compatible configuration adapter
# ---------------------------------------------------------------------

class LegacyConfigAdapter:
    """
    Compatibility layer between the original application and the new
    TrimTech BusinessConfig architecture.

    Existing files can continue using:

        CONFIG.BUSINESS_NAME
        CONFIG.QUESTIONS
        CONFIG.SERVICES

    while the data is now supplied by the new business registry.
    """

    def __init__(self, business: BusinessConfig) -> None:
        self._business = business

    @property
    def BUSINESS_ID(self) -> str:
        return str(
            getattr(self._business, "business_id", "")
            or ""
        ).strip()

    @property
    def BUSINESS_TYPE(self) -> str:
        return str(
            getattr(self._business, "business_type", "")
            or ""
        ).strip()

    @property
    def BUSINESS_NAME(self) -> str:
        return str(
            getattr(self._business, "business_name", "")
            or "TrimTech"
        ).strip()

    @property
    def TIMEZONE(self) -> str:
        return str(
            getattr(self._business, "timezone_name", "")
            or "Europe/London"
        ).strip()

    @property
    def CURRENCY(self) -> str:
        return str(
            getattr(self._business, "currency_symbol", "")
            or getattr(self._business, "currency", "")
            or "£"
        ).strip()

    @property
    def QUESTIONS(self) -> Any:
        metadata = getattr(
            self._business,
            "metadata",
            {},
        ) or {}

        return metadata.get(
            "questions",
            (),
        )

    @property
    def SERVICES(self) -> Any:
        return getattr(
            self._business,
            "services",
            {},
        )

    @property
    def FEATURES(self) -> Any:
        return getattr(
            self._business,
            "features",
            None,
        )

    @property
    def METADATA(self) -> dict[str, Any]:
        metadata = getattr(
            self._business,
            "metadata",
            {},
        ) or {}

        return dict(metadata)

    def __getattr__(self, name: str) -> Any:
        """
        Allow older code to access matching BusinessConfig attributes
        through CONFIG without needing immediate rewrites.
        """

        try:
            return getattr(
                self._business,
                name,
            )

        except AttributeError as error:
            raise AttributeError(
                f"Business configuration has no attribute {name!r}."
            ) from error


CONFIG = LegacyConfigAdapter(
    ACTIVE_BUSINESS
)


# ---------------------------------------------------------------------
# Compatibility helpers used by existing application files
# ---------------------------------------------------------------------

def get_business() -> BusinessConfig:
    return ACTIVE_BUSINESS


def get_business_type() -> str:
    return BUSINESS


def get_business_name() -> str:
    return CONFIG.BUSINESS_NAME


def get_questions() -> Any:
    return CONFIG.QUESTIONS


def get_services() -> Any:
    return CONFIG.SERVICES


def get_features() -> Any:
    return CONFIG.FEATURES


def is_feature_enabled(
    feature_name: str,
) -> bool:
    features = get_features()

    if features is None:
        return False

    checker = getattr(
        features,
        "is_enabled",
        None,
    )

    if callable(checker):
        return bool(
            checker(feature_name)
        )

    return bool(
        getattr(
            features,
            feature_name,
            False,
        )
    )


def get_timezone_name() -> str:
    return CONFIG.TIMEZONE


def get_currency_symbol() -> str:
    return CONFIG.CURRENCY


# ---------------------------------------------------------------------
# Temporary legacy Garage integration compatibility
# ---------------------------------------------------------------------

if BUSINESS == "garage":
    try:
        from integrations import garage_agent  # noqa: F401

    except ImportError:
        garage_agent = None
else:
    garage_agent = None


def describe_active_business() -> dict[str, Any]:
    """
    Small diagnostic helper for local migration testing.
    """

    services = get_services()

    try:
        service_count = len(services)
    except TypeError:
        service_count = 0

    return {
        "business_id": CONFIG.BUSINESS_ID,
        "business_type": BUSINESS,
        "business_name": get_business_name(),
        "timezone": get_timezone_name(),
        "currency": get_currency_symbol(),
        "service_count": service_count,
    }