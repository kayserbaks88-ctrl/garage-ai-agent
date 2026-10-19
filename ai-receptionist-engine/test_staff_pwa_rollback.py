"""Compatibility regressions; PostgreSQL tests require an isolated test URL.

The external validation runner rejects every database except its own loopback
database and blocks outbound Python network calls. No production fixture data.
"""
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from flask import Flask
import test_staff_agency as fixtures
from trimtech.modules.staff import accounts, database, manager_auth, onboarding, routes as staff

ROOT = Path(__file__).parent


class CompatibilityPublicTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__, template_folder=str(ROOT / 'templates'), static_folder=str(ROOT / 'static'))
        self.app.secret_key = 'isolated-rollback-unit-test'
        self.app.testing = True
        self.app.register_blueprint(staff.staff_blueprint)
        self.client = self.app.test_client()

    def test_public_endpoints_need_no_database_and_are_not_cached(self):
        with patch.object(staff, '_current_employee', side_effect=AssertionError('employee database used')), \
                patch.object(manager_auth, 'identity', side_effect=AssertionError('manager database used')):
            for path in ('/staff/employee/app', '/staff/employee/app/install',
                         '/staff/employee/app/offline', '/staff/employee-sw.js',
                         '/staff/employee/app/manifest.webmanifest'):
                with self.subTest(path=path):
                    response = self.client.get(path)
                    self.assertEqual(response.status_code, 200)
                    self.assertIn('no-store', response.headers['Cache-Control'])

    def test_manifest_identity_scope_branding_and_icon_files(self):
        manifest = json.loads(self.client.get('/staff/employee/app/manifest.webmanifest').data)
        for key, value in dict(id='/staff/employee/app', start_url='/staff/employee/app',
                               scope='/staff/', display='standalone', name='Staff Manager',
                               short_name='Staff Manager').items():
            self.assertEqual(manifest[key], value)
        for icon in manifest['icons']:
            with self.client.get(icon['src']) as response:
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.data[:8], b'\x89PNG\r\n\x1a\n')
        page = self.client.get('/staff/employee/app').data
        self.assertIn(b'crossorigin="use-credentials"', page)
        self.assertIn(b'apple-touch-icon.png', page)

    def test_logged_out_role_selection_uses_existing_login_routes(self):
        page = self.client.get('/staff/employee/app')
        self.assertIn(b'Manager sign in', page.data)
        self.assertIn(b'Employee sign in', page.data)
        self.assertIn(b'Install / app help', page.data)
        manager = self.client.get('/staff/employee/app?role=manager', follow_redirects=True)
        self.assertEqual(manager.request.path, '/staff/account/login')
        response = self.client.get('/staff/employee/app?role=employee&workplace=Example-Workplace')
        self.assertEqual(response.location, '/staff/example-workplace/employee/login')

    def test_invalid_role_and_workplace_never_become_external_redirects(self):
        self.assertEqual(self.client.get('/staff/employee/app?role=owner').status_code, 400)
        for workplace in ('https://evil.example', '//evil.example', '../account', 'a/b', 'a' * 81, '<script>'):
            response = self.client.get('/staff/employee/app', query_string={'workplace': workplace, 'next': 'https://evil.example'})
            self.assertEqual(response.status_code, 200)
            self.assertNotIn('Location', response.headers)
            self.assertIn(b'Enter the workplace code', response.data)

    def test_launcher_does_not_accept_submissions_or_set_authenticated_state(self):
        self.assertEqual(self.client.post('/staff/employee/app', data={'role': 'manager'}).status_code, 405)
        self.client.get('/staff/employee/app?role=employee')
        with self.client.session_transaction() as state:
            self.assertNotIn(staff._EMPLOYEE_SESSION_KEY, state)
        self.assertIsNone(self.client.get_cookie(manager_auth.COOKIE))

    def test_worker_is_javascript_and_has_only_lifecycle_handlers(self):
        response = self.client.get('/staff/employee-sw.js')
        self.assertEqual(response.mimetype, 'application/javascript')
        self.assertEqual(response.headers['X-Content-Type-Options'], 'nosniff')
        source = response.get_data(as_text=True)
        self.assertIn("addEventListener('install'", source)
        self.assertIn("addEventListener('activate'", source)
        for forbidden in ('fetch(', "addEventListener('fetch'", 'respondWith', 'caches.', 'indexedDB',
                          'localStorage', 'registerSync', 'unregister(', '.navigate(', 'clearSiteData'):
            self.assertNotIn(forbidden, source)

    def test_public_offline_page_contains_no_forms_and_returns_to_stable_entry(self):
        page = self.client.get('/staff/employee/app/offline').data
        self.assertNotIn(b'<form', page)
        self.assertIn(b'/staff/employee/app', page)
        self.assertIn(b'Reconnect', page)

    def test_compatibility_page_does_not_depend_on_full_pwa_assets(self):
        page = self.client.get('/staff/employee/app').get_data(as_text=True)
        for asset in ('staff_pwa_head', 'staff_pwa.js', 'staff_pwa.css', 'target="_blank"'):
            self.assertNotIn(asset, page)
        self.assertIn("register('/staff/employee-sw.js'", page)
        self.assertIn("scope: '/staff/'", page)
        self.assertIn('if (!navigator.onLine)', page)
        self.assertIn('event.preventDefault()', page)


