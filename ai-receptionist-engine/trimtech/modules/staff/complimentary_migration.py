"""Explicit additive ledger for platform-granted complimentary Staff access.

Independent of Stripe: it never reads or writes sb_* billing tables.
"""
import hashlib

from trimtech.modules.staff import accounts_migration, migrations, onboarding_migration
from trimtech.modules.staff.database import StaffDatabaseError, transaction

VERSION = '20261101_staff_complimentary_v1'
SQL = """
CREATE TABLE sc_grants (
 id BIGSERIAL PRIMARY KEY,
 business_id VARCHAR(100) NOT NULL REFERENCES sm_businesses(id),
 days INTEGER NOT NULL CHECK(days IN (3,7,14,30)),
 reason TEXT NOT NULL CHECK(char_length(reason) BETWEEN 1 AND 1000),
 granted_by TEXT NOT NULL,
 granted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 starts_at TIMESTAMPTZ NOT NULL,
 expires_at TIMESTAMPTZ NOT NULL,
 revoked_at TIMESTAMPTZ,
 revoked_by TEXT,
 revoke_reason TEXT,
 CHECK(expires_at>starts_at)
);
CREATE INDEX sc_grants_business ON sc_grants(business_id,expires_at);
"""
CHECKSUM = hashlib.sha256(SQL.encode()).hexdigest()


def fingerprint(cursor):
    class ScopedCursor:
        def execute(self, sql, *args):
            return cursor.execute(sql.replace("'sm_%%'", "'sc_%%'").replace('sm_schema_migrations', 'sc_schema_migrations'), *args)
        def fetchall(self):
            return cursor.fetchall()
    return accounts_migration.fingerprint(ScopedCursor())


def verify(cursor):
    cursor.execute('SELECT checksum,schema_fingerprint FROM sc_schema_migrations WHERE version=%s', (VERSION,))
    if cursor.fetchone() != (CHECKSUM, fingerprint(cursor)):
        raise StaffDatabaseError('Staff complimentary access schema verification failed.')


def migrate(cursor):
    cursor.execute('SELECT pg_advisory_xact_lock(731942025)')
    migrations.verify(cursor)
    accounts_migration.verify(cursor)
    onboarding_migration.verify(cursor)
    cursor.execute('CREATE TABLE IF NOT EXISTS sc_schema_migrations(version TEXT PRIMARY KEY,checksum TEXT NOT NULL,schema_fingerprint TEXT NOT NULL,applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW())')
    cursor.execute('SELECT version FROM sc_schema_migrations WHERE version=%s', (VERSION,))
    if cursor.fetchone():
        verify(cursor)
        return
    cursor.execute(SQL)
    cursor.execute('INSERT INTO sc_schema_migrations(version,checksum,schema_fingerprint) VALUES (%s,%s,%s)', (VERSION, CHECKSUM, fingerprint(cursor)))
    migrations.verify(cursor)
    accounts_migration.verify(cursor)
    onboarding_migration.verify(cursor)


if __name__ == '__main__':
    with transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL lock_timeout='5s'")
            cursor.execute("SET LOCAL statement_timeout='60s'")
            migrate(cursor)
    print('Staff complimentary access migration verified and committed.')
