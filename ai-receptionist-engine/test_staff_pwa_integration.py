"""Employee PWA/recovery regressions using synthetic, disposable PostgreSQL schemas."""
import os
import unittest
from unittest.mock import patch

import test_staff_agency as fixtures
from trimtech.modules.staff import accounts, database, employee_recovery

OLD_PASSWORD = 'previous employee test passphrase'
NEW_PASSWORD = 'recovered employee test passphrase'
TOKEN = 'A' * 43


@unittest.skipUnless(os.getenv('STAFF_TEST_DATABASE_URL'), 'Requires isolated PostgreSQL')
class EmployeePwaIntegrationTests(unittest.TestCase):
    for name in ('setUp', 'cleanup_schema', 'connect', 'insert', 'client', 'post', 'row', 'gps', 'current'):
        locals()[name] = getattr(fixtures.AgencyDatabaseTests, name)

    def credentials(self):
        database.execute("UPDATE staff_employees SET phone='07700000001',email='alex@example.test' WHERE business_id='alpha' AND id=%s", (self.employee,))
        database.execute("""INSERT INTO so_employee_credentials(employee_id,business_id,password_hash,version)
            VALUES (%s,'alpha',%s,'before-reset')""", (self.employee, accounts.password_hash(OLD_PASSWORD)))
        with self.worker.session_transaction() as state:
            state['_staff_employee_auth'] = {
                **state['_staff_employee_auth'], 'credential_version': 'before-reset'}

    def test_shared_launcher_uses_real_separate_sessions_and_memberships(self):
        self.assertEqual(self.worker.get('/staff/employee/app').location, '/staff/alpha/employee')
        self.assertEqual(self.manager.get('/staff/employee/app').location, '/staff/account')
        both = self.client(employee=self.employee, manager=True)
        response = both.get('/staff/employee/app')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Choose your workspace', response.data)
        self.assertEqual(both.get('/staff/employee/app?role=employee').location, '/staff/alpha/employee')
        self.assertEqual(both.get('/staff/employee/app?role=manager').location, '/staff/account')
        for client in (both, self.manager):
            self.assertEqual(client.get('/staff/beta').status_code,404)
        self.assertEqual(self.worker.get('/staff/alpha').status_code,302)
        anonymous=self.client()
        self.assertEqual(anonymous.get('/staff/employee/app?role=manager',follow_redirects=True).request.path,'/staff/account/login')
        database.execute("UPDATE sm_memberships SET active=FALSE WHERE administrator_id='test-manager' AND business_id='alpha'")
        self.assertEqual(both.get('/staff/alpha').status_code,404)
        self.assertEqual(both.get('/staff/alpha/employee').status_code,200)

    def test_expired_and_inactive_sessions_never_open_a_dashboard(self):
        database.execute("UPDATE sm_sessions SET expires_at=NOW()-INTERVAL '1 minute'")
        self.assertEqual(self.manager.get('/staff/employee/app').status_code,200)
        self.assertEqual(self.manager.get('/staff/alpha').status_code,302)
        with self.worker.session_transaction() as state:
            state['_staff_employee_auth']={**state['_staff_employee_auth'],'issued_at':0}
        self.assertEqual(self.worker.get('/staff/employee/app').status_code,200)
        worker=self.client(employee=self.employee)
        database.execute("UPDATE staff_employees SET status='inactive' WHERE business_id='alpha' AND id=%s",(self.employee,))
        self.assertEqual(worker.get('/staff/employee/app').status_code,200)
        self.assertEqual(worker.get('/staff/alpha/employee').status_code,302)

    def test_recovery_rotates_real_credentials_rejects_replay_and_preserves_tenant_isolation(self):
        self.credentials()
        self.assertEqual(self.worker.get('/staff/alpha/employee/clocking').status_code, 200)
        with patch.object(employee_recovery.secrets, 'token_urlsafe', return_value=TOKEN), \
                patch.object(employee_recovery, 'send_staff_email', return_value=(True, None, 'mock-provider')) as send:
            employee_recovery.issue('alpha', 'alex@example.test', ('07700000001',), 'https://staff.example.test')
        send.assert_called_once()
        self.assertFalse(employee_recovery.consume('beta', TOKEN, NEW_PASSWORD))
        self.assertTrue(employee_recovery.consume('alpha', TOKEN, NEW_PASSWORD))
        self.assertFalse(employee_recovery.consume('alpha', TOKEN, NEW_PASSWORD))
        self.assertEqual(self.worker.get('/staff/alpha/employee/clocking').status_code, 302)
        employee = self.client()
        self.assertEqual(self.post(employee, 'employee/login', {'phone': '07700000001', 'payroll_number': OLD_PASSWORD}).status_code, 401)
        self.assertEqual(self.post(employee, 'employee/login', {'phone': '07700000001', 'payroll_number': NEW_PASSWORD}).status_code, 302)
        self.assertEqual(employee.get('/staff/alpha/employee/clocking').status_code, 200)
        self.assertEqual(employee.get('/staff/beta/employee/clocking').status_code, 302)
        self.assertEqual(employee.get('/staff/alpha').status_code, 302)
        self.assertEqual(self.manager.get('/staff/alpha').status_code, 200)
        self.assertEqual(self.manager.get('/staff/beta').status_code, 404)
        self.assertEqual(self.post(employee, 'employee/logout').status_code, 302)
        self.assertEqual(employee.get('/staff/alpha/employee/clocking').status_code, 302)

    def test_real_employee_clocking_and_existing_dashboard_work_with_pwa_links(self):
        self.assertEqual(self.worker.get('/staff/alpha/employee/clocking').status_code, 200)
        self.assertEqual(self.post(self.worker, 'employee/clock-in', {'site_id': self.site, **self.gps()}).status_code, 302)
        shift = self.current()
        self.assertIsNotNone(shift)
        self.assertEqual(shift['approval_status'], 'pending')
        self.post(self.worker, 'employee/break/start', {'shift_id': shift['id']})
        pause = database.fetch_one("SELECT * FROM staff_breaks WHERE business_id='alpha' AND employee_id=%s AND shift_id=%s", (self.employee, shift['id']))
        self.assertIsNotNone(pause)
        self.post(self.worker, 'employee/break/end', {'shift_id': shift['id'], 'break_id': pause['id']})
        self.assertIsNotNone(self.row('staff_breaks', pause['id'])['ended_at'])
        self.post(self.worker, 'employee/clock-out', {'shift_id': shift['id'], **self.gps()})
        self.assertIsNotNone(self.row('staff_shifts', shift['id'])['clock_out_at'])
        for page in ('hours', 'rota', 'pay', 'leave'):
            response = self.worker.get('/staff/alpha/employee/' + page)
            self.assertEqual(response.status_code, 200)
            self.assertIn(b'/staff/employee/app/manifest.webmanifest', response.data)
            self.assertIn('no-store', response.headers['Cache-Control'])
        self.assertEqual(self.manager.get('/staff/alpha').status_code, 200)
