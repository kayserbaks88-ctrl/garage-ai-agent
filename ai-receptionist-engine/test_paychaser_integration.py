import os
import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

import requests

from trimtech.modules.staff import paychaser_integration


TOKEN = 'local-test-service-token-' + ('x' * 40)
API_URL = 'https://paychaser.example.test/api/platform/control-centre/v1/summary'


def summary_payload():
    return {
        'schema_version': 1,
        'as_of': '2026-10-30T15:00:00+00:00',
        'data_freshness': 'live_database_query',
        'business_records_updated_at': '2026-10-30T14:00:00+00:00',
        'subscription_records_updated_at': '2026-10-30T14:30:00+00:00',
        'registered_businesses': 4,
        'businesses_without_subscription': 2,
        'active_trials': 1,
        'subscription_status_counts': {
            'active': 1,
            'trialing': 1,
            'past_due': 0,
            'canceled': 0,
            'unpaid': 0,
            'incomplete': 0,
            'incomplete_expired': 0,
            'checkout_pending': 0,
            'other': 0,
        },
        'scheduled_cancellations': 1,
    }


class PayChaserIntegrationClientTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(
            os.environ,
            {
                'PAYCHASER_CONTROL_CENTRE_API_URL': API_URL,
                'PAYCHASER_CONTROL_CENTRE_API_TOKEN': TOKEN,
            },
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_summary_uses_bearer_auth_https_and_bounded_timeout(self):
        response = Mock(ok=True, status_code=200)
        response.json.return_value = summary_payload()
        with patch.object(
            paychaser_integration.requests,
            'get',
            return_value=response,
        ) as get:
            result = paychaser_integration.fetch_summary()

        self.assertTrue(result['available'])
        self.assertEqual(result['status'], 'connected')
        self.assertEqual(result['data']['registered_businesses'], 4)
        self.assertEqual(result['data']['active_trials'], 1)
        self.assertEqual(result['data']['scheduled_cancellations'], 1)
        self.assertEqual(result['data']['as_of'].tzinfo, timezone.utc)
        self.assertEqual(
            result['data']['subscription_records_updated_at'].hour,
            14,
        )
        self.assertEqual(get.call_args.args[0], API_URL)
        self.assertEqual(
            get.call_args.kwargs['headers']['Authorization'],
            f'Bearer {TOKEN}',
        )
        self.assertEqual(get.call_args.kwargs['timeout'], (2, 4))
        self.assertFalse(get.call_args.kwargs['allow_redirects'])

    def test_missing_or_insecure_configuration_is_not_called(self):
        with patch.dict(
            os.environ,
            {'PAYCHASER_CONTROL_CENTRE_API_URL': 'http://paychaser.example.test' + paychaser_integration.API_PATH},
        ), patch.object(paychaser_integration.requests, 'get') as get:
            result = paychaser_integration.fetch_summary()

        self.assertFalse(result['available'])
        self.assertEqual(result['status'], 'not_configured')
        get.assert_not_called()

    def test_malformed_endpoint_is_reported_as_unconfigured(self):
        with patch.dict(
            os.environ,
            {'PAYCHASER_CONTROL_CENTRE_API_URL': 'https://[invalid'},
        ), patch.object(paychaser_integration.requests, 'get') as get:
            result = paychaser_integration.fetch_summary()

        self.assertEqual(result['status'], 'not_configured')
        get.assert_not_called()

    def test_timeout_returns_specific_safe_unavailable_state(self):
        with patch.object(
            paychaser_integration.requests,
            'get',
            side_effect=requests.Timeout(),
        ):
            result = paychaser_integration.fetch_summary()

        self.assertFalse(result['available'])
        self.assertEqual(result['status'], 'timeout')
        self.assertIn('timed out', result['message'])

    def test_remote_authentication_failure_is_reported_without_secrets(self):
        response = Mock(ok=False, status_code=401)
        with patch.object(
            paychaser_integration.requests,
            'get',
            return_value=response,
        ):
            result = paychaser_integration.fetch_summary()

        self.assertEqual(result['status'], 'authentication_error')
        self.assertNotIn(TOKEN, result['message'])

    def test_remote_service_error_is_reported_as_unavailable(self):
        response = Mock(ok=False, status_code=503)
        with patch.object(
            paychaser_integration.requests,
            'get',
            return_value=response,
        ):
            result = paychaser_integration.fetch_summary()

        self.assertEqual(result['status'], 'unavailable')
        self.assertIn('temporarily unavailable', result['message'])

    def test_malformed_or_stale_response_is_not_rendered_as_data(self):
        payload = summary_payload()
        payload['registered_businesses'] = True
        response = Mock(ok=True, status_code=200)
        response.json.return_value = payload
        with patch.object(
            paychaser_integration.requests,
            'get',
            return_value=response,
        ):
            result = paychaser_integration.fetch_summary()

        self.assertFalse(result['available'])
        self.assertEqual(result['status'], 'invalid_response')
        self.assertNotIn('data', result)


if __name__ == '__main__':
    unittest.main()
