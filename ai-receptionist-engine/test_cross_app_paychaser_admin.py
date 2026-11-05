"""Control Centre <-> PayChaser business administration, both real apps in one process.

Set PAYCHASER_REPO_PATH to a PayChaser checkout that contains the business admin
API. The PayChaser app runs on in-memory SQLite and requests never leave the
process, so no network, Stripe or production data is involved.
"""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PAYCHASER_PATH = os.environ.get('PAYCHASER_REPO_PATH', '')
TOKEN = 'e2e-service-token-' + 'x' * 40
HOST = 'https://paychaser.invalid'
BASE = '/staff/platform/paychaser/businesses'


class Reply:
    def __init__(self, response):
        self.response = response
        self.status_code = response.status_code
        self.ok = response.status_code < 400

    def json(self):
        return self.response.get_json()


@unittest.skipUnless(PAYCHASER_PATH and (Path(PAYCHASER_PATH) / 'paychaser').is_dir(), 'PAYCHASER_REPO_PATH not set')
class CrossAppPayChaserAdminTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, PAYCHASER_PATH)
        cls.addClassCleanup(sys.path.remove, PAYCHASER_PATH)
        environment = patch.dict(os.environ, {
            'DATABASE_URL': 'sqlite://', 'PAYCHASER_SEED_DEMO': 'false', 'SECRET_KEY': 'pc-test-secret',
            'PAYCHASER_CONTROL_CENTRE_API_TOKEN': TOKEN,
            'PAYCHASER_CONTROL_CENTRE_API_URL': HOST + '/api/platform/control-centre/v1/summary'})
        environment.start()
        cls.addClassCleanup(environment.stop)
        from paychaser import create_app
        cls.paychaser = create_app()
        cls.paychaser.config.update(TESTING=True)

    def setUp(self):
        from flask import Flask
        from paychaser.extensions import db
        from paychaser.models import Business, PlatformBusinessAudit
        from trimtech.modules.auth.routes import auth_blueprint
        from trimtech.modules.platform.routes import platform_blueprint
        from trimtech.modules.staff.routes import staff_blueprint
        self.db, self.Business, self.Audit = db, Business, PlatformBusinessAudit
        with self.paychaser.app_context():
            db.drop_all()
            db.create_all()
            business = Business(name='Alpha Ltd', slug='alpha', email='a@alpha.example')
            other = Business(name='Beta Ltd', slug='beta', email='b@beta.example')
            db.session.add_all([business, other])
            db.session.commit()
            self.business_id, self.other_id = business.id, other.id
        self.addCleanup(self.drop)
        env = patch.dict(os.environ, {
            'PAYCHASER_CONTROL_CENTRE_API_TOKEN': TOKEN, 'PLATFORM_ADMIN_USERNAME': 'owner',
            'PLATFORM_ADMIN_PASSWORD': 'owner-test-password-123',
            'PAYCHASER_CONTROL_CENTRE_API_URL': HOST + '/api/platform/control-centre/v1/summary'})
        env.start()
        self.addCleanup(env.stop)
        client = self.paychaser.test_client()

        def route(method, url, headers=None, json=None, **kwargs):
            self.assertTrue(url.startswith(HOST + '/'), url)
            return Reply(client.open(url[len(HOST):], method=method, headers=headers, json=json))
        import requests
        transport = patch.object(requests, 'request', route)
        transport.start()
        self.addCleanup(transport.stop)
        staff = Flask(__name__, template_folder=str(Path(__file__).parent / 'templates'))
        staff.config.update(SECRET_KEY='staff-test-secret', TESTING=True)
        for blueprint in (auth_blueprint, platform_blueprint, staff_blueprint):
            staff.register_blueprint(blueprint)
        self.staff = staff

    def drop(self):
        with self.paychaser.app_context():
            self.db.session.remove()
            self.db.drop_all()

    def owner(self, source='dedicated'):
        client = self.staff.test_client()
        with client.session_transaction() as session:
            session.update(platform_admin_authenticated=True, auth_role='platform_admin',
                           platform_admin_username='owner', platform_admin_auth_source=source,
                           _staff_csrf_token='ok')
        return client

    def form(self, **over):
        data = dict(csrf_token='ok', reason='Customer asked', name='Alpha Group', email='NEW@alpha.example',
                    phone='01', address_line_1='1 High St', address_line_2='', town_or_city='Leeds',
                    postcode='ls1 1aa', country_code='gb', company_number='123')
        data.update(over)
        return data

    def row(self, business_id):
        with self.paychaser.app_context():
            row = self.db.session.get(self.Business, business_id)
            return row.name, row.email, row.postcode, row.invoice_prefix

    def test_owner_lists_views_and_edits_with_audit(self):
        client = self.owner()
        listing = client.get(BASE)
        self.assertEqual(listing.status_code, 200)
        self.assertIn('Alpha Ltd', listing.get_data(as_text=True))
        self.assertEqual(client.get(f'{BASE}/{self.business_id}').status_code, 200)
        invoice_prefix = self.row(self.business_id)[3]
        self.assertEqual(client.post(f'{BASE}/{self.business_id}', data=self.form()).status_code, 302)
        self.assertEqual(self.row(self.business_id), ('Alpha Group', 'new@alpha.example', 'LS1 1AA', invoice_prefix))
        self.assertEqual(self.row(self.other_id)[0], 'Beta Ltd')
        with self.paychaser.app_context():
            audit = self.db.session.query(self.Audit).one()
            self.assertEqual((audit.actor, audit.reason), ('platform:owner', 'Customer asked'))
        page = client.get(f'{BASE}/{self.business_id}').get_data(as_text=True)
        self.assertIn('Alpha Group', page)
        self.assertNotIn(TOKEN, page)

    def test_invalid_input_is_rejected_and_nothing_is_written(self):
        client = self.owner()
        before = self.row(self.business_id)
        for bad in ({'name': ''}, {'email': 'not-an-email'}, {'reason': ''}, {'country_code': 'ZZZZ'}):
            self.assertIn(client.post(f'{BASE}/{self.business_id}', data=self.form(**bad)).status_code, (200, 302, 422))
        self.assertEqual(self.row(self.business_id), before)
        with self.paychaser.app_context():
            self.assertEqual(self.db.session.query(self.Audit).count(), 0)

    def test_unauthorised_access_is_denied_everywhere(self):
        anonymous = self.staff.test_client()
        shared = self.owner(source='shared')
        for client in (anonymous, shared):
            before = self.row(self.business_id)
            self.assertNotEqual(client.get(BASE).status_code, 200)
            self.assertNotEqual(client.get(f'{BASE}/{self.business_id}').status_code, 200)
            self.assertIn(client.post(f'{BASE}/{self.business_id}', data=self.form()).status_code, (302, 400, 401, 403))
            self.assertEqual(self.row(self.business_id), before)
        self.assertEqual(self.owner().post(f'{BASE}/{self.business_id}', data=self.form(csrf_token='wrong')).status_code, 400)
        direct = self.paychaser.test_client()
        url = f'/api/platform/control-centre/v1/businesses/{self.business_id}'
        self.assertEqual(direct.patch(url, json={'actor': 'x', 'reason': 'x', 'changes': {'name': 'Hack'}}).status_code, 401)
        self.assertEqual(self.row(self.business_id)[0], 'Alpha Ltd')


if __name__ == '__main__':
    unittest.main()
