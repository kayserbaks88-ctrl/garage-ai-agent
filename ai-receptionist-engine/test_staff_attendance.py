"""Attendance evidence tests using disposable PostgreSQL schemas only."""
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import test_staff_operations as fixtures
from trimtech.modules.staff import attendance, attendance_exceptions, database, presence


class AttendanceUnitTests(unittest.TestCase):
    def test_lateness_grace_and_no_schedule(self):
        start = datetime(2026, 10, 5, 9, tzinfo=timezone.utc)
        with patch.dict(os.environ, {"STAFF_LATE_GRACE_MINUTES": "5"}):
            self.assertIsNone(attendance.late_minutes(start, None))
            self.assertIsNone(attendance.late_minutes(start - timedelta(minutes=1), start))
            self.assertIsNone(attendance.late_minutes(start + timedelta(minutes=5), start))
            self.assertEqual(attendance.late_minutes(start + timedelta(minutes=8), start), 8)
            self.assertEqual(attendance.late_minutes(start + timedelta(minutes=5, seconds=1), start), 6)
        with patch.dict(os.environ, {"STAFF_LATE_GRACE_MINUTES": "10"}):
            self.assertIsNone(attendance.late_minutes(start + timedelta(minutes=8), start))
        with patch.dict(os.environ, {"STAFF_LATE_GRACE_MINUTES": "invalid"}):
            self.assertEqual(attendance.grace_minutes(), 5)


