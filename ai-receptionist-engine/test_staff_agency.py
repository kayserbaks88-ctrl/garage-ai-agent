"""Real PostgreSQL route tests in disposable, uniquely named schemas.

Set STAFF_TEST_DATABASE_URL to a disposable local PostgreSQL database.
No DATABASE_URL or production application credentials are used by these tests.
"""
import os
import time
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import psycopg2
from cryptography.fernet import Fernet
from flask import Flask
from psycopg2 import sql
from psycopg2.extras import RealDictCursor

from dashboard_auth import dashboard_auth
from trimtech.modules.staff import agency, database, migrations
from trimtech.modules.staff.payroll import parse_shift_datetime
from trimtech.modules.staff.routes import staff_blueprint


class AgencyValidationTests(unittest.TestCase):
    def test_distance_handles_zero_coordinates_and_missing_origin(self):
        self.assertEqual(agency.distance_km({"latitude": 0, "longitude": 0}, {"latitude": 0, "longitude": 0}), Decimal("0.00"))
        self.assertIsNone(agency.distance_km(None, {"latitude": 0, "longitude": 0}))
        self.assertEqual(agency.distance_km({"latitude": 0, "longitude": 0}, {"latitude": 0, "longitude": 1}), Decimal("111.19"))

    def test_uk_clock_changes_require_real_unambiguous_times(self):
        for value in ("2026-03-29T01:30", "2026-10-25T01:30"):
            with self.assertRaises(ValueError):
                parse_shift_datetime(value, "start")
        self.assertEqual(parse_shift_datetime("2026-10-25T01:30+01:00", "start").hour, 0)
        self.assertEqual(parse_shift_datetime("2026-10-25T01:30+00:00", "start").hour, 1)

    def test_fresh_gps_required(self):
        for values in ({"accuracy": "10"}, {"accuracy": "nan", "captured_at": datetime.now(timezone.utc).isoformat()},
                       {"accuracy": "10", "captured_at": (datetime.now(timezone.utc)-timedelta(minutes=5)).isoformat()}):
            with self.assertRaises(ValueError):
                agency.gps_evidence(values, required=True)


