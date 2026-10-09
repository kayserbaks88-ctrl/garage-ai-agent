import os
import unittest
from unittest.mock import Mock, patch

import requests
from flask import Flask, request

from dashboard_auth import dashboard_auth
from trimtech.modules.staff.routes import staff_blueprint, _address_lookup_requests, _site_values


class AddressLookupTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"STAFF_ADDRESS_LOOKUP_ENVIRONMENT": "staging",
            "STAFF_IDEAL_POSTCODES_API_KEY": "test-secret"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.provider = patch("trimtech.modules.staff.address_lookup.requests.get")
        self.get = self.provider.start()
        self.addCleanup(self.provider.stop)
        self.get.return_value = Mock(status_code=200)
        self.app = Flask(__name__)
        self.app.secret_key = "test-key"
        self.app.register_blueprint(dashboard_auth)
        self.app.register_blueprint(staff_blueprint)
        self.identity = patch('trimtech.modules.staff.manager_auth.identity', side_effect=lambda: {'id':'test-manager'} if request.cookies.get('__Host-staff_admin') else None)
        self.identity.start()
        self.addCleanup(self.identity.stop)
        self.membership = patch('trimtech.modules.staff.accounts.membership',return_value={'role':'owner'})
        self.membership.start()
        self.addCleanup(self.membership.stop)
        self.trial=patch('trimtech.modules.staff.onboarding.status',return_value={'state':'legacy'})
        self.trial.start();self.addCleanup(self.trial.stop)
        self.subscription=patch('trimtech.modules.staff.billing.entitlement',return_value={'managed':False,'paid':False})
        self.subscription.start();self.addCleanup(self.subscription.stop)
        self.client = self.app.test_client()
        self.client.set_cookie('__Host-staff_admin','unit-test-session')
        with self.client.session_transaction() as session:
            session["_staff_csrf_token"] = "csrf"
        _address_lookup_requests.clear()

    def post(self, **values):
        return self.client.post("/staff/alpha/sites/address-lookup",
            data={"csrf_token": "csrf", **values})

    def test_postcode_street_and_site_queries_use_uk_provider(self):
        self.get.return_value.json.return_value = {"code": 2000, "result": {"hits": [
            {"id": "paf_123", "suggestion": "Test Building, London SW1A 1AA", "latitude": 51}]}}
        for query in ("SW1A 1AA", "Test Street London", "Test Building"):
            result = self.post(query=query)
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json["suggestions"][0]["id"], "paf_123")
            self.assertEqual(self.get.call_args.kwargs["params"]["context"], "GBR")
            self.assertEqual(self.get.call_args.kwargs["params"]["query"], query)
            self.assertNotIn("api_key", self.get.call_args.kwargs["params"])
            self.assertNotIn(b"test-secret", result.data)
            self.assertIn("no-store", result.headers["Cache-Control"])

    def test_selection_returns_full_address_without_coordinates(self):
        self.get.return_value.json.return_value = {"code": 2000, "result": {
            "line_1": "Test Building", "line_2": "10 Test Street", "line_3": "",
            "post_town": "London", "postcode": "SW1A 1AA", "latitude": 51.5, "longitude": -0.1}}
        result = self.post(address_id="paf_123")
        self.assertEqual(result.json, {"address": "Test Building, 10 Test Street, London, SW1A 1AA"})
        self.assertTrue(self.get.call_args.args[0].endswith("/paf_123/gbr"))

    def test_staging_gate_and_missing_key_fail_without_network(self):
        for settings in ({"STAFF_ADDRESS_LOOKUP_ENVIRONMENT": "production"},
                         {"STAFF_IDEAL_POSTCODES_API_KEY": ""}):
            with patch.dict(os.environ, settings):
                self.assertEqual(self.post(query="London").status_code, 503)
        self.get.assert_not_called()

    def test_authentication_csrf_validation_and_rate_limit(self):
        self.assertEqual(self.client.post("/staff/alpha/sites/address-lookup", data={"query": "London"}).status_code, 400)
        for values in ({"query": "ab"}, {"query": "x" * 201}, {"address_id": "../keys"}):
            self.assertEqual(self.post(**values).status_code, 400)
        self.client.delete_cookie('__Host-staff_admin')
        self.assertEqual(self.post(query="London").status_code, 401)
        self.client.set_cookie('__Host-staff_admin','unit-test-session')
        import time
        _address_lookup_requests["alpha"] = (time.monotonic(), 60)
        self.assertEqual(self.post(query="London").status_code, 429)
        self.get.assert_not_called()

    def test_provider_failures_are_sanitized_and_empty_results_work(self):
        self.get.side_effect = requests.Timeout("test-secret")
        response = self.post(query="London")
        self.assertEqual(response.status_code, 503)
        self.assertNotIn(b"test-secret", response.data)
        self.get.side_effect = None
        for status in (401, 402, 429, 500):
            self.get.return_value.status_code = status
            self.assertEqual(self.post(query="London").status_code, 503)
        self.get.return_value.status_code = 200
        self.get.return_value.json.return_value = {"code": 2000, "result": {"hits": []}}
        self.assertEqual(self.post(query="London").json, {"suggestions": []})
        self.get.return_value.json.return_value = {"unexpected": "test-secret"}
        self.assertEqual(self.post(query="London").status_code, 503)

    def test_selected_address_requires_separate_coordinate_review(self):
        values = {"name": "Test", "latitude": "51.5", "longitude": "-0.1",
                  "allowed_radius_metres": "250", "address_lookup_selected": "1"}
        with self.assertRaises(ValueError):
            _site_values(values)
        self.assertEqual(_site_values({**values, "coordinates_reviewed": "on"})[0], "Test")
