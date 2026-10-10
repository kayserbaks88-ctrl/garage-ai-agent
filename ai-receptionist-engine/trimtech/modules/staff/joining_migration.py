"""Explicit additive migration for approval-gated employee joining; never run at startup."""
import hashlib
from trimtech.modules.staff import migrations, accounts_migration, onboarding_migration, billing_migration
from trimtech.modules.staff.database import transaction, StaffDatabaseError

VERSION='20261010_staff_joining_v1'
SQL="""
CREATE TABLE sj_links (
 id TEXT PRIMARY KEY,
 business_id VARCHAR(100) NOT NULL REFERENCES sm_businesses(id),
 token_hash TEXT NOT NULL UNIQUE,
 expires_at TIMESTAMPTZ NOT NULL,
 revoked_at TIMESTAMPTZ,
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX sj_one_current_link ON sj_links(business_id) WHERE revoked_at IS NULL;
CREATE TABLE sj_registrations (
 id TEXT PRIMARY KEY,
 business_id VARCHAR(100) NOT NULL REFERENCES sm_businesses(id),
 link_id TEXT NOT NULL REFERENCES sj_links(id),
 full_name VARCHAR(150) NOT NULL,
 email VARCHAR(254) NOT NULL CHECK(email=lower(btrim(email))),
 phone VARCHAR(40) NOT NULL,
 password_hash TEXT,
 status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected')),
 employee_id BIGINT UNIQUE REFERENCES staff_employees(id),
 reviewed_by TEXT,
 reviewed_at TIMESTAMPTZ,
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 UNIQUE(business_id,email),
 UNIQUE(business_id,phone),
 CHECK((status='approved' AND employee_id IS NOT NULL) OR (status<>'approved' AND employee_id IS NULL)),
 CHECK((status='pending' AND password_hash IS NOT NULL) OR (status<>'pending' AND password_hash IS NULL))
);
CREATE INDEX sj_registrations_scope ON sj_registrations(business_id,status);
"""
CHECKSUM=hashlib.sha256(SQL.encode()).hexdigest()

def fingerprint(cursor):
    class Scoped:
        def execute(self,sql,*args):
            return cursor.execute(sql.replace("'sm_%%'","'sj_%%'").replace('sm_schema_migrations','sj_schema_migrations'),*args)
        def fetchall(self): return [tuple(row.values()) if isinstance(row,dict) else row for row in cursor.fetchall()]
    return accounts_migration.fingerprint(Scoped())

def verify(cursor):
    cursor.execute('SELECT checksum,schema_fingerprint FROM sj_schema_migrations WHERE version=%s',(VERSION,))
    row=cursor.fetchone()
    actual=tuple(row.values()) if isinstance(row,dict) else row
    if actual!=(CHECKSUM,fingerprint(cursor)):
        raise StaffDatabaseError('Employee joining schema verification failed.')

def migrate(cursor):
    cursor.execute('SELECT pg_advisory_xact_lock(731942024)')
    for module in (migrations,accounts_migration,onboarding_migration,billing_migration): module.verify(cursor)
    cursor.execute('CREATE TABLE IF NOT EXISTS sj_schema_migrations(version TEXT PRIMARY KEY,checksum TEXT NOT NULL,schema_fingerprint TEXT NOT NULL,applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW())')
    cursor.execute('SELECT version FROM sj_schema_migrations WHERE version=%s',(VERSION,))
    if cursor.fetchone():
        verify(cursor)
        return
    cursor.execute(SQL)
    cursor.execute('INSERT INTO sj_schema_migrations(version,checksum,schema_fingerprint) VALUES (%s,%s,%s)',(VERSION,CHECKSUM,fingerprint(cursor)))
    for module in (migrations,accounts_migration,onboarding_migration,billing_migration): module.verify(cursor)

if __name__=='__main__':
    with transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL lock_timeout='5s'")
            cursor.execute("SET LOCAL statement_timeout='60s'")
            migrate(cursor)
    print('Employee joining migration verified and committed.')
