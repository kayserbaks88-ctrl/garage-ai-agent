"""Employee recovery service and HTTP regressions; database/provider calls mocked."""
import os
import time
import unittest
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from flask import session
from test_staff_account_ui import preview_app
from trimtech.modules.staff import accounts, employee_invitations, employee_recovery as recovery, employee_identity
from trimtech.modules.staff import routes as staff, onboarding_routes
from trimtech.modules.staff.manager_auth import COOKIE

TOKEN = 'A' * 43
PASSWORD = 'a secure employee recovery passphrase'
BASE = 'https://staff.example.test'


@contextmanager
def mocked_database(one=None, many=None):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = one
    cursor.fetchall.return_value = many or []
    with patch.object(recovery, 'transaction') as transaction, patch.object(recovery.agency, 'lock_business') as lock:
        transaction.return_value.__enter__.return_value = connection
        yield cursor, lock


class EmployeeRecoveryServiceTests(unittest.TestCase):
    def test_eligible_employee_email_uses_recorded_address_and_one_hour_hashed_token(self):
        with mocked_database(many=[{'id': 7, 'email': ' Worker@Example.Test ', 'version': 'current'}]) as (cursor, lock), \
                patch.object(recovery.secrets, 'token_urlsafe', return_value=TOKEN), \
                patch.object(recovery, 'send_staff_email', return_value=(True, None, 'provider')) as send:
            recovery.issue('alpha', 'worker@example.test', ('07700000001',), BASE)
        lock.assert_called_once_with(cursor, 'alpha')
        query = cursor.execute.call_args_list[0]
        self.assertEqual(query.args[1], ('alpha', 'worker@example.test', ['07700000001']))
        for condition in ("e.status='active'", 'b.active', 'so_employee_credentials', 'c.business_id=e.business_id', 'LIMIT 2', 'FOR UPDATE OF e,c'):
            self.assertIn(condition, query.args[0])
        insert = cursor.execute.call_args_list[1]
        self.assertIn("INTERVAL '1 hour'", insert.args[0])
        self.assertEqual(insert.args[1][1], recovery.token_digest(TOKEN))
        self.assertTrue(insert.args[1][0].startswith('employee-reset-current-'))
        self.assertNotIn(TOKEN, str(insert.args[1]))
        self.assertEqual(send.call_args.args[0], 'worker@example.test')
        self.assertIn('/staff/alpha/employee/reset#token=' + TOKEN, send.call_args.args[2])
        self.assertFalse(any(c.args[0].lstrip().startswith('UPDATE') for c in cursor.execute.call_args_list))

    def test_unknown_or_ambiguous_matches_do_not_issue_or_send(self):
        for employees in ([], [{'id': 1}, {'id': 2}]):
            with self.subTest(employees=employees), mocked_database(many=employees) as (cursor, _), \
                    patch.object(recovery, 'send_staff_email') as send:
                recovery.issue('alpha', 'worker@example.test', ('07700000001',), BASE)
                send.assert_not_called()
                self.assertEqual(cursor.execute.call_count, 1)

    def test_formatted_phone_is_normalized_in_the_database_predicate(self):
        with mocked_database() as (cursor, _):
            recovery.issue('alpha', 'worker@example.test', ('+44 7700 000001', '07700-000001'), BASE)
        self.assertIn(employee_identity.PHONE_SQL, cursor.execute.call_args.args[0])
        self.assertEqual(cursor.execute.call_args.args[1][2], ['07700000001'])

    def test_dispatch_diagnostics_do_not_expose_identity_or_provider_details(self):
        with mocked_database(many=[{'id': 7, 'email': 'worker@example.test', 'version': 'v1'}]), \
                patch.object(recovery, 'send_staff_email', return_value=(False, TOKEN, None)), \
                self.assertLogs(recovery.logger, level='WARNING') as logs:
            recovery.issue('alpha', 'worker@example.test', ('07700000001',), BASE)
        self.assertIn('stage=attempt', str(logs.output))
        self.assertIn('reason=provider_rejected', str(logs.output))
        self.assertNotIn(TOKEN, str(logs.output))
        self.assertNotIn('worker@example.test', str(logs.output))

    def test_unsafe_public_url_does_not_access_database(self):
        for base in ('http://evil.test', 'https://user@evil.test', 'https://staff.test/path', 'https://staff.test?query=1'):
            with patch.object(recovery, 'transaction') as transaction:
                recovery.issue('alpha', 'worker@example.test', ('07700000001',), base)
                transaction.assert_not_called()

    def test_reset_namespace_is_distinct_from_invitation_and_manager_tokens(self):
        self.assertNotEqual(recovery.token_digest(TOKEN), accounts.digest(TOKEN))
        with patch.object(employee_invitations, 'transaction') as transaction:
            cursor = transaction.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
            cursor.fetchone.return_value = None
            with self.assertRaises(ValueError):
                employee_invitations.accept(TOKEN, PASSWORD)
            self.assertEqual(cursor.execute.call_args.args[1], (accounts.digest(TOKEN),))

    def test_consumption_is_tenant_bound_atomic_and_never_provisions_credentials(self):
        with mocked_database(one={'id': 'employee-reset-id', 'employee_id': 7}) as (cursor, lock), \
                patch.object(accounts, 'password_hash', return_value='hashed'):
            self.assertTrue(recovery.consume('alpha', TOKEN, PASSWORD))
        lock.assert_called_once_with(cursor, 'alpha')
        calls = cursor.execute.call_args_list
        self.assertEqual(calls[0].args[1], ('alpha', recovery.token_digest(TOKEN)))
        for condition in ('i.business_id=%s', 'i.consumed_at IS NULL', 'i.expires_at>NOW()',
                          'lower(btrim(e.email))=i.email', 'b.active', "e.status='active'",
                          'so_employee_credentials', "i.id LIKE 'employee-reset-' || c.version", 'FOR UPDATE OF i,e,c'):
            self.assertIn(condition, calls[0].args[0])
        self.assertEqual(calls[1].args[1][0], 'hashed')
        self.assertEqual(len(calls[1].args[1][1]), 32)
        self.assertEqual(calls[1].args[1][2:], ('alpha', 7))
        self.assertEqual(calls[2].args[1], ('alpha', 7))
        self.assertIn('consumed_at IS NULL', calls[2].args[0])
        self.assertFalse(any('INSERT' in c.args[0] or 'sm_administrators' in c.args[0] for c in calls))

    def test_expired_replayed_wrong_tenant_or_changed_identity_cannot_write(self):
        with mocked_database() as (cursor, _):
            self.assertFalse(recovery.consume('beta', TOKEN, PASSWORD))
            self.assertEqual(cursor.execute.call_count, 1)

    def test_malformed_token_and_invalid_password_never_open_transaction(self):
        with patch.object(recovery, 'transaction') as transaction:
            self.assertFalse(recovery.consume('alpha', 'short', PASSWORD))
            with self.assertRaises(ValueError):
                recovery.consume('alpha', TOKEN, 'short')
            transaction.assert_not_called()

    def test_background_queue_is_bounded_and_releases_slots_on_failure(self):
        with patch.object(recovery, '_slots') as slots, patch.object(recovery, '_workers') as workers:
            slots.acquire.return_value = False
            recovery.enqueue('alpha', 'worker@example.test', ('07700000001',), BASE)
            workers.submit.assert_not_called()
            slots.acquire.return_value = True
            workers.submit.side_effect = RuntimeError('private identity and token')
            with self.assertLogs(recovery.logger, level='WARNING') as logs:
                recovery.enqueue('alpha', 'worker@example.test', ('07700000001',), BASE)
            slots.release.assert_called_once()
            self.assertNotIn('private identity', str(logs.output))

    def test_background_delivery_failure_is_private_and_releases_slot(self):
        with patch.object(recovery, '_slots') as slots, patch.object(recovery, 'issue', side_effect=RuntimeError(TOKEN)):
            with self.assertLogs(recovery.logger, level='WARNING') as logs:
                recovery._deliver('alpha', 'worker@example.test', ('07700000001',), BASE)
            slots.release.assert_called_once()
            self.assertNotIn(TOKEN, str(logs.output))


