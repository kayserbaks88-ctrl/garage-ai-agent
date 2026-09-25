"""Versioned, transactional Staff Manager upgrades.

Run on a staging copy first: python -m trimtech.modules.staff.migrations
Application startup checks the recorded version; it never enables agency mode.
"""
from __future__ import annotations

import hashlib
import json
import re


VERSION = "20260923_agency_v1"
SQL = """
CREATE TABLE staff_settings (
    business_id VARCHAR(100) PRIMARY KEY,
    organisation_mode TEXT NOT NULL DEFAULT 'fixed'
        CHECK (organisation_mode IN ('fixed','agency')),
    travel_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
INSERT INTO staff_settings (business_id)
SELECT business_id FROM staff_business_settings
UNION SELECT business_id FROM staff_employees
UNION SELECT business_id FROM staff_sites
UNION SELECT business_id FROM staff_shifts;

ALTER TABLE staff_sites ADD COLUMN client_reference VARCHAR(160);
CREATE TABLE staff_assignments (
    id BIGSERIAL PRIMARY KEY,
    business_id VARCHAR(100) NOT NULL,
    employee_id BIGINT NOT NULL REFERENCES staff_employees(id) ON DELETE RESTRICT,
    site_id BIGINT NOT NULL REFERENCES staff_sites(id) ON DELETE RESTRICT,
    starts_at TIMESTAMPTZ NOT NULL,
    ends_at TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL DEFAULT 'scheduled' CHECK (status IN ('scheduled','cancelled')),
    created_by TEXT NOT NULL,
    override_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (ends_at > starts_at)
);
CREATE INDEX staff_assignments_employee_window
    ON staff_assignments (business_id,employee_id,starts_at,ends_at);

ALTER TABLE staff_shifts
    ADD COLUMN assignment_id BIGINT REFERENCES staff_assignments(id) ON DELETE SET NULL,
    ADD COLUMN assigned_site_name VARCHAR(160),
    ADD COLUMN assigned_site_address TEXT,
    ADD COLUMN planned_start_at TIMESTAMPTZ,
    ADD COLUMN planned_end_at TIMESTAMPTZ,
    ADD COLUMN site_latitude_snapshot NUMERIC(10,7),
    ADD COLUMN site_longitude_snapshot NUMERIC(10,7),
    ADD COLUMN site_radius_snapshot INTEGER,
    ADD COLUMN clock_in_accuracy NUMERIC(10,2),
    ADD COLUMN clock_out_accuracy NUMERIC(10,2),
    ADD COLUMN clock_in_captured_at TIMESTAMPTZ,
    ADD COLUMN clock_out_captured_at TIMESTAMPTZ,
    ADD COLUMN clock_in_verification TEXT,
    ADD COLUMN clock_out_verification TEXT;

CREATE TABLE staff_travel_origins (
    business_id VARCHAR(100) NOT NULL,
    employee_id BIGINT NOT NULL REFERENCES staff_employees(id) ON DELETE RESTRICT,
    encrypted_origin TEXT,
    consented_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    disabled_at TIMESTAMPTZ,
    PRIMARY KEY (business_id,employee_id)
);
CREATE TABLE staff_shift_travel (
    shift_id BIGINT PRIMARY KEY REFERENCES staff_shifts(id) ON DELETE RESTRICT,
    business_id VARCHAR(100) NOT NULL,
    encrypted_origin_snapshot TEXT,
    site_latitude NUMERIC(10,7),
    site_longitude NUMERIC(10,7),
    distance_km NUMERIC(8,2) CHECK (distance_km >= 0),
    method TEXT NOT NULL DEFAULT 'straight_line' CHECK (method='straight_line'),
    calculated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    review_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (review_status IN ('pending','reviewed')),
    manager_distance_km NUMERIC(8,2) CHECK (manager_distance_km >= 0),
    adjustment_reason TEXT,
    reviewed_by TEXT,
    reviewed_at TIMESTAMPTZ
);
CREATE TABLE staff_audit (
    id BIGSERIAL PRIMARY KEY,
    business_id VARCHAR(100) NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id BIGINT,
    old_values JSONB,
    new_values JSONB,
    reason TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX staff_audit_business_entity
    ON staff_audit (business_id,entity_type,entity_id,created_at);
ALTER TABLE staff_payroll_runs ADD COLUMN needs_recalculation BOOLEAN NOT NULL DEFAULT FALSE;
CREATE TABLE staff_payroll_adjustments (
    id BIGSERIAL PRIMARY KEY,
    business_id VARCHAR(100) NOT NULL,
    shift_id BIGINT NOT NULL REFERENCES staff_shifts(id) ON DELETE RESTRICT,
    payroll_run_id BIGINT NOT NULL REFERENCES staff_payroll_runs(id) ON DELETE RESTRICT,
    requested_by TEXT NOT NULL,
    proposed_values JSONB NOT NULL,
    reason TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','resolved')),
    resolution TEXT,
    resolved_by TEXT,
    resolved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

CHECKSUM = hashlib.sha256(SQL.encode()).hexdigest()


def _canonical_schema_sql(definition):
    """Keep varchar-list fingerprints stable across PostgreSQL dump/restore.

    PostgreSQL reparses a varchar-array cast to text[] as per-element text
    casts during restore. Normalize only that equivalent literal-array form
    back to the original spelling, retaining values, types and all other SQL.
    This preserves fingerprints already recorded on the original schema.
    """
    literal = r"'(?:[^']|'')*'::character varying"
    element = rf"\({literal}\)::text"
    pattern = rf"ARRAY\[{element}(?:, {element})*\]"
    return re.sub(pattern, lambda match: "(ARRAY[" + ", ".join(
        re.findall(literal, match.group(0))) + "])::text[]", definition)


def schema_fingerprint(cursor):
    """Detect column, constraint and index drift, without environment-specific OIDs."""
    cursor.execute("""
        SELECT table_name,column_name,data_type,udt_name,is_nullable,column_default,
               character_maximum_length,numeric_precision,numeric_scale
        FROM information_schema.columns
        WHERE table_schema=current_schema() AND table_name LIKE 'staff_%%'
          AND table_name <> 'staff_schema_migrations'
        ORDER BY table_name,ordinal_position
    """)
    columns = cursor.fetchall()
    cursor.execute("""
        SELECT c.relname,k.conname,pg_get_constraintdef(k.oid)
        FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid
        JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname=current_schema() AND c.relname LIKE 'staff_%%'
          AND c.relname <> 'staff_schema_migrations' ORDER BY c.relname,k.conname
    """)
    constraints = [(table, name, _canonical_schema_sql(definition))
                   for table, name, definition in cursor.fetchall()]
    cursor.execute("""
        SELECT tablename,indexname,indexdef FROM pg_indexes
        WHERE schemaname=current_schema() AND tablename LIKE 'staff_%%'
          AND tablename <> 'staff_schema_migrations' ORDER BY tablename,indexname
    """)
    indexes = [(table, name, _canonical_schema_sql(definition))
               for table, name, definition in cursor.fetchall()]
    return hashlib.sha256(json.dumps(
        [columns, constraints, indexes], default=str, sort_keys=True
    ).encode()).hexdigest()


def migrate(cursor):
    cursor.execute("SELECT pg_advisory_xact_lock(731942023)")
    cursor.execute("""CREATE TABLE IF NOT EXISTS staff_schema_migrations (
        version TEXT PRIMARY KEY, checksum TEXT NOT NULL,
        schema_fingerprint TEXT NOT NULL, applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )""")
    cursor.execute("SELECT checksum FROM staff_schema_migrations WHERE version=%s", (VERSION,))
    if cursor.fetchone():
        verify(cursor)
        return
    # Deliberately no IF NOT EXISTS: an unversioned partial upgrade must fail.
    cursor.execute(SQL)
    fingerprint = schema_fingerprint(cursor)
    cursor.execute("INSERT INTO staff_schema_migrations (version,checksum,schema_fingerprint) VALUES (%s,%s,%s)",
                   (VERSION, CHECKSUM, fingerprint))


def verify(cursor):
    from trimtech.modules.staff.database import StaffDatabaseError

    cursor.execute("SELECT to_regclass('staff_schema_migrations')")
    if not cursor.fetchone()[0]:
        raise StaffDatabaseError("Run the versioned Staff Manager migration before starting the application.")
    cursor.execute("SELECT checksum,schema_fingerprint FROM staff_schema_migrations WHERE version=%s", (VERSION,))
    row = cursor.fetchone()
    if not row or row[0] != CHECKSUM or row[1] != schema_fingerprint(cursor):
        raise StaffDatabaseError("Staff Manager migration checksum or schema drift detected; review the staging migration.")


if __name__ == "__main__":
    from trimtech.modules.staff.database import init_staff_database

    init_staff_database(migrate=True)
    print(f"Verified Staff Manager migration {VERSION}; existing businesses remain fixed.")
