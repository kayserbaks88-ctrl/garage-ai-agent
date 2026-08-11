from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
from datetime import timedelta
from pathlib import Path
from typing import Any

from werkzeug.security import (
    check_password_hash,
    generate_password_hash,
)

from trimtech.modules.auth.models import (
    BusinessUser,
    CustomerInvite,
    new_identifier,
    normalise_email,
    normalise_username,
    utc_now,
    utc_now_iso,
)


DEFAULT_DATABASE_PATH = Path(
    os.getenv(
        "ONBOARDING_DB_PATH",
        "data/trimtech.db",
    )
)


class AuthRepositoryError(RuntimeError):
    """
    Raised when TrimTech auth data cannot be read or written.
    """


def database_path() -> Path:
    path = Path(
        os.getenv(
            "ONBOARDING_DB_PATH",
            str(DEFAULT_DATABASE_PATH),
        )
    )

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    return path


def connect() -> sqlite3.Connection:
    try:
        connection = sqlite3.connect(
            database_path(),
            timeout=15,
        )

        connection.row_factory = sqlite3.Row

        connection.execute(
            "PRAGMA foreign_keys = ON"
        )

        connection.execute(
            "PRAGMA journal_mode = WAL"
        )

        ensure_schema(
            connection
        )

        return connection

    except sqlite3.Error as error:
        raise AuthRepositoryError(
            f"Could not open TrimTech auth database: {error}"
        ) from error


def ensure_schema(
    connection: sqlite3.Connection,
) -> None:
    try:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS business_users (
                user_id TEXT PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                business_id TEXT NOT NULL,
                email TEXT NOT NULL DEFAULT '',
                full_name TEXT NOT NULL DEFAULT '',
                role TEXT NOT NULL DEFAULT 'business_user',
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_login_at TEXT NOT NULL DEFAULT ''
            )
            """
        )

        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_business_users_business_id
            ON business_users (business_id)
            """
        )

        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_business_users_email
            ON business_users (email)
            """
        )

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS customer_invites (
                invite_id TEXT PRIMARY KEY,
                business_id TEXT NOT NULL,
                business_name TEXT NOT NULL,
                business_type TEXT NOT NULL,
                email TEXT NOT NULL,
                token_hash TEXT NOT NULL UNIQUE,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                used_at TEXT NOT NULL DEFAULT '',
                created_by TEXT NOT NULL DEFAULT 'platform_admin',
                active INTEGER NOT NULL DEFAULT 1
            )
            """
        )

        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_customer_invites_business_id
            ON customer_invites (business_id)
            """
        )

        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_customer_invites_email
            ON customer_invites (email)
            """
        )

        connection.commit()

    except sqlite3.Error as error:
        raise AuthRepositoryError(
            f"Could not initialise TrimTech auth database: {error}"
        ) from error


# =========================================================
# Password helpers
# =========================================================


def hash_password(
    password: str,
) -> str:
    clean_password = str(
        password or ""
    )

    if len(clean_password) < 10:
        raise ValueError(
            "Password must be at least 10 characters."
        )

    return generate_password_hash(
        clean_password,
    )


def verify_password(
    password_hash: str,
    password: str,
) -> bool:
    try:
        return check_password_hash(
            password_hash,
            password,
        )

    except ValueError:
        return False


# =========================================================
# Invite token helpers
# =========================================================


def create_raw_invite_token() -> str:
    """
    Generate the secret token sent to the customer.
    """

    return secrets.token_urlsafe(
        32
    )


def hash_invite_token(
    raw_token: str,
) -> str:
    return hashlib.sha256(
        str(
            raw_token
            or ""
        ).encode(
            "utf-8"
        )
    ).hexdigest()


# =========================================================
# Business users
# =========================================================


