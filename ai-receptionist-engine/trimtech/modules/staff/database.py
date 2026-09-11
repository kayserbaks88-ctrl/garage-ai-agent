from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any, Iterator, Mapping, Sequence

import psycopg2
from psycopg2.extensions import connection as PostgreSQLConnection
from psycopg2.extras import RealDictCursor


class StaffDatabaseError(RuntimeError):
    """Raised when the Staff Manager database cannot be used safely."""


def _database_url() -> str:
    database_url = os.getenv("DATABASE_URL", "").strip()

    if not database_url:
        raise StaffDatabaseError(
            "DATABASE_URL is missing. Add the Render PostgreSQL internal "
            "database URL to the web service environment variables."
        )

    # Older providers sometimes return the retired postgres:// scheme.
    if database_url.startswith("postgres://"):
        database_url = "postgresql://" + database_url[len("postgres://") :]

    return database_url


def get_connection() -> PostgreSQLConnection:
    """Open a PostgreSQL connection using the shared Render DATABASE_URL."""
    try:
        return psycopg2.connect(
            _database_url(),
            connect_timeout=10,
            application_name="trimtech_staff_manager",
        )
    except psycopg2.Error as error:
        raise StaffDatabaseError(
            "TrimTech Staff Manager could not connect to PostgreSQL."
        ) from error


