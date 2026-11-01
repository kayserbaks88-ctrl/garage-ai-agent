"""Registration abuse protection; no database, Cloudflare or email access."""
import unittest
from unittest.mock import patch

import requests

from test_staff_account_ui import preview_app
from trimtech.modules.staff import accounts, manager_auth, registration_protection as protection

ORIGINAL_LIMITED = accounts.limited
ENV = {'STAFF_REGISTRATION_ENABLED': '1', 'TURNSTILE_SITE_KEY': '', 'TURNSTILE_SECRET_KEY': ''}
TURNSTILE = {**ENV, 'TURNSTILE_SITE_KEY': 'site-test', 'TURNSTILE_SECRET_KEY': 'secret-test'}
FORM = {'business_name': 'Oakfield Test Ltd', 'contact_name': 'Owner', 'email': 'owner@example.test',
        'password': 'a long synthetic passphrase'}


class Reply:
    def __init__(self, body, ok=True):
        self.body, self.ok = body, ok

    def raise_for_status(self):
        if not self.ok:
            raise requests.HTTPError('bad status')

    def json(self):
        if self.body is None:
            raise ValueError('not json')
        return self.body


class RegistrationBase(unittest.TestCase):
    environment = ENV

    def setUp(self):
        self.client = preview_app().test_client()
        patches = [patch.dict('os.environ', self.environment),
                   patch.object(accounts, 'limited', return_value=True),
                   patch.object(accounts, 'register', return_value=('owner@example.test', 'raw-token')),
                   patch.object(accounts, 'send_link')]
        self.environ, self.limited, self.register, self.send = [p.start() for p in patches]
        for p in patches:
            self.addCleanup(p.stop)

    def page(self):
        html = self.client.get('/staff/account/register').get_data(as_text=True)
        with self.client.session_transaction() as session:
            return html, session['_staff_register_nonce'], session['_staff_csrf_token']

    def post(self, nonce=None, csrf=None, **extra):
        data = {**FORM, **extra}
        if csrf is not None:
            data['csrf_token'] = csrf
        if nonce is not None:
            data['form_nonce'] = nonce
        return self.client.post('/staff/account/register', data=data, base_url='https://localhost')

    def submit(self, **extra):
        _, nonce, csrf = self.page()
        return self.post(nonce, csrf, **extra)


class AutomatedSubmissionTests(RegistrationBase):
    def test_legitimate_registration_still_works_without_turnstile_configured(self):
        html, _, _ = self.page()
        self.assertIn('name="form_nonce"', html)
        self.assertNotIn('cf-turnstile', html)
        response = self.submit()
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Request received', response.data)
        self.register.assert_called_once()
        self.send.assert_called_once()

    def test_honeypot_returns_normal_reply_but_creates_and_sends_nothing(self):
        response = self.submit(company_website='http://spam.example')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Request received', response.data)
        self.register.assert_not_called()
        self.send.assert_not_called()

    def test_direct_post_without_a_loaded_form_is_rejected(self):
        with self.client.session_transaction() as session:
            session['_staff_csrf_token'] = 'csrf'
        response = self.post('guessed-nonce', 'csrf')
        self.assertEqual(response.status_code, 400)
        self.register.assert_not_called()

    def test_wrong_and_missing_nonce_are_rejected(self):
        _, nonce, csrf = self.page()
        self.assertEqual(self.post('not-the-nonce', csrf).status_code, 400)
        _, nonce, csrf = self.page()
        self.assertEqual(self.post(None, csrf).status_code, 400)
        self.register.assert_not_called()


class DuplicateSubmissionTests(RegistrationBase):
    def test_replayed_form_submission_is_rejected_and_registers_once(self):
        _, nonce, csrf = self.page()
        self.assertEqual(self.post(nonce, csrf).status_code, 200)
        replay = self.post(nonce, csrf)
        self.assertEqual(replay.status_code, 400)
        self.assertIn(b'already submitted', replay.data)
        self.assertEqual(self.register.call_count, 1)
        self.assertEqual(self.send.call_count, 1)

    def test_validation_error_reissues_a_fresh_form_token(self):
        self.register.side_effect = ValueError('Enter a valid email address.')
        _, nonce, csrf = self.page()
        self.assertEqual(self.post(nonce, csrf).status_code, 400)
        self.register.side_effect = None
        with self.client.session_transaction() as session:
            fresh = session['_staff_register_nonce']
        self.assertNotEqual(fresh, nonce)
        self.assertEqual(self.post(fresh, csrf).status_code, 200)

    def test_existing_email_gets_the_same_reply_and_no_second_email(self):
        self.register.return_value = None
        first = self.submit()
        self.assertEqual(first.status_code, 200)
        self.assertIn(b'Request received', first.data)
        self.send.assert_called_once_with(None, 'verify', unittest.mock.ANY)


