"""Navigation and dedicated-page tests for the Staff Manager control centre split.

Reuses the disposable-schema fixture from test_staff_agency.py.
"""
import os
import unittest

import test_staff_agency as fixtures


@unittest.skipUnless(os.getenv("STAFF_TEST_DATABASE_URL"), "Set STAFF_TEST_DATABASE_URL for real PostgreSQL integration tests")
class StaffNavigationTests(unittest.TestCase):
    setUp = fixtures.AgencyDatabaseTests.setUp
    cleanup_schema = fixtures.AgencyDatabaseTests.cleanup_schema
    connect = fixtures.AgencyDatabaseTests.connect
    insert = fixtures.AgencyDatabaseTests.insert
    client = fixtures.AgencyDatabaseTests.client
    post = fixtures.AgencyDatabaseTests.post
    row = fixtures.AgencyDatabaseTests.row

    PAGES = ("approvals", "employees", "attendance", "leave", "payroll")

    def test_dedicated_pages_load_for_managers_and_require_login(self):
        anonymous = self.client()
        for page in self.PAGES:
            with self.subTest(page=page):
                response = self.manager.get(f"/staff/alpha/{page}")
                self.assertEqual(response.status_code, 200)
                redirected = anonymous.get(f"/staff/alpha/{page}")
                self.assertEqual(redirected.status_code, 302)
                self.assertIn("/login", redirected.location)

    def test_control_centre_is_concise_and_links_to_every_page(self):
        page = self.manager.get("/staff/alpha")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"TrimTech Staff Manager", page.data)
        self.assertIn(b"Staff control centre", page.data)
        # The control centre links out to every section instead of stacking them.
        for target in ("/staff/alpha/approvals", "/staff/alpha/employees",
                       "/staff/alpha/attendance", "/staff/alpha/leave",
                       "/staff/alpha/payroll", "/staff/alpha/agency"):
            self.assertIn(target.encode(), page.data)
        # The old broken garage-dashboard link must not exist on this page.
        self.assertNotIn(b"/dashboard/alpha", page.data)
        # Full section content (e.g. the employee directory table) has moved off this page.
        self.assertNotIn(b'id="employee-rows"', page.data)
        self.assertNotIn(b'id="bulk-approve"', page.data)

    def test_each_dedicated_page_has_a_back_to_hub_button(self):
        for page in self.PAGES:
            with self.subTest(page=page):
                response = self.manager.get(f"/staff/alpha/{page}")
                self.assertIn("Back to Staff Manager".encode(), response.data)
        agency_page = self.manager.get("/staff/alpha/agency")
        self.assertIn("Back to Staff Manager".encode(), agency_page.data)
        # The control centre itself is the hub: no redundant back button to itself.
        hub = self.manager.get("/staff/alpha")
        self.assertNotIn(b'\xe2\x86\x90 Back to Staff Manager', hub.data)

    def test_employee_profile_and_shift_correction_moved_to_their_pages(self):
        shift = self.row("staff_shifts", self.old_shift)
        profile_page = self.manager.get(f"/staff/alpha/employees?employee={self.employee}")
        self.assertIn(b"Edit employee details", profile_page.data)
        approvals_edit_page = self.manager.get(f"/staff/alpha/approvals?edit_shift={shift['id']}")
        self.assertEqual(approvals_edit_page.status_code, 200)

    def test_work_sites_moved_to_assignments_page(self):
        page = self.manager.get("/staff/alpha/agency")
        self.assertIn(b'id="sites"', page.data)
        self.assertIn(b"First site", page.data)
        self.assertNotIn(b'id="sites"', self.manager.get("/staff/alpha").data)


if __name__ == "__main__":
    unittest.main()
