"""Explicit additive Staff subscription ledger. Never changes payroll or shared billing."""
import hashlib

from trimtech.modules.staff import accounts_migration, migrations, onboarding_migration
from trimtech.modules.staff.database import StaffDatabaseError, transaction

VERSION = '20261008_staff_billing_v1'
SQL = """
CREATE TABLE sb_accounts (
 business_id VARCHAR(100) PRIMARY KEY REFERENCES sm_businesses(id),
 stripe_account_id TEXT NOT NULL,
 livemode BOOLEAN NOT NULL,
 customer_id TEXT,
 customer_key TEXT NOT NULL UNIQUE,
 customer_name TEXT NOT NULL,
 customer_email TEXT NOT NULL,
 customer_requested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 UNIQUE(stripe_account_id,livemode,customer_id)
);
CREATE TABLE sb_checkouts (
 id TEXT PRIMARY KEY,
 business_id VARCHAR(100) NOT NULL REFERENCES sb_accounts(business_id),
 actor_id TEXT NOT NULL REFERENCES sm_administrators(id),
 price_id TEXT NOT NULL,
 product_id TEXT NOT NULL,
 return_url TEXT NOT NULL,
 session_id TEXT UNIQUE,
 status TEXT NOT NULL DEFAULT 'creating' CHECK(status IN ('creating','open','complete','expired')),
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 expires_at TIMESTAMPTZ NOT NULL
);
CREATE UNIQUE INDEX sb_checkout_pending ON sb_checkouts(business_id) WHERE status IN ('creating','open');
CREATE TABLE sb_subscriptions (
 id TEXT PRIMARY KEY,
 business_id VARCHAR(100) NOT NULL REFERENCES sb_accounts(business_id),
 checkout_id TEXT NOT NULL UNIQUE REFERENCES sb_checkouts(id),
 status TEXT NOT NULL CHECK(status IN ('active','trialing','past_due','unpaid','canceled','incomplete','incomplete_expired','paused','invalid')),
 cancel_at_period_end BOOLEAN NOT NULL DEFAULT FALSE,
 period_end TIMESTAMPTZ,
 paid_until TIMESTAMPTZ,
 latest_invoice_id TEXT,
 invoice_status TEXT,
 verified_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX sb_subscription_business ON sb_subscriptions(business_id);
CREATE TABLE sb_events (
 id TEXT PRIMARY KEY,
 business_id VARCHAR(100) NOT NULL REFERENCES sb_accounts(business_id),
 event_type TEXT NOT NULL,
 object_id TEXT NOT NULL,
 processed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""
CHECKSUM = hashlib.sha256(SQL.encode()).hexdigest()


def fingerprint(cursor):
    class ScopedCursor:
        def execute(self, sql, *args):
            return cursor.execute(sql.replace("'sm_%%'", "'sb_%%'").replace('sm_schema_migrations', 'sb_schema_migrations'), *args)
        def fetchall(self):
            return cursor.fetchall()
    return accounts_migration.fingerprint(ScopedCursor())


def verify(cursor):
    cursor.execute('SELECT checksum,schema_fingerprint FROM sb_schema_migrations WHERE version=%s', (VERSION,))
    if cursor.fetchone() != (CHECKSUM, fingerprint(cursor)):
        raise StaffDatabaseError('Staff billing schema verification failed.')


def migrate(cursor):
    cursor.execute('SELECT pg_advisory_xact_lock(731942024)')
    migrations.verify(cursor)
    accounts_migration.verify(cursor)
    onboarding_migration.verify(cursor)
    cursor.execute('CREATE TABLE IF NOT EXISTS sb_schema_migrations(version TEXT PRIMARY KEY,checksum TEXT NOT NULL,schema_fingerprint TEXT NOT NULL,applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW())')
    cursor.execute('SELECT version FROM sb_schema_migrations WHERE version=%s', (VERSION,))
    if cursor.fetchone():
        verify(cursor)
        return
    cursor.execute(SQL)
    cursor.execute('INSERT INTO sb_schema_migrations(version,checksum,schema_fingerprint) VALUES (%s,%s,%s)', (VERSION, CHECKSUM, fingerprint(cursor)))
    migrations.verify(cursor)
    accounts_migration.verify(cursor)
    onboarding_migration.verify(cursor)


if __name__ == '__main__':
    with transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL lock_timeout='5s'")
            cursor.execute("SET LOCAL statement_timeout='60s'")
            migrate(cursor)
    print('Staff billing migration verified and committed.')
