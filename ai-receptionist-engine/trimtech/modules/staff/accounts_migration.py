"""Independent, additive Staff identity schema; never modifies operational/payroll tables."""
import hashlib
import json

from trimtech.modules.staff.database import transaction, StaffDatabaseError
from trimtech.modules.staff.migrations import verify as verify_staff, _canonical_schema_sql

VERSION = '20261008_staff_identity_v1'
SQL = """
CREATE TABLE sm_businesses (
    id VARCHAR(100) PRIMARY KEY,
    name VARCHAR(160) NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE sm_administrators (
    id TEXT PRIMARY KEY,
    email VARCHAR(254) NOT NULL UNIQUE CHECK (email=lower(btrim(email))),
    contact_name VARCHAR(160) NOT NULL,
    password_hash TEXT NOT NULL,
    verified_at TIMESTAMPTZ,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE sm_memberships (
    administrator_id TEXT NOT NULL REFERENCES sm_administrators(id),
    business_id VARCHAR(100) NOT NULL REFERENCES sm_businesses(id),
    role TEXT NOT NULL DEFAULT 'owner' CHECK (role IN ('owner','administrator')),
    active BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (administrator_id,business_id)
);
CREATE TABLE sm_tokens (
    token_hash TEXT PRIMARY KEY,
    administrator_id TEXT NOT NULL REFERENCES sm_administrators(id),
    purpose TEXT NOT NULL CHECK (purpose IN ('verify','reset')),
    expires_at TIMESTAMPTZ NOT NULL,
    consumed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX sm_tokens_administrator ON sm_tokens(administrator_id,purpose);
CREATE TABLE sm_sessions (
    token_hash TEXT PRIMARY KEY,
    administrator_id TEXT NOT NULL REFERENCES sm_administrators(id),
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX sm_sessions_administrator ON sm_sessions(administrator_id);
CREATE TABLE sm_owner_provisions (
    business_id VARCHAR(100) NOT NULL REFERENCES sm_businesses(id),
    administrator_id TEXT NOT NULL REFERENCES sm_administrators(id),
    operator TEXT NOT NULL,
    reason TEXT NOT NULL,
    manifest_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY(business_id,administrator_id)
);
CREATE TABLE sm_rate_limits (
    key_hash TEXT PRIMARY KEY,
    window_started TIMESTAMPTZ NOT NULL,
    attempts INTEGER NOT NULL CHECK (attempts>0)
);
"""
CHECKSUM = hashlib.sha256(SQL.encode()).hexdigest()


def fingerprint(cursor):
    cursor.execute("""SELECT table_name,column_name,data_type,udt_name,is_nullable,column_default,
        character_maximum_length,numeric_precision,numeric_scale FROM information_schema.columns
        WHERE table_schema=current_schema() AND table_name LIKE 'sm_%%'
        AND table_name <> 'sm_schema_migrations' ORDER BY table_name,ordinal_position""")
    columns = cursor.fetchall()
    cursor.execute("""SELECT c.relname,k.conname,pg_get_constraintdef(k.oid)
        FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid
        JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname=current_schema() AND c.relname LIKE 'sm_%%'
        AND c.relname <> 'sm_schema_migrations' ORDER BY c.relname,k.conname""")
    constraints = [(t,n,_canonical_schema_sql(d)) for t,n,d in cursor.fetchall()]
    cursor.execute("""SELECT tablename,indexname,indexdef FROM pg_indexes
        WHERE schemaname=current_schema() AND tablename LIKE 'sm_%%'
        AND tablename <> 'sm_schema_migrations' ORDER BY tablename,indexname""")
    indexes = [(t,n,_canonical_schema_sql(d)) for t,n,d in cursor.fetchall()]
    return hashlib.sha256(json.dumps([columns,constraints,indexes],default=str,sort_keys=True).encode()).hexdigest()


def verify(cursor):
    cursor.execute('SELECT checksum,schema_fingerprint FROM sm_schema_migrations WHERE version=%s', (VERSION,))
    row = cursor.fetchone()
    if not row or row != (CHECKSUM, fingerprint(cursor)):
        raise StaffDatabaseError('Staff identity schema verification failed.')


def migrate(cursor):
    cursor.execute('SELECT pg_advisory_xact_lock(731942024)')
    verify_staff(cursor)
    cursor.execute("""CREATE TABLE IF NOT EXISTS sm_schema_migrations (
        version TEXT PRIMARY KEY, checksum TEXT NOT NULL, schema_fingerprint TEXT NOT NULL,
        applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW())""")
    cursor.execute('SELECT version FROM sm_schema_migrations WHERE version=%s', (VERSION,))
    if cursor.fetchone():
        verify(cursor)
        return
    cursor.execute(SQL)
    cursor.execute('INSERT INTO sm_schema_migrations(version,checksum,schema_fingerprint) VALUES (%s,%s,%s)',
                   (VERSION,CHECKSUM,fingerprint(cursor)))
    verify_staff(cursor)


if __name__ == '__main__':
    with transaction() as connection:
        with connection.cursor() as cursor:
            migrate(cursor)
    print('Staff identity migration verified and committed; operational tables unchanged.')