class RateLimitTests(RegistrationBase):
    def test_registration_tightens_only_the_per_email_limit_and_blocks_when_exceeded(self):
        self.limited.return_value = False
        response = self.submit()
        self.assertEqual(response.status_code, 429)
        self.register.assert_not_called()
        # Without trusted proxy CIDRs all visitors share one address bucket, so it must not be tightened.
        self.assertEqual(self.limited.call_args.kwargs, {'identity_limit': 3})

    def test_other_actions_keep_their_existing_limits(self):
        self.assertEqual(ORIGINAL_LIMITED.__kwdefaults__, {'identity_limit': 5, 'address_limit': 30})


class TurnstileConfiguredTests(RegistrationBase):
    environment = TURNSTILE

    def test_widget_and_script_render_only_when_configured(self):
        html, _, _ = self.page()
        self.assertIn('data-sitekey="site-test"', html)
        self.assertIn('https://challenges.cloudflare.com/turnstile/v0/api.js', html)
        self.assertNotIn('secret-test', html)

    def test_missing_token_is_rejected_before_any_account_is_created(self):
        with patch.object(protection.requests, 'post') as call:
            response = self.submit()
        self.assertEqual(response.status_code, 400)
        call.assert_not_called()
        self.register.assert_not_called()

    def test_invalid_token_is_rejected(self):
        with patch.object(protection.requests, 'post', return_value=Reply({'success': False})):
            response = self.submit(**{'cf-turnstile-response': 'bad'})
        self.assertEqual(response.status_code, 400)
        self.register.assert_not_called()

    def test_non_boolean_success_is_not_accepted(self):
        with patch.object(protection.requests, 'post', return_value=Reply({'success': 'true'})):
            self.assertEqual(self.submit(**{'cf-turnstile-response': 'x'}).status_code, 400)

    def test_cloudflare_outage_fails_closed(self):
        for failure in (requests.ConnectionError('down'), requests.Timeout('slow')):
            with patch.object(protection.requests, 'post', side_effect=failure):
                self.assertEqual(self.submit(**{'cf-turnstile-response': 'x'}).status_code, 503)
        for reply in (Reply({}, ok=False), Reply(None)):
            with patch.object(protection.requests, 'post', return_value=reply):
                self.assertEqual(self.submit(**{'cf-turnstile-response': 'x'}).status_code, 503)
        self.register.assert_not_called()

    def test_valid_token_registers_and_secret_goes_only_to_cloudflare(self):
        with patch.object(protection.requests, 'post', return_value=Reply({'success': True})) as call:
            response = self.submit(**{'cf-turnstile-response': 'good-token'})
        self.assertEqual(response.status_code, 200)
        self.register.assert_called_once()
        args, kwargs = call.call_args
        self.assertEqual(args[0], 'https://challenges.cloudflare.com/turnstile/v0/siteverify')
        self.assertEqual(kwargs['data']['response'], 'good-token')
        self.assertEqual(kwargs['data']['secret'], 'secret-test')
        self.assertEqual(kwargs['timeout'], 5)
        self.assertNotIn(b'secret-test', response.data)

    def test_one_key_alone_does_not_enable_or_break_registration(self):
        with patch.dict('os.environ', {'TURNSTILE_SECRET_KEY': ''}):
            self.assertEqual(self.submit().status_code, 200)


class UnchangedFlowTests(RegistrationBase):
    def test_closed_registration_stays_closed(self):
        with patch.dict('os.environ', {'STAFF_REGISTRATION_ENABLED': '0'}):
            self.assertEqual(self.client.get('/staff/account/register').status_code, 503)
            self.assertEqual(self.client.get('/staff/account/login').status_code, 200)

    def test_email_verification_still_gates_the_trial_and_login(self):
        import inspect
        from trimtech.modules.staff import onboarding
        self.assertIn('a.verified_at IS NOT NULL', inspect.getsource(onboarding.activate))
        self.assertIn('verified_at', inspect.getsource(accounts.authenticate))


if __name__ == '__main__':
    unittest.main()
