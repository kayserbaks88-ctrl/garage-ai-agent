"""Migration-free employee PWA regressions. All database operations are mocked."""
import json
import time
import struct
import unittest
from contextlib import contextmanager, ExitStack
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

from flask import Flask, render_template
from trimtech.modules.staff import routes as staff, onboarding_routes, employee_identity

ROOT = Path(__file__).parent


def preview_app():
    app = Flask(__name__, template_folder=str(ROOT / 'templates'), static_folder=str(ROOT / 'static'))
    app.secret_key = 'pwa-local-test-only'
    app.testing = True
    app.register_blueprint(staff.staff_blueprint)
    return app


class EmployeePwaTests(unittest.TestCase):
    def setUp(self):
        self.app = preview_app()
        self.client = self.app.test_client()

    def test_public_shell_does_not_query_database_and_is_not_cached(self):
        with patch.object(staff, 'fetch_one', side_effect=AssertionError('database accessed')), \
                patch.object(onboarding_routes, 'fetch_one', side_effect=AssertionError('database accessed')):
            for path in ('employee/app', 'employee/app/install', 'employee/app/offline',
                         'employee/app/manifest.webmanifest', 'employee-sw.js'):
                response = self.client.get('/staff/' + path)
                self.assertEqual(response.status_code, 200, path)
                self.assertIn('no-store', response.headers['Cache-Control'])

    def test_manifest_icons_and_scope(self):
        response = self.client.get('/staff/employee/app/manifest.webmanifest')
        self.assertEqual(response.mimetype, 'application/manifest+json')
        manifest = json.loads(response.data)
        self.assertEqual(manifest['start_url'], '/staff/employee/app')
        self.assertEqual(manifest['scope'], '/staff/')
        self.assertEqual(manifest['display'], 'standalone')
        self.assertEqual(manifest['id'], '/staff/employee/app')
        self.assertEqual(manifest['name'], 'Staff Manager')
        for icon in manifest['icons']:
            data = (ROOT / icon['src'].lstrip('/')).read_bytes()
            width, height = struct.unpack('>II', data[16:24])
            self.assertEqual(f'{width}x{height}', icon['sizes'])
            with self.client.get(icon['src']) as response:
                self.assertEqual(response.status_code, 200)

    def test_launcher_redirect_only_to_existing_employee_login(self):
        response = self.client.get('/staff/employee/app?workplace=Oakfield')
        self.assertEqual(response.location, '/staff/oakfield/employee/login')
        for value in ('https://evil.test', '../account', 'a/b', 'a' * 81):
            response = self.client.get('/staff/employee/app', query_string={'workplace': value})
            self.assertEqual(response.status_code, 200)
            self.assertIn(b'Enter the workplace code', response.data)

    def test_worker_has_embedded_public_fallback_and_no_storage_or_queue(self):
        response = self.client.get('/staff/employee-sw.js')
        source = response.get_data(as_text=True)
        self.assertNotIn('__STAFF_OFFLINE_HTML__', source)
        self.assertIn('Reconnect to continue', source)
        for forbidden in ('caches.', 'indexedDB', 'localStorage', 'sync', 'put('):
            self.assertNotIn(forbidden, source)
        self.assertNotIn('Service-Worker-Allowed', response.headers)

    def test_existing_login_and_logout_preserve_csrf_and_tenant_session(self):
        def lookup(sql, parameters):
            return None if 'NOT active' in sql else {'id': 'alpha'}
        with self.client.session_transaction() as state:
            state['_staff_csrf_token'] = 'test-csrf'
        with patch.object(staff.onboarding, 'status', return_value={'state': 'active'}), \
                patch.object(staff.accounts, 'limited', return_value=True), \
                patch.object(staff, 'fetch_one', side_effect=lookup), \
                patch.object(employee_identity, 'find', return_value={'id': 7}), \
                patch.object(staff.employee_invitations, 'credential', return_value={
                    'version': 'v1', 'password_hash': staff.accounts.password_hash('employee secure password')}):
            response = self.client.post('/staff/alpha/employee/login', data={
                'csrf_token': 'test-csrf', 'phone': '07700000001', 'payroll_number': 'employee secure password'})
        self.assertEqual(response.status_code, 302)
        with self.client.session_transaction() as state:
            self.assertEqual(state[staff._EMPLOYEE_SESSION_KEY]['business_id'], 'alpha')
        self.assertEqual(self.client.post('/staff/alpha/employee/logout').status_code, 400)
        self.client.post('/staff/beta/employee/logout', data={'csrf_token': 'test-csrf'})
        with self.client.session_transaction() as state:
            self.assertIn(staff._EMPLOYEE_SESSION_KEY, state)
        self.client.post('/staff/alpha/employee/logout', data={'csrf_token': 'test-csrf'})
        with self.client.session_transaction() as state:
            self.assertNotIn(staff._EMPLOYEE_SESSION_KEY, state)

    def test_cross_business_employee_routes_never_reach_database(self):
        with self.client.session_transaction() as state:
            state['_staff_csrf_token'] = 'test-csrf'
            state[staff._EMPLOYEE_SESSION_KEY] = {
                'business_id': 'alpha', 'employee_id': 7, 'issued_at': int(time.time())}
        with patch.object(staff, 'fetch_one', side_effect=AssertionError('tenant bypass')):
            for path in ('', '/clocking', '/hours', '/rota', '/pay', '/leave', '/payslips/1/download', '/payslips/1/view'):
                response = self.client.get('/staff/beta/employee' + path)
                self.assertEqual(response.status_code, 302, path)
                self.assertTrue(response.location.endswith('/beta/employee/login'))
            for path in ('clock-in', 'clock-out', 'break/start', 'break/end', 'leave'):
                response = self.client.post('/staff/beta/employee/' + path, data={'csrf_token': 'test-csrf'})
                self.assertEqual(response.status_code, 302, path)

    def test_employee_navigation_rendered_with_tenant_links(self):
        with self.app.test_request_context('/staff/alpha/employee/hours'), \
                patch.object(onboarding_routes, 'fetch_one', return_value={'name': 'Example'}):
            html = render_template('staff_employee_base.html', employee={'full_name': 'Test Employee'},
                                   business_slug='alpha', page='hours', csrf_token=lambda: 'test-csrf')
        self.assertIn('employee-mobile-nav', html)
        self.assertIn('/staff/alpha/employee/clocking', html)
        self.assertIn('name="csrf_token" value="test-csrf"', html)
        self.assertIn('staff_pwa.js', html)

    @contextmanager
    def employee(self):
        record = {'id': 7, 'full_name': 'Test Employee', 'business_id': 'alpha', 'status': 'active'}
        def lookup(sql, params):
            if 'FROM staff_employees WHERE id=' in sql:
                self.assertEqual(params, (7, 'alpha'))
                return record
            if 'staff_shifts' in sql:
                return None
            return None
        with self.client.session_transaction() as state:
            state['_staff_csrf_token'] = 'test-csrf'
            state[staff._EMPLOYEE_SESSION_KEY] = {'business_id': 'alpha', 'employee_id': 7,
                                                  'issued_at': int(time.time())}
        with ExitStack() as stack:
            for target, name, value in (
                (staff, 'fetch_one', None), (staff, 'fetch_all', []),
                (onboarding_routes, 'fetch_one', {'name': 'Example workplace'}),
                (staff.employee_invitations, 'credential', None),
                (staff.onboarding, 'status', {'state': 'legacy'}),
                (staff.onboarding, 'access', {'state': 'legacy'}),
                (staff.agency, 'settings', {'organisation_mode': 'fixed', 'travel_enabled': False}),
                (staff.agency, 'upcoming_assignments', []),
            ):
                mock = stack.enter_context(patch.object(target, name, return_value=value))
                if target is staff and name == 'fetch_one':
                    mock.side_effect = lookup
            yield

    def post(self, path, **data):
        return self.client.post('/staff/alpha/employee/' + path,
                                data={'csrf_token': 'test-csrf', **data})

    def test_employee_tools_render_with_existing_guards_and_no_store(self):
        from trimtech.modules.staff import rota
        with self.employee(), patch.object(rota, 'fetch_all', return_value=[]) as query:
            for path in ('clocking', 'hours', 'rota', 'pay', 'leave'):
                response = self.client.get('/staff/alpha/employee/' + path)
                self.assertEqual(response.status_code, 200, path)
                self.assertIn('no-store', response.headers['Cache-Control'])
                self.assertIn(b'employee-mobile-nav', response.data)
            self.assertEqual(query.call_args.args[1][:2], ('alpha', 7))

    def test_clock_in_validates_gps_and_keeps_pending_manager_approval(self):
        site = {'id': 2, 'name': 'Test site', 'latitude': 51.5, 'longitude': -.12,
                'allowed_radius_metres': 100, 'photo_required': False}
        with self.employee(), patch.object(staff, 'transaction') as transaction, \
                patch.object(staff.agency, 'locked_settings', return_value={'organisation_mode': 'fixed'}), \
                patch.object(staff.agency, 'snapshot_shift') as snapshot:
            cursor = transaction.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
            cursor.rowcount = 1
            cursor.fetchone.side_effect = [{'id': 7}, None, site, {'id': 10}]
            self.assertEqual(self.post('clock-in', site_id=2, latitude=51.5, longitude=-.12, accuracy=5).status_code, 302)
            inserts = [c for c in cursor.execute.call_args_list if 'INSERT INTO staff_shifts' in c.args[0]]
            self.assertEqual(inserts[0].args[1][:2], ('alpha', 7))
            self.assertIn("'pending'", inserts[0].args[0])
            snapshot.assert_called_once()
            cursor.reset_mock()
            cursor.fetchone.side_effect = [{'id': 7}, None, site]
            snapshot.reset_mock()
            self.post('clock-in', site_id=2, latitude=52.5, longitude=-.12, accuracy=5)
            self.assertFalse(any('INSERT INTO staff_shifts' in c.args[0] for c in cursor.execute.call_args_list))
            snapshot.assert_not_called()

    def test_clock_out_and_breaks_are_scoped_to_employee_and_shift(self):
        now = datetime.now(timezone.utc)
        site = {'id': 2, 'latitude': 51.5, 'longitude': -.12,
                'allowed_radius_metres': 100, 'photo_required': False}
        with self.employee(), patch.object(staff, 'transaction') as transaction, \
                patch.object(staff.agency, 'locked_settings', return_value={'organisation_mode': 'fixed'}):
            cursor = transaction.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
            cursor.rowcount = 1
            cursor.fetchone.side_effect = [{'id': 7}, {'id': 10, 'site_id': 2}, site, {'finished_at': now}]
            self.post('clock-out', shift_id=10, latitude=51.5, longitude=-.12, accuracy=5)
            update = next(c for c in cursor.execute.call_args_list if 'UPDATE staff_shifts SET clock_out_at' in c.args[0])
            self.assertEqual(update.args[1][-3:], (10, 'alpha', 7))
            self.assertIn("approval_status='pending'", update.args[0])
            cursor.reset_mock()
            cursor.fetchone.side_effect = [{'id': 7}, {'id': 10}, {'break_policy': 'unpaid'}]
            self.post('break/start', shift_id=10)
            insert = next(c for c in cursor.execute.call_args_list if 'INSERT INTO staff_breaks' in c.args[0])
            self.assertEqual(insert.args[1], ('alpha', 7, 10, False))
            cursor.reset_mock()
            cursor.fetchone.side_effect = [{'id': 7}, {'id': 10}]
            self.post('break/end', shift_id=10, break_id=11)
            update = next(c for c in cursor.execute.call_args_list if 'UPDATE staff_breaks SET ended_at=clock_timestamp()' in c.args[0])
            self.assertEqual(update.args[1], (11, 10, 'alpha', 7))

    def test_leave_requires_manager_approval_and_payslip_lookup_is_scoped(self):
        with self.employee(), patch.object(staff, '_insert_leave') as insert:
            response = self.post('leave', leave_type='holiday', start_date='2026-11-02', end_date='2026-11-03')
            self.assertEqual(response.status_code, 302)
            self.assertEqual(insert.call_args.args[:2], ('alpha', 7))
            self.assertEqual(insert.call_args.args[-1], 'pending')
        with self.app.test_request_context('/staff/alpha/employee/pay'), \
                patch.object(staff, 'fetch_one', return_value=None) as query:
            from werkzeug.exceptions import NotFound
            with self.assertRaises(NotFound):
                staff._payslip_record('alpha', 99, 7)
            self.assertEqual(query.call_args.args[1], (99, 'alpha', 7, 7))

    def test_payslip_download_requires_employee_and_approved_record(self):
        from trimtech.modules.staff import payslip_pdf
        slip = {'status': 'approved', 'needs_recalculation': False, 'payment_date': date(2026, 10, 16)}
        with self.employee(), patch.object(payslip_pdf, 'render', return_value=b'%PDF-test'):
            normal_lookup = staff.fetch_one.side_effect
            def lookup(sql, params):
                if 'FROM staff_payslips p JOIN' in sql:
                    self.assertEqual(params, (99, 'alpha', 7, 7))
                    return slip
                return normal_lookup(sql, params)
            staff.fetch_one.side_effect = lookup
            response = self.client.get('/staff/alpha/employee/payslips/99/download')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.mimetype, 'application/pdf')
            self.assertIn('no-store', response.headers['Cache-Control'])
            slip['status'] = 'draft'
            self.assertEqual(self.client.get('/staff/alpha/employee/payslips/99/download').status_code, 404)

    def test_manager_and_onboarding_urls_keep_their_existing_routes(self):
        urls = self.app.url_map.bind('localhost')
        for path in ('/staff/alpha', '/staff/employee-app', '/staff/account/register'):
            endpoint, _ = urls.match(path)
            self.assertNotIn(endpoint, {'staff.employee_app', 'staff.employee_app_install'})

    def test_launcher_roles_are_navigation_not_authorization(self):
        from trimtech.modules.staff import manager_auth
        self.assertEqual(self.client.get('/staff/employee/app?role=manager').location, '/staff/account')
        self.assertEqual(self.client.get('/staff/account').location, '/staff/account/login')
        self.assertEqual(self.client.get('/staff/employee/app?role=owner').status_code, 400)
        self.assertEqual(self.client.get('/staff/employee/app?workplace=https://evil.test').status_code, 200)
        with self.employee():
            self.assertEqual(self.client.get('/staff/employee/app').location, '/staff/alpha/employee')
            self.assertEqual(self.client.get('/staff/alpha').status_code, 302)
            self.client.set_cookie(manager_auth.COOKIE, 'A'*43)
            with patch.object(manager_auth, 'identity', return_value={'id':'manager'}):
                response = self.client.get('/staff/employee/app')
                self.assertEqual(response.status_code, 200)
                self.assertIn(b'Choose your workspace', response.data)
                self.assertEqual(self.client.get('/staff/employee/app?role=employee').location, '/staff/alpha/employee')
                self.assertEqual(self.client.get('/staff/employee/app?role=manager').location, '/staff/account')
                with patch.object(staff.accounts, 'membership', return_value=None):
                    self.assertEqual(self.client.get('/staff/beta').status_code, 404)

    def test_launcher_expired_employee_and_manager_sessions_fail_closed(self):
        from trimtech.modules.staff import manager_auth
        with self.client.session_transaction() as state:
            state[staff._EMPLOYEE_SESSION_KEY] = {'business_id':'alpha','employee_id':7,'issued_at':0}
        with patch.object(staff, 'fetch_one', side_effect=AssertionError('expired employee queried')):
            self.assertEqual(self.client.get('/staff/employee/app').status_code, 200)
        self.client.set_cookie(manager_auth.COOKIE, 'A'*43)
        with patch.object(manager_auth, 'identity', return_value=None):
            self.assertEqual(self.client.get('/staff/employee/app').status_code, 200)
        with patch.object(manager_auth, 'identity', side_effect=staff.StaffDatabaseError('unavailable')):
            self.assertEqual(self.client.get('/staff/employee/app').status_code, 503)
        with patch.object(manager_auth, 'identity', return_value={'id':'manager'}):
            self.assertEqual(self.client.get('/staff/employee/app').location, '/staff/account')
            self.assertEqual(self.client.get('/staff/employee/app?role=employee').status_code, 200)

    def test_shared_metadata_and_registration_remains_outside_pwa(self):
        from trimtech.modules.staff import manager_auth
        for path in ('/staff/employee/app', '/staff/employee/app/install','/staff/account/login'):
            response = self.client.get(path)
            self.assertIn(b'crossorigin="use-credentials"', response.data)
            self.assertIn(b'name="apple-mobile-web-app-capable" content="yes"', response.data)
            self.assertIn(b'name="apple-mobile-web-app-title" content="Staff Manager"', response.data)
        self.assertNotIn(b'staff_pwa.js', self.client.get('/staff/account/register').data)
        with self.app.test_request_context('/staff/alpha'), patch.object(staff.onboarding, 'access', return_value={'state':'legacy'}), \
                patch.object(onboarding_routes, 'fetch_one', return_value={'name':'Example workplace'}):
            html=render_template('staff_base.html', business_slug='alpha', csrf_token=lambda:'csrf')
        for existing in ('/staff/account','/staff/alpha/settings','/staff/account/logout'):
            self.assertIn(existing, html)
        self.assertIn('manager-pwa-nav', html)
        self.assertNotIn('target="_blank"', html)

    def test_synthetic_preview_is_read_only_and_keeps_manager_tenant_guard(self):
        import importlib.util
        spec=importlib.util.spec_from_file_location('staff_preview_checks',ROOT/'tests/staff_pwa_preview.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with module.synthetic_preview() as app:
            client=app.test_client()
            self.assertEqual(client.get('/qa/manager',follow_redirects=True).status_code,200)
            for path in ('','/employees','/attendance','/approvals','/leave','/agency','/payroll','/settings'):
                response=client.get('/staff/alpha'+path)
                self.assertEqual(response.status_code,200,path)
                self.assertIn(b'crossorigin="use-credentials"',response.data,path)
                self.assertIn(b'data-pwa-status',response.data,path)
                menu=response.text.split('<details class="manager-pwa-nav manager-mobile-menu">',1)[1].split('</details>',1)[0]
                for label in ('Dashboard','Switch Workspace','Staff','Attendance','Assignments','Rota','Approvals','Payroll','Settings','Sign Out','Install / app help'):
                    self.assertIn('>'+label+'<',menu,path)
                self.assertIn('method="post" action="/staff/account/logout"',menu)
                self.assertIn('name="csrf_token"',menu)
                self.assertNotIn('target=',menu)
                self.assertNotIn('/staff/beta',menu)
            self.assertEqual(client.get('/staff/beta').status_code,404)
            self.assertEqual(client.post('/staff/alpha/employees').status_code,409)
            self.assertEqual(client.get('/healthz').json['database'],'blocked')
            client.get('/qa/both')
            self.assertIn(b'Choose your workspace',client.get('/staff/employee/app').data)
            self.assertEqual(client.get('/staff/employee/app/preview/manager',follow_redirects=True).request.path,'/staff/account')
            self.assertIn(b'/staff/employee/app/preview/employee',client.get('/staff/alpha').data)


if __name__ == '__main__':
    unittest.main()