@unittest.skipUnless(os.getenv("STAFF_TEST_DATABASE_URL"), "Requires disposable local PostgreSQL")
class AttendanceDatabaseTests(unittest.TestCase):
    for _name in ("setUp", "cleanup_schema", "connect", "insert", "client", "post", "row",
                  "enable_agency", "assignment", "assignment_values", "gps", "current", "payroll",
                  "open_shift", "sample", "events"):
        locals()[_name] = getattr(fixtures.OperationsDatabaseTests, _name)

    def test_presence_timeline_stale_return_and_pay_unchanged(self):
        shift_id = self.open_shift(agency_mode=True)
        before = self.row("staff_shifts", shift_id)
        now = datetime.now(timezone.utc)
        self.sample(shift_id, now)
        for seconds in (30, 60, 90, 120):
            self.sample(shift_id, now + timedelta(seconds=seconds), latitude="51.51")
        with patch.object(presence, "utcnow", return_value=now + timedelta(seconds=241)):
            state = presence.overview("alpha")[shift_id]
        self.assertEqual(state["label"], "Location unavailable/stale")
        self.assertIsNotNone(state["last_confirmed_at"])
        self.sample(shift_id, now + timedelta(seconds=250))
        with patch.object(presence, "utcnow", return_value=now + timedelta(seconds=251)):
            self.assertEqual(presence.overview("alpha")[shift_id]["label"], "On site")
        rows = [{"id": shift_id}]
        attendance.enrich("alpha", rows)
        labels = [e["label"] for e in rows[0]["timeline"]]
        self.assertEqual(labels.count("Left site"), 1)
        self.assertEqual(labels.count("Returned"), 1)
        self.assertIn("Location unavailable/stale", labels)
        self.assertEqual(before, self.row("staff_shifts", shift_id))
        foreign = [{"id": shift_id}]
        attendance.enrich("beta", foreign)
        self.assertEqual(foreign, [{"id": shift_id}])

    def test_uncertain_samples_do_not_refresh_confirmed_location(self):
        shift_id = self.open_shift()
        now = datetime.now(timezone.utc)
        self.sample(shift_id, now)
        for seconds in (30, 60, 90, 121, 150):
            with patch.object(presence, "distance_metres", return_value=255):
                self.sample(shift_id, now + timedelta(seconds=seconds), accuracy="10")
        with patch.object(presence, "utcnow", return_value=now + timedelta(seconds=151)):
            state = presence.overview("alpha")[shift_id]
        self.assertEqual(state["status"], "location_stale")
        self.assertEqual(state["last_confirmed_at"], now.isoformat())
        rows = [{"id": shift_id}]
        attendance.enrich("alpha", rows)
        self.assertNotIn("Left site", [e["label"] for e in rows[0]["timeline"]])
        self.sample(shift_id, now + timedelta(seconds=180))
        attendance.enrich("alpha", rows)
        labels = [e["label"] for e in rows[0]["timeline"]]
        self.assertNotIn("Returned", labels)
        self.assertIn("On site confirmed", labels)

    def test_fixed_assignment_late_on_attendance_and_approval(self):
        now = datetime.now(timezone.utc)
        assignment_id = self.assignment(start=now-timedelta(minutes=8), end=now+timedelta(hours=1))
        shift_id = self.open_shift()
        # Use exact instants so setup latency does not affect minute rounding.
        database.execute("UPDATE staff_shifts SET clock_in_at=%s WHERE id=%s", (now, shift_id))
        old_key = f"assignment:{assignment_id}:late:{now.isoformat()}"
        database.execute("""INSERT INTO staff_attendance_reviews(business_id,event_key,note,reviewed_by)
            VALUES ('alpha',%s,'Reviewed with employee','manager')""", (old_key,))
        late_events = [event for event in attendance_exceptions.collect("alpha") if event["kind"] == "Late clock-in"]
        self.assertEqual(late_events[0]["review"]["note"], "Reviewed with employee")
        page = self.manager.get("/staff/alpha/attendance")
        self.assertIn(b"Late by 8 minutes", page.data)
        self.assertIn(b"Attendance timeline", page.data)
        database.execute("UPDATE staff_shifts SET clock_out_at=%s WHERE id=%s", (now+timedelta(hours=1), shift_id))
        self.assertIn(b"Late by 8 minutes", self.manager.get("/staff/alpha/approvals").data)
        self.assertIn(b"Clocked out", self.manager.get(f"/staff/alpha/approvals?edit_shift={shift_id}").data)
        with patch.dict(os.environ, {"STAFF_LATE_GRACE_MINUTES": "10"}):
            self.assertNotIn(b"Late by 8 minutes", self.manager.get("/staff/alpha/approvals").data)

    def test_agency_snapshot_and_unscheduled_shift(self):
        shift_id = self.open_shift(agency_mode=True)
        shift = self.row("staff_shifts", shift_id)
        database.execute("UPDATE staff_shifts SET clock_in_at=planned_start_at+INTERVAL '8 minutes' WHERE id=%s", (shift_id,))
        rows = [{"id": shift_id}, {"id": self.old_shift}]
        attendance.enrich("alpha", rows)
        self.assertEqual(rows[0]["late_minutes"], 8)
        self.assertIsNone(rows[1]["late_minutes"])
        database.execute("UPDATE staff_assignments SET starts_at=starts_at-INTERVAL '1 hour' WHERE id=%s", (shift["assignment_id"],))
        attendance.enrich("alpha", rows)
        self.assertEqual(rows[0]["late_minutes"], 8)

    def test_confirmed_departure_after_stale_gap(self):
        shift_id = self.open_shift()
        now = datetime.now(timezone.utc)
        self.sample(shift_id, now)
        for seconds in (180, 210, 240):
            response = self.sample(shift_id, now + timedelta(seconds=seconds), latitude="51.51")
        self.assertEqual(response.json["status"], "left_site")
        self.assertEqual(self.sample(shift_id, now + timedelta(seconds=270)).json["status"], "returned")

    def test_fixed_ambiguous_schedule_is_not_marked_late(self):
        shift_id = self.open_shift()
        now = datetime.now(timezone.utc)
        self.assignment(start=now-timedelta(minutes=15), end=now+timedelta(minutes=15))
        self.assignment(start=now+timedelta(minutes=15), end=now+timedelta(hours=1))
        database.execute("UPDATE staff_shifts SET clock_out_at=%s WHERE id=%s", (now+timedelta(hours=1), shift_id))
        rows = [{"id": shift_id}]
        attendance.enrich("alpha", rows)
        self.assertIsNone(rows[0]["late_minutes"])
