from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


PLATFORM_ADMIN_ROLE = "platform_admin"
BUSINESS_USER_ROLE = "business_user"

ALLOWED_ROLES = {
    PLATFORM_ADMIN_ROLE,
    BUSINESS_USER_ROLE,
}


def utc_now() -> datetime:
    return datetime.now(
        timezone.utc
    )


def utc_now_iso() -> str:
    return utc_now().isoformat()


def clean_text(
    value: Any,
) -> str:
    return str(
        value or ""
    ).strip()


def normalise_username(
    value: Any,
) -> str:
    return (
        clean_text(value)
        .lower()
    )


def normalise_email(
    value: Any,
) -> str:
    return (
        clean_text(value)
        .lower()
    )


def normalise_business_id(
    value: Any,
) -> str:
    return (
        clean_text(value)
        .lower()
        .replace("_", "-")
        .replace(" ", "-")
    )


def new_identifier() -> str:
    return uuid4().hex


@dataclass(slots=True)
class BusinessUser:
    """
    One customer account.

    Every business user is permanently linked to one
    TrimTech business ID.

    Example:

        username:
            john@eliteautocentre.co.uk

        business_id:
            elite-auto-centre

    A business user must never be allowed to access another
    business simply by changing a URL.
    """

    user_id: str
    username: str
    password_hash: str

    business_id: str

    email: str = ""
    full_name: str = ""

    role: str = BUSINESS_USER_ROLE

    active: bool = True

    created_at: str = ""
    updated_at: str = ""
    last_login_at: str = ""

    def __post_init__(
        self,
    ) -> None:
        self.user_id = clean_text(
            self.user_id
        ) or new_identifier()

        self.username = (
            normalise_username(
                self.username
            )
        )

        self.email = normalise_email(
            self.email
        )

        self.full_name = clean_text(
            self.full_name
        )

        self.business_id = (
            normalise_business_id(
                self.business_id
            )
        )

        self.password_hash = clean_text(
            self.password_hash
        )

        self.role = (
            clean_text(
                self.role
            ).lower()
            or BUSINESS_USER_ROLE
        )

        self.created_at = (
            clean_text(
                self.created_at
            )
            or utc_now_iso()
        )

        self.updated_at = (
            clean_text(
                self.updated_at
            )
            or self.created_at
        )

        self.last_login_at = clean_text(
            self.last_login_at
        )

        self.validate()

    def validate(
        self,
    ) -> None:
        if not self.user_id:
            raise ValueError(
                "User ID is required."
            )

        if not self.username:
            raise ValueError(
                "Username is required."
            )

        if not self.password_hash:
            raise ValueError(
                "Password hash is required."
            )

        if not self.business_id:
            raise ValueError(
                "Business ID is required."
            )

        if self.role not in ALLOWED_ROLES:
            raise ValueError(
                f"Unsupported user role: {self.role}"
            )

    def to_dict(
        self,
        *,
        include_password_hash: bool = False,
    ) -> dict[str, Any]:
        data = {
            "user_id": self.user_id,
            "username": self.username,
            "business_id": self.business_id,
            "email": self.email,
            "full_name": self.full_name,
            "role": self.role,
            "active": self.active,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_login_at": self.last_login_at,
        }

        if include_password_hash:
            data[
                "password_hash"
            ] = self.password_hash

        return data

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
    ) -> "BusinessUser":
        return cls(
            user_id=clean_text(
                data.get(
                    "user_id"
                )
            ),
            username=clean_text(
                data.get(
                    "username"
                )
            ),
            password_hash=clean_text(
                data.get(
                    "password_hash"
                )
            ),
            business_id=clean_text(
                data.get(
                    "business_id"
                )
            ),
            email=clean_text(
                data.get(
                    "email"
                )
            ),
            full_name=clean_text(
                data.get(
                    "full_name"
                )
            ),
            role=clean_text(
                data.get(
                    "role"
                )
            )
            or BUSINESS_USER_ROLE,
            active=bool(
                data.get(
                    "active",
                    True,
                )
            ),
            created_at=clean_text(
                data.get(
                    "created_at"
                )
            ),
            updated_at=clean_text(
                data.get(
                    "updated_at"
                )
            ),
            last_login_at=clean_text(
                data.get(
                    "last_login_at"
                )
            ),
        )


