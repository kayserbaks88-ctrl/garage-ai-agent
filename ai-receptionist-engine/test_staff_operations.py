"""Presence/notification tests. Network delivery is always mocked."""
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import test_staff_agency as fixtures
from integrations.email_helper import send_staff_email
from trimtech.modules.staff import database, migrations, notifications, operations_migration, presence


class OperationsUnitTests(unittest.TestCase):
    def test_drift_requires_grace_and_repeated_confirmations(self):
        now = datetime.now(timezone.utc)
        state = dict(radius_metres=100, status="on_site", departed=False, outside_count=0, outside_since=None)
        config = dict(grace_seconds=60, confirmations=3)
        state, _ = presence.advance(state, 105, 10, now, config)
        self.assertEqual(state["outside_count"], 0)
        for offset in (0, 30):
            state, _ = presence.advance(state, 200, 10, now+timedelta(seconds=offset), config)
            self.assertEqual(state["status"], "on_site")
        state, _ = presence.advance(state, 200, 10, now+timedelta(seconds=60), config)
        self.assertEqual(state["status"], "left_site")
        state, _ = presence.advance(state, 0, 10, now+timedelta(seconds=90), config)
        self.assertEqual(state["status"], "returned")

    def test_email_content_uk_times_html_escaping_and_safe_portal(self):
        row = {"business_id": "alpha", "action": "updated", "details": {
            "employee_name": "Alex <script>", "site_name": "Site & job", "address": "1 Test St, London SW1A 1AA",
            "client_reference": "REF-1", "starts_at": "2026-10-25T00:30:00+00:00", "ends_at": "2026-10-25T02:30:00+00:00"}}
        with patch.dict(os.environ, {"STAFF_PUBLIC_BASE_URL": "https://staging.example.test"}):
            subject, text, html = notifications.message(row)
        self.assertIn("01:30 BST", text)
        self.assertIn("02:30 GMT", text)
        self.assertIn("REF-1", text)
        self.assertIn("SW1A 1AA", text)
        self.assertIn("https://staging.example.test/staff/alpha/employee", html)
        self.assertIn("Open Staff Manager", html)
        self.assertNotIn("<script>", html)
        with patch.dict(os.environ, {"STAFF_PUBLIC_BASE_URL": "http://untrusted.test"}):
            with self.assertRaises(ValueError): notifications.message(row)

    def test_email_transport_sanitizes_errors_and_uses_idempotency(self):
        with patch.dict(os.environ, {"RESEND_API_KEY": "fake-key", "RESEND_FROM_EMAIL": "sender@example.test"}), \
                patch("integrations.email_helper.requests.post") as post:
            post.return_value.status_code=429
            self.assertEqual(send_staff_email("test@example.test", "Subject", "Text", "HTML", "event-1"),
                             (False,"provider_http_429",None))
            self.assertEqual(post.call_args.kwargs["headers"]["Idempotency-Key"], "event-1")
            post.return_value.status_code=200
            post.return_value.json.return_value={"id":"mail-id"}
            self.assertEqual(send_staff_email("test@example.test", "Subject", "Text", "HTML", "event-1"),
                             (True,None,"mail-id"))