def create_business_user(
    *,
    username: str,
    password: str,
    business_id: str,
    email: str = "",
    full_name: str = "",
) -> BusinessUser:
    clean_username = (
        normalise_username(
            username
        )
    )

    clean_email = (
        normalise_email(
            email
        )
    )

    if not clean_username:
        raise AuthRepositoryError(
            "Username is required."
        )

    password_hash = hash_password(
        password
    )

    user = BusinessUser(
        user_id=new_identifier(),
        username=clean_username,
        password_hash=password_hash,
        business_id=business_id,
        email=clean_email,
        full_name=full_name,
        created_at=utc_now_iso(),
        updated_at=utc_now_iso(),
    )

    connection = connect()

    try:
        connection.execute(
            """
            INSERT INTO business_users (
                user_id,
                username,
                password_hash,
                business_id,
                email,
                full_name,
                role,
                active,
                created_at,
                updated_at,
                last_login_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user.user_id,
                user.username,
                user.password_hash,
                user.business_id,
                user.email,
                user.full_name,
                user.role,
                1 if user.active else 0,
                user.created_at,
                user.updated_at,
                user.last_login_at,
            ),
        )

        connection.commit()

    except sqlite3.IntegrityError as error:
        raise AuthRepositoryError(
            "That username is already registered."
        ) from error

    except sqlite3.Error as error:
        raise AuthRepositoryError(
            f"Could not create business user: {error}"
        ) from error

    finally:
        connection.close()

    return user


def get_business_user_by_username(
    username: str,
) -> BusinessUser | None:
    clean_username = (
        normalise_username(
            username
        )
    )

    if not clean_username:
        return None

    connection = connect()

    try:
        row = connection.execute(
            """
            SELECT *
            FROM business_users
            WHERE username = ?
            LIMIT 1
            """,
            (
                clean_username,
            ),
        ).fetchone()

    except sqlite3.Error as error:
        raise AuthRepositoryError(
            f"Could not load business user: {error}"
        ) from error

    finally:
        connection.close()

    if row is None:
        return None

    return BusinessUser.from_dict(
        dict(
            row
        )
    )


def authenticate_business_user(
    username: str,
    password: str,
) -> BusinessUser | None:
    user = get_business_user_by_username(
        username
    )

    if user is None:
        return None

    if not user.active:
        return None

    if not verify_password(
        user.password_hash,
        password,
    ):
        return None

    mark_business_user_login(
        user.user_id
    )

    return get_business_user_by_username(
        user.username
    )


def mark_business_user_login(
    user_id: str,
) -> None:
    connection = connect()

    try:
        connection.execute(
            """
            UPDATE business_users
            SET
                last_login_at = ?,
                updated_at = ?
            WHERE user_id = ?
            """,
            (
                utc_now_iso(),
                utc_now_iso(),
                user_id,
            ),
        )

        connection.commit()

    except sqlite3.Error as error:
        raise AuthRepositoryError(
            f"Could not update business user login time: {error}"
        ) from error

    finally:
        connection.close()


def list_business_users(
    business_id: str | None = None,
) -> list[BusinessUser]:
    connection = connect()

    try:
        if business_id:
            rows = connection.execute(
                """
                SELECT *
                FROM business_users
                WHERE business_id = ?
                ORDER BY created_at ASC
                """,
                (
                    business_id,
                ),
            ).fetchall()

        else:
            rows = connection.execute(
                """
                SELECT *
                FROM business_users
                ORDER BY created_at ASC
                """
            ).fetchall()

    except sqlite3.Error as error:
        raise AuthRepositoryError(
            f"Could not list business users: {error}"
        ) from error

    finally:
        connection.close()

    return [
        BusinessUser.from_dict(
            dict(
                row
            )
        )
        for row in rows
    ]


# =========================================================
# Customer invites
# =========================================================


def create_customer_invite(
    *,
    business_id: str,
    business_name: str,
    business_type: str,
    email: str,
    created_by: str = "platform_admin",
    expires_hours: int = 72,
) -> tuple[CustomerInvite, str]:
    """
    Create a one-time customer invite.

    Returns:

        (invite, raw_token)

    The raw token must only be returned to the caller so it can be
    placed into the registration link. Only its SHA-256 hash is stored.
    """

    clean_email = (
        normalise_email(
            email
        )
    )

    if not clean_email:
        raise AuthRepositoryError(
            "Customer email is required."
        )

    if "@" not in clean_email:
        raise AuthRepositoryError(
            "Customer email is invalid."
        )

    raw_token = (
        create_raw_invite_token()
    )

    token_hash = (
        hash_invite_token(
            raw_token
        )
    )

    expiry = (
        utc_now()
        + timedelta(
            hours=max(
                1,
                int(
                    expires_hours
                ),
            )
        )
    ).isoformat()

    invite = CustomerInvite(
        invite_id=new_identifier(),
        business_id=business_id,
        business_name=business_name,
        business_type=business_type,
        email=clean_email,
        token_hash=token_hash,
        expires_at=expiry,
        created_at=utc_now_iso(),
        created_by=created_by,
        active=True,
    )

    connection = connect()

    try:
        connection.execute(
            """
            INSERT INTO customer_invites (
                invite_id,
                business_id,
                business_name,
                business_type,
                email,
                token_hash,
                expires_at,
                created_at,
                used_at,
                created_by,
                active
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                invite.invite_id,
                invite.business_id,
                invite.business_name,
                invite.business_type,
                invite.email,
                invite.token_hash,
                invite.expires_at,
                invite.created_at,
                invite.used_at,
                invite.created_by,
                1 if invite.active else 0,
            ),
        )

        connection.commit()

    except sqlite3.Error as error:
        raise AuthRepositoryError(
            f"Could not create customer invite: {error}"
        ) from error

    finally:
        connection.close()

    return (
        invite,
        raw_token,
    )