@unittest.skipUnless(os.getenv("STAFF_TEST_DATABASE_URL"), "Set STAFF_TEST_DATABASE_URL for real PostgreSQL integration tests")
class AgencyDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.url = os.environ["STAFF_TEST_DATABASE_URL"]
        self.schema = "staff_test_" + uuid.uuid4().hex
        self.admin = psycopg2.connect(self.url)
        self.admin.autocommit = True
        with self.admin.cursor() as cursor:
            cursor.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(self.schema)))
        self.addCleanup(self.cleanup_schema)
        self.connection_patch = patch.object(database, "get_connection", self.connect)
        self.connection_patch.start()
        self.addCleanup(self.connection_patch.stop)
        self.key_patch = patch.dict(os.environ, {"STAFF_TRAVEL_KEY": Fernet.generate_key().decode()})
        self.key_patch.start()
        self.addCleanup(self.key_patch.stop)
        with database.transaction() as connection:
            with connection.cursor() as cursor:
                for statement in database.SCHEMA_STATEMENTS:
                    cursor.execute(statement)
        self.employee = self.insert("""INSERT INTO staff_employees
            (business_id,full_name,phone,hourly_rate,payroll_number) VALUES ('alpha','Alex','07001',15,'111') RETURNING id""")
        self.second = self.insert("""INSERT INTO staff_employees
            (business_id,full_name,phone,hourly_rate,payroll_number) VALUES ('alpha','Blair','07002',20,'222') RETURNING id""")
        self.foreign_employee = self.insert("""INSERT INTO staff_employees
            (business_id,full_name,phone,hourly_rate,payroll_number) VALUES ('beta','Other','07003',20,'333') RETURNING id""")
        self.site = self.insert("""INSERT INTO staff_sites (business_id,name,address,latitude,longitude)
            VALUES ('alpha','First site','1 Test Street',51.5,-0.12) RETURNING id""")
        self.second_site = self.insert("""INSERT INTO staff_sites (business_id,name,address,latitude,longitude)
            VALUES ('alpha','Second site','2 Test Street',52,-1) RETURNING id""")
        self.foreign_site = self.insert("""INSERT INTO staff_sites (business_id,name,address,latitude,longitude)
            VALUES ('beta','Private site','3 Test Street',51.5,-0.12) RETURNING id""")
        self.old_shift = self.insert("""INSERT INTO staff_shifts
            (business_id,employee_id,site_id,site_name,clock_in_at,clock_out_at)
            VALUES ('alpha',%s,%s,'Old shift',NOW()-INTERVAL '5 days',NOW()-INTERVAL '5 days'+INTERVAL '1 hour') RETURNING id""",
            (self.employee, self.site))
        database.init_staff_database(migrate=True)
        self.app = Flask(__name__, template_folder=str(Path(__file__).parent / "templates"))
        self.app.secret_key = "test-session-key"
        self.app.testing = True
        self.app.register_blueprint(dashboard_auth)
        self.app.register_blueprint(staff_blueprint)
        self.manager = self.client(manager=True)
        self.worker = self.client(employee=self.employee)
        self.worker2 = self.client(employee=self.second)

    def cleanup_schema(self):
        # Only a schema created by this test can be removed.
        assert self.schema.startswith("staff_test_") and len(self.schema) == 43
        with self.admin.cursor() as cursor:
            cursor.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(self.schema)))
        self.admin.close()

    def connect(self):
        return psycopg2.connect(self.url, options=f"-c search_path={self.schema} -c timezone=UTC")

    def insert(self, query, parameters=()):
        return database.fetch_one(query, parameters)["id"]

    def client(self, employee=None, manager=False, business="alpha"):
        client = self.app.test_client()
        with client.session_transaction() as session:
            session["_staff_csrf_token"] = "test-csrf"
            if manager:
                session["dashboard_authenticated"] = True
                session["dashboard_username"] = "reviewer"
            if employee:
                session["_staff_employee_auth"] = {"business_id": business, "employee_id": employee, "issued_at": int(time.time())}
        return client

    def post(self, client, path, data=None):
        return client.post("/staff/alpha/" + path, data={"csrf_token": "test-csrf", **(data or {})})

    def row(self, table, row_id):
        return database.fetch_one(f"SELECT * FROM {table} WHERE id=%s", (row_id,))

    def enable_agency(self):
        response = self.post(self.manager, "settings/organisation", {"organisation_mode": "agency", "reason": "Pilot"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(agency.settings("alpha")["organisation_mode"], "agency")

    def assignment_values(self, employee=None, site=None, start=None, end=None):
        now = datetime.now(timezone.utc)
        return {"employee_id": employee or self.employee, "site_id": site or self.site,
                "starts_at": (start or now-timedelta(minutes=5)).isoformat(),
                "ends_at": (end or now+timedelta(hours=1)).isoformat(), "reason": "Scheduled job"}

    def assignment(self, **kwargs):
        with database.transaction() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                return agency.save_assignment(cursor, "alpha", "manager:test", self.assignment_values(**kwargs))

    def gps(self, **kwargs):
        return {"latitude": "51.5", "longitude": "-0.12", "accuracy": "8",
                "captured_at": datetime.now(timezone.utc).isoformat(), **kwargs}

    def current(self, employee=None):
        return database.fetch_one("SELECT * FROM staff_shifts WHERE employee_id=%s AND clock_out_at IS NULL", (employee or self.employee,))

    def completed_shift(self):
        now = datetime.now(timezone.utc)
        return self.insert("""INSERT INTO staff_shifts
            (business_id,employee_id,site_id,site_name,clock_in_at,clock_out_at,approval_status)
            VALUES ('alpha',%s,%s,'First site',%s,%s,'approved') RETURNING id""",
            (self.employee, self.site, now-timedelta(hours=2), now-timedelta(hours=1)))

    def edit_values(self, shift):
        return {"clock_in_at": shift["clock_in_at"].isoformat(),
                "clock_out_at": (shift["clock_out_at"]+timedelta(minutes=30)).isoformat(),
                "site_id": self.site, "adjustment_reason": "Corrected end time"}

    def payroll(self, shift_id):
        shift = self.row("staff_shifts", shift_id)
        day = shift["clock_in_at"].astimezone(agency.UK_TIMEZONE).date().isoformat()
        self.post(self.manager, "payroll/generate", {"period_start": day, "period_end": day})
        row = database.fetch_one("SELECT * FROM staff_payroll_runs WHERE business_id='alpha'")
        self.assertIsNotNone(row)
        return row

    def test_migration_is_repeatable_and_preserves_legacy(self):
        database.init_staff_database(migrate=True)
        database.init_staff_database()
        shift = self.row("staff_shifts", self.old_shift)
        self.assertEqual(shift["site_name"], "Old shift")
        self.assertIsNone(shift["assignment_id"])
        self.assertIsNone(shift["clock_in_accuracy"])
        self.assertFalse(database.fetch_all("SELECT * FROM staff_shift_travel"))
        self.assertEqual(agency.settings("alpha")["organisation_mode"], "fixed")
        with self.connect() as connection:
            with connection.cursor() as cursor:
                # pg_dump reconstructs these definitions; reparsing changes
                # varchar-array cast spelling without changing their meaning.
                cursor.execute("""SELECT c.relname,k.conname,pg_get_constraintdef(k.oid)
                    FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid
                    JOIN pg_namespace n ON n.oid=c.relnamespace
                    WHERE n.nspname=current_schema() AND k.contype='c'
                      AND c.relname LIKE 'staff_%%'""")
                for table, name, definition in cursor.fetchall():
                    cursor.execute(sql.SQL("ALTER TABLE {} DROP CONSTRAINT {}").format(
                        sql.Identifier(table), sql.Identifier(name)))
                    cursor.execute(sql.SQL("ALTER TABLE {} ADD CONSTRAINT {} ").format(
                        sql.Identifier(table), sql.Identifier(name)) + sql.SQL(definition))
                cursor.execute("""SELECT indexname,indexdef FROM pg_indexes
                    WHERE schemaname=current_schema() AND indexname='staff_leave_exact_request_unique'""")
                name, definition = cursor.fetchone()
                cursor.execute(sql.SQL("DROP INDEX {}").format(sql.Identifier(name)))
                cursor.execute(definition)
                migrations.verify(cursor)
                cursor.execute("SAVEPOINT restored_schema")
                cursor.execute("ALTER TABLE staff_employees DROP CONSTRAINT staff_employees_role_valid")
                cursor.execute("""ALTER TABLE staff_employees ADD CONSTRAINT staff_employees_role_valid
                    CHECK (role IN ('owner','manager','staff','unexpected_role'))""")
                with self.assertRaises(database.StaffDatabaseError):
                    migrations.verify(cursor)
                cursor.execute("ROLLBACK TO SAVEPOINT restored_schema")
                cursor.execute("DROP INDEX staff_leave_exact_request_unique")
                cursor.execute(definition.replace("'approved'", "'rejected'"))
                with self.assertRaises(database.StaffDatabaseError):
                    migrations.verify(cursor)
                cursor.execute("ROLLBACK TO SAVEPOINT restored_schema")
                cursor.execute("ALTER TABLE staff_assignments ADD COLUMN unexpected INTEGER")
                with self.assertRaises(database.StaffDatabaseError):
                    migrations.verify(cursor)
            connection.rollback()

    def test_fixed_flow_clock_break_leave_review_profile_payroll(self):
        home = self.worker.get("/staff/alpha/employee")
        self.assertEqual(home.status_code, 200)
        self.assertIn(b'name="site_id"', home.data)
        self.assertNotIn(b'name="assignment_id"', home.data)
        self.post(self.worker, "employee/clock-in", {"site_id": self.site, **self.gps()})
        shift = self.current()
        self.assertIsNotNone(shift)
        self.assertIsNone(shift["assignment_id"])
        self.assertFalse(database.fetch_all("SELECT * FROM staff_shift_travel"))
        self.post(self.worker, "employee/break/start", {"shift_id": shift["id"]})
        br = database.fetch_one("SELECT * FROM staff_breaks WHERE shift_id=%s", (shift["id"],))
        self.post(self.worker, "employee/break/end", {"shift_id": shift["id"], "break_id": br["id"]})
        self.post(self.worker, "employee/clock-out", {"shift_id": shift["id"], **self.gps()})
        self.assertIsNone(self.current())
        self.assertEqual(self.row("staff_shifts", shift["id"])["clock_out_verification"], "within_radius")
        self.post(self.worker, "employee/leave", {"leave_type": "holiday", "start_date": "2027-02-01", "end_date": "2027-02-02"})
        leave = database.fetch_one("SELECT * FROM staff_leave_requests WHERE employee_id=%s", (self.employee,))
        self.assertEqual(leave["approval_status"], "pending")
        self.post(self.manager, f"leave/{leave['id']}/approve")
        self.assertEqual(self.row("staff_leave_requests", leave["id"])["approval_status"], "approved")
        self.post(self.manager, "shifts/approve-selected", {"shift_ids": [shift["id"]]})
        self.assertEqual(self.row("staff_shifts", shift["id"])["approval_status"], "approved")
        response = self.manager.get(f"/staff/alpha?employee={self.employee}&edit_shift={shift['id']}")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Assignment and clocking evidence", response.data)
        self.payroll(shift["id"])

    def test_agency_assignments_two_employees_and_gps(self):
        self.enable_agency()
        first = self.assignment()
        second = self.assignment(employee=self.second, site=self.second_site)
        home = self.worker.get("/staff/alpha/employee")
        self.assertEqual(home.status_code, 200)
        self.assertIn(b'name="assignment_id"', home.data)
        self.assertNotIn(b'name="site_id"', home.data)
        self.assertNotIn(b"Second site", home.data)
        self.post(self.worker, "employee/clock-in", {"assignment_id": second, **self.gps()})
        self.assertIsNone(self.current())
        for gps in (self.gps(latitude="0", longitude="0"), self.gps(accuracy="1000"), {}, self.gps(captured_at="")):
            self.post(self.worker, "employee/clock-in", {"assignment_id": first, **gps})
            self.assertIsNone(self.current())
        self.post(self.worker, "employee/clock-in", {"assignment_id": first, "site_id": self.foreign_site, **self.gps()})
        shift = self.current()
        self.assertEqual(shift["site_id"], self.site)
        self.assertEqual(shift["assignment_id"], first)
        self.assertEqual(shift["assigned_site_address"], "1 Test Street")
        travel = database.fetch_one("SELECT * FROM staff_shift_travel WHERE shift_id=%s", (shift["id"],))
        self.assertIsNone(travel["distance_km"])
        self.post(self.worker2, "employee/clock-in", {"assignment_id": second, **self.gps(latitude="52", longitude="-1")})
        self.assertEqual(self.current(self.second)["site_id"], self.second_site)
        self.post(self.worker, "employee/clock-out", {"shift_id": shift["id"], **self.gps(latitude="52")})
        self.assertIsNotNone(self.current())
        self.post(self.worker, "employee/clock-out", {"shift_id": shift["id"], **self.gps()})
        self.assertIsNone(self.current())

    def test_assignment_windows_overlap_cancellation_and_override(self):
        now = datetime.now(timezone.utc)
        assignment = self.assignment(start=now, end=now+timedelta(hours=1))
        self.assignment(start=now+timedelta(hours=1), end=now+timedelta(hours=2))
        with self.assertRaisesRegex(ValueError, "overlapping"):
            self.assignment(start=now+timedelta(minutes=30), end=now+timedelta(hours=2))
        self.post(self.manager, f"assignments/{assignment}/cancel", {"reason": "Client cancelled"})
        self.assertEqual(self.row("staff_assignments", assignment)["status"], "cancelled")
        values = self.assignment_values(start=now, end=now+timedelta(hours=1))
        self.post(self.manager, "assignments", {**values, "override": "on"})
        self.assertTrue(database.fetch_one("SELECT id FROM staff_audit WHERE action='assignment_override'"))
        self.assertEqual(self.manager.get("/staff/alpha/agency").status_code, 200)

    def test_simultaneous_overlaps_are_serialized(self):
        def create():
            try:
                return self.assignment()
            except ValueError:
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: create(), range(2)))
        self.assertEqual(sum(value is not None for value in results), 1)

    def test_missing_cancelled_future_and_cross_business_assignments(self):
        self.enable_agency()
        self.post(self.worker, "employee/clock-in", {"site_id": self.site, **self.gps()})
        self.assertIsNone(self.current())
        now = datetime.now(timezone.utc)
        future = self.assignment(start=now+timedelta(hours=2), end=now+timedelta(hours=3))
        self.post(self.worker, "employee/clock-in", {"assignment_id": future, **self.gps()})
        self.assertIsNone(self.current())
        self.post(self.manager, f"assignments/{future}/cancel", {"reason": "Cancelled"})
        self.post(self.worker, "employee/clock-in", {"assignment_id": future, **self.gps()})
        self.assertIsNone(self.current())
        for values in (dict(employee=self.foreign_employee), dict(site=self.foreign_site)):
            with self.assertRaises(ValueError):
                self.assignment(**values)

    def test_origins_require_consent_are_encrypted_and_snapshotted(self):
        self.enable_agency()
        values = {"origin_address": "Private origin", "origin_latitude": "51.6", "origin_longitude": "-0.12", "coordinates_verified": "on"}
        self.post(self.worker, "employee/travel-origin", values)
        self.assertFalse(database.fetch_all("SELECT * FROM staff_travel_origins"))
        self.post(self.worker, "employee/travel-origin", {**values, "consent": "on"})
        stored = database.fetch_one("SELECT * FROM staff_travel_origins WHERE employee_id=%s", (self.employee,))
        self.assertNotIn("Private origin", stored["encrypted_origin"])
        self.assertEqual(agency.origin_for_employee("alpha", self.employee)["address"], "Private origin")
        self.assertIsNone(agency.origin_for_employee("beta", self.employee))
        assignment = self.assignment()
        self.post(self.worker, "employee/clock-in", {"assignment_id": assignment, **self.gps()})
        shift = self.current()
        before = database.fetch_one("SELECT * FROM staff_shift_travel WHERE shift_id=%s", (shift["id"],))
        self.assertGreater(before["distance_km"], 0)
        self.post(self.worker, "employee/travel-origin", {**values, "origin_latitude": "52", "consent": "on"})
        after = database.fetch_one("SELECT * FROM staff_shift_travel WHERE shift_id=%s", (shift["id"],))
        self.assertEqual(before, after)
        self.post(self.worker, "employee/travel-origin", {"disable": "on"})
        self.assertIsNone(agency.origin_for_employee("alpha", self.employee))
        self.assertIsNone(database.fetch_one("SELECT encrypted_origin FROM staff_travel_origins WHERE employee_id=%s", (self.employee,))["encrypted_origin"])

    def test_photo_restriction_and_csrf_authorization(self):
        self.assertEqual(self.worker.post("/staff/alpha/employee/clock-in", data={"site_id": self.site}).status_code, 400)
        response = self.post(self.worker, "assignments", self.assignment_values())
        self.assertIn("/login", response.location)
        self.assertEqual(self.worker.get("/staff/beta/employee").status_code, 302)
        database.execute("UPDATE staff_sites SET photo_required=TRUE WHERE id=%s", (self.site,))
        self.post(self.worker, "employee/clock-in", {"site_id": self.site, **self.gps()})
        self.assertIsNone(self.current())
        self.post(self.worker, "employee/clock-in", {"site_id": self.foreign_site, **self.gps()})
        self.assertIsNone(self.current())

    def test_correction_resets_approval_and_recalculates_draft(self):
        shift_id = self.completed_shift()
        run = self.payroll(shift_id)
        shift = self.row("staff_shifts", shift_id)
        self.post(self.manager, f"shifts/{shift_id}/edit", self.edit_values(shift))
        self.assertEqual(self.row("staff_shifts", shift_id)["approval_status"], "pending")
        self.assertTrue(self.row("staff_payroll_runs", run["id"])["needs_recalculation"])
        self.post(self.manager, f"payroll/{run['id']}/approve")
        self.assertEqual(self.row("staff_payroll_runs", run["id"])["status"], "draft")
        self.post(self.manager, f"payroll/{run['id']}/recalculate")
        self.assertTrue(self.row("staff_payroll_runs", run["id"])["needs_recalculation"])
        self.post(self.manager, f"shifts/{shift_id}/approve")
        self.post(self.manager, f"payroll/{run['id']}/recalculate")
        updated = self.row("staff_payroll_runs", run["id"])
        self.assertFalse(updated["needs_recalculation"])
        self.assertEqual(updated["total_gross_pay"], Decimal("22.50"))
        self.assertTrue(database.fetch_one("SELECT id FROM staff_audit WHERE entity_id=%s AND action='shift_corrected'", (shift_id,)))

    def test_finalized_payroll_preserved_with_adjustment_workflow(self):
        shift_id = self.completed_shift()
        run = self.payroll(shift_id)
        self.post(self.manager, f"payroll/{run['id']}/approve")
        before = self.row("staff_shifts", shift_id)
        self.post(self.manager, f"shifts/{shift_id}/edit", self.edit_values(before))
        self.assertEqual(self.row("staff_shifts", shift_id), before)
        adjustment = database.fetch_one("SELECT * FROM staff_payroll_adjustments WHERE shift_id=%s", (shift_id,))
        self.assertEqual(adjustment["status"], "pending")
        self.post(self.manager, f"payroll-adjustments/{adjustment['id']}/resolve", {"resolution": "External payroll adjustment ADJ-42"})
        self.assertEqual(self.row("staff_payroll_adjustments", adjustment["id"])["status"], "resolved")
        self.assertEqual(self.row("staff_payroll_runs", run["id"])["total_gross_pay"], Decimal("15.00"))

    def test_agency_review_preserves_snapshots_and_excludes_travel_from_pay(self):
        self.enable_agency()
        self.post(self.worker, "employee/travel-origin", {
            "origin_address": "Consented origin", "origin_latitude": "51.6", "origin_longitude": "-0.12",
            "coordinates_verified": "on", "consent": "on", "approximate": "on"})
        assignment = self.assignment()
        self.post(self.worker, "employee/clock-in", {"assignment_id": assignment, **self.gps()})
        shift = self.current()
        self.post(self.worker, "employee/break/start", {"shift_id": shift["id"]})
        br = database.fetch_one("SELECT * FROM staff_breaks WHERE shift_id=%s", (shift["id"],))
        self.post(self.worker, "employee/clock-out", {"shift_id": shift["id"], **self.gps()})
        self.assertIsNotNone(self.row("staff_breaks", br["id"])["ended_at"])
        reassignment = self.assignment_values(site=self.second_site)
        self.post(self.manager, f"assignments/{assignment}/edit", reassignment)
        self.assertEqual(self.row("staff_assignments", assignment)["site_id"], self.second_site)
        snapshot = self.row("staff_shifts", shift["id"])
        self.assertEqual(snapshot["site_id"], self.site)
        self.assertEqual(snapshot["assigned_site_name"], "First site")
        original_travel = database.fetch_one("SELECT * FROM staff_shift_travel WHERE shift_id=%s", (shift["id"],))
        now = datetime.now(timezone.utc)
        values = {"clock_in_at": (now-timedelta(hours=3)).isoformat(),
                  "clock_out_at": (now-timedelta(hours=1)).isoformat(),
                  f"break_{br['id']}_started_at": (now-timedelta(hours=2)).isoformat(),
                  f"break_{br['id']}_ended_at": (now-timedelta(hours=1, minutes=30)).isoformat(),
                  "site_id": self.second_site, "manager_distance_km": "12.34", "adjustment_reason": "Verified times and job"}
        self.post(self.manager, f"shifts/{shift['id']}/edit", values)
        updated = self.row("staff_shifts", shift["id"])
        self.assertEqual(updated["site_id"], self.second_site)
        self.assertEqual(updated["assigned_site_name"], "First site")
        self.assertEqual(updated["clock_in_latitude"], snapshot["clock_in_latitude"])
        travel = database.fetch_one("SELECT * FROM staff_shift_travel WHERE shift_id=%s", (shift["id"],))
        self.assertEqual(travel["distance_km"], original_travel["distance_km"])
        self.assertEqual(travel["manager_distance_km"], Decimal("12.34"))
        self.post(self.manager, f"shifts/{shift['id']}/approve")
        run = self.payroll(shift["id"])
        self.assertEqual(run["total_gross_pay"], Decimal("22.50"))
        self.assertEqual(self.manager.get(f"/staff/alpha?edit_shift={shift['id']}").status_code, 200)
        origin_page = self.manager.get(f"/staff/alpha/agency?origin_employee={self.employee}")
        self.assertIn(b"Consented origin", origin_page.data)
        self.assertEqual(self.manager.get(f"/staff/alpha/agency?origin_employee={self.foreign_employee}").status_code, 404)

    def test_consecutive_jobs_clock_at_their_own_sites(self):
        self.enable_agency()
        first = self.assignment()
        self.post(self.worker, "employee/clock-in", {"assignment_id": first, **self.gps()})
        shift = self.current()
        self.post(self.worker, "employee/clock-out", {"shift_id": shift["id"], **self.gps()})
        boundary = datetime.now(timezone.utc)
        self.post(self.manager, f"assignments/{first}/edit", self.assignment_values(
            start=boundary-timedelta(hours=1), end=boundary))
        second = self.assignment(site=self.second_site, start=boundary, end=boundary+timedelta(hours=1))
        self.post(self.worker, "employee/clock-in", {"assignment_id": second, **self.gps(latitude="52", longitude="-1")})
        self.assertEqual(self.current()["site_id"], self.second_site)
        self.assertEqual(self.current()["assignment_id"], second)
        self.assertNotEqual(self.current()["id"], shift["id"])

    def test_corrections_require_reason_valid_breaks_and_business_ownership(self):
        shift_id = self.completed_shift()
        before = self.row("staff_shifts", shift_id)
        for changes in ({"adjustment_reason": ""}, {"site_id": self.foreign_site}, {"manager_distance_km": "10"}):
            self.post(self.manager, f"shifts/{shift_id}/edit", {**self.edit_values(before), **changes})
            self.assertEqual(self.row("staff_shifts", shift_id), before)
        foreign = self.insert("""INSERT INTO staff_shifts
            (business_id,employee_id,site_id,site_name,clock_in_at,clock_out_at)
            VALUES ('beta',%s,%s,'Private',NOW()-INTERVAL '2 hours',NOW()-INTERVAL '1 hour') RETURNING id""",
            (self.foreign_employee, self.foreign_site))
        foreign_before = self.row("staff_shifts", foreign)
        self.post(self.manager, f"shifts/{foreign}/edit", self.edit_values(before))
        self.post(self.manager, "shifts/approve-selected", {"shift_ids": [foreign]})
        self.assertEqual(self.row("staff_shifts", foreign), foreign_before)
        br = self.insert("""INSERT INTO staff_breaks (business_id,employee_id,shift_id,started_at,ended_at)
            VALUES ('alpha',%s,%s,%s,%s) RETURNING id""",
            (self.employee, shift_id, before["clock_in_at"]+timedelta(minutes=10), before["clock_in_at"]+timedelta(minutes=20)))
        values = {**self.edit_values(before), f"break_{br}_started_at": before["clock_in_at"].isoformat(),
                  f"break_{br}_ended_at": (before["clock_out_at"]+timedelta(hours=2)).isoformat()}
        self.post(self.manager, f"shifts/{shift_id}/edit", values)
        self.assertEqual(self.row("staff_shifts", shift_id), before)

    def test_profile_edit_leave_rejection_cancellation_and_fixed_travel_opt_in(self):
        self.post(self.manager, f"employees/{self.employee}/edit", {
            "full_name": "Alex Updated", "phone": "07001", "email": "alex@example.test", "role": "staff", "hourly_rate": "18.50"})
        self.assertEqual(self.row("staff_employees", self.employee)["hourly_rate"], Decimal("18.50"))
        self.post(self.worker, "employee/leave", {"leave_type": "holiday", "start_date": "2027-03-01", "end_date": "2027-03-02"})
        leave = database.fetch_one("SELECT * FROM staff_leave_requests")
        self.post(self.manager, f"leave/{leave['id']}/reject", {"manager_note": "No cover"})
        self.assertEqual(self.row("staff_leave_requests", leave["id"])["approval_status"], "rejected")
        self.post(self.worker, "employee/leave", {"leave_type": "holiday", "start_date": "2027-04-01", "end_date": "2027-04-02"})
        pending = database.fetch_one("SELECT * FROM staff_leave_requests WHERE approval_status='pending'")
        self.post(self.worker, f"employee/leave/{pending['id']}/cancel")
        self.assertEqual(self.row("staff_leave_requests", pending["id"])["approval_status"], "cancelled")
        self.post(self.manager, "settings/organisation", {"organisation_mode": "fixed", "travel_enabled": "on", "reason": "Opt in"})
        self.post(self.worker, "employee/travel-origin", {"origin_address": "AB1 2CD", "consent": "on"})
        self.post(self.worker, "employee/clock-in", {"site_id": self.site, **self.gps()})
        self.assertIsNotNone(self.current())
        self.assertIsNone(database.fetch_one("SELECT distance_km FROM staff_shift_travel")["distance_km"])
        self.post(self.manager, "settings/organisation", {"organisation_mode": "agency", "reason": "Switch"})
        self.assertEqual(agency.settings("alpha")["organisation_mode"], "fixed")

    def test_schema_drift_is_not_repaired_by_startup(self):
        database.execute("ALTER TABLE staff_shifts DROP COLUMN adjustment_reason")
        with self.assertRaises(database.StaffDatabaseError):
            database.init_staff_database()
        with self.assertRaises(database.StaffDatabaseError):
            database.init_staff_database(migrate=True)
        self.assertIsNone(database.fetch_one("""SELECT column_name FROM information_schema.columns
            WHERE table_schema=current_schema() AND table_name='staff_shifts' AND column_name='adjustment_reason'"""))

    def test_invalid_roster_date_returns_validation_error(self):
        self.assertEqual(self.manager.get("/staff/alpha/agency?week=not-a-date").status_code, 400)
        self.assertEqual(self.manager.get("/staff/alpha/agency?week=9999-12-31").status_code, 400)

    def test_fixed_whatsapp_clocking_and_agency_portal_handoff(self):
        from trimtech.modules.staff import agent

        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
            # Intent classification uses the existing local fallback, never the API.
            reply = agent.handle_message("alpha", "07001", "clock in at First site",
                location={"latitude": 51.5, "longitude": -0.12})
            self.assertIsNotNone(self.current(), reply)
            agent.handle_message("alpha", "07001", "start break")
            self.assertTrue(database.fetch_one("SELECT id FROM staff_breaks WHERE ended_at IS NULL"))
            agent.handle_message("alpha", "07001", "end break")
            self.assertFalse(database.fetch_one("SELECT id FROM staff_breaks WHERE ended_at IS NULL"))
            reply = agent.handle_message("alpha", "07001", "clock out",
                location={"latitude": 51.5, "longitude": -0.12})
            self.assertIsNone(self.current(), reply)
            self.enable_agency()
            self.assignment()
            reply = agent.handle_message("alpha", "07001", "clock in at First site",
                location={"latitude": 51.5, "longitude": -0.12})
            self.assertIn("employee portal", reply)
            self.assertIsNone(self.current())


if __name__ == "__main__":
    unittest.main()
