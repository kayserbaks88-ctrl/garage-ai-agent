"""Staff v2 polish regressions; all delivery mocked, databases synthetic/local only."""
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import test_staff_agency as fixtures
from trimtech.modules.staff import agency, database, notifications


class PolishUnitTests(unittest.TestCase):
    def test_date_controls_dst_overnight_and_same_day_default(self):
        values = dict(start_date="2026-09-30", start_time="23:30", end_date="2026-10-01", end_time="02:00")
        self.assertEqual(agency.assignment_datetime(values, "end") - agency.assignment_datetime(values, "start"), timedelta(hours=2.5))
        values.update(start_time="09:00", end_date="", end_time="17:00")
        self.assertEqual(agency.assignment_datetime(values, "end") - agency.assignment_datetime(values, "start"), timedelta(hours=8))
        for day in ("2026-03-29", "2026-10-25"):
            with self.subTest(day=day), self.assertRaises(ValueError):
                agency.assignment_datetime(dict(start_date=day, start_time="01:30"), "start")
        for offset, hour in (("+01:00", 0), ("+00:00", 1)):
            result = agency.assignment_datetime(dict(start_date="2026-10-25", start_time="01:30", start_offset=offset), "start")
            self.assertEqual(result.hour, hour)
            fields = agency.assignment_form_values(dict(starts_at=result, ends_at=result))
            self.assertEqual(fields["start_offset"], offset)
            self.assertEqual(agency.assignment_datetime(fields, "start"), result)
        for clock, day, offset in (("01:30", "2026-03-29", "+00:00"), ("09:00", "2026-07-01", "+00:00"), ("09:00+03:00", "2026-09-30", "")):
            with self.subTest(clock=clock, day=day), self.assertRaises(ValueError):
                agency.assignment_datetime(dict(start_date=day, start_time=clock, start_offset=offset), "start")

    def test_portal_url_uses_trusted_render_environment_not_request_host(self):
        row = dict(business_id="alpha", action="created", details=dict(employee_name="Alex", site_name="Site", address="Full address", client_reference="REF", starts_at="2026-09-30T09:00:00+01:00", ends_at="2026-09-30T17:00:00+01:00"))
        with patch.dict(os.environ, {"STAFF_PUBLIC_BASE_URL": "", "RENDER_EXTERNAL_URL": "https://staff.example.test"}):
            _, text, html = notifications.message(row)
            self.assertIn("https://staff.example.test/staff/alpha/employee", html)
            self.assertIn("09:00 BST", text)
            self.assertIn("Open Staff Manager", html)
        with patch.dict(os.environ, {"STAFF_PUBLIC_BASE_URL": "http://bad.test", "RENDER_EXTERNAL_URL": "https://good.test"}):
            with self.assertRaises(ValueError):
                notifications.message(row)

    def test_directions_handles_zero_coordinates_and_encodes_address(self):
        self.assertIn("destination=0%2C0", agency.assignment_directions(dict(latitude=0, longitude=0)))
        self.assertIn("destination=1+Test+St+%26+Yard", agency.assignment_directions(dict(address="1 Test St & Yard")))
        self.assertIsNone(agency.assignment_directions({}))