@contextmanager
def transaction() -> Iterator[PostgreSQLConnection]:
    """Commit successful work and roll back automatically after an error."""
    connection = get_connection()

    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def fetch_one(
    query: str,
    parameters: Sequence[Any] | Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    with transaction() as connection:
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(query, parameters)
            row = cursor.fetchone()
            return dict(row) if row else None


def fetch_all(
    query: str,
    parameters: Sequence[Any] | Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    with transaction() as connection:
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(query, parameters)
            return [dict(row) for row in cursor.fetchall()]


def execute(
    query: str,
    parameters: Sequence[Any] | Mapping[str, Any] | None = None,
) -> int:
    """Execute a write statement and return the number of affected rows."""
    with transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(query, parameters)
            return cursor.rowcount


SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS staff_employees (
        id BIGSERIAL PRIMARY KEY,
        business_id VARCHAR(100) NOT NULL,
        full_name VARCHAR(160) NOT NULL,
        phone VARCHAR(40) NOT NULL,
        email VARCHAR(254),
        role VARCHAR(40) NOT NULL DEFAULT 'staff',
        hourly_rate NUMERIC(10, 2) NOT NULL DEFAULT 0,
        status VARCHAR(20) NOT NULL DEFAULT 'active',
        payroll_number VARCHAR(60),
        tax_code VARCHAR(30),
        national_insurance_number VARCHAR(30),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CONSTRAINT staff_employees_business_phone_unique
            UNIQUE (business_id, phone),
        CONSTRAINT staff_employees_hourly_rate_nonnegative
            CHECK (hourly_rate >= 0),
        CONSTRAINT staff_employees_role_valid
            CHECK (role IN ('owner', 'manager', 'staff')),
        CONSTRAINT staff_employees_status_valid
            CHECK (status IN ('active', 'inactive'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS staff_sites (
        id BIGSERIAL PRIMARY KEY,
        business_id VARCHAR(100) NOT NULL,
        name VARCHAR(160) NOT NULL,
        address TEXT,
        latitude NUMERIC(10, 7),
        longitude NUMERIC(10, 7),
        allowed_radius_metres INTEGER NOT NULL DEFAULT 250,
        photo_required BOOLEAN NOT NULL DEFAULT FALSE,
        active BOOLEAN NOT NULL DEFAULT TRUE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CONSTRAINT staff_sites_business_name_unique
            UNIQUE (business_id, name),
        CONSTRAINT staff_sites_radius_positive
            CHECK (allowed_radius_metres > 0)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS staff_shifts (
        id BIGSERIAL PRIMARY KEY,
        business_id VARCHAR(100) NOT NULL,
        employee_id BIGINT NOT NULL
            REFERENCES staff_employees(id) ON DELETE RESTRICT,
        site_id BIGINT
            REFERENCES staff_sites(id) ON DELETE SET NULL,
        site_name VARCHAR(160) NOT NULL,
        clock_in_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        clock_out_at TIMESTAMPTZ,
        clock_in_latitude NUMERIC(10, 7),
        clock_in_longitude NUMERIC(10, 7),
        clock_out_latitude NUMERIC(10, 7),
        clock_out_longitude NUMERIC(10, 7),
        clock_in_photo_url TEXT,
        clock_out_photo_url TEXT,
        approval_status VARCHAR(20) NOT NULL DEFAULT 'pending',
        approved_by BIGINT
            REFERENCES staff_employees(id) ON DELETE SET NULL,
        approved_at TIMESTAMPTZ,
        manager_note TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CONSTRAINT staff_shifts_clock_order_valid
            CHECK (clock_out_at IS NULL OR clock_out_at >= clock_in_at),
        CONSTRAINT staff_shifts_approval_status_valid
            CHECK (approval_status IN ('pending', 'approved', 'rejected'))
    )
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS staff_one_open_shift_per_employee
        ON staff_shifts (business_id, employee_id)
        WHERE clock_out_at IS NULL
    """,
    """
    CREATE INDEX IF NOT EXISTS staff_shifts_business_clock_in_index
        ON staff_shifts (business_id, clock_in_at DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS staff_shifts_business_approval_index
        ON staff_shifts (business_id, approval_status, clock_in_at DESC)
    """,
    """
    CREATE TABLE IF NOT EXISTS staff_breaks (
        id BIGSERIAL PRIMARY KEY,
        business_id VARCHAR(100) NOT NULL,
        shift_id BIGINT NOT NULL
            REFERENCES staff_shifts(id) ON DELETE CASCADE,
        employee_id BIGINT NOT NULL
            REFERENCES staff_employees(id) ON DELETE RESTRICT,
        started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        ended_at TIMESTAMPTZ,
        paid BOOLEAN NOT NULL DEFAULT FALSE,
        note TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CONSTRAINT staff_breaks_time_order_valid
            CHECK (ended_at IS NULL OR ended_at >= started_at)
    )
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS staff_one_open_break_per_shift
        ON staff_breaks (shift_id)
        WHERE ended_at IS NULL
    """,
    """
    CREATE INDEX IF NOT EXISTS staff_breaks_business_started_index
        ON staff_breaks (business_id, started_at DESC)
    """,
    """
    CREATE TABLE IF NOT EXISTS staff_payroll_runs (
        id BIGSERIAL PRIMARY KEY,
        business_id VARCHAR(100) NOT NULL,
        period_start DATE NOT NULL,
        period_end DATE NOT NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'draft',
        total_gross_pay NUMERIC(12, 2) NOT NULL DEFAULT 0,
        total_deductions NUMERIC(12, 2) NOT NULL DEFAULT 0,
        total_net_pay NUMERIC(12, 2) NOT NULL DEFAULT 0,
        approved_by BIGINT
            REFERENCES staff_employees(id) ON DELETE SET NULL,
        approved_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CONSTRAINT staff_payroll_runs_period_unique
            UNIQUE (business_id, period_start, period_end),
        CONSTRAINT staff_payroll_runs_period_valid
            CHECK (period_end >= period_start),
        CONSTRAINT staff_payroll_runs_status_valid
            CHECK (status IN ('draft', 'approved', 'sent', 'paid')),
        CONSTRAINT staff_payroll_runs_totals_nonnegative
            CHECK (
                total_gross_pay >= 0
                AND total_deductions >= 0
                AND total_net_pay >= 0
            )
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS staff_payslips (
        id BIGSERIAL PRIMARY KEY,
        business_id VARCHAR(100) NOT NULL,
        payroll_run_id BIGINT NOT NULL
            REFERENCES staff_payroll_runs(id) ON DELETE CASCADE,
        employee_id BIGINT NOT NULL
            REFERENCES staff_employees(id) ON DELETE RESTRICT,
        worked_minutes INTEGER NOT NULL DEFAULT 0,
        paid_break_minutes INTEGER NOT NULL DEFAULT 0,
        unpaid_break_minutes INTEGER NOT NULL DEFAULT 0,
        payable_minutes INTEGER NOT NULL DEFAULT 0,
        hourly_rate NUMERIC(10, 2) NOT NULL DEFAULT 0,
        gross_pay NUMERIC(12, 2) NOT NULL DEFAULT 0,
        deductions NUMERIC(12, 2) NOT NULL DEFAULT 0,
        net_pay NUMERIC(12, 2) NOT NULL DEFAULT 0,
        pdf_url TEXT,
        emailed_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CONSTRAINT staff_payslips_run_employee_unique
            UNIQUE (payroll_run_id, employee_id),
        CONSTRAINT staff_payslips_values_nonnegative
            CHECK (
                worked_minutes >= 0
                AND paid_break_minutes >= 0
                AND unpaid_break_minutes >= 0
                AND payable_minutes >= 0
                AND hourly_rate >= 0
                AND gross_pay >= 0
                AND deductions >= 0
                AND net_pay >= 0
            )
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS staff_payslips_business_employee_index
        ON staff_payslips (business_id, employee_id, created_at DESC)
    """,
)


def init_staff_database() -> None:
    """Create the Staff Manager tables and indexes when they do not exist."""
    try:
        with transaction() as connection:
            with connection.cursor() as cursor:
                for statement in SCHEMA_STATEMENTS:
                    cursor.execute(statement)
    except psycopg2.Error as error:
        raise StaffDatabaseError(
            "TrimTech Staff Manager database setup failed."
        ) from error

