"""Additive ledger for platform registration review: reversible deactivation history and notification de-duplication.

Uses its own sr_ prefix so the sc_ complimentary-access schema fingerprint is unchanged.
It never deletes records and never reads or writes sb_* billing tables.
"""
import hashlib

from trimtech.modules.staff import accounts_migration, complimentary_migration, migrations, onboarding_migration
from trimtech.modules.staff.database import StaffDatabaseError, transaction

VERSION = '20261101_staff_registration_review_v1'
SQL = """
CREATE TABLE sr_review_batches (
 id BIGSERIAL PRIMARY KEY,
 action TEXT NOT NULL CHECK(action IN ('deactivate','reactivate')),
 actor TEXT NOT NULL,
 reason TEXT NOT NULL CHECK(char_length(reason) BETWEEN 1 AND 500),
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE sr_review_items (
 id BIGSERIAL PRIMARY KEY,
 batch_id BIGINT NOT NULL REFERENCES sr_review_batches(id),
 business_id VARCHAR(100) NOT NULL REFERENCES sm_businesses(id),
 previous_active BOOLEAN NOT NULL,
 new_active BOOLEAN NOT NULL
);
CREATE INDEX sr_review_items_business ON sr_review_items(business_id,id);
CREATE TABLE sr_registration_notices (
 business_id VARCHAR(100) NOT NULL REFERENCES sm_businesses(id),
 event TEXT NOT NULL CHECK(event IN ('registered','verified')),
 status TEXT NOT NULL DEFAULT 'claimed' CHECK(status IN ('claimed','sent','failed')),
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 PRIMARY KEY(business_id,event)
);
"""
CHECKSUM = hashlib.sha256(SQL.encode()).hexdigest()


def fingerprint(cursor):
    class ScopedCursor:
        def execute(self, sql, *args):
            return cursor.execute(sql.replace("'sm_%%'", "'sr_%%'").replace('sm_schema_migrations', 'sr_schema_migrations'), *args)
        def fetchall(self):
            return cursor.fetchall()
    return accounts_migration.fingerprint(ScopedCursor())


def verify(cursor):
    cursor.execute('SELECT checksum,schema_fingerprint FROM sr_schema_migrations WHERE version=%s', (VERSION,))
    if cursor.fetchone() != (CHECKSUM, fingerprint(cursor)):
        raise StaffDatabaseError('Staff registration review schema verification failed.')


def migrate(cursor):
    cursor.execute('SELECT pg_advisory_xact_lock(731942026)')
    migrations.verify(cursor)
    accounts_migration.verify(cursor)
    onboarding_migration.verify(cursor)
    complimentary_migration.verify(cursor)
    cursor.execute('CREATE TABLE IF NOT EXISTS sr_schema_migrations(version TEXT PRIMARY KEY,checksum TEXT NOT NULL,schema_fingerprint TEXT NOT NULL,applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW())')
    cursor.execute('SELECT version FROM sr_schema_migrations WHERE version=%s', (VERSION,))
    if cursor.fetchone():
        verify(cursor)
        return
    cursor.execute(SQL)
    cursor.execute('INSERT INTO sr_schema_migrations(version,checksum,schema_fingerprint) VALUES (%s,%s,%s)', (VERSION, CHECKSUM, fingerprint(cursor)))
    migrations.verify(cursor)
    accounts_migration.verify(cursor)
    onboarding_migration.verify(cursor)
    complimentary_migration.verify(cursor)


if __name__ == '__main__':
    with transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL lock_timeout='5s'")
            cursor.execute("SET LOCAL statement_timeout='60s'")
            migrate(cursor)
    print('Staff registration review migration verified and committed.')