@unittest.skipUnless(os.getenv('STAFF_TEST_DATABASE_URL'), 'Requires isolated PostgreSQL')
class CompatibilityDatabaseTests(unittest.TestCase):
    for name in ('setUp', 'cleanup_schema', 'connect', 'insert', 'client', 'post', 'row', 'gps', 'current'):
        locals()[name] = getattr(fixtures.AgencyDatabaseTests, name)

    def test_employee_only_launch_reaches_existing_guarded_dashboard(self):
        response = self.worker.get('/staff/employee/app', follow_redirects=True)
        self.assertEqual(response.request.path, '/staff/alpha/employee')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.worker.get('/staff/alpha').status_code, 302)

    def test_manager_only_launch_reaches_existing_workspace_selector(self):
        response = self.manager.get('/staff/employee/app', follow_redirects=True)
        self.assertEqual(response.request.path, '/staff/account')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.manager.get('/staff/alpha/employee').status_code, 302)

    def test_simultaneous_sessions_choose_role_without_changing_either(self):
        both = self.client(employee=self.employee, manager=True)
        cookie = both.get_cookie(manager_auth.COOKIE).value
        with both.session_transaction() as state:
            auth = dict(state[staff._EMPLOYEE_SESSION_KEY])
        self.assertIn(b'Choose your workspace', both.get('/staff/employee/app').data)
        self.assertEqual(both.get('/staff/employee/app?role=employee').location, '/staff/alpha/employee')
        self.assertEqual(both.get('/staff/employee/app?role=manager').location, '/staff/account')
        self.assertEqual(both.get_cookie(manager_auth.COOKIE).value, cookie)
        with both.session_transaction() as state:
            self.assertEqual(state[staff._EMPLOYEE_SESSION_KEY], auth)

    def test_role_or_workplace_choice_cannot_grant_tenant_access(self):
        both = self.client(employee=self.employee, manager=True)
        both.get('/staff/employee/app?role=employee&workplace=beta')
        self.assertEqual(both.get('/staff/beta/employee').status_code, 302)
        self.assertEqual(both.get('/staff/beta').status_code, 404)
        for path in ('/staff/alpha', '/staff/beta'):
            self.assertEqual(self.worker.get(path).status_code, 302)
        self.assertEqual(self.client().get('/staff/employee/app?role=manager', follow_redirects=True).request.path,
                         '/staff/account/login')

    def test_signed_session_cannot_pair_foreign_employee_with_local_business(self):
        forged = self.client(employee=self.foreign_employee, business='alpha')
        self.assertIn(b'Employee sign in', forged.get('/staff/employee/app').data)
        self.assertEqual(forged.get('/staff/alpha/employee').status_code, 302)

    def test_revoked_manager_membership_is_enforced_by_destination(self):
        database.execute("UPDATE sm_memberships SET active=FALSE WHERE administrator_id='test-manager' AND business_id='alpha'")
        self.assertEqual(self.manager.get('/staff/employee/app').location, '/staff/account')
        self.assertEqual(self.manager.get('/staff/alpha').status_code, 404)
        self.assertNotIn(b'Alpha</', self.manager.get('/staff/account').data)
        self.assertEqual(self.worker.get('/staff/alpha/employee').status_code, 200)

    def test_expired_manager_and_employee_sessions_return_to_sign_in(self):
        database.execute("UPDATE sm_sessions SET expires_at=NOW()-INTERVAL '1 minute'")
        self.assertIn(b'Manager sign in', self.manager.get('/staff/employee/app').data)
        with self.worker.session_transaction() as state:
            state[staff._EMPLOYEE_SESSION_KEY] = {**state[staff._EMPLOYEE_SESSION_KEY], 'issued_at': 0}
        self.assertIn(b'Employee sign in', self.worker.get('/staff/employee/app').data)

    def test_inactive_employee_and_deactivated_business_cannot_launch_employee_dashboard(self):
        database.execute("UPDATE staff_employees SET status='inactive' WHERE business_id='alpha' AND id=%s", (self.employee,))
        self.assertIn(b'Employee sign in', self.worker.get('/staff/employee/app').data)
        active_worker = self.client(employee=self.second)
        database.execute("UPDATE sm_businesses SET active=FALSE WHERE id='alpha'")
        self.assertIn(b'Employee sign in', active_worker.get('/staff/employee/app').data)
        self.assertEqual(self.manager.get('/staff/alpha').status_code, 404)

    def test_credentials_rotation_invalidates_existing_employee_session(self):
        database.execute("INSERT INTO so_employee_credentials(employee_id,business_id,password_hash,version) VALUES (%s,'alpha',%s,'new-version')",
                         (self.employee, accounts.password_hash('synthetic changed credential')))
        self.assertIn(b'Employee sign in', self.worker.get('/staff/employee/app').data)

    def test_database_failure_is_closed_not_authorized(self):
        with patch.object(staff, '_current_employee', side_effect=database.StaffDatabaseError('test only')):
            self.assertEqual(self.worker.get('/staff/employee/app').status_code, 503)
        with patch.object(manager_auth, 'identity', side_effect=database.StaffDatabaseError('test only')):
            self.assertEqual(self.manager.get('/staff/employee/app').status_code, 503)

    def test_trial_dates_unchanged_and_expired_trial_writes_stay_blocked(self):
        with database.transaction() as connection:
            with connection.cursor() as cursor:
                onboarding.begin(cursor, 'alpha', 'test-manager')
                onboarding.activate(cursor, 'test-manager')
        database.execute("INSERT INTO so_employee_credentials(employee_id,business_id,password_hash,version) VALUES (%s,'alpha',%s,'v1')",
                         (self.employee, accounts.password_hash('synthetic trial credential')))
        with self.worker.session_transaction() as state:
            state[staff._EMPLOYEE_SESSION_KEY] = {**state[staff._EMPLOYEE_SESSION_KEY], 'credential_version': 'v1'}
        before = onboarding.status('alpha')
        self.assertEqual(self.worker.get('/staff/employee/app', follow_redirects=True).status_code, 200)
        self.assertEqual(self.manager.get('/staff/employee/app', follow_redirects=True).status_code, 200)
        self.assertEqual(onboarding.status('alpha'), before)
        database.execute("UPDATE so_trials SET starts_at=NOW()-INTERVAL '337 hours',ends_at=NOW()-INTERVAL '1 hour' WHERE business_id='alpha'")
        self.assertEqual(self.post(self.worker, 'employee/clock-in', {'site_id': self.site, **self.gps()}).status_code, 402)
        self.assertEqual(self.post(self.manager, 'sites', {'name': 'Not created'}).status_code, 402)
        self.assertIsNone(self.current())
        self.assertEqual(self.worker.get('/staff/employee/app', follow_redirects=True).status_code, 200)

    def test_login_logout_and_csrf_remain_separate(self):
        password = 'synthetic employee credential only'
        database.execute("UPDATE staff_employees SET phone='07700000001' WHERE id=%s", (self.employee,))
        database.execute("INSERT INTO so_employee_credentials(employee_id,business_id,password_hash,version) VALUES (%s,'alpha',%s,'v1')",
                         (self.employee, accounts.password_hash(password)))
        both = self.client(manager=True)
        self.assertEqual(self.post(both, 'employee/login', {'phone': '07700000001', 'payroll_number': password}).status_code, 302)
        self.assertEqual(both.post('/staff/alpha/employee/logout').status_code, 400)
        self.assertIn(b'Choose your workspace', both.get('/staff/employee/app').data)
        self.assertEqual(self.post(both, 'employee/logout').status_code, 302)
        self.assertEqual(both.get('/staff/employee/app').location, '/staff/account')
        worker_and_manager = self.client(employee=self.second, manager=True)
        response = worker_and_manager.post('/staff/account/logout', data={'csrf_token': 'test-csrf'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(worker_and_manager.get('/staff/employee/app').location, '/staff/alpha/employee')


if __name__ == '__main__':
    unittest.main()
