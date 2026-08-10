from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any


DEFAULT_DATABASE_PATH = Path(
    os.getenv(
        "ONBOARDING_DB_PATH",
        "data/trimtech.db",
    )
)


class OnboardingRepositoryError(RuntimeError):
    """
    Raised when persistent onboarding storage cannot be read or written.
    """


def database_path() -> Path:
    """
    Return the configured TrimTech onboarding database path.

    Local default:

        data/trimtech.db

    Render can later use a persistent disk path such as:

        /var/data/trimtech.db
    """

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
    """
    Open the onboarding database and ensure its schema exists.
    """

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
        raise OnboardingRepositoryError(
            f"Could not open onboarding database: {error}"
        ) from error


def ensure_schema(
    connection: sqlite3.Connection,
) -> None:
    """
    Create the persistent businesses table when required.
    """

    try:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS onboarding_businesses (
                business_slug TEXT PRIMARY KEY,
                business_name TEXT NOT NULL,
                business_type TEXT NOT NULL,
                owner_name TEXT NOT NULL DEFAULT '',
                email TEXT NOT NULL DEFAULT '',
                phone TEXT NOT NULL DEFAULT '',
                onboarding_complete INTEGER NOT NULL DEFAULT 0,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_onboarding_businesses_type
            ON onboarding_businesses (business_type)
            """
        )

        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_onboarding_businesses_complete
            ON onboarding_businesses (onboarding_complete)
            """
        )

        connection.commit()

    except sqlite3.Error as error:
        raise OnboardingRepositoryError(
            f"Could not initialise onboarding database: {error}"
        ) from error


