"""Additive trial/setup schema; existing operational and identity fingerprints unchanged."""
import hashlib
from trimtech.modules.staff.database import transaction, StaffDatabaseError
from trimtech.modules.staff import accounts_migration, migrations

VERSION='20261008_staff_onboarding_v1'
SQL="""
CREATE TABLE so_trials (
 business_id VARCHAR(100) PRIMARY KEY REFERENCES sm_businesses(id),
 administrator_id TEXT NOT NULL REFERENCES sm_administrators(id),
 starts_at TIMESTAMPTZ, ends_at TIMESTAMPTZ,
 CHECK ((starts_at IS NULL AND ends_at IS NULL) OR
        (starts_at IS NOT NULL AND ends_at IS NOT NULL AND ends_at=starts_at+INTERVAL '336 hours'))
);
CREATE TABLE so_trial_claims (
 email VARCHAR(254) PRIMARY KEY,
 business_id VARCHAR(100) NOT NULL UNIQUE REFERENCES so_trials(business_id),
 claimed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE so_setup (
 business_id VARCHAR(100) PRIMARY KEY REFERENCES sm_businesses(id),
 business_type VARCHAR(100) NOT NULL DEFAULT '',
 company_address VARCHAR(1000) NOT NULL DEFAULT '',
 current_step TEXT NOT NULL DEFAULT 'company',
 completed JSONB NOT NULL DEFAULT '{}',
 updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE so_employee_credentials (
 employee_id BIGINT PRIMARY KEY REFERENCES staff_employees(id),
 business_id VARCHAR(100) NOT NULL REFERENCES sm_businesses(id),
 password_hash TEXT NOT NULL,
 version TEXT NOT NULL,
 activated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE so_employee_invites (
 id TEXT PRIMARY KEY,
 token_hash TEXT NOT NULL UNIQUE,
 employee_id BIGINT NOT NULL REFERENCES staff_employees(id),
 business_id VARCHAR(100) NOT NULL REFERENCES sm_businesses(id),
 email VARCHAR(254) NOT NULL,
 expires_at TIMESTAMPTZ NOT NULL,
 consumed_at TIMESTAMPTZ,
 status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','accepted_by_provider','failed','accepted','revoked')),
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX so_employee_invites_scope ON so_employee_invites(business_id,employee_id);
"""
CHECKSUM=hashlib.sha256(SQL.encode()).hexdigest()


def fingerprint(cursor):
    # Reuse the existing canonical catalogue fingerprint algorithm for this separate namespace.
    class ScopedCursor:
        def execute(self,sql,*args):
            return cursor.execute(sql.replace("'sm_%%'","'so_%%'").replace('sm_schema_migrations','so_schema_migrations'),*args)
        def fetchall(self):
            return cursor.fetchall()
    return accounts_migration.fingerprint(ScopedCursor())


def verify(cursor):
    cursor.execute('SELECT checksum,schema_fingerprint FROM so_schema_migrations WHERE version=%s',(VERSION,))
    row=cursor.fetchone()
    if not row or row!=(CHECKSUM,fingerprint(cursor)):
        raise StaffDatabaseError('Staff onboarding schema verification failed.')


def migrate(cursor):
    cursor.execute('SELECT pg_advisory_xact_lock(731942024)')
    migrations.verify(cursor)
    accounts_migration.verify(cursor)
    cursor.execute('CREATE TABLE IF NOT EXISTS so_schema_migrations(version TEXT PRIMARY KEY,checksum TEXT NOT NULL,schema_fingerprint TEXT NOT NULL,applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW())')
    cursor.execute('SELECT version FROM so_schema_migrations WHERE version=%s',(VERSION,))
    if cursor.fetchone():
        verify(cursor)
        return
    cursor.execute(SQL)
    cursor.execute('INSERT INTO so_schema_migrations(version,checksum,schema_fingerprint) VALUES (%s,%s,%s)',(VERSION,CHECKSUM,fingerprint(cursor)))
    accounts_migration.verify(cursor)
    migrations.verify(cursor)


if __name__=='__main__':
    with transaction() as connection:
        with connection.cursor() as cursor:
            migrate(cursor)
    print('Staff onboarding migration verified and committed.')
