"""Compatibility-to-full-PWA contract; no production or provider access."""
import json
import unittest
from types import SimpleNamespace

from flask import Blueprint, Flask, current_app

from test_staff_pwa import ROOT, preview_app
from trimtech.modules.staff import pwa_compat


class Deployment2ContractTests(unittest.TestCase):
    def setUp(self):
        self.full = preview_app()
        self.compat = Flask('compatibility_contract', static_folder=str(ROOT / 'static'),
                            template_folder=str(ROOT / 'templates'))
        bp = Blueprint('staff', 'compatibility_contract', url_prefix='/staff')
        pwa_compat.register_routes(SimpleNamespace(staff_blueprint=bp, current_app=current_app))
        self.compat.register_blueprint(bp)

    def test_manifest_identity_and_assets_equal_compatibility_release(self):
        path = '/staff/employee/app/manifest.webmanifest'
        full = json.loads(self.full.test_client().get(path).data)
        compat = json.loads(self.compat.test_client().get(path).data)
        self.assertEqual(full, compat)
        self.assertEqual(full['id'], '/staff/employee/app')
        self.assertEqual(full['scope'], '/staff/')

    def test_stable_public_routes_registered_exactly_once(self):
        for path in ['/staff/employee/app', '/staff/employee/app/install',
                     '/staff/employee/app/offline',
                     '/staff/employee/app/manifest.webmanifest', '/staff/employee-sw.js']:
            for app in [self.full, self.compat]:
                rules = [r for r in app.url_map.iter_rules() if r.rule == path]
                self.assertEqual(len(rules), 1, path)
                self.assertIn('GET', rules[0].methods)
                self.assertNotIn('POST', rules[0].methods)

    def test_both_worker_versions_share_url_without_storage_or_reload(self):
        for app in [self.full, self.compat]:
            response = app.test_client().get('/staff/employee-sw.js')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.mimetype, 'application/javascript')
            self.assertNotIn('Location', response.headers)
            source = response.text
            for forbidden in ['caches.', 'indexedDB', 'localStorage', 'location.reload',
                              'registration.sync', 'setInterval']:
                self.assertNotIn(forbidden, source)
        compat_source = self.compat.test_client().get('/staff/employee-sw.js').text
        self.assertNotIn("addEventListener('fetch'", compat_source)

    def test_offline_document_remains_public_and_identical_on_rollback(self):
        path = '/staff/employee/app/offline'
        self.assertEqual(self.full.test_client().get(path).data,
                         self.compat.test_client().get(path).data)


if __name__ == '__main__':
    unittest.main()