def save_business_record(
    data: dict[str, Any],
) -> dict[str, Any]:
    """
    Insert or update one onboarding business.

    The complete onboarding record is stored as JSON while the important
    identity fields are also indexed as normal database columns.
    """

    if not isinstance(
        data,
        dict,
    ):
        raise OnboardingRepositoryError(
            "Business record must be a dictionary."
        )

    business_slug = str(
        data.get(
            "business_slug"
        )
        or ""
    ).strip()

    business_name = str(
        data.get(
            "business_name"
        )
        or ""
    ).strip()

    business_type = str(
        data.get(
            "business_type"
        )
        or ""
    ).strip()

    owner_name = str(
        data.get(
            "owner_name"
        )
        or ""
    ).strip()

    email = str(
        data.get(
            "email"
        )
        or ""
    ).strip()

    phone = str(
        data.get(
            "phone"
        )
        or ""
    ).strip()

    onboarding_complete = bool(
        data.get(
            "onboarding_complete",
            False,
        )
    )

    if not business_slug:
        raise OnboardingRepositoryError(
            "Business slug is required."
        )

    if not business_name:
        raise OnboardingRepositoryError(
            "Business name is required."
        )

    if not business_type:
        raise OnboardingRepositoryError(
            "Business type is required."
        )

    try:
        payload_json = json.dumps(
            data,
            ensure_ascii=False,
            separators=(
                ",",
                ":",
            ),
        )

    except (
        TypeError,
        ValueError,
    ) as error:
        raise OnboardingRepositoryError(
            f"Business record could not be serialised: {error}"
        ) from error

    connection = connect()

    try:
        connection.execute(
            """
            INSERT INTO onboarding_businesses (
                business_slug,
                business_name,
                business_type,
                owner_name,
                email,
                phone,
                onboarding_complete,
                payload_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)

            ON CONFLICT(business_slug)
            DO UPDATE SET
                business_name = excluded.business_name,
                business_type = excluded.business_type,
                owner_name = excluded.owner_name,
                email = excluded.email,
                phone = excluded.phone,
                onboarding_complete = excluded.onboarding_complete,
                payload_json = excluded.payload_json,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                business_slug,
                business_name,
                business_type,
                owner_name,
                email,
                phone,
                1
                if onboarding_complete
                else 0,
                payload_json,
            ),
        )

        connection.commit()

        return dict(
            data
        )

    except sqlite3.Error as error:
        connection.rollback()

        raise OnboardingRepositoryError(
            f"Could not save business '{business_slug}': {error}"
        ) from error

    finally:
        connection.close()


def load_business_record(
    business_slug: str,
) -> dict[str, Any] | None:
    """
    Load one business by its unique slug.
    """

    clean_slug = str(
        business_slug
        or ""
    ).strip()

    if not clean_slug:
        return None

    connection = connect()

    try:
        row = connection.execute(
            """
            SELECT payload_json
            FROM onboarding_businesses
            WHERE business_slug = ?
            LIMIT 1
            """,
            (
                clean_slug,
            ),
        ).fetchone()

    except sqlite3.Error as error:
        raise OnboardingRepositoryError(
            f"Could not load business '{clean_slug}': {error}"
        ) from error

    finally:
        connection.close()

    if row is None:
        return None

    try:
        payload = json.loads(
            row[
                "payload_json"
            ]
        )

    except (
        json.JSONDecodeError,
        TypeError,
    ) as error:
        raise OnboardingRepositoryError(
            f"Stored business '{clean_slug}' contains invalid JSON."
        ) from error

    if not isinstance(
        payload,
        dict,
    ):
        raise OnboardingRepositoryError(
            f"Stored business '{clean_slug}' is invalid."
        )

    return payload


def business_record_exists(
    business_slug: str,
) -> bool:
    """
    Return True when a business exists in persistent storage.
    """

    clean_slug = str(
        business_slug
        or ""
    ).strip()

    if not clean_slug:
        return False

    connection = connect()

    try:
        row = connection.execute(
            """
            SELECT 1
            FROM onboarding_businesses
            WHERE business_slug = ?
            LIMIT 1
            """,
            (
                clean_slug,
            ),
        ).fetchone()

        return row is not None

    except sqlite3.Error as error:
        raise OnboardingRepositoryError(
            f"Could not check business '{clean_slug}': {error}"
        ) from error

    finally:
        connection.close()


def list_business_records() -> list[dict[str, Any]]:
    """
    Return every saved business, newest updated records first.
    """

    connection = connect()

    try:
        rows = connection.execute(
            """
            SELECT payload_json
            FROM onboarding_businesses
            ORDER BY updated_at DESC, business_name ASC
            """
        ).fetchall()

    except sqlite3.Error as error:
        raise OnboardingRepositoryError(
            f"Could not list onboarding businesses: {error}"
        ) from error

    finally:
        connection.close()

    businesses: list[
        dict[str, Any]
    ] = []

    for row in rows:
        try:
            payload = json.loads(
                row[
                    "payload_json"
                ]
            )

        except (
            json.JSONDecodeError,
            TypeError,
        ):
            continue

        if isinstance(
            payload,
            dict,
        ):
            businesses.append(
                payload
            )

    return businesses


def delete_business_record(
    business_slug: str,
) -> bool:
    """
    Delete one onboarding business.

    Returns True if a record was deleted.
    """

    clean_slug = str(
        business_slug
        or ""
    ).strip()

    if not clean_slug:
        return False

    connection = connect()

    try:
        cursor = connection.execute(
            """
            DELETE FROM onboarding_businesses
            WHERE business_slug = ?
            """,
            (
                clean_slug,
            ),
        )

        connection.commit()

        return (
            cursor.rowcount
            > 0
        )

    except sqlite3.Error as error:
        connection.rollback()

        raise OnboardingRepositoryError(
            f"Could not delete business '{clean_slug}': {error}"
        ) from error

    finally:
        connection.close()


def repository_health() -> dict[str, Any]:
    """
    Small health check for diagnostics and deployment testing.
    """

    path = database_path()

    connection = connect()

    try:
        count = connection.execute(
            """
            SELECT COUNT(*) AS total
            FROM onboarding_businesses
            """
        ).fetchone()

        total = (
            int(
                count[
                    "total"
                ]
            )
            if count
            else 0
        )

    except sqlite3.Error as error:
        raise OnboardingRepositoryError(
            f"Onboarding database health check failed: {error}"
        ) from error

    finally:
        connection.close()

    return {
        "success": True,
        "database": str(
            path
        ),
        "business_count": total,
    }