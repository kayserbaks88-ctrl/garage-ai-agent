"""Marketing-only tests: disposable SQLite state, mocked verification and delivery."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from werkzeug.datastructures import MultiDict

from marketing_site import app as marketing
from marketing_site import demo_security as security


class DemoSecurityTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.environment = dict(
            MARKETING_DEMO_ENABLED='true', MARKETING_DEMO_PROTECTION_TESTED='true',
            MARKETING_TURNSTILE_SITE_KEY='local-configured-site-key',
            MARKETING_TURNSTILE_SECRET_KEY='local-configured-turnstile-secret',
            MARKETING_TURNSTILE_HOSTNAMES='marketing.example.test',
            MARKETING_DEMO_STATE_SECRET='local-isolated-state-secret-at-least-32-chars',
            MARKETING_DEMO_STATE_DB=str(self.directory / 'demo.sqlite3'),
        )
        env = patch.dict(os.environ, self.environment, clear=True)
        env.start()
        self.addCleanup(env.stop)
        marketing.app.testing = True
        self.client = marketing.app.test_client()
        self.senders = []
        for name in ('send_lead_notification', 'send_customer_confirmation', 'send_whatsapp_demo_confirmation'):
            sender = patch.object(marketing, name, return_value=(True, ''))
            self.senders.append(sender.start())
            self.addCleanup(sender.stop)
        outbound = patch.object(marketing, 'urlopen', side_effect=AssertionError('Unexpected delivery network call'))
        outbound.start()
        self.addCleanup(outbound.stop)
        verification = patch.object(security, 'urlopen')
        self.verify = verification.start()
        self.addCleanup(verification.stop)
        self.verification_response()

    def verification_response(self, **overrides):
        data = dict(success=True, hostname='marketing.example.test', action='marketing_demo',
                    challenge_ts=datetime.now(timezone.utc).isoformat())
        data.update(overrides)
        self.verify.return_value.__enter__.return_value.read.return_value = json.dumps(data).encode()

    def values(self, n=1, **overrides):
        values = dict(name='José O’Neill', business_name="O’Neill & Sons Garage Ltd", phone=f'07700000{n:03}',
                    email=f'owner{n}@example.test', contact_method='email', garage_size='2-5',
                    message='Please show us appointment booking.', website='',
                    **{'cf-turnstile-response': f'local-token-{n}'})
        values.update(overrides)
        return values

    def post(self, values=None, address='192.0.2.1'):
        return self.client.post('/demo', data=self.values() if values is None else values,
                                environ_overrides={'REMOTE_ADDR': address})

    def no_delivery(self):
        for sender in self.senders:
            sender.assert_not_called()

    def test_disabled_switch_is_first_and_rest_of_site_works(self):
        for value in ('false', '', 'garbage', '0'):
            with self.subTest(value=value), patch.dict(os.environ, MARKETING_DEMO_ENABLED=value):
                self.assertEqual(self.post().status_code, 503)
                landing = self.client.get('/')
                self.assertEqual(landing.status_code, 200)
                landing.close()
                self.assertEqual(self.client.get('/health').json['status'], 'ok')
                page = self.client.get('/demo')
                self.assertEqual(page.status_code, 200)
                self.assertIn(b'<fieldset disabled', page.data)
                self.assertNotIn(b'cf-turnstile"', page.data)
        self.verify.assert_not_called()
        self.no_delivery()

    def test_missing_configuration_or_testing_acknowledgement_fails_closed(self):
        for name in self.environment:
            with self.subTest(name=name), patch.dict(os.environ):
                os.environ.pop(name)
                self.assertEqual(self.post().status_code, 503)
        self.verify.assert_not_called()
        self.no_delivery()

    def test_cloudflare_dummy_keys_and_unsafe_proxy_config_cannot_open_form(self):
        for name, value in [('MARKETING_TURNSTILE_SITE_KEY', '1x00000000000000000000AA'),
                            ('MARKETING_TURNSTILE_SECRET_KEY', '1x0000000000000000000000000000000AA'),
                            ('MARKETING_DEMO_TRUSTED_PROXY_CIDRS', '0.0.0.0/0'),
                            ('MARKETING_DEMO_TRUSTED_PROXY_CIDRS', 'invalid')]:
            with self.subTest(name=name), patch.dict(os.environ, {name: value}):
                self.assertEqual(self.post().status_code, 503)
        self.no_delivery()

    def test_form_enables_button_only_after_challenge_and_never_exposes_secrets(self):
        page = self.client.get('/demo')
        self.assertIn(b'data-action="marketing_demo"', page.data)
        self.assertIn(b'id="demo-submit" class="submit" type="submit" disabled', page.data)
        self.assertIn(b'data-expired-callback="demoExpired"', page.data)
        self.assertIn(b'name="website"', page.data)
        self.assertEqual(page.headers['Cache-Control'], 'no-store')
        self.assertNotIn(self.environment['MARKETING_TURNSTILE_SECRET_KEY'].encode(), page.data)

    def test_genuine_enquiry_verified_then_sent_once_with_normalized_values(self):
        values = self.values()
        values['email'] = ' OWNER1@EXAMPLE.TEST '
        values['phone'] = '+44 7700 000001'
        self.assertEqual(self.post(values).status_code, 200)
        for sender in self.senders:
            sender.assert_called_once()
            self.assertEqual(sender.call_args.args[0]['email'], 'owner1@example.test')
            self.assertEqual(sender.call_args.args[0]['phone'], '07700000001')
        outbound = self.verify.call_args.args[0]
        self.assertEqual(outbound.full_url, security.SITEVERIFY)
        self.assertEqual(self.verify.call_args.kwargs['timeout'], 5)
        self.assertIn(b'remoteip=192.0.2.1', outbound.data)

    def test_links_markup_controls_and_obfuscated_links_in_names_are_rejected(self):
        attacks = ['https://evil.test', 'www.evil.test', 'evil.com', 'evil . com', '<a href=x>Click</a>',
                   'https%3A%2F%2Fevil.test', 'https：／／evil.test', 'James\r\nBcc:spam@test', 'hello\u200bworld']
        for field in ('name', 'business_name'):
            for attack in attacks:
                with self.subTest(field=field, attack=attack):
                    self.assertEqual(self.post(self.values(**{field: attack}), address=f'192.0.2.{attacks.index(attack)+10}').status_code, 400)
        self.verify.assert_not_called()
        self.no_delivery()

    def test_honeypot_and_invalid_fields_never_verify_or_send(self):
        bad_values = [('website', 'https://spam.test'), ('email', 'not-an-email'), ('phone', 'random'),
                      ('name', 'x'*121), ('business_name', 'x'*161), ('message', 'x'*1001),
                      ('contact_method', 'sms'), ('garage_size', 'invented'), ('cf-turnstile-response', '')]
        for n, (field, value) in enumerate(bad_values):
            values = self.values()
            values[field] = value
            with self.subTest(field=field):
                self.assertEqual(self.post(values, address=f'192.0.2.{n+10}').status_code, 400)
        self.verify.assert_not_called()
        self.no_delivery()

    def test_duplicate_fields_unknown_fields_and_oversized_requests_rejected(self):
        values = MultiDict(self.values())
        values.add('name', 'Other Name')
        self.assertEqual(self.post(values).status_code, 400)
        values = self.values()
        values['approved'] = 'true'
        self.assertEqual(self.post(values).status_code, 400)
        self.assertEqual(self.client.post('/demo', data='a'*16385, content_type='application/x-www-form-urlencoded').status_code, 413)
        self.assertEqual(self.client.post('/demo', json=self.values()).status_code, 415)
        self.no_delivery()

    def test_verification_requires_success_expected_hostname_action_and_fresh_timestamp(self):
        invalid = [dict(success=False), dict(success=1), dict(hostname='evil.test'), dict(action='login'),
                   dict(challenge_ts='invalid'), dict(challenge_ts=datetime.now().isoformat()),
                   dict(challenge_ts=(datetime.now(timezone.utc)-timedelta(minutes=6)).isoformat()),
                   dict(challenge_ts=(datetime.now(timezone.utc)+timedelta(minutes=2)).isoformat())]
        for n, values in enumerate(invalid):
            with self.subTest(values=values):
                self.verification_response(**values)
                self.assertEqual(self.post(address=f'192.0.2.{n+10}').status_code, 400)
        self.no_delivery()

    def test_verification_outage_malformed_reply_and_missing_fields_fail_closed(self):
        self.verify.side_effect = TimeoutError()
        self.assertEqual(self.post().status_code, 400)
        self.verify.side_effect = None
        for body in (b'not json', b'{}', b'[]'):
            self.verify.return_value.__enter__.return_value.read.return_value = body
            self.assertEqual(self.post().status_code, 400)
        self.no_delivery()

    def test_ip_rate_limit_survives_new_clients_and_ignores_spoofed_forwarded_headers(self):
        values = self.values()
        values['website'] = 'bot'
        for _ in range(5):
            self.assertEqual(self.post(values).status_code, 400)
        client = marketing.app.test_client()
        response = client.post('/demo', data=self.values(), headers={'X-Forwarded-For': '203.0.113.123'}, environ_overrides={'REMOTE_ADDR': '192.0.2.1'})
        self.assertEqual(response.status_code, 429)
        self.verify.assert_not_called()
        self.no_delivery()

    def test_trusted_proxy_uses_rightmost_untrusted_address(self):
        with patch.dict(os.environ, MARKETING_DEMO_TRUSTED_PROXY_CIDRS='10.0.0.0/8'):
            with marketing.app.test_request_context('/demo', environ_overrides={'REMOTE_ADDR': '10.0.0.5'},
                                                   headers={'X-Forwarded-For': '1.2.3.4, 192.0.2.10, 10.0.0.6'}):
                self.assertEqual(security.client_address(marketing.request, security.configuration()), '192.0.2.10')

    def test_contact_and_token_duplicates_rejected_across_clients(self):
        self.assertEqual(self.post().status_code, 200)
        cases = [self.values(), self.values(2), self.values(3), self.values(4)]
        cases[1]['email'] = ' OWNER1@EXAMPLE.TEST '
        cases[2]['phone'] = '+44 7700 000001'
        cases[3]['cf-turnstile-response'] = 'local-token-1'
        for values in cases:
            self.assertEqual(self.post(values, address='192.0.2.2').status_code, 409)
        for sender in self.senders:
            self.assertEqual(sender.call_count, 1)

    def test_concurrent_duplicates_are_reserved_atomically(self):
        def submit(n):
            return marketing.app.test_client().post('/demo', data=self.values(), environ_overrides={'REMOTE_ADDR': f'192.0.2.{n}'}).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            codes = sorted(pool.map(submit, (10, 11)))
        self.assertEqual(codes, [200, 409])
        for sender in self.senders:
            self.assertEqual(sender.call_count, 1)

    def test_daily_global_delivery_budget_caps_distributed_spam(self):
        for n in range(1, 11):
            self.assertEqual(self.post(self.values(n), address=f'192.0.2.{n}').status_code, 200)
        self.assertEqual(self.post(self.values(11), address='192.0.2.11').status_code, 429)
        for sender in self.senders:
            self.assertEqual(sender.call_count, 10)

    def test_storage_failure_prevents_verification_and_delivery(self):
        with patch.dict(os.environ, MARKETING_DEMO_STATE_DB=str(self.directory)):
            self.assertEqual(self.post().status_code, 503)
        self.verify.assert_not_called()
        self.no_delivery()

    def test_global_attempt_limit_blocks_distributed_invalid_requests(self):
        values = self.values(website='bot')
        for n in range(100):
            self.assertEqual(self.post(values, address=f'192.0.2.{n+1}').status_code, 400)
        self.assertEqual(self.post(address='192.0.2.200').status_code, 429)
        self.verify.assert_not_called()
        self.no_delivery()

    def test_failed_delivery_is_not_repeated_on_retry(self):
        for sender in self.senders:
            sender.return_value = (False, 'local mocked failure')
        self.assertEqual(self.post().status_code, 200)
        self.assertEqual(self.post().status_code, 409)
        for sender in self.senders:
            self.assertEqual(sender.call_count, 1)

    def test_route_inventory_includes_staff_marketing_page(self):
        self.assertEqual({rule.rule for rule in marketing.app.url_map.iter_rules()}, {'/', '/staff-manager', '/demo', '/health', '/static/<path:filename>'})


if __name__ == '__main__':
    unittest.main()
