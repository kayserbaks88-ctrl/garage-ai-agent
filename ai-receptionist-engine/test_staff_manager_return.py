"""Explicit standalone manager navigation, including populated detail screens."""
import os
import unittest
from unittest.mock import patch

import test_staff_payslip_rota as fixtures
from trimtech.modules.staff import database, onboarding


@unittest.skipUnless(os.getenv('STAFF_TEST_DATABASE_URL'), 'Requires disposable PostgreSQL')
class ManagerReturnTests(unittest.TestCase):
    for name in ['setUp', 'cleanup_schema', 'connect', 'insert', 'client', 'post', 'row',
                 'profile', 'shift', 'generate', 'assignment', 'assignment_values', 'payroll']:
        locals()[name] = getattr(fixtures.PayslipRotaTests, name)

    def test_all_manager_sections_and_populated_details_have_direct_dashboard_link(self):
        run, slip = self.payroll()
        shift = database.fetch_one("SELECT id FROM staff_shifts WHERE business_id='alpha' AND employee_id=%s AND clock_out_at IS NOT NULL LIMIT 1", (self.employee,))
        with database.transaction() as connection:
            with connection.cursor() as cursor:
                onboarding.begin(cursor, 'alpha', 'test-manager')
                onboarding.activate(cursor, 'test-manager')
        paths = ['employees', f'employees?employee={self.employee}', 'attendance',
                 'approvals', f"approvals?edit_shift={shift['id']}", 'leave',
                 'payroll', f"payroll/{run['id']}", f"payroll/payslips/{slip['id']}/view",
                 'agency', 'agency?week=2026-04-27', 'settings', 'setup', 'setup/sites',
                 'employees/onboarding', 'subscription']
        for path in paths:
            with self.subTest(path=path):
                response = self.manager.get('/staff/alpha/' + path)
                self.assertEqual(response.status_code, 200, response.data[:100])
                html = response.text
                self.assertIn('class="manager-dashboard-return" href="/staff/alpha"', html)
                self.assertIn('Back to Dashboard</a>', html)
                self.assertLess(html.index('class="manager-dashboard-return"'), html.index('<details class="manager-pwa-nav'))
                self.assertIn('Switch Workspace', html)
                self.assertIn('no-store', response.headers['Cache-Control'])

    def test_unused_checklist_is_not_loaded_on_employee_directory(self):
        with database.transaction() as connection:
            with connection.cursor() as cursor:
                onboarding.begin(cursor, 'alpha', 'test-manager')
                onboarding.activate(cursor, 'test-manager')
        with patch.object(onboarding, 'checklist', side_effect=AssertionError('Unused checklist loaded')):
            response = self.manager.get('/staff/alpha/employees')
        self.assertEqual(response.status_code, 200)

    def test_employee_navigation_and_tenant_bound_return_are_preserved(self):
        response = self.worker.get('/staff/alpha/employee/clocking')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'employee-mobile-nav', response.data)
        self.assertNotIn(b'class="manager-dashboard-return"', response.data)
        self.assertEqual(self.manager.get('/staff/beta/payroll').status_code, 404)
