"""Recovery routes and token guards; no database, network or migrations."""
import unittest
from unittest.mock import MagicMock, patch

from test_staff_account_ui import preview_app
from trimtech.modules.staff import accounts
from trimtech.modules.staff.manager_auth import COOKIE


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.app = preview_app()
        self.app.testing = True
        self.client = self.app.test_client()
        with self.client.session_transaction() as session:
            session['_staff_csrf_token'] = 'recovery-csrf'
        self.token = 'A' * 43
        self.password = 'a new long recovery passphrase'
        limited = patch.object(accounts, 'limited', return_value=True)
        limited.start()
        self.addCleanup(limited.stop)

    def submit(self):
        return self.client.post('/staff/account/reset', data={
            'csrf_token': 'recovery-csrf', 'token': self.token, 'password': self.password})

    def test_success_redirect_refresh_and_sign_in_navigation(self):
        with patch.object(accounts, 'consume', return_value=True) as consume:
            response = self.submit()
            self.assertEqual(response.status_code, 303)
            self.assertEqual(response.location, '/staff/account/reset/success')
            self.assertNotIn(self.token, response.location)
            self.assertIn('no-store', response.headers['Cache-Control'])
            self.assertTrue(any(c.startswith(COOKIE + '=;') and 'Secure' in c and 'HttpOnly' in c
                                for c in response.headers.getlist('Set-Cookie')))
            for _ in range(2):
                success = self.client.get(response.location)
                self.assertIn(b'Password updated successfully', success.data)
                self.assertIn(b'href="/staff/account/login">Sign in</a>', success.data)
                self.assertNotIn(b'<form', success.data)
                self.assertIn('no-store', success.headers['Cache-Control'])
            consume.assert_called_once_with(self.token, 'reset', self.password)
        login = self.client.get('/staff/account/login')
        self.assertIn(b'action="/staff/account/login"', login.data)
        with patch.object(accounts, 'authenticate', return_value='new-session'), patch.object(accounts, 'revoke'):
            signed_in = self.client.post('/staff/account/login', data={
                'csrf_token': 'recovery-csrf', 'email': 'owner@example.test', 'password': self.password})
        self.assertEqual(signed_in.location, '/staff/account')
        self.assertTrue(any('Secure' in c and 'HttpOnly' in c and 'SameSite=Lax' in c
                            for c in signed_in.headers.getlist('Set-Cookie') if c.startswith(COOKIE + '=')))

    def test_duplicate_post_and_replay_offer_sign_in_without_success_claim(self):
        with patch.object(accounts, 'consume', side_effect=[True, False]):
            self.assertEqual(self.submit().status_code, 303)
            replay = self.submit()
        self.assertEqual(replay.status_code, 400)
        self.assertIn(b'If you already updated your password, you can sign in.', replay.data)
        self.assertIn(b'href="/staff/account/login">Sign in</a>', replay.data)
        self.assertIn(b'Request a new reset email', replay.data)
        self.assertNotIn(b'Password updated successfully', replay.data)
        self.assertNotIn(b'data-reset-form', replay.data)
        self.assertNotIn(self.token.encode(), replay.data)

    def test_csrf_still_required_and_password_validation_allows_retry(self):
        with patch.object(accounts, 'consume') as consume:
            self.assertEqual(self.client.post('/staff/account/reset', data={
                'token': self.token, 'password': self.password}).status_code, 400)
            consume.assert_not_called()
        with patch.object(accounts, 'consume', side_effect=ValueError('Use a longer password.')):
            response = self.submit()
        self.assertEqual(response.status_code, 400)
        self.assertIn(b'data-reset-form', response.data)
        self.assertIn(self.token.encode(), response.data)
        self.assertNotIn(self.password.encode(), response.data)

    def test_reset_get_never_consumes_a_token(self):
        with patch.object(accounts, 'consume') as consume:
            response = self.client.get('/staff/account/reset')
            self.assertEqual(response.status_code, 200)
            self.assertIn('no-store', response.headers['Cache-Control'])
            consume.assert_not_called()

    def test_rate_limits_and_temporary_failure_remain_safe(self):
        with patch.object(accounts, 'limited', return_value=False), patch.object(accounts, 'consume') as consume:
            self.assertEqual(self.submit().status_code, 429)
            consume.assert_not_called()
        from trimtech.modules.staff.database import StaffDatabaseError
        with patch.object(accounts, 'consume', side_effect=StaffDatabaseError('private details')):
            response = self.submit()
        self.assertEqual(response.status_code, 503)
        self.assertIn(b'data-reset-form', response.data)
        self.assertNotIn(b'private details', response.data)

    def test_email_verification_still_returns_its_existing_sign_in_form(self):
        with patch.object(accounts, 'consume', return_value=True):
            response = self.client.post('/staff/account/verify', data={
                'csrf_token': 'recovery-csrf', 'token': self.token, 'password': self.password})
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Email verified. You can now sign in.', response.data)
        self.assertIn(b'action="/staff/account/login"', response.data)


class RecoveryTokenTests(unittest.TestCase):
    def test_one_time_expiry_and_session_revocation_guards_are_preserved(self):
        for rows, expected in (([('owner',), ('owner',)], True), ([('owner',), None], False), ([None], False)):
            with self.subTest(rows=rows):
                connection = MagicMock()
                cursor = connection.cursor.return_value.__enter__.return_value
                cursor.fetchone.side_effect = rows
                with patch.object(accounts, 'transaction') as transaction, patch.object(accounts, 'password_hash', return_value='hashed'):
                    transaction.return_value.__enter__.return_value = connection
                    self.assertEqual(accounts.consume('A' * 43, 'reset', 'new passphrase'), expected)
                statements = [call.args[0] for call in cursor.execute.call_args_list]
                self.assertIn('FOR UPDATE OF a', statements[0])
                self.assertEqual(cursor.execute.call_args_list[0].args[1][1], 'reset')
                if len(rows) == 2:
                    self.assertIn('consumed_at IS NULL AND expires_at>NOW()', statements[1])
                self.assertEqual(any('DELETE FROM sm_sessions' in sql for sql in statements), expected)
                self.assertEqual(any('SET password_hash=' in sql for sql in statements), expected)


if __name__ == '__main__':
    unittest.main()
