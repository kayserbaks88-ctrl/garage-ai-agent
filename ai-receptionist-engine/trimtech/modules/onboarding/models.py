from __future__ import annotations

"""
TrimTech onboarding data models.

This module defines the information collected while a new business
is being configured for the TrimTech AI platform.
"""

import re
from dataclasses import asdict, dataclass, field
from typing import Any


SUPPORTED_BUSINESS_TYPES = {
    "garage",
    "barber",
    "cleaning",
    "accountant",
    "other",
}


def clean_text(value: Any) -> str:
    return str(value or "").strip()


def normalise_business_type(value: Any) -> str:
    business_type = clean_text(value).lower()
    business_type = re.sub(
        r"[^a-z0-9_-]+",
        "_",
        business_type,
    ).strip("_")

    if business_type in SUPPORTED_BUSINESS_TYPES:
        return business_type

    return "other"


def create_business_slug(value: Any) -> str:
    slug = clean_text(value).lower()

    slug = re.sub(
        r"[^a-z0-9]+",
        "-",
        slug,
    )

    return slug.strip("-")


@dataclass(slots=True)
class OnboardingBusiness:
    business_name: str
    owner_name: str
    email: str
    phone: str
    business_type: str

    business_slug: str = ""
    address: str = ""
    postcode: str = ""
    website: str = ""

    timezone: str = "Europe/London"
    currency: str = "GBP"
    country: str = "United Kingdom"

    services: list[dict[str, Any]] = field(
        default_factory=list
    )

    opening_hours: dict[str, Any] = field(
        default_factory=dict
    )

    integrations: dict[str, Any] = field(
        default_factory=dict
    )

    onboarding_complete: bool = False

    def __post_init__(self) -> None:
        self.business_name = clean_text(
            self.business_name
        )

        self.owner_name = clean_text(
            self.owner_name
        )

        self.email = clean_text(
            self.email
        ).lower()

        self.phone = clean_text(
            self.phone
        )

        self.business_type = normalise_business_type(
            self.business_type
        )

        self.business_slug = (
            create_business_slug(
                self.business_slug
                or self.business_name
            )
        )

        self.address = clean_text(
            self.address
        )

        self.postcode = clean_text(
            self.postcode
        ).upper()

        self.website = clean_text(
            self.website
        )

    def validate(self) -> list[str]:
        errors: list[str] = []

        if not self.business_name:
            errors.append(
                "Business name is required."
            )

        if not self.owner_name:
            errors.append(
                "Owner name is required."
            )

        if not self.email:
            errors.append(
                "Email address is required."
            )
        elif "@" not in self.email:
            errors.append(
                "Enter a valid email address."
            )

        if not self.phone:
            errors.append(
                "Phone number is required."
            )

        if not self.business_slug:
            errors.append(
                "The business URL could not be created."
            )

        return errors

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
    ) -> "OnboardingBusiness":
        return cls(
            business_name=data.get(
                "business_name",
                "",
            ),
            owner_name=data.get(
                "owner_name",
                "",
            ),
            email=data.get(
                "email",
                "",
            ),
            phone=data.get(
                "phone",
                "",
            ),
            business_type=data.get(
                "business_type",
                "other",
            ),
            business_slug=data.get(
                "business_slug",
                "",
            ),
            address=data.get(
                "address",
                "",
            ),
            postcode=data.get(
                "postcode",
                "",
            ),
            website=data.get(
                "website",
                "",
            ),
            timezone=data.get(
                "timezone",
                "Europe/London",
            ),
            currency=data.get(
                "currency",
                "GBP",
            ),
            country=data.get(
                "country",
                "United Kingdom",
            ),
            services=list(
                data.get(
                    "services",
                    [],
                )
                or []
            ),
            opening_hours=dict(
                data.get(
                    "opening_hours",
                    {},
                )
                or {}
            ),
            integrations=dict(
                data.get(
                    "integrations",
                    {},
                )
                or {}
            ),
            onboarding_complete=bool(
                data.get(
                    "onboarding_complete",
                    False,
                )
            ),
        )