class EmployeeRecoveryRouteTests(unittest.TestCase):
    def setUp(self):
        self.app = preview_app()
        self.app.testing = True
        self.client = self.app.test_client()
        with self.client.session_transaction() as state:
            state['_staff_csrf_token'] = 'test-csrf'
        for target, value in ((onboarding_routes, 'fetch_one'),):
            mock = patch.object(target, value, return_value={'name': 'Example workplace'})
            mock.start(); self.addCleanup(mock.stop)
        limiter = patch.object(accounts, 'limited', return_value=True)
        self.limiter = limiter.start(); self.addCleanup(limiter.stop)

    def post(self, action, **data):
        return self.client.post('/staff/alpha/employee/' + action, data={'csrf_token': 'test-csrf', **data})

    def test_recovery_acknowledgement_and_navigation_do_not_depend_on_account(self):
        with patch.object(recovery, 'enqueue') as enqueue, patch.dict(os.environ, STAFF_PUBLIC_BASE_URL=BASE):
            responses = [self.post('recover', email=email, phone='07700000001')
                         for email in ('worker@example.test', 'unknown@example.test')]
            self.assertEqual(enqueue.call_count, 2)  # Eligibility is never queried in the HTTP request.
        self.assertEqual(responses[0].status_code, 303)
        self.assertEqual(responses[0].location, responses[1].location)
        sent = self.client.get(responses[0].location)
        self.assertIn(b'If these details match an eligible employee account', sent.data)
        self.assertIn('no-store', sent.headers['Cache-Control'])
        self.limiter.return_value = False
        with patch.object(recovery, 'enqueue') as enqueue:
            self.assertEqual(self.post('recover', email='worker@example.test', phone='07700000001').location, responses[0].location)
            enqueue.assert_not_called()

    def test_phone_variants_share_the_same_identity_rate_limit(self):
        with patch.object(recovery, 'enqueue'):
            for phone in ('07700000001', '+44 7700 000001', '00447700000001'):
                self.post('recover', email=' Worker@Example.Test ', phone=phone)
        identities = [c.args[1] for c in self.limiter.call_args_list]
        self.assertEqual(len(set(identities)), 1)

    def test_invalid_input_is_generic_and_never_queued(self):
        with patch.object(recovery, 'enqueue') as enqueue:
            response = self.post('recover', email='not-email', phone='bad')
            self.assertEqual(response.status_code, 303)
            enqueue.assert_not_called()

    def test_csrf_and_payload_limits_apply_to_both_employee_forms(self):
        with patch.object(recovery, 'enqueue') as enqueue, patch.object(recovery, 'consume') as consume:
            for action in ('recover', 'reset'):
                self.assertEqual(self.client.post('/staff/alpha/employee/' + action, data={}).status_code, 400)
                self.assertEqual(self.post(action, token='x' * 17000).status_code, 413)
            enqueue.assert_not_called(); consume.assert_not_called()

    def test_success_is_prg_and_preserves_administrator_authentication(self):
        self.client.set_cookie(COOKIE, 'existing-manager-session')
        with self.client.session_transaction() as state:
            state[staff._EMPLOYEE_SESSION_KEY] = {'business_id': 'alpha'}
            state['platform_admin_authenticated'] = True
        with patch.object(recovery, 'consume', return_value=True) as consume:
            response = self.post('reset', token=TOKEN, password=PASSWORD)
            self.assertEqual(response.status_code, 303)
            for _ in range(2):
                success = self.client.get(response.location)
                self.assertIn(b'Password updated successfully', success.data)
                self.assertIn(b'href="/staff/alpha/employee/login">Sign in</a>', success.data)
                self.assertNotIn(b'<form', success.data)
                self.assertNotIn(TOKEN.encode(), success.data)
            consume.assert_called_once_with('alpha', TOKEN, PASSWORD)
        with self.client.session_transaction() as state:
            self.assertNotIn(staff._EMPLOYEE_SESSION_KEY, state)
            self.assertTrue(state['platform_admin_authenticated'])
        self.assertEqual(self.client.get_cookie(COOKIE).value, 'existing-manager-session')

    def test_replay_is_friendly_and_rate_limited_reset_never_consumes(self):
        with patch.object(recovery, 'consume', return_value=False):
            response = self.post('reset', token=TOKEN, password=PASSWORD)
        self.assertEqual(response.status_code, 400)
        self.assertIn(b'If you already updated your password, you can sign in.', response.data)
        self.assertIn(b'/staff/alpha/employee/recover', response.data)
        self.assertNotIn(TOKEN.encode(), response.data)
        self.limiter.return_value = False
        with patch.object(recovery, 'consume') as consume:
            self.assertEqual(self.post('reset', token=TOKEN, password=PASSWORD).status_code, 429)
            consume.assert_not_called()

    def test_password_validation_keeps_the_token_for_retry(self):
        with patch.object(recovery, 'consume', side_effect=ValueError('Use a longer password.')):
            response = self.post('reset', token=TOKEN, password='short')
        self.assertEqual(response.status_code, 400)
        self.assertIn(TOKEN.encode(), response.data)
        self.assertIn(b'data-reset-form', response.data)
        self.assertNotIn(b'value="short"', response.data)

    def test_duplicate_submission_cannot_report_two_successes(self):
        with patch.object(recovery, 'consume', side_effect=[True, False]):
            self.assertEqual(self.post('reset', token=TOKEN, password=PASSWORD).status_code, 303)
            self.assertEqual(self.post('reset', token=TOKEN, password=PASSWORD).status_code, 400)

    def test_new_password_sign_in_uses_employee_credentials_in_the_same_tenant(self):
        hashed = accounts.password_hash(PASSWORD)
        def lookup(sql, parameters):
            if 'SELECT id,payroll_number' in sql:
                self.assertEqual(parameters[0], 'alpha')
                return {'id': 7, 'payroll_number': 'legacy-number'}
            return {'id': 'alpha'}
        with patch.object(staff.onboarding, 'status', return_value={'state': 'active'}), \
                patch.object(staff, 'fetch_one', side_effect=lookup), \
                patch.object(employee_identity, 'find', return_value={'id': 7, 'payroll_number': 'legacy-number'}), \
                patch.object(employee_invitations, 'credential', return_value={'password_hash': hashed, 'version': 'new'}):
            response = self.post('login', phone='07700000001', payroll_number=PASSWORD)
        self.assertEqual(response.status_code, 302)
        with self.client.session_transaction() as state:
            self.assertEqual(state[staff._EMPLOYEE_SESSION_KEY]['business_id'], 'alpha')
            self.assertEqual(state[staff._EMPLOYEE_SESSION_KEY]['credential_version'], 'new')
            self.assertNotIn('platform_admin_authenticated', state)
        self.assertIsNone(self.client.get_cookie(COOKIE))

    def test_reset_does_not_clear_another_tenants_employee_session(self):
        with self.client.session_transaction() as state:
            state[staff._EMPLOYEE_SESSION_KEY] = {'business_id': 'beta'}
        with patch.object(recovery, 'consume', return_value=True):
            self.post('reset', token=TOKEN, password=PASSWORD)
        with self.client.session_transaction() as state:
            self.assertEqual(state[staff._EMPLOYEE_SESSION_KEY]['business_id'], 'beta')

    def test_rotated_version_invalidates_preexisting_employee_session(self):
        with self.app.test_request_context('/preview'), patch.object(staff, 'fetch_one', return_value={'id': 7}), \
                patch.object(employee_invitations, 'credential', return_value={'version': 'new'}):
            session[staff._EMPLOYEE_SESSION_KEY] = {'employee_id': 7, 'business_id': 'alpha',
                'issued_at': int(time.time()), 'credential_version': 'old'}
            self.assertIsNone(staff._current_employee('alpha'))
            self.assertNotIn(staff._EMPLOYEE_SESSION_KEY, session)


if __name__ == '__main__':
    unittest.main()