@unittest.skipUnless(os.getenv("STAFF_TEST_DATABASE_URL"), "Requires disposable local PostgreSQL")
class PolishDatabaseTests(unittest.TestCase):
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

    def test_default_email_sends_all_actions_and_logs_without_private_data(self):
        database.execute("UPDATE staff_employees SET email='private@example.test' WHERE business_id='alpha'")
        with patch.dict(os.environ, {"STAFF_PUBLIC_BASE_URL": "", "RENDER_EXTERNAL_URL": "https://production.example.test"}), \
                patch.object(notifications, "send_staff_email", return_value=(True, None, "provider-id")) as send, \
                self.assertLogs(notifications.logger, level="INFO") as logs:
            os.environ.pop("STAFF_ASSIGNMENT_EMAIL_ENABLED", None)
            self.post(self.manager, "assignments", self.assignment_values())
            assignment_id = database.fetch_one("SELECT id FROM staff_assignments")["id"]
            self.post(self.manager, f"assignments/{assignment_id}/edit", self.assignment_values())
            self.post(self.manager, f"assignments/{assignment_id}/edit", self.assignment_values(employee=self.second))
            self.post(self.manager, f"assignments/{assignment_id}/cancel", {"reason": "Changed plan"})
            notices = database.fetch_all("SELECT * FROM staff_assignment_notifications ORDER BY id")
            self.assertEqual([n["action"] for n in notices], ["created", "updated", "reassigned_away", "updated", "cancelled"])
            self.assertTrue(all(n["status"] == "sent" for n in notices))
            notifications.dispatch("alpha", assignment_id)
            self.assertEqual(send.call_count, 5)
        output = "\n".join(logs.output)
        self.assertEqual(output.count("email attempted:"), 5)
        self.assertEqual(output.count("email sent:"), 5)
        self.assertNotIn("private@example.test", output)
        self.assertNotIn("First site", output)

    def test_explicit_disable_is_preserved_and_missing_url_is_clear(self):
        database.execute("UPDATE staff_employees SET email='worker@example.test' WHERE id=%s", (self.employee,))
        with patch.object(notifications, "send_staff_email") as send, self.assertLogs(notifications.logger) as logs:
            self.post(self.manager, "assignments", self.assignment_values())
            send.assert_not_called()
        self.assertIn("email_disabled", "\n".join(logs.output))
        with patch.dict(os.environ, {"STAFF_ASSIGNMENT_EMAIL_ENABLED": "1", "STAFF_PUBLIC_BASE_URL": "", "RENDER_EXTERNAL_URL": ""}), self.assertLogs(notifications.logger) as logs:
            assignment_id = database.fetch_one("SELECT id FROM staff_assignments")["id"]
            self.post(self.manager, f"assignments/{assignment_id}/edit", self.assignment_values())
        self.assertIn("portal_url_not_configured", "\n".join(logs.output))

    def test_provider_failure_and_queue_sql_failure_preserve_assignment(self):
        database.execute("UPDATE staff_employees SET email='worker@example.test' WHERE id=%s", (self.employee,))
        with patch.dict(os.environ, {"STAFF_ASSIGNMENT_EMAIL_ENABLED": "1", "RENDER_EXTERNAL_URL": "https://staff.example.test", "STAFF_PUBLIC_BASE_URL": ""}), \
                patch.object(notifications, "send_staff_email", return_value=(False, "provider_http_429", None)), self.assertLogs(notifications.logger) as logs:
            self.post(self.manager, "assignments", self.assignment_values())
        self.assertIn("email failed:", "\n".join(logs.output))
        self.assertEqual(database.fetch_one("SELECT status FROM staff_assignment_notifications")["status"], "failed")
        assignment_id = database.fetch_one("SELECT id FROM staff_assignments")["id"]
        def broken_queue(cursor, *args):
            cursor.execute("SELECT 1/0")
        with patch.object(notifications, "_queue", side_effect=broken_queue), self.assertLogs(notifications.logger) as logs:
            response = self.post(self.manager, f"assignments/{assignment_id}/cancel", {"reason": "Cancelled"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.row("staff_assignments", assignment_id)["status"], "cancelled")
        self.assertIn("notification_queue_failed", "\n".join(logs.output))

    def test_my_jobs_scope_history_and_clock_rules(self):
        self.enable_agency()
        database.execute("UPDATE staff_sites SET client_reference='MY-REF' WHERE id=%s", (self.site,))
        current = self.assignment()
        now = datetime.now(timezone.utc)
        upcoming = self.assignment(start=now+timedelta(days=1), end=now+timedelta(days=1, hours=1))
        past = self.assignment(start=now-timedelta(days=2), end=now-timedelta(days=2)+timedelta(hours=1))
        other = self.assignment(employee=self.second, site=self.second_site)
        foreign = self.insert("""INSERT INTO staff_assignments (business_id,employee_id,site_id,starts_at,ends_at,created_by)
            VALUES ('beta',%s,%s,NOW(),NOW()+INTERVAL '1 hour','test') RETURNING id""", (self.foreign_employee, self.foreign_site))
        page = self.worker.get("/staff/alpha/employee").get_data(as_text=True)
        self.assertIn("My Jobs", page)
        self.assertLess(page.index("Current job"), page.index("Clock-in status"))
        for job in (current, upcoming): self.assertIn(f'data-job-id="{job}"', page)
        self.assertIn(f'data-history-job-id="{past}"', page)
        for job in (other, foreign): self.assertNotIn(f'data-job-id="{job}"', page)
        self.assertNotIn("Second site", page.split('id="my-jobs-title"')[1].split('id="clock-title"')[0])
        self.assertIn("MY-REF", page)
        self.assertIn("Ready to clock in", page)
        self.assertIn("destination=51.5000000%2C-0.1200000", page)
        self.assertIn("Window ended", page)
        self.post(self.worker, "employee/clock-in", {"assignment_id": other, **self.gps()})
        self.assertIsNone(self.current())
        database.execute("UPDATE staff_sites SET photo_required=TRUE WHERE id=%s", (self.site,))
        page = self.worker.get("/staff/alpha/employee").get_data(as_text=True)
        self.assertNotIn("Ready to clock in", page)
        self.post(self.worker, "employee/clock-in", {"assignment_id": current, **self.gps()})
        self.assertIsNone(self.current())
        database.execute("UPDATE staff_sites SET photo_required=FALSE,active=FALSE WHERE id=%s", (self.site,))
        page = self.worker.get("/staff/alpha/employee").get_data(as_text=True)
        self.assertIn("This site is inactive", page)
        self.assertNotIn("Ready to clock in", page)
        self.post(self.worker, "employee/clock-in", {"assignment_id": current, **self.gps()})
        self.assertIsNone(self.current())
        database.execute("UPDATE staff_sites SET active=TRUE WHERE id=%s", (self.site,))
        self.post(self.worker, "employee/clock-in", {"assignment_id": current, **self.gps()})
        self.assertIsNotNone(self.current())

    def test_manager_date_controls_save_edit_overnight_and_reject_bad_order(self):
        page = self.manager.get("/staff/alpha/agency").get_data(as_text=True)
        for name in ("start_date", "start_time", "end_date", "end_time"):
            self.assertIn(f'name="{name}"', page)
        self.assertNotIn('name="starts_at"', page)
        values = dict(employee_id=self.employee, site_id=self.site, reason="Night job", start_date="2030-06-01", start_time="23:00", end_date="2030-06-02", end_time="02:00")
        self.post(self.manager, "assignments", values)
        job = database.fetch_one("SELECT * FROM staff_assignments")
        self.assertEqual(job["ends_at"]-job["starts_at"], timedelta(hours=3))
        page = self.manager.get(f"/staff/alpha/agency?assignment={job['id']}").get_data(as_text=True)
        self.assertIn('value="2030-06-02"', page)
        self.assertIn('value="23:00:00"', page)
        self.post(self.manager, f"assignments/{job['id']}/edit", {**values, "end_date": "2030-06-01"})
        self.assertEqual(self.row("staff_assignments", job["id"])["ends_at"], job["ends_at"])


if __name__ == "__main__":
    unittest.main()
