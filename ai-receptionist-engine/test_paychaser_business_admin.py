import os
import unittest
from unittest.mock import patch

import requests
from flask import Flask

from trimtech.modules.auth.routes import auth_blueprint
from trimtech.modules.platform.routes import platform_blueprint
from trimtech.modules.staff import paychaser_integration as paychaser
from trimtech.modules.staff.routes import staff_blueprint

TOKEN = 'pc-service-token-' + 'x' * 40
SUMMARY_URL = 'https://paychaser.example/api/platform/control-centre/v1/summary'
BUSINESS = {
    'id': 7, 'slug': 'alpha', 'name': 'Alpha Ltd', 'email': 'a@alpha.example', 'phone': '', 'address_line_1': '',
    'address_line_2': '', 'town_or_city': '', 'postcode': '', 'country_code': 'GB', 'company_number': '',
    'created_at': '2026-01-01T00:00:00+00:00', 'updated_at': '2026-01-02T00:00:00+00:00',
    'trial_started_at': None, 'member_count': 2,
    'subscription': {'status': 'active', 'current_period_end': None, 'cancel_at_period_end': False},
    'stripe_customer_id': 'cus_must_not_render', 'invoice_prefix': 'LEAK',
}


class FakeResponse:
    def __init__(self, status, payload):
        self.status_code, self._payload = status, payload
        self.ok = 200 <= status < 300

    def json(self):
        if self._payload is None:
            raise ValueError('no json')
        return self._payload


class PayChaserBusinessAdminTests(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.config.update(SECRET_KEY='test-only-secret', TESTING=True)
        for blueprint in (auth_blueprint, platform_blueprint, staff_blueprint):
            app.register_blueprint(blueprint)
        env = patch.dict(os.environ, PLATFORM_ADMIN_USERNAME='test-admin', PLATFORM_ADMIN_PASSWORD='test-only-password',
                         PAYCHASER_CONTROL_CENTRE_API_URL=SUMMARY_URL, PAYCHASER_CONTROL_CENTRE_API_TOKEN=TOKEN)
        env.start()
        self.addCleanup(env.stop)
        self.app = app
        self.client = self.login(app.test_client())
        self.calls = []

    def login(self, client, source='dedicated'):
        with client.session_transaction() as session:
            session.update(platform_admin_authenticated=True, auth_role='platform_admin',
                           platform_admin_username='test-admin', platform_admin_auth_source=source,
                           _staff_csrf_token='csrf-ok')
        return client

    def fake(self, responses):
        def request(method, url, **kwargs):
            self.calls.append((method, url, kwargs))
            return responses.pop(0) if isinstance(responses, list) else responses(method, url, kwargs)
        return patch.object(requests, 'request', request)

    def test_list_and_detail_pages_render_whitelisted_fields_only(self):
        with self.fake([FakeResponse(200, {'schema_version': 1, 'businesses': [BUSINESS]}), FakeResponse(200, {'schema_version': 1, 'business': BUSINESS})]):
            listing = self.client.get('/staff/platform/paychaser/businesses')
            detail = self.client.get('/staff/platform/paychaser/businesses/7')
        self.assertEqual((listing.status_code, detail.status_code), (200, 200))
        for page in (listing, detail):
            text = page.get_data(as_text=True)
            self.assertIn('Alpha Ltd', text)
            for secret in ('cus_must_not_render', 'LEAK', TOKEN):
                self.assertNotIn(secret, text)
        method, url, kwargs = self.calls[0]
        self.assertEqual((method, url), ('GET', 'https://paychaser.example/api/platform/control-centre/v1/businesses'))
        self.assertEqual(kwargs['headers']['Authorization'], 'Bearer ' + TOKEN)
        self.assertFalse(kwargs['allow_redirects'])

    def test_successful_edit_sends_audited_patch_with_actor_and_reason(self):
        form = {'csrf_token': 'csrf-ok', 'reason': 'Customer asked', 'name': 'Alpha Group', 'email': 'a@alpha.example',
                'phone': '', 'address_line_1': '', 'address_line_2': '', 'town_or_city': '', 'postcode': '',
                'country_code': 'GB', 'company_number': '', 'invoice_prefix': 'HACK', 'currency': 'USD'}
        with self.fake([FakeResponse(200, {'schema_version': 1, 'business': dict(BUSINESS, name='Alpha Group')})]):
            response = self.client.post('/staff/platform/paychaser/businesses/7', data=form)
        self.assertEqual(response.status_code, 302)
        method, url, kwargs = self.calls[0]
        self.assertEqual((method, url.rsplit('/', 1)[1]), ('PATCH', '7'))
        body = kwargs['json']
        self.assertEqual((body['actor'], body['reason']), ('platform:test-admin', 'Customer asked'))
        self.assertEqual(set(body['changes']), set(paychaser.PROFILE_FIELDS))
        self.assertNotIn('invoice_prefix', body['changes'])
        self.assertNotIn('currency', body['changes'])

    def test_validation_errors_are_shown_and_service_failures_are_safe(self):
        form = {'csrf_token': 'csrf-ok', 'reason': 'r', 'name': ''}
        with self.fake([FakeResponse(422, {'error': 'validation_failed', 'fields': {'name': 'Enter the business name.'}})]):
            response = self.client.post('/staff/platform/paychaser/businesses/7', data=form, follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        with self.client.session_transaction() as session:
            flashes = [message for _, message in session['_flashes']]
        self.assertIn('Enter the business name.', ' '.join(flashes))
        for outcome in (requests.Timeout(), requests.ConnectionError('http://secret-host token')):
            def boom(*args, **kwargs):
                raise outcome
            with patch.object(requests, 'request', boom):
                page = self.client.get('/staff/platform/paychaser/businesses')
            self.assertEqual(page.status_code, 503)
            self.assertNotIn('secret-host', page.get_data(as_text=True))
        with self.fake([FakeResponse(404, None)]):
            self.assertEqual(self.client.get('/staff/platform/paychaser/businesses/99').status_code, 404)
        with self.fake([FakeResponse(200, {'schema_version': 1, 'businesses': [{'id': 'x'}]})]):
            self.assertEqual(self.client.get('/staff/platform/paychaser/businesses').status_code, 503)

    def test_unconfigured_integration_never_calls_paychaser(self):
        with patch.dict(os.environ, {'PAYCHASER_CONTROL_CENTRE_API_URL': ''}):
            with self.fake([]):
                self.assertEqual(self.client.get('/staff/platform/paychaser/businesses').status_code, 503)
                self.client.post('/staff/platform/paychaser/businesses/7', data={'csrf_token': 'csrf-ok', 'reason': 'r'})
        self.assertEqual(self.calls, [])

    def test_only_dedicated_platform_owner_with_csrf_can_use_it(self):
        paths = ['/staff/platform/paychaser/businesses', '/staff/platform/paychaser/businesses/7']
        data = {'csrf_token': 'csrf-ok', 'name': 'Hacked', 'reason': 'x'}
        anonymous = self.app.test_client()
        shared = self.login(self.app.test_client(), source='shared')
        with self.fake([]):
            for client in (anonymous, shared):
                for path in paths:
                    self.assertIn(client.get(path).status_code, (302, 401, 403), path)
                self.assertIn(client.post(paths[1], data=data).status_code, (302, 400, 401, 403))
            self.assertEqual(self.client.post(paths[1], data={'name': 'No csrf', 'reason': 'x'}).status_code, 400)
        self.assertEqual(self.calls, [])


if __name__ == '__main__':
    unittest.main()
