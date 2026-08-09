from __future__ import annotations

import importlib
import os
import re
from collections.abc import Iterable
from dataclasses import replace
from typing import Any

from trimtech.core.business import (
    BusinessConfig,
    BusinessFeatures,
    ServiceDefinition,
)


DEFAULT_BUSINESS_TYPE = "garage"


class BusinessRegistry:
    """
    Loads and stores TrimTech business configurations.

    There are two different levels:

    1. Business type templates

       Examples:

           garage
           barber
           cleaning
           accountant

       These live inside:

           trimtech/businesses/<business_type>/config.py

       and expose:

           BUSINESS_CONFIG

    2. Individual onboarded businesses

       Examples:

           elite-auto-centre
           trimtech-garage
           jays-barbers

       These are loaded from the onboarding storage and converted
       into BusinessConfig objects at runtime.

    This allows many businesses of the same type to share the same
    TrimTech engine while keeping their own identity, services,
    integrations and settings.
    """

    def __init__(self) -> None:
        self._business_types: dict[str, BusinessConfig] = {}
        self._business_instances: dict[str, BusinessConfig] = {}

    # ---------------------------------------------------------
    # Normalisation
    # ---------------------------------------------------------

    @staticmethod
    def normalise_business_type(
        value: str | None,
    ) -> str:
        business_type = str(value or "").strip().lower()

        return (
            business_type
            .replace("-", "_")
            .replace(" ", "_")
        )

    @staticmethod
    def normalise_business_id(
        value: str | None,
    ) -> str:
        business_id = str(value or "").strip().lower()

        business_id = re.sub(
            r"[^a-z0-9]+",
            "-",
            business_id,
        )

        return business_id.strip("-")

    @staticmethod
    def normalise_service_key(
        value: Any,
    ) -> str:
        text = str(value or "").strip().lower()

        text = re.sub(
            r"[^a-z0-9]+",
            "_",
            text,
        )

        return text.strip("_")

    # ---------------------------------------------------------
    # Business type templates
    # ---------------------------------------------------------

    def register(
        self,
        business: BusinessConfig,
    ) -> BusinessConfig:
        """
        Register a business TYPE configuration.

        Example:

            garage
            barber
        """

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

        existing = self._business_types.get(
            business_type
        )

        if existing and existing != business:
            raise ValueError(
                f"Business type already registered: "
                f"{business_type}"
            )

        self._business_types[
            business_type
        ] = business

        return business

    def load(
        self,
        business_type: str,
    ) -> BusinessConfig:
        """
        Load a business TYPE template.

        Example:

            load("garage")
        """

        normalised_type = self.normalise_business_type(
            business_type
        )

        if not normalised_type:
            raise ValueError(
                "Business type cannot be empty."
            )

        registered = self._business_types.get(
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
                    f"Unknown business type: "
                    f"{normalised_type}"
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

    # ---------------------------------------------------------
    # Individual business instances
    # ---------------------------------------------------------

    def register_instance(
        self,
        business: BusinessConfig,
    ) -> BusinessConfig:
        """
        Register one individual onboarded business.

        Unlike business type registration, multiple business
        instances may use the same business_type.
        """

        if not isinstance(business, BusinessConfig):
            raise TypeError(
                "Only BusinessConfig objects can be registered."
            )

        business_id = self.normalise_business_id(
            business.business_id
        )

        if not business_id:
            raise ValueError(
                "Business ID cannot be empty."
            )

        self._business_instances[
            business_id
        ] = business

        return business

    def load_instance(
        self,
        business_id: str,
        *,
        refresh: bool = False,
    ) -> BusinessConfig:
        """
        Load an individual business created by onboarding.

        Example:

            load_instance("elite-auto-centre")

        The onboarding record supplies the identity, services,
        integrations, timezone and currency.

        The matching business type config supplies the standard
        TrimTech feature defaults for that industry.
        """

        normalised_id = self.normalise_business_id(
            business_id
        )

        if not normalised_id:
            raise ValueError(
                "Business ID cannot be empty."
            )

        if not refresh:
            cached = self._business_instances.get(
                normalised_id
            )

            if cached:
                return cached

        onboarding_business = (
            self._load_onboarding_business(
                normalised_id
            )
        )

        if onboarding_business is None:
            raise LookupError(
                f"Unknown business: {normalised_id}"
            )

        business_type = self.normalise_business_type(
            onboarding_business.business_type
        )

        if not business_type:
            raise ValueError(
                f"Business {normalised_id} "
                f"has no business type."
            )

        try:
            type_template = self.load(
                business_type
            )
        except LookupError:
            type_template = self._generic_template(
                business_type=business_type,
                business_id=normalised_id,
                business_name=(
                    onboarding_business.business_name
                    or normalised_id
                ),
            )

        services = self._build_services(
            onboarding_business.services
        )

        if not services:
            services = type_template.services

        features = self._build_features(
            template_features=type_template.features,
            integrations=(
                onboarding_business.integrations
                or {}
            ),
        )

        currency_code = (
            str(
                onboarding_business.currency
                or type_template.currency_code
                or "GBP"
            )
            .strip()
            .upper()
        )

        currency_symbol = self._currency_symbol(
            currency_code,
            fallback=type_template.currency_symbol,
        )

        timezone_name = (
            str(
                onboarding_business.timezone
                or type_template.timezone_name
                or "Europe/London"
            )
            .strip()
        )

        metadata = dict(
            type_template.metadata
            or {}
        )

        metadata.update(
            {
                "business_slug": normalised_id,
                "owner_name": (
                    onboarding_business.owner_name
                ),
                "email": onboarding_business.email,
                "phone": onboarding_business.phone,
                "address": onboarding_business.address,
                "postcode": onboarding_business.postcode,
                "website": onboarding_business.website,
                "country": onboarding_business.country,
                "onboarding_complete": bool(
                    onboarding_business.onboarding_complete
                ),
                "source": "onboarding",
            }
        )

        business = BusinessConfig(
            business_id=normalised_id,
            business_type=business_type,
            business_name=(
                onboarding_business.business_name
                or type_template.business_name
            ),
            timezone_name=timezone_name,
            currency_code=currency_code,
            currency_symbol=currency_symbol,
            features=features,
            services=services,
            metadata=metadata,
        )

        return self.register_instance(
            business
        )

    def _load_onboarding_business(
        self,
        business_id: str,
    ):
        """
        Import the onboarding service only when required.

        Keeping this import here avoids forcing the core registry
        to initialise the onboarding module during normal startup.
        """

        try:
            from trimtech.modules.onboarding.service import (
                load_onboarding_business,
            )
        except ImportError as error:
            raise RuntimeError(
                "TrimTech onboarding module "
                "could not be loaded."
            ) from error

        try:
            return load_onboarding_business(
                business_id
            )

        except FileNotFoundError:
            return None

        except Exception as error:
            # Some storage implementations return None when a
            # business does not exist, while others may raise.
            #
            # Preserve real errors except for clearly missing
            # business records.
            error_text = str(error).lower()

            missing_markers = (
                "not found",
                "does not exist",
                "no such file",
                "unknown business",
            )

            if any(
                marker in error_text
                for marker in missing_markers
            ):
                return None

            raise

    # ---------------------------------------------------------
    # Service conversion
    # ---------------------------------------------------------

    def _build_services(
        self,
        raw_services: Any,
    ) -> tuple[ServiceDefinition, ...]:
        if not isinstance(
            raw_services,
            (list, tuple),
        ):
            return ()

        services: list[ServiceDefinition] = []
        used_keys: set[str] = set()

        for index, raw_service in enumerate(
            raw_services,
            start=1,
        ):
            if not isinstance(
                raw_service,
                dict,
            ):
                continue

            name = str(
                raw_service.get("name")
                or raw_service.get("service_name")
                or raw_service.get("label")
                or ""
            ).strip()

            if not name:
                continue

            key = self.normalise_service_key(
                raw_service.get("key")
                or raw_service.get("service_key")
                or name
            )

            if not key:
                key = f"service_{index}"

            original_key = key
            duplicate_number = 2

            while key in used_keys:
                key = (
                    f"{original_key}_"
                    f"{duplicate_number}"
                )
                duplicate_number += 1

            duration = self._safe_positive_int(
                raw_service.get(
                    "duration_minutes",
                    raw_service.get(
                        "duration",
                        raw_service.get(
                            "minutes",
                            30,
                        ),
                    ),
                ),
                default=30,
            )

            price = self._safe_price(
                raw_service.get(
                    "price",
                    0.0,
                )
            )

            aliases_raw = raw_service.get(
                "aliases",
                (),
            )

            if isinstance(
                aliases_raw,
                str,
            ):
                aliases = tuple(
                    item.strip()
                    for item in aliases_raw.split(",")
                    if item.strip()
                )

            elif isinstance(
                aliases_raw,
                (list, tuple, set),
            ):
                aliases = tuple(
                    str(item).strip()
                    for item in aliases_raw
                    if str(item).strip()
                )

            else:
                aliases = ()

            metadata = raw_service.get(
                "metadata",
                {},
            )

            if not isinstance(
                metadata,
                dict,
            ):
                metadata = {}

            enabled = bool(
                raw_service.get(
                    "enabled",
                    True,
                )
            )

            services.append(
                ServiceDefinition(
                    key=key,
                    name=name,
                    duration_minutes=duration,
                    price=price,
                    aliases=aliases,
                    enabled=enabled,
                    metadata=dict(metadata),
                )
            )

            used_keys.add(key)

        return tuple(services)

    # ---------------------------------------------------------
    # Feature conversion
    # ---------------------------------------------------------

    def _build_features(
        self,
        *,
        template_features: BusinessFeatures,
        integrations: dict[str, Any],
    ) -> BusinessFeatures:
        """
        Start with the industry's normal feature set and then
        enable communication features selected during onboarding.
        """

        google_calendar = bool(
            integrations.get(
                "google_calendar",
                False,
            )
        )

        vapi_voice = bool(
            integrations.get(
                "vapi_voice",
                False,
            )
        )

        whatsapp = bool(
            integrations.get(
                "whatsapp",
                False,
            )
        )

        email = bool(
            integrations.get(
                "email",
                False,
            )
        )

        return replace(
            template_features,
            dashboard=True,
            bookings=(
                template_features.bookings
                or google_calendar
            ),
            voice_agent=(
                template_features.voice_agent
                or vapi_voice
            ),
            whatsapp=(
                template_features.whatsapp
                or whatsapp
            ),
            email=(
                template_features.email
                or email
            ),
        )

    # ---------------------------------------------------------
    # Generic business fallback
    # ---------------------------------------------------------

    def _generic_template(
        self,
        *,
        business_type: str,
        business_id: str,
        business_name: str,
    ) -> BusinessConfig:
        """
        Fallback for an onboarded business type that does not yet
        have its own trimtech/businesses/<type>/config.py module.

        This allows onboarding to continue working while new
        industry-specific templates are added later.
        """

        return BusinessConfig(
            business_id=business_id,
            business_type=business_type,
            business_name=business_name,
            timezone_name="Europe/London",
            currency_code="GBP",
            currency_symbol="£",
            features=BusinessFeatures(
                dashboard=True,
                bookings=True,
                crm=True,
                reminders=True,
                revenue=True,
                reports=True,
                analytics=True,
                ai_activity=True,
            ),
            services=(),
            metadata={
                "industry_template": "generic",
            },
        )

    # ---------------------------------------------------------
    # Helpers
    # ---------------------------------------------------------

    @staticmethod
    def _safe_positive_int(
        value: Any,
        *,
        default: int,
    ) -> int:
        try:
            number = int(
                float(value)
            )
        except (
            TypeError,
            ValueError,
        ):
            return default

        if number <= 0:
            return default

        return number

    @staticmethod
    def _safe_price(
        value: Any,
    ) -> float:
        try:
            price = float(value)
        except (
            TypeError,
            ValueError,
        ):
            return 0.0

        if price < 0:
            return 0.0

        return round(
            price,
            2,
        )

    @staticmethod
    def _currency_symbol(
        currency_code: str,
        *,
        fallback: str = "£",
    ) -> str:
        symbols = {
            "GBP": "£",
            "USD": "$",
            "EUR": "€",
            "CAD": "$",
            "AUD": "$",
            "NZD": "$",
            "JPY": "¥",
        }

        return symbols.get(
            currency_code.upper(),
            fallback or currency_code,
        )

    # ---------------------------------------------------------
    # Active business
    # ---------------------------------------------------------

    def load_active(
        self,
    ) -> BusinessConfig:
        """
        Load the currently selected business.

        TRIMTECH_BUSINESS_ID takes priority when present.

        This means a deployment can run as:

            TRIMTECH_BUSINESS_ID=elite-auto-centre

        Otherwise the older business TYPE environment variables
        continue to work exactly as before.
        """

        business_id = (
            os.getenv("TRIMTECH_BUSINESS_ID")
            or os.getenv("BUSINESS_ID")
            or ""
        ).strip()

        if business_id:
            return self.load_instance(
                business_id
            )

        business_type = (
            os.getenv("TRIMTECH_BUSINESS_TYPE")
            or os.getenv("BUSINESS_TYPE")
            or DEFAULT_BUSINESS_TYPE
        )

        return self.load(
            business_type
        )

    # ---------------------------------------------------------
    # Getters
    # ---------------------------------------------------------

    def get(
        self,
        business_type: str,
    ) -> BusinessConfig | None:
        normalised_type = (
            self.normalise_business_type(
                business_type
            )
        )

        if not normalised_type:
            return None

        return self._business_types.get(
            normalised_type
        )

    def get_instance(
        self,
        business_id: str,
    ) -> BusinessConfig | None:
        normalised_id = (
            self.normalise_business_id(
                business_id
            )
        )

        if not normalised_id:
            return None

        return self._business_instances.get(
            normalised_id
        )

    def registered_business_types(
        self,
    ) -> tuple[str, ...]:
        return tuple(
            sorted(
                self._business_types.keys()
            )
        )

    def registered_businesses(
        self,
    ) -> tuple[BusinessConfig, ...]:
        """
        Backwards-compatible list of registered TYPE configs.
        """

        return tuple(
            self._business_types[key]
            for key in sorted(
                self._business_types
            )
        )

    def registered_business_instances(
        self,
    ) -> tuple[BusinessConfig, ...]:
        return tuple(
            self._business_instances[key]
            for key in sorted(
                self._business_instances
            )
        )

    def register_many(
        self,
        businesses: Iterable[BusinessConfig],
    ) -> None:
        for business in businesses:
            self.register(
                business
            )

    def clear(
        self,
    ) -> None:
        self._business_types.clear()
        self._business_instances.clear()


business_registry = BusinessRegistry()


def get_active_business() -> BusinessConfig:
    """
    Return the currently selected TrimTech business.

    Existing type-based deployments continue to work:

        TRIMTECH_BUSINESS_TYPE=garage

    Individual businesses can now also be selected:

        TRIMTECH_BUSINESS_ID=elite-auto-centre
    """

    return business_registry.load_active()


def load_business(
    business_type: str,
) -> BusinessConfig:
    """
    Load a business TYPE template.

    Example:

        load_business("garage")
    """

    return business_registry.load(
        business_type
    )


def load_business_instance(
    business_id: str,
    *,
    refresh: bool = False,
) -> BusinessConfig:
    """
    Load one onboarded business by its unique slug / ID.

    Example:

        load_business_instance(
            "elite-auto-centre"
        )
    """

    return business_registry.load_instance(
        business_id,
        refresh=refresh,
    )