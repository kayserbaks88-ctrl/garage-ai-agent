from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class BusinessFeatures:
    """
    Controls which TrimTech modules and business-specific features
    are enabled for a business.
    """

    dashboard: bool = True
    bookings: bool = True
    crm: bool = True
    reminders: bool = True
    revenue: bool = True
    reports: bool = True
    analytics: bool = True
    ai_activity: bool = True

    voice_agent: bool = False
    whatsapp: bool = False
    email: bool = False
    sms: bool = False

    vehicles: bool = False
    dvla: bool = False
    mot_reminders: bool = False
    service_reminders: bool = False

    staff: bool = False
    sites: bool = False
    invoices: bool = False
    payroll: bool = False

    def is_enabled(self, feature_name: str) -> bool:
        """
        Check whether a feature is enabled.
        """

        normalised_name = str(feature_name or "").strip().lower()

        if not normalised_name:
            return False

        if not hasattr(self, normalised_name):
            return False

        return bool(getattr(self, normalised_name))

    def to_dict(self) -> dict[str, bool]:
        return {
            "dashboard": self.dashboard,
            "bookings": self.bookings,
            "crm": self.crm,
            "reminders": self.reminders,
            "revenue": self.revenue,
            "reports": self.reports,
            "analytics": self.analytics,
            "ai_activity": self.ai_activity,
            "voice_agent": self.voice_agent,
            "whatsapp": self.whatsapp,
            "email": self.email,
            "sms": self.sms,
            "vehicles": self.vehicles,
            "dvla": self.dvla,
            "mot_reminders": self.mot_reminders,
            "service_reminders": self.service_reminders,
            "staff": self.staff,
            "sites": self.sites,
            "invoices": self.invoices,
            "payroll": self.payroll,
        }


@dataclass(frozen=True)
class ServiceDefinition:
    """
    Describes one service offered by a business.

    This can be used by bookings, calendars, dashboards,
    reminders, reports and revenue calculations.
    """

    key: str
    name: str
    duration_minutes: int
    price: float = 0.0
    aliases: tuple[str, ...] = field(default_factory=tuple)
    enabled: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        clean_key = self.key.strip().lower().replace(" ", "_")
        clean_name = self.name.strip()

        if not clean_key:
            raise ValueError("Service key cannot be empty.")

        if not clean_name:
            raise ValueError("Service name cannot be empty.")

        if self.duration_minutes <= 0:
            raise ValueError(
                "Service duration must be greater than zero."
            )

        if self.price < 0:
            raise ValueError(
                "Service price cannot be negative."
            )

        object.__setattr__(self, "key", clean_key)
        object.__setattr__(self, "name", clean_name)
        object.__setattr__(
            self,
            "price",
            round(float(self.price), 2),
        )

    def matches(self, value: Any) -> bool:
        candidate = normalise_service_value(value)

        if not candidate:
            return False

        accepted_values = {
            normalise_service_value(self.key),
            normalise_service_value(self.name),
        }

        accepted_values.update(
            normalise_service_value(alias)
            for alias in self.aliases
            if normalise_service_value(alias)
        )

        if candidate in accepted_values:
            return True

        return any(
            accepted_value in candidate
            for accepted_value in accepted_values
            if accepted_value
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "name": self.name,
            "duration_minutes": self.duration_minutes,
            "price": self.price,
            "aliases": list(self.aliases),
            "enabled": self.enabled,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class BusinessConfig:
    """
    Shared configuration for one business using TrimTech.

    The same platform can load different BusinessConfig objects
    for garages, barbers, cleaning companies and other industries.
    """

    business_id: str
    business_type: str
    business_name: str

    timezone_name: str = "Europe/London"
    currency_code: str = "GBP"
    currency_symbol: str = "£"

    features: BusinessFeatures = field(
        default_factory=BusinessFeatures
    )

    services: tuple[ServiceDefinition, ...] = field(
        default_factory=tuple
    )

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        clean_business_id = (
            self.business_id
            .strip()
            .lower()
            .replace(" ", "-")
        )

        clean_business_type = (
            self.business_type
            .strip()
            .lower()
            .replace(" ", "_")
        )

        clean_business_name = self.business_name.strip()

        if not clean_business_id:
            raise ValueError(
                "Business ID cannot be empty."
            )

        if not clean_business_type:
            raise ValueError(
                "Business type cannot be empty."
            )

        if not clean_business_name:
            raise ValueError(
                "Business name cannot be empty."
            )

        try:
            ZoneInfo(self.timezone_name)
        except Exception as error:
            raise ValueError(
                f"Invalid timezone: {self.timezone_name}"
            ) from error

        object.__setattr__(
            self,
            "business_id",
            clean_business_id,
        )

        object.__setattr__(
            self,
            "business_type",
            clean_business_type,
        )

        object.__setattr__(
            self,
            "business_name",
            clean_business_name,
        )

        self._validate_unique_services()

    @property
    def timezone(self) -> ZoneInfo:
        return ZoneInfo(self.timezone_name)

    def _validate_unique_services(self) -> None:
        seen_keys: set[str] = set()

        for service in self.services:
            if service.key in seen_keys:
                raise ValueError(
                    f"Duplicate service key: {service.key}"
                )

            seen_keys.add(service.key)

    def feature_enabled(
        self,
        feature_name: str,
    ) -> bool:
        return self.features.is_enabled(feature_name)

    def enabled_services(
        self,
    ) -> tuple[ServiceDefinition, ...]:
        return tuple(
            service
            for service in self.services
            if service.enabled
        )

    def service_by_key(
        self,
        service_key: Any,
    ) -> ServiceDefinition | None:
        candidate = normalise_service_value(
            service_key
        ).replace(" ", "_")

        if not candidate:
            return None

        for service in self.services:
            if service.key == candidate:
                return service

        return None

    def resolve_service(
        self,
        value: Any,
    ) -> ServiceDefinition | None:
        candidate = normalise_service_value(value)

        if not candidate:
            return None

        direct_match = self.service_by_key(candidate)

        if direct_match:
            return direct_match

        for service in self.enabled_services():
            if service.matches(candidate):
                return service

        return None

    def service_label(self, value: Any) -> str:
        service = self.resolve_service(value)

        if service:
            return service.name

        fallback = str(value or "").strip()

        return fallback or "Appointment"

    def service_price(self, value: Any) -> float:
        service = self.resolve_service(value)

        if not service:
            return 0.0

        return service.price

    def service_duration(self, value: Any) -> int:
        service = self.resolve_service(value)

        if not service:
            return 0

        return service.duration_minutes

    def to_dict(self) -> dict[str, Any]:
        return {
            "business_id": self.business_id,
            "business_type": self.business_type,
            "business_name": self.business_name,
            "timezone": self.timezone_name,
            "currency": {
                "code": self.currency_code,
                "symbol": self.currency_symbol,
            },
            "features": self.features.to_dict(),
            "services": [
                service.to_dict()
                for service in self.enabled_services()
            ],
            "metadata": dict(self.metadata),
        }


def normalise_service_value(value: Any) -> str:
    """
    Convert service names into a consistent comparison format.
    """

    text = str(value or "").strip().lower()

    return (
        text
        .replace("_", " ")
        .replace("-", " ")
        .replace(".", "")
        .replace("&", "and")
    )