def get_customer_invite_by_token(
    raw_token: str,
) -> CustomerInvite | None:
    token_hash = (
        hash_invite_token(
            raw_token
        )
    )

    if not token_hash:
        return None

    connection = connect()

    try:
        row = connection.execute(
            """
            SELECT *
            FROM customer_invites
            WHERE token_hash = ?
            LIMIT 1
            """,
            (
                token_hash,
            ),
        ).fetchone()

    except sqlite3.Error as error:
        raise AuthRepositoryError(
            f"Could not load customer invite: {error}"
        ) from error

    finally:
        connection.close()

    if row is None:
        return None

    return CustomerInvite.from_dict(
        dict(
            row
        )
    )


def mark_customer_invite_used(
    invite_id: str,
) -> None:
    connection = connect()

    try:
        connection.execute(
            """
            UPDATE customer_invites
            SET
                used_at = ?,
                active = 0
            WHERE invite_id = ?
            """,
            (
                utc_now_iso(),
                invite_id,
            ),
        )

        connection.commit()

    except sqlite3.Error as error:
        raise AuthRepositoryError(
            f"Could not mark customer invite as used: {error}"
        ) from error

    finally:
        connection.close()


def revoke_customer_invite(
    invite_id: str,
) -> bool:
    connection = connect()

    try:
        cursor = connection.execute(
            """
            UPDATE customer_invites
            SET active = 0
            WHERE invite_id = ?
            """,
            (
                invite_id,
            ),
        )

        connection.commit()

        return (
            cursor.rowcount > 0
        )

    except sqlite3.Error as error:
        raise AuthRepositoryError(
            f"Could not revoke customer invite: {error}"
        ) from error

    finally:
        connection.close()


def list_customer_invites(
    business_id: str | None = None,
) -> list[CustomerInvite]:
    connection = connect()

    try:
        if business_id:
            rows = connection.execute(
                """
                SELECT *
                FROM customer_invites
                WHERE business_id = ?
                ORDER BY created_at DESC
                """,
                (
                    business_id,
                ),
            ).fetchall()

        else:
            rows = connection.execute(
                """
                SELECT *
                FROM customer_invites
                ORDER BY created_at DESC
                """
            ).fetchall()

    except sqlite3.Error as error:
        raise AuthRepositoryError(
            f"Could not list customer invites: {error}"
        ) from error

    finally:
        connection.close()

    return [
        CustomerInvite.from_dict(
            dict(
                row
            )
        )
        for row in rows
    ]


# =========================================================
# Health
# =========================================================


def auth_repository_health() -> dict[str, Any]:
    connection = connect()

    try:
        user_row = connection.execute(
            """
            SELECT COUNT(*) AS total
            FROM business_users
            """
        ).fetchone()

        invite_row = connection.execute(
            """
            SELECT COUNT(*) AS total
            FROM customer_invites
            """
        ).fetchone()

        return {
            "success": True,
            "database": str(
                database_path()
            ),
            "business_users": (
                int(
                    user_row[
                        "total"
                    ]
                )
                if user_row
                else 0
            ),
            "customer_invites": (
                int(
                    invite_row[
                        "total"
                    ]
                )
                if invite_row
                else 0
            ),
        }

    except sqlite3.Error as error:
        raise AuthRepositoryError(
            f"Auth database health check failed: {error}"
        ) from error

    finally:
        connection.close()