@dataclass(slots=True)
class CustomerInvite:
    """
    One secure invitation to create a TrimTech customer account.

    Security design:

    - the raw registration token is sent to the customer
    - only a hash of the token is stored in the database
    - the invitation expires
    - the invitation can only be used once
    - the invitation is tied to one specific business
    """

    invite_id: str

    business_id: str
    business_name: str
    business_type: str

    email: str

    token_hash: str

    expires_at: str

    created_at: str = ""
    used_at: str = ""

    created_by: str = "platform_admin"

    active: bool = True

    def __post_init__(
        self,
    ) -> None:
        self.invite_id = (
            clean_text(
                self.invite_id
            )
            or new_identifier()
        )

        self.business_id = (
            normalise_business_id(
                self.business_id
            )
        )

        self.business_name = clean_text(
            self.business_name
        )

        self.business_type = (
            clean_text(
                self.business_type
            )
            .lower()
            .replace("-", "_")
            .replace(" ", "_")
        )

        self.email = normalise_email(
            self.email
        )

        self.token_hash = clean_text(
            self.token_hash
        )

        self.expires_at = clean_text(
            self.expires_at
        )

        self.created_at = (
            clean_text(
                self.created_at
            )
            or utc_now_iso()
        )

        self.used_at = clean_text(
            self.used_at
        )

        self.created_by = (
            clean_text(
                self.created_by
            )
            or "platform_admin"
        )

        self.validate()

    def validate(
        self,
    ) -> None:
        if not self.invite_id:
            raise ValueError(
                "Invite ID is required."
            )

        if not self.business_id:
            raise ValueError(
                "Business ID is required."
            )

        if not self.business_name:
            raise ValueError(
                "Business name is required."
            )

        if not self.business_type:
            raise ValueError(
                "Business type is required."
            )

        if not self.email:
            raise ValueError(
                "Customer email is required."
            )

        if "@" not in self.email:
            raise ValueError(
                "Customer email is invalid."
            )

        if not self.token_hash:
            raise ValueError(
                "Invite token hash is required."
            )

        if not self.expires_at:
            raise ValueError(
                "Invite expiry is required."
            )

    @property
    def used(
        self,
    ) -> bool:
        return bool(
            self.used_at
        )

    @property
    def expired(
        self,
    ) -> bool:
        try:
            expiry = datetime.fromisoformat(
                self.expires_at.replace(
                    "Z",
                    "+00:00",
                )
            )

        except ValueError:
            return True

        if expiry.tzinfo is None:
            expiry = expiry.replace(
                tzinfo=timezone.utc
            )

        return (
            utc_now()
            >= expiry.astimezone(
                timezone.utc
            )
        )

    @property
    def usable(
        self,
    ) -> bool:
        return (
            self.active
            and not self.used
            and not self.expired
        )

    def to_dict(
        self,
        *,
        include_token_hash: bool = False,
    ) -> dict[str, Any]:
        data = {
            "invite_id": self.invite_id,
            "business_id": self.business_id,
            "business_name": self.business_name,
            "business_type": self.business_type,
            "email": self.email,
            "expires_at": self.expires_at,
            "created_at": self.created_at,
            "used_at": self.used_at,
            "created_by": self.created_by,
            "active": self.active,
            "used": self.used,
            "expired": self.expired,
            "usable": self.usable,
        }

        if include_token_hash:
            data[
                "token_hash"
            ] = self.token_hash

        return data

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
    ) -> "CustomerInvite":
        return cls(
            invite_id=clean_text(
                data.get(
                    "invite_id"
                )
            ),
            business_id=clean_text(
                data.get(
                    "business_id"
                )
            ),
            business_name=clean_text(
                data.get(
                    "business_name"
                )
            ),
            business_type=clean_text(
                data.get(
                    "business_type"
                )
            ),
            email=clean_text(
                data.get(
                    "email"
                )
            ),
            token_hash=clean_text(
                data.get(
                    "token_hash"
                )
            ),
            expires_at=clean_text(
                data.get(
                    "expires_at"
                )
            ),
            created_at=clean_text(
                data.get(
                    "created_at"
                )
            ),
            used_at=clean_text(
                data.get(
                    "used_at"
                )
            ),
            created_by=clean_text(
                data.get(
                    "created_by"
                )
            )
            or "platform_admin",
            active=bool(
                data.get(
                    "active",
                    True,
                )
            ),
        )