"""Focused launch checks, not onboarding rehearsal; no database or provider access."""
import unittest
from unittest.mock import patch, MagicMock

from flask import session
from test_staff_account_ui import preview_app
from trimtech.modules.staff import accounts, employee_identity, employee_invitations, onboarding
from trimtech.modules.staff import employee_recovery, manager_auth, onboarding_routes, routes as staff


class EmployeeIdentifierTests(unittest.TestCase):
    def test_phone_formats_share_one_identifier(self):
        for value in ('07700 000001', '+44 7700-000001', '00447700000001'):
            self.assertEqual(employee_identity.identifier(value), ('phone', '07700000001'))
        self.assertEqual(employee_identity.identifier('07001'), ('phone', '07001'))  # Existing legacy IDs.

    def test_email_is_canonical_and_lookup_is_tenant_scoped(self):
        kind, value = employee_identity.identifier(' Worker@Example.Test ')
        with patch.object(employee_identity, 'fetch_all', return_value=[{'id': 7}]) as lookup:
            self.assertEqual(employee_identity.find('oakfield', kind, value), {'id': 7})
        sql, params = lookup.call_args.args
        self.assertEqual(params, ('oakfield', 'worker@example.test'))
        self.assertIn('e.business_id=%s', sql)
        self.assertIn('lower(btrim(e.email))=%s', sql)
        self.assertIn('LIMIT 2', sql)

    def test_missing_or_duplicate_email_never_selects_an_employee(self):
        for rows in ([], [{'id': 7}, {'id': 8}]):
            with patch.object(employee_identity, 'fetch_all', return_value=rows):
                self.assertIsNone(employee_identity.find('oakfield', 'email', 'worker@example.test'))

    def test_normalized_phone_lookup_covers_formatted_stored_numbers(self):
        with patch.object(employee_identity, 'fetch_all', return_value=[{'id': 7}]) as lookup:
            employee_identity.find('oakfield', 'phone', '07700000001')
        self.assertIn(employee_identity.PHONE_SQL, lookup.call_args.args[0])
        # The old recovery predicate could not match any submitted canonical variant.
        stored = '+44 7700 000001'
        self.assertNotIn(stored, ('07700000001', '+447700000001', '00447700000001'))
        self.assertEqual(employee_identity.phone(stored), '07700000001')

    def test_email_and_phone_login_create_the_same_employee_session(self):
        app = preview_app(); client = app.test_client()
        client.set_cookie(manager_auth.COOKIE, 'A' * 43)
        with client.session_transaction() as state:
            state['_staff_csrf_token'] = 'csrf'
        credential = {'password_hash': accounts.password_hash('a long employee password'), 'version': 'v1'}
        def business_lookup(sql, parameters):
            self.assertEqual(parameters, ('oakfield',))
            if 'NOT active' in sql:
                return None
            if 'AND active' in sql:
                return {'id': 'oakfield'}
            self.fail('Unexpected employee login query: ' + sql)
        for identifier in ('worker@example.test', '+44 7700 000001'):
            with patch.object(onboarding, 'status', return_value={'state': 'active'}), \
                    patch.object(employee_identity, 'find', return_value={'id': 7}), \
                    patch.object(employee_invitations, 'credential', return_value=credential), \
                    patch.object(staff, 'fetch_one', side_effect=business_lookup), \
                    patch.object(accounts, 'limited', return_value=True):
                response = client.post('/staff/oakfield/employee/login', data={
                    'csrf_token': 'csrf', 'phone': identifier, 'payroll_number': 'a long employee password'})
            self.assertEqual(response.status_code, 302)
            with client.session_transaction() as state:
                self.assertEqual(state[staff._EMPLOYEE_SESSION_KEY]['employee_id'], 7)
                self.assertEqual(state[staff._EMPLOYEE_SESSION_KEY]['business_id'], 'oakfield')
                self.assertNotIn('platform_admin_authenticated', state)
            self.assertEqual(client.get_cookie(manager_auth.COOKIE).value, 'A' * 43)


class ManagerPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.app = preview_app()
        self.now = 0
        self.raw = 'A' * 43
        self.valid = True
        self.app.add_url_rule('/staff/<business_slug>/session-check', 'session_check',
            manager_auth.dashboard_login_required(lambda business_slug: 'authorized'))
        self.client = self.app.test_client()
        with self.client.session_transaction() as state:
            state['_staff_csrf_token'] = 'csrf'
            state[staff._EMPLOYEE_SESSION_KEY] = {'business_id': 'oakfield', 'employee_id': 7}
        for target, attribute, replacement in (
            (accounts, 'authenticate', lambda *a: self.raw),
            (accounts, 'revoke', lambda raw: None),
            (accounts, 'limited', lambda *a, **k: True),
            (accounts, 'current', lambda raw: {'id': 'manager'} if raw == self.raw and self.valid and self.now < 28800 else None),
            (accounts, 'membership', lambda administrator, business: {'role': 'owner'} if business == 'oakfield' else None),
            (onboarding, 'access', lambda business: {'state': 'active'})):
            mock = patch.object(target, attribute, side_effect=replacement)
            mock.start(); self.addCleanup(mock.stop)
        self.login = self.client.post('/staff/account/login', base_url='https://localhost',
            data={'csrf_token': 'csrf', 'email': 'manager@example.test', 'password': 'a long manager password'})

    def test_cookie_is_persistent_secure_and_survives_return_after_one_minute(self):
        cookie = next(c for c in self.login.headers.getlist('Set-Cookie') if c.startswith(manager_auth.COOKIE + '='))
        for attribute in ('Max-Age=28800', 'Expires=', 'Secure', 'HttpOnly', 'SameSite=Lax', 'Path=/'):
            self.assertIn(attribute, cookie)
        for self.now in (0, 61, 3600):
            self.assertEqual(self.client.get('/staff/oakfield/session-check', base_url='https://localhost').status_code, 200)
        with self.client.session_transaction() as state:
            self.assertEqual(state[staff._EMPLOYEE_SESSION_KEY]['employee_id'], 7)

    def test_server_expiry_revocation_and_tenant_isolation_still_apply(self):
        self.assertEqual(self.client.get('/staff/trimtech/session-check', base_url='https://localhost').status_code, 404)
        self.now = 28800
        self.assertEqual(self.client.get('/staff/oakfield/session-check', base_url='https://localhost').status_code, 302)
        self.now = 61; self.valid = False
        self.assertEqual(self.client.get('/staff/oakfield/session-check', base_url='https://localhost').status_code, 302)

    def test_explicit_manager_logout_preserves_employee_session(self):
        with self.client.session_transaction() as state:
            csrf = state['_staff_csrf_token']
        self.assertEqual(self.client.post('/staff/account/logout', base_url='https://localhost', data={'csrf_token': csrf}).status_code, 302)
        self.assertIsNone(self.client.get_cookie(manager_auth.COOKIE))
        with self.client.session_transaction() as state:
            self.assertEqual(state[staff._EMPLOYEE_SESSION_KEY]['employee_id'], 7)

    def test_auth_diagnostics_never_log_the_cookie(self):
        self.valid = False
        with self.assertLogs(manager_auth.logger, level='WARNING') as logs:
            self.client.get('/staff/oakfield/session-check', base_url='https://localhost')
        self.assertIn('server_session_unavailable', str(logs.output))
        self.assertNotIn(self.raw, str(logs.output))


class PublicTrialChecks(unittest.TestCase):
    def test_public_registration_flag_gates_only_registration(self):
        client = preview_app().test_client()
        with patch.dict('os.environ', STAFF_REGISTRATION_ENABLED='0'):
            self.assertEqual(client.get('/staff/account/register').status_code, 503)
            self.assertEqual(client.get('/staff/account/login').status_code, 200)
        with patch.dict('os.environ', STAFF_REGISTRATION_ENABLED='1'):
            response = client.get('/staff/account/register')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'No card is required', response.data)
        self.assertNotIn(b'name="card', response.data)

    def test_verified_trial_is_exactly_336_hours_and_not_restarted(self):
        cursor = MagicMock()
        cursor.fetchall.side_effect = [[('oakfield', 'manager@example.test')], []]
        cursor.fetchone.return_value = ('oakfield',)
        onboarding.activate(cursor, 'manager')
        onboarding.activate(cursor, 'manager')
        updates = [c for c in cursor.execute.call_args_list if c.args[0].startswith('UPDATE so_trials')]
        self.assertEqual(len(updates), 1)
        self.assertIn("INTERVAL '336 hours'", updates[0].args[0])
        self.assertIn('starts_at IS NULL', updates[0].args[0])

    def test_expired_trial_blocks_writes_before_handler(self):
        app = preview_app()
        handler = MagicMock(return_value='unexpected write')
        protected = manager_auth.dashboard_login_required(handler)
        with app.test_request_context('/staff/oakfield/setup', method='POST'), \
                patch.object(manager_auth, 'identity', return_value={'id': 'manager'}), \
                patch.object(accounts, 'membership', return_value={'role': 'owner'}), \
                patch.object(onboarding, 'access', return_value={'state': 'expired'}), \
                patch.object(manager_auth, 'render_template', return_value='read-only access'):
            self.assertEqual(protected('oakfield')[1], 402)
            handler.assert_not_called()


if __name__ == '__main__':
    unittest.main()
