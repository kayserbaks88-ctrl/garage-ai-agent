"""Operator-run preflight: no dotenv, migrations, account creation or data writes."""
import json
import os
import sys

import psycopg2
from psycopg2 import sql

from trimtech.modules.staff import migrations, accounts_migration
from trimtech.modules.staff import onboarding_migration, billing_migration


def main():
    if not os.environ.get("DATABASE_URL", "").strip():
        print(json.dumps({"result": "STOP", "reason": "DATABASE_URL is not supplied"}))
        return 1
    report = {"transaction": "read-only", "schemas": {}, "businesses": []}
    failed = False
    try:
        connection = psycopg2.connect(
            os.environ["DATABASE_URL"], connect_timeout=10,
            application_name="staff_readonly_preflight",
        )
        try:
            connection.set_session(readonly=True, isolation_level="REPEATABLE READ")
            with connection.cursor() as cursor:
                cursor.execute("SET LOCAL statement_timeout='30s'")
                cursor.execute("SET LOCAL lock_timeout='5s'")
                cursor.execute("SHOW transaction_read_only")
                if cursor.fetchone()[0] != "on":
                    raise RuntimeError("Read-only guard failed")
                cursor.execute("SELECT current_schema()")
                schema = cursor.fetchone()[0]
                cursor.execute("SELECT table_name FROM information_schema.tables WHERE table_schema=%s", (schema,))
                tables = {row[0] for row in cursor.fetchall()}
                for label, ledger, module in (
                    ("operational_v3", "staff_schema_migrations", migrations),
                    ("identity", "sm_schema_migrations", accounts_migration),
                    ("onboarding", "so_schema_migrations", onboarding_migration),
                    ("billing", "sb_schema_migrations", billing_migration),
                ):
                    prefix = ledger.split("_")[0] + "_"
                    if ledger not in tables:
                        partial = any(table.startswith(prefix) for table in tables)
                        report["schemas"][label] = "ledger_missing_review_required" if partial else "not_installed"
                        failed = failed or partial or label == "operational_v3"
                        continue
                    # A savepoint lets inventory continue after a failed verification.
                    cursor.execute("SAVEPOINT schema_check")
                    try:
                        module.verify(cursor)
                        report["schemas"][label] = "verified_against_candidate_code"
                    except Exception:
                        cursor.execute("ROLLBACK TO SAVEPOINT schema_check")
                        report["schemas"][label] = "verification_failed_review_required"
                        failed = True
                    finally:
                        cursor.execute("RELEASE SAVEPOINT schema_check")

                cursor.execute("""SELECT table_name FROM information_schema.columns
                    WHERE table_schema=%s AND left(table_name,6)='staff_'
                    AND column_name='business_id' ORDER BY table_name""", (schema,))
                sources = [row[0] for row in cursor.fetchall()]
                business_sources = {}
                for table in sources:
                    cursor.execute(sql.SQL("SELECT DISTINCT business_id FROM {}.{} WHERE business_id IS NOT NULL").format(
                        sql.Identifier(schema), sql.Identifier(table)))
                    for (business_id,) in cursor.fetchall():
                        business_sources.setdefault(business_id, []).append(table)
                eligible = {"staff_employees", "staff_sites", "staff_business_settings", "staff_settings"}
                identity_verified = report["schemas"]["identity"] == "verified_against_candidate_code"
                for business_id, found_in in sorted(business_sources.items()):
                    item = {"business_id": business_id, "sources": found_in,
                            "recognized_by_provisioner": bool(eligible.intersection(found_in))}
                    if not identity_verified:
                        item["ownership"] = "not_evaluated_identity_schema_unverified"
                    else:
                        cursor.execute("SELECT active FROM sm_businesses WHERE id=%s", (business_id,))
                        business = cursor.fetchone()
                        cursor.execute("""SELECT m.active,a.active,a.verified_at IS NOT NULL
                            FROM sm_memberships m JOIN sm_administrators a ON a.id=m.administrator_id
                            WHERE m.business_id=%s AND m.role='owner'""", (business_id,))
                        owners = cursor.fetchall()
                        if business and not business[0]:
                            status = "inactive_business_manual_review"
                        elif not owners:
                            status = "no_owner_membership_verified_manifest_required"
                        elif len(owners) != 1 or not all(m and a for m, a, v in owners):
                            status = "ownership_state_manual_review"
                        elif not owners[0][2]:
                            status = "active_owner_email_verification_pending"
                        else:
                            status = "active_verified_owner_present_independent_confirmation_required"
                        item["ownership"] = status
                    report["businesses"].append(item)
            # Never commit, including on successful completion.
        finally:
            connection.rollback()
            connection.close()
    except Exception:
        # Connection/SQL exceptions can contain hosts or credentials. Never print them.
        report["result"] = "STOP"
        report["reason"] = "Read-only check could not complete; connection, permissions or schema require manual review"
        print(json.dumps(report, indent=2))
        return 1
    report["result"] = "STOP_REVIEW_REQUIRED" if failed else "READ_ONLY_CHECK_COMPLETED"
    report["note"] = "Schema absence is not permission to migrate; IDs and owner states are not proof of ownership."
    print(json.dumps(report, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