@unittest.skipUnless(os.getenv("STAFF_TEST_DATABASE_URL"), "Requires disposable local PostgreSQL")
class OperationsDatabaseTests(unittest.TestCase):
    # Reuse fixture helpers, without inheriting and duplicating its test methods.
    setUp = fixtures.AgencyDatabaseTests.setUp
    cleanup_schema = fixtures.AgencyDatabaseTests.cleanup_schema
    connect = fixtures.AgencyDatabaseTests.connect
    insert = fixtures.AgencyDatabaseTests.insert
    client = fixtures.AgencyDatabaseTests.client
    post = fixtures.AgencyDatabaseTests.post
    row = fixtures.AgencyDatabaseTests.row
    enable_agency = fixtures.AgencyDatabaseTests.enable_agency
    assignment = fixtures.AgencyDatabaseTests.assignment
    assignment_values = fixtures.AgencyDatabaseTests.assignment_values
    gps = fixtures.AgencyDatabaseTests.gps
    current = fixtures.AgencyDatabaseTests.current
    payroll = fixtures.AgencyDatabaseTests.payroll

    def emails(self):
        return database.fetch_all("SELECT * FROM staff_assignment_notifications ORDER BY id")

    def events(self, shift_id):
        return database.fetch_all("SELECT * FROM staff_presence_events WHERE shift_id=%s ORDER BY id", (shift_id,))

    def open_shift(self, agency_mode=False):
        values = {"site_id": self.site, **self.gps()}
        if agency_mode:
            self.enable_agency()
            values["assignment_id"] = self.assignment()
        self.post(self.worker, "employee/clock-in", values)
        return self.current()["id"]

    def sample(self, shift_id, now, **values):
        with patch.object(presence, "utcnow", return_value=now):
            return self.post(self.worker, "employee/presence", {"shift_id": shift_id,
                **self.gps(captured_at=now.isoformat()), **values})

    def test_assignment_emails_created_updated_reassigned_cancelled(self):
        database.execute("UPDATE staff_employees SET email='worker@example.test' WHERE business_id='alpha'")
        with patch.dict(os.environ, {"STAFF_ASSIGNMENT_EMAIL_ENABLED":"1", "STAFF_PUBLIC_BASE_URL":"https://staging.example.test"}), \
                patch.object(notifications, "send_staff_email", return_value=(True,None,"provider-id")) as send:
            self.post(self.manager, "assignments", self.assignment_values())
            assignment_id = self.emails()[0]["assignment_id"]
            self.post(self.manager, f"assignments/{assignment_id}/edit", self.assignment_values())
            self.post(self.manager, f"assignments/{assignment_id}/edit", self.assignment_values(employee=self.second))
            self.post(self.manager, f"assignments/{assignment_id}/cancel", {"reason":"Cancelled"})
            rows = self.emails()
            self.assertEqual([r["action"] for r in rows], ["created","updated","reassigned_away","updated","cancelled"])
            self.assertTrue(all(r["status"] == "sent" and r["provider_id"] == "provider-id" for r in rows))
            self.assertEqual(rows[2]["employee_id"], self.employee)
            self.assertEqual(rows[3]["employee_id"], self.second)
            self.assertEqual(send.call_count, 5)
            notifications.dispatch("alpha",assignment_id)
            self.assertEqual(send.call_count, 5)

    def test_email_failure_does_not_rollback_assignment_and_failed_actions_do_not_queue(self):
        database.execute("UPDATE staff_employees SET email='worker@example.test' WHERE id=%s", (self.employee,))
        with patch.dict(os.environ, {"STAFF_ASSIGNMENT_EMAIL_ENABLED":"1", "STAFF_PUBLIC_BASE_URL":"https://staging.example.test"}), \
                patch.object(notifications, "send_staff_email", side_effect=RuntimeError("unavailable")):
            response=self.post(self.manager,"assignments", self.assignment_values())
        self.assertEqual(response.status_code,302)
        self.assertEqual(self.emails()[0]["status"],"failed")
        self.assertEqual(self.row("staff_assignments",self.emails()[0]["assignment_id"])["status"],"scheduled")
        self.post(self.manager,"assignments",self.assignment_values())  # Overlap is rejected.
        self.assertEqual(len(self.emails()),1)

    def test_missing_employee_email_is_audited(self):
        with patch.dict(os.environ,{"STAFF_ASSIGNMENT_EMAIL_ENABLED":"1"}):
            self.post(self.manager,"assignments", self.assignment_values())
        self.assertEqual(self.emails()[0]["error_code"],"employee_email_missing_or_invalid")

    def test_presence_left_returned_stale_and_snapshot_target(self):
        shift_id=self.open_shift(agency_mode=True)
        now=datetime.now(timezone.utc)
        self.assertEqual(self.sample(shift_id,now).json["status"],"on_site")
        # Editing the site must not move this shift's geofence.
        database.execute("UPDATE staff_sites SET latitude=0,longitude=0 WHERE id=%s",(self.site,))
        for offset in (30,60):
            self.assertEqual(self.sample(shift_id,now+timedelta(seconds=offset),latitude="51.51").json["status"],"on_site")
        self.assertEqual(self.sample(shift_id,now+timedelta(seconds=90),latitude="51.51").json["status"],"left_site")
        self.assertEqual(self.sample(shift_id,now+timedelta(seconds=120)).json["status"],"returned")
        with patch.object(presence,"utcnow",return_value=now+timedelta(seconds=241)):
            result=presence.overview("alpha")
            presence.overview("alpha")
        self.assertEqual(result[shift_id]["status"],"location_stale")
        self.assertEqual(self.events(shift_id)[-1]["reason"],"updates_stopped")
        self.assertEqual(sum(e["reason"]=="updates_stopped" for e in self.events(shift_id)),1)
        self.assertEqual(self.sample(shift_id,now+timedelta(seconds=250)).json["status"],"on_site")

    def test_presence_rejects_bad_replay_cross_employee_and_closed_shift(self):
        shift_id=self.open_shift()
        now=datetime.now(timezone.utc)
        self.assertEqual(self.sample(shift_id,now).status_code,200)
        before=self.events(shift_id)
        for values in ({"accuracy":"1000"},{"latitude":"NaN"},{"captured_at":(now-timedelta(minutes=5)).isoformat()}):
            self.assertEqual(self.sample(shift_id,now+timedelta(seconds=30),**values).status_code,400)
        self.assertEqual(self.sample(shift_id,now+timedelta(seconds=30),captured_at=now.isoformat()).status_code,400)
        self.assertEqual(self.post(self.worker2,"employee/presence",{"shift_id":shift_id,**self.gps()}).status_code,400)
        self.assertEqual(self.worker.post("/staff/alpha/employee/presence",data={"shift_id":shift_id}).status_code,400)
        self.assertEqual(self.events(shift_id),before)
        self.post(self.worker,"employee/clock-out",{"shift_id":shift_id,**self.gps()})
        self.assertEqual(self.sample(shift_id,now+timedelta(seconds=60)).status_code,400)
        self.assertEqual(self.events(shift_id),before)
        self.post(self.manager,f"shifts/{shift_id}/approve")
        self.payroll(shift_id)
        self.assertEqual(self.events(shift_id),before)

    def test_manager_dashboard_and_employee_portal_render_presence(self):
        shift_id=self.open_shift()
        self.assertIn(b"data-presence-portal",self.worker.get("/staff/alpha/employee").data)
        self.assertEqual(self.manager.get("/staff/alpha").status_code,200)
        page=self.manager.get("/staff/alpha/attendance")
        self.assertEqual(page.status_code,200)
        self.assertIn(b"data-presence-shift",page.data)
        self.assertIn(str(shift_id), self.post(self.manager,"presence/status").json["shifts"])
        self.assertEqual(self.post(self.worker,"presence/status").status_code,401)

    def restore_v1(self):
        database.execute("DROP TABLE staff_presence_events,staff_shift_presence,staff_assignment_notifications")
        database.execute("DELETE FROM staff_schema_migrations WHERE version=%s",(operations_migration.VERSION,))

    def test_upgrade_preserves_legacy_migration_and_records(self):
        self.restore_v1()
        before=database.fetch_one("SELECT * FROM staff_schema_migrations WHERE version=%s",(migrations.VERSION,))
        shift=self.row("staff_shifts",self.old_shift)
        with self.assertRaises(database.StaffDatabaseError): database.init_staff_database()
        database.init_staff_database(migrate=True)
        database.init_staff_database(migrate=True)
        self.assertEqual(database.fetch_one("SELECT * FROM staff_schema_migrations WHERE version=%s",(migrations.VERSION,)),before)
        self.assertEqual(self.row("staff_shifts",self.old_shift),shift)
        database.init_staff_database()

    def test_upgrade_rejects_v1_drift_without_partial_changes(self):
        self.restore_v1()
        database.execute("ALTER TABLE staff_sites ADD COLUMN unexpected TEXT")
        with self.assertRaises(database.StaffDatabaseError): database.init_staff_database(migrate=True)
        self.assertIsNone(database.fetch_one("SELECT to_regclass('staff_shift_presence') AS name")["name"])
