"""Additive assignment notification and shift-presence migration."""
import hashlib

VERSION = "20260928_staff_operations_v2"
SQL = """
CREATE TABLE staff_assignment_notifications (
    id BIGSERIAL PRIMARY KEY,
    business_id VARCHAR(100) NOT NULL,
    assignment_id BIGINT NOT NULL REFERENCES staff_assignments(id) ON DELETE RESTRICT,
    employee_id BIGINT NOT NULL REFERENCES staff_employees(id) ON DELETE RESTRICT,
    event_key TEXT NOT NULL UNIQUE,
    action TEXT NOT NULL CHECK (action IN ('created','updated','cancelled','reassigned_away')),
    recipient TEXT,
    details JSONB NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','sent','failed','disabled')),
    provider_id TEXT,
    error_code TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    attempted_at TIMESTAMPTZ
);
CREATE INDEX staff_notifications_pending ON staff_assignment_notifications (business_id,assignment_id,id) WHERE status='pending';
CREATE TABLE staff_shift_presence (
    shift_id BIGINT PRIMARY KEY REFERENCES staff_shifts(id) ON DELETE RESTRICT,
    business_id VARCHAR(100) NOT NULL,
    employee_id BIGINT NOT NULL REFERENCES staff_employees(id) ON DELETE RESTRICT,
    site_latitude NUMERIC(10,7),
    site_longitude NUMERIC(10,7),
    radius_metres INTEGER,
    status TEXT NOT NULL DEFAULT 'location_stale' CHECK (status IN ('on_site','left_site','returned','location_stale')),
    last_captured_at TIMESTAMPTZ,
    last_received_at TIMESTAMPTZ,
    outside_since TIMESTAMPTZ,
    outside_count INTEGER NOT NULL DEFAULT 0,
    departed BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX staff_presence_business ON staff_shift_presence (business_id,shift_id);
CREATE TABLE staff_presence_events (
    id BIGSERIAL PRIMARY KEY,
    shift_id BIGINT NOT NULL REFERENCES staff_shifts(id) ON DELETE RESTRICT,
    business_id VARCHAR(100) NOT NULL,
    employee_id BIGINT NOT NULL REFERENCES staff_employees(id) ON DELETE RESTRICT,
    status TEXT NOT NULL CHECK (status IN ('on_site','left_site','returned','location_stale')),
    captured_at TIMESTAMPTZ,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    effective_at TIMESTAMPTZ NOT NULL,
    distance_metres NUMERIC(12,2),
    accuracy_metres NUMERIC(10,2),
    reason TEXT NOT NULL
);
CREATE INDEX staff_presence_events_shift ON staff_presence_events (business_id,shift_id,id);
"""
CHECKSUM = hashlib.sha256(SQL.encode()).hexdigest()
