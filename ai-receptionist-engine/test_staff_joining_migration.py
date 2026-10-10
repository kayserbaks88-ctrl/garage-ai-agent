"""First-application preservation and rollback checks in disposable PostgreSQL schemas."""
import os
import unittest
from unittest.mock import patch

import psycopg2
from psycopg2 import sql

import test_staff_agency as fixtures
from trimtech.modules.staff import database, joining_migration


@unittest.skipUnless(os.getenv('STAFF_TEST_DATABASE_URL'), 'Requires isolated PostgreSQL')
class JoiningMigrationTests(unittest.TestCase):
    for name in ('setUp', 'cleanup_schema', 'connect', 'insert', 'client'):
        locals()[name] = getattr(fixtures.AgencyDatabaseTests, name)

    def snapshot(self):
        with database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT tablename FROM pg_tables WHERE schemaname=current_schema() AND tablename NOT LIKE 'sj_%%' ORDER BY tablename")
                names = [row[0] for row in cursor.fetchall()]
                result = {}
                for name in names:
                    cursor.execute(sql.SQL('SELECT to_jsonb(t)::text FROM {} t ORDER BY to_jsonb(t)::text').format(sql.Identifier(name)))
                    result[name] = cursor.fetchall()
                return result

    def seed_existing_records(self):
        run = self.insert("INSERT INTO staff_payroll_runs(business_id,period_start,period_end,status,total_gross_pay,total_net_pay) VALUES ('alpha','2026-10-01','2026-10-07','paid',100,100) RETURNING id")
        self.insert("INSERT INTO staff_payslips(business_id,payroll_run_id,employee_id,gross_pay,net_pay) VALUES ('alpha',%s,%s,100,100) RETURNING id", (run, self.employee))
        database.execute("CREATE TABLE unrelated_application_records(id TEXT PRIMARY KEY, details JSONB NOT NULL)")
        database.execute("INSERT INTO unrelated_application_records VALUES ('garage-voice','{\"preserve\":true}'),('paychaser','{\"preserve\":true}')")

    def test_first_application_and_repeat_preserve_every_existing_table(self):
        self.seed_existing_records()
        before = self.snapshot()
        for _ in range(2):
            with database.transaction() as connection:
                with connection.cursor() as cursor:
                    joining_migration.migrate(cursor)
                    joining_migration.verify(cursor)
            self.assertEqual(self.snapshot(), before)

    def test_failed_first_application_rolls_back_new_tables_and_preserves_records(self):
        self.seed_existing_records()
        before = self.snapshot()
        with patch.object(joining_migration, 'SQL', joining_migration.SQL + '\nSELECT 1/0;'):
            with self.assertRaises(psycopg2.Error):
                with database.transaction() as connection:
                    with connection.cursor() as cursor:
                        joining_migration.migrate(cursor)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(database.fetch_all("SELECT tablename FROM pg_tables WHERE schemaname=current_schema() AND tablename LIKE 'sj_%%'"), [])
