"""Explicit additive store for a platform-managed business contact email.

It never alters sm_* tables, so existing login identities and fingerprints are untouched.
"""
import hashlib

from trimtech.modules.staff import accounts_migration, migrations, onboarding_migration
from trimtech.modules.staff.database import StaffDatabaseError, transaction

VERSION = '20261104_staff_business_contact_v1'
SQL = """
CREATE TABLE sd_contacts (
 business_id VARCHAR(100) PRIMARY KEY REFERENCES sm_businesses(id),
 contact_email VARCHAR(254) NOT NULL CHECK(contact_email=lower(btrim(contact_email))),
 updated_by TEXT NOT NULL,
 updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""
CHECKSUM = hashlib.sha256(SQL.encode()).hexdigest()


def fingerprint(cursor):
    class ScopedCursor:
        def execute(self, sql, *args):
            return cursor.execute(sql.replace("'sm_%%'", "'sd_%%'").replace('sm_schema_migrations', 'sd_schema_migrations'), *args)
        def fetchall(self):
            return cursor.fetchall()
    return accounts_migration.fingerprint(ScopedCursor())


def present(cursor):
    cursor.execute("SELECT to_regclass('sd_contacts') IS NOT NULL AS present")
    row = cursor.fetchone()
    return bool(row['present'] if hasattr(row, 'keys') else row[0])


def verify(cursor):
    cursor.execute('SELECT checksum,schema_fingerprint FROM sd_schema_migrations WHERE version=%s', (VERSION,))
    if cursor.fetchone() != (CHECKSUM, fingerprint(cursor)):
        raise StaffDatabaseError('Staff business contact schema verification failed.')


def migrate(cursor):
    cursor.execute('SELECT pg_advisory_xact_lock(731942027)')
    migrations.verify(cursor)
    accounts_migration.verify(cursor)
    onboarding_migration.verify(cursor)
    cursor.execute('CREATE TABLE IF NOT EXISTS sd_schema_migrations(version TEXT PRIMARY KEY,checksum TEXT NOT NULL,schema_fingerprint TEXT NOT NULL,applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW())')
    cursor.execute('SELECT version FROM sd_schema_migrations WHERE version=%s', (VERSION,))
    if cursor.fetchone():
        verify(cursor)
        return
    cursor.execute(SQL)
    cursor.execute('INSERT INTO sd_schema_migrations(version,checksum,schema_fingerprint) VALUES (%s,%s,%s)', (VERSION, CHECKSUM, fingerprint(cursor)))
    migrations.verify(cursor)
    accounts_migration.verify(cursor)
    onboarding_migration.verify(cursor)


if __name__ == '__main__':
    with transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL lock_timeout='5s'")
            cursor.execute("SET LOCAL statement_timeout='60s'")
            migrate(cursor)
    print('Staff business contact migration verified and committed.')
