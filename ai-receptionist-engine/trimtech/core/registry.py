from __future__ import annotations

import importlib
import os
from collections.abc import Iterable

from trimtech.core.business import BusinessConfig


DEFAULT_BUSINESS_TYPE = "garage"


class BusinessRegistry:
    """
    Loads and stores business configurations.

    Each business lives inside:

        trimtech/businesses/<business_type>/config.py

    That config module must expose:

        BUSINESS_CONFIG
    """

    def __init__(self) -> None:
        self._businesses: dict[str, BusinessConfig] = {}

    @staticmethod
    def normalise_business_type(value: str | None) -> str:
        business_type = str(value or "").strip().lower()

        return (
            business_type
            .replace("-", "_")
            .replace(" ", "_")
        )

    def register(
        self,
        business: BusinessConfig,
    ) -> BusinessConfig:
        if not isinstance(business, BusinessConfig):
            raise TypeError(
                "Only BusinessConfig objects can be registered."
            )

        business_type = self.normalise_business_type(
            business.business_type
        )

        if not business_type:
            raise ValueError(
                "Business type cannot be empty."
            )

        existing = self._businesses.get(business_type)

        if existing and existing != business:
            raise ValueError(
                f"Business type already registered: {business_type}"
            )

        self._businesses[business_type] = business

        return business

    def load(
        self,
        business_type: str,
    ) -> BusinessConfig:
        normalised_type = self.normalise_business_type(
            business_type
        )

        if not normalised_type:
            raise ValueError(
                "Business type cannot be empty."
            )

        registered = self._businesses.get(
            normalised_type
        )

        if registered:
            return registered

        module_path = (
            f"trimtech.businesses."
            f"{normalised_type}.config"
        )

        try:
            config_module = importlib.import_module(
                module_path
            )

        except ModuleNotFoundError as error:
            if error.name == module_path:
                raise LookupError(
                    f"Unknown business type: {normalised_type}"
                ) from error

            raise

        business = getattr(
            config_module,
            "BUSINESS_CONFIG",
            None,
        )

        if business is None:
            raise AttributeError(
                f"{module_path} must define BUSINESS_CONFIG."
            )

        return self.register(business)

    def load_active(self) -> BusinessConfig:
        business_type = (
            os.getenv("TRIMTECH_BUSINESS_TYPE")
            or os.getenv("BUSINESS_TYPE")
            or DEFAULT_BUSINESS_TYPE
        )

        return self.load(business_type)

    def get(
        self,
        business_type: str,
    ) -> BusinessConfig | None:
        normalised_type = self.normalise_business_type(
            business_type
        )

        if not normalised_type:
            return None

        return self._businesses.get(
            normalised_type
        )

    def registered_business_types(
        self,
    ) -> tuple[str, ...]:
        return tuple(
            sorted(self._businesses.keys())
        )

    def registered_businesses(
        self,
    ) -> tuple[BusinessConfig, ...]:
        return tuple(
            self._businesses[key]
            for key in sorted(self._businesses)
        )

    def register_many(
        self,
        businesses: Iterable[BusinessConfig],
    ) -> None:
        for business in businesses:
            self.register(business)

    def clear(self) -> None:
        self._businesses.clear()


business_registry = BusinessRegistry()


def get_active_business() -> BusinessConfig:
    """
    Return the business selected by the environment.

    Example Render environment value:

        TRIMTECH_BUSINESS_TYPE=garage
    """

    return business_registry.load_active()


def load_business(
    business_type: str,
) -> BusinessConfig:
    return business_registry.load(business_type)