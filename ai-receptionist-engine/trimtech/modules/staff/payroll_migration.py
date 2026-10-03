"""Additive statutory payroll ledger and attendance exception review."""
import hashlib

VERSION = "20261003_staff_payroll_v3"
SQL = """
CREATE TABLE staff_payroll_profiles (
    business_id VARCHAR(100) NOT NULL,
    employee_id BIGINT NOT NULL REFERENCES staff_employees(id) ON DELETE RESTRICT,
    tax_year TEXT NOT NULL CHECK(tax_year='2026/27'),
    tax_code TEXT NOT NULL,
    tax_basis TEXT NOT NULL CHECK(tax_basis IN ('cumulative','noncumulative')),
    frequency TEXT NOT NULL CHECK(frequency IN ('weekly','monthly')),
    ni_category TEXT NOT NULL,
    pension_method TEXT NOT NULL CHECK(pension_method IN ('none','net_pay','relief_at_source')),
    pension_basis TEXT NOT NULL CHECK(pension_basis IN ('qualifying','all')),
    employee_pension_rate NUMERIC(5,2) NOT NULL CHECK(employee_pension_rate BETWEEN 0 AND 100),
    employer_pension_rate NUMERIC(5,2) NOT NULL CHECK(employer_pension_rate BETWEEN 0 AND 100),
    opening_taxable_pay NUMERIC(12,2) NOT NULL DEFAULT 0 CHECK(opening_taxable_pay>=0),
    opening_paye NUMERIC(12,2) NOT NULL DEFAULT 0 CHECK(opening_paye>=0),
    opening_through DATE NOT NULL,
    reviewed_by TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY(business_id,employee_id)
);
ALTER TABLE staff_payroll_runs ADD COLUMN calculation_version TEXT,
    ADD COLUMN payment_date DATE, ADD COLUMN pay_frequency TEXT, ADD COLUMN employer_name TEXT,
    ADD COLUMN employer_ni NUMERIC(12,2) NOT NULL DEFAULT 0,
    ADD COLUMN employer_pension NUMERIC(12,2) NOT NULL DEFAULT 0;
CREATE TABLE staff_payroll_calculations (
    payslip_id BIGINT PRIMARY KEY REFERENCES staff_payslips(id) ON DELETE RESTRICT,
    business_id VARCHAR(100) NOT NULL,
    employee_id BIGINT NOT NULL REFERENCES staff_employees(id) ON DELETE RESTRICT,
    payroll_run_id BIGINT NOT NULL REFERENCES staff_payroll_runs(id) ON DELETE RESTRICT,
    payment_date DATE NOT NULL,
    tax_year TEXT NOT NULL,
    tax_period INTEGER NOT NULL,
    frequency TEXT NOT NULL,
    profile JSONB NOT NULL,
    employee_name TEXT NOT NULL,
    employer_name TEXT NOT NULL,
    result JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (business_id,employee_id,tax_year,frequency,tax_period)
);
CREATE INDEX staff_calculations_history ON staff_payroll_calculations(business_id,employee_id,payment_date);
CREATE TABLE staff_payslip_notifications (
    payslip_id BIGINT PRIMARY KEY REFERENCES staff_payslips(id) ON DELETE RESTRICT,
    business_id VARCHAR(100) NOT NULL,
    recipient TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('pending','sent','failed','disabled')),
    event_key TEXT NOT NULL UNIQUE,
    error_code TEXT,
    provider_id TEXT,
    attempted_at TIMESTAMPTZ
);
CREATE TABLE staff_attendance_reviews (
    business_id VARCHAR(100) NOT NULL,
    event_key TEXT NOT NULL,
    note TEXT NOT NULL,
    reviewed_by TEXT NOT NULL,
    reviewed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY(business_id,event_key)
);
-- PAYE refunds can make total deductions negative. Existing other constraints stay.
ALTER TABLE staff_payslips DROP CONSTRAINT staff_payslips_values_nonnegative;
ALTER TABLE staff_payslips ADD CONSTRAINT staff_payslips_values_nonnegative CHECK(
    worked_minutes>=0 AND paid_break_minutes>=0 AND unpaid_break_minutes>=0
    AND payable_minutes>=0 AND hourly_rate>=0 AND gross_pay>=0 AND net_pay>=0);
ALTER TABLE staff_payroll_runs DROP CONSTRAINT staff_payroll_runs_totals_nonnegative;
ALTER TABLE staff_payroll_runs ADD CONSTRAINT staff_payroll_runs_totals_nonnegative
    CHECK(total_gross_pay>=0 AND total_net_pay>=0);
"""
CHECKSUM = hashlib.sha256(SQL.encode()).hexdigest()
