import os
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask

from trimtech.modules.auth.routes import auth_blueprint
from trimtech.modules.onboarding.models import OnboardingBusiness
from trimtech.modules.platform.routes import platform_blueprint
from trimtech.modules.staff import platform_control
from trimtech.modules.staff.routes import staff_blueprint


class ControlCentreSummaryTests(unittest.TestCase):
    def test_summary_separates_registrations_from_verified_staff_billing(self):
        garage = [
            OnboardingBusiness(
                business_name='Garage One',
                owner_name='Owner',
                email='owner@example.test',
                phone='0123456789',
                business_type='garage',
                onboarding_complete=True,
            ),
            OnboardingBusiness(
                business_name='Garage Two',
                owner_name='Owner',
                email='owner2@example.test',
                phone='0123456789',
                business_type='garage',
            ),
        ]
        staff_rows = [
            {
                'state': 'active_trial',
                'employee_count': 3,
                'subscription_status': 'trialing',
                'cancel_at_period_end': False,
            },
            {
                'state': 'paid',
                'employee_count': 2,
                'subscription_status': 'active',
                'cancel_at_period_end': True,
            },
            {
                'state': 'inactive',
                'employee_count': 0,
                'subscription_status': 'past_due',
                'invoice_status': 'open',
                'cancel_at_period_end': False,
            },
        ]

        summary = platform_control.build_control_centre_summary(
            garage,
            {'businesses': staff_rows},
        )

        self.assertEqual(summary['products']['garage']['businesses'], 2)
        self.assertEqual(summary['products']['garage']['completed_registrations'], 1)
        self.assertIsNone(summary['products']['garage']['subscriptions'])
        self.assertEqual(summary['products']['staff']['businesses'], 3)
        self.assertEqual(summary['products']['staff']['employees'], 5)
        self.assertEqual(summary['products']['staff']['trials'], 1)
        self.assertEqual(summary['products']['staff']['subscriptions'], 1)
        self.assertEqual(summary['products']['staff']['cancellations'], 1)
        self.assertEqual(summary['products']['staff']['payment_issues'], 1)
        self.assertEqual(summary['products']['paychaser']['status'], 'not_configured')
        self.assertIsNone(summary['products']['paychaser']['businesses'])
        self.assertIsNone(summary['revenue'])

    def test_paychaser_summary_is_aggregated_without_business_details(self):
        timestamp = datetime(2026, 10, 30, 15, 0, tzinfo=timezone.utc)
        paychaser = {
            'available': True,
            'status': 'connected',
            'message': '',
            'data': {
                'registered_businesses': 7,
                'businesses_without_subscription': 3,
                'active_trials': 2,
                'scheduled_cancellations': 1,
                'subscription_status_counts': {
                    'active': 2,
                    'trialing': 2,
                    'past_due': 1,
                    'canceled': 1,
                    'unpaid': 0,
                    'incomplete': 0,
                    'incomplete_expired': 0,
                    'checkout_pending': 1,
                    'other': 0,
                },
                'as_of': timestamp,
                'business_records_updated_at': timestamp,
                'subscription_records_updated_at': timestamp,
            },
        }

        summary = platform_control.build_control_centre_summary(
            [],
            {'businesses': []},
            paychaser_data=paychaser,
        )

        self.assertTrue(summary['products']['paychaser']['available'])
        self.assertEqual(summary['products']['paychaser']['businesses'], 7)
        self.assertEqual(summary['products']['paychaser']['trials'], 2)
        self.assertEqual(summary['products']['paychaser']['cancellations'], 1)
        self.assertEqual(
            summary['products']['paychaser']['subscriptions']['past_due'],
            1,
        )

    def test_failed_data_sources_are_unavailable_not_zero(self):
        summary = platform_control.build_control_centre_summary(
            None,
            None,
            garage_available=False,
            staff_available=False,
        )

        self.assertIsNone(summary['products']['garage']['businesses'])
        self.assertIsNone(summary['products']['staff']['businesses'])
        self.assertIsNone(summary['products']['staff']['payment_issues'])
        self.assertFalse(summary['products']['garage']['available'])
        self.assertFalse(summary['products']['staff']['available'])


class ControlCentreAuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            SECRET_KEY='test-only-control-centre-secret',
            TESTING=True,
            TEMPLATES_AUTO_RELOAD=True,
        )
        self.app.register_blueprint(auth_blueprint)
        self.app.register_blueprint(platform_blueprint)
        self.app.register_blueprint(staff_blueprint)
        self.client = self.app.test_client()
        self.environment = patch.dict(
            os.environ,
            PLATFORM_ADMIN_USERNAME='test-platform-admin',
            PLATFORM_ADMIN_PASSWORD='test-only-password',
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_unauthenticated_and_business_owner_sessions_are_denied(self):
        response = self.client.get('/staff/platform/control-centre')
        self.assertEqual(response.status_code, 302)

        with self.client.session_transaction() as session:
            session['business_user_authenticated'] = True
            session['business_id'] = 'ordinary-business'
        response = self.client.get('/staff/platform/control-centre')
        self.assertEqual(response.status_code, 302)

    def test_legacy_platform_login_session_is_denied(self):
        with self.client.session_transaction() as session:
            session['platform_admin_authenticated'] = True
            session['auth_role'] = 'platform_admin'
            session['platform_admin_username'] = 'test-platform-admin'
            session['platform_admin_auth_source'] = 'legacy_dashboard'

        response = self.client.get('/staff/platform/control-centre')

        self.assertEqual(response.status_code, 403)

    def test_platform_login_records_credential_source(self):
        response = self.client.post(
            '/platform/login',
            data={
                'username': 'test-platform-admin',
                'password': 'test-only-password',
            },
        )
        self.assertEqual(response.status_code, 302)
        with self.client.session_transaction() as session:
            self.assertEqual(session['platform_admin_auth_source'], 'dedicated')

        fallback_client = self.app.test_client()
        with patch.dict(
            os.environ,
            {
                'PLATFORM_ADMIN_USERNAME': '',
                'PLATFORM_ADMIN_PASSWORD': '',
                'DASHBOARD_USERNAME': 'legacy-dashboard-user',
                'DASHBOARD_PASSWORD': 'legacy-dashboard-password',
            },
        ):
            response = fallback_client.post(
                '/platform/login',
                data={
                    'username': 'legacy-dashboard-user',
                    'password': 'legacy-dashboard-password',
                },
            )
        self.assertEqual(response.status_code, 302)
        with fallback_client.session_transaction() as session:
            self.assertEqual(session['platform_admin_auth_source'], 'legacy_dashboard')

    def test_dedicated_platform_admin_sees_read_only_summary(self):
        with self.client.session_transaction() as session:
            session['platform_admin_authenticated'] = True
            session['auth_role'] = 'platform_admin'
            session['platform_admin_username'] = 'test-platform-admin'
            session['platform_admin_auth_source'] = 'dedicated'

        garage = [
            SimpleNamespace(onboarding_complete=True),
        ]
        with (
            patch.object(platform_control, 'list_onboarding_businesses', return_value=garage),
            patch.object(
                platform_control,
                'directory',
                return_value={
                    'businesses': [
                        {
                            'state': 'paid',
                            'employee_count': 1,
                            'subscription_status': 'active',
                            'cancel_at_period_end': False,
                        },
                    ],
                },
            ),
        ):
            response = self.client.get('/staff/platform/control-centre')

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Setup pending', response.data)
        self.assertIn(b'Integration pending', response.data)
        self.assertIn(b'1', response.data)
        self.assertNotIn(b'owner@example.test', response.data)
        self.assertNotIn(b'customer invoice', response.data.lower())

    def test_paychaser_failure_is_visible_without_blocking_control_centre(self):
        with self.client.session_transaction() as session:
            session['platform_admin_authenticated'] = True
            session['auth_role'] = 'platform_admin'
            session['platform_admin_username'] = 'test-platform-admin'
            session['platform_admin_auth_source'] = 'dedicated'

        with (
            patch.object(platform_control, 'list_onboarding_businesses', return_value=[]),
            patch.object(platform_control, 'directory', return_value={'businesses': []}),
            patch.object(
                platform_control,
                'fetch_summary',
                return_value={
                    'available': False,
                    'status': 'timeout',
                    'message': 'PayChaser summary request timed out.',
                },
            ),
        ):
            response = self.client.get('/staff/platform/control-centre')

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Temporarily unavailable', response.data)
        self.assertIn(b'PayChaser summary request timed out.', response.data)

    def test_paychaser_summary_is_rendered_as_aggregates(self):
        with self.client.session_transaction() as session:
            session['platform_admin_authenticated'] = True
            session['auth_role'] = 'platform_admin'
            session['platform_admin_username'] = 'test-platform-admin'
            session['platform_admin_auth_source'] = 'dedicated'

        timestamp = datetime(2026, 10, 30, 15, 0, tzinfo=timezone.utc)
        paychaser_data = {
            'available': True,
            'status': 'connected',
            'message': '',
            'data': {
                'registered_businesses': 7,
                'businesses_without_subscription': 3,
                'active_trials': 2,
                'scheduled_cancellations': 1,
                'subscription_status_counts': {
                    'active': 2,
                    'trialing': 2,
                    'past_due': 1,
                    'canceled': 1,
                    'unpaid': 0,
                    'incomplete': 0,
                    'incomplete_expired': 0,
                    'checkout_pending': 1,
                    'other': 0,
                },
                'as_of': timestamp,
            },
        }
        with (
            patch.object(platform_control, 'list_onboarding_businesses', return_value=[]),
            patch.object(platform_control, 'directory', return_value={'businesses': []}),
            patch.object(
                platform_control,
                'fetch_summary',
                return_value=paychaser_data,
            ),
        ):
            response = self.client.get('/staff/platform/control-centre')

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Connected', response.data)
        self.assertIn(b'Active free trials', response.data)
        self.assertIn(b'Paying subscribers', response.data)
        self.assertIn(b'Trialing subscriptions', response.data)
        self.assertIn(b'Past due', response.data)
        self.assertIn(b'15:00 UTC', response.data)
        self.assertNotIn(b'stripe-customer', response.data.lower())


if __name__ == '__main__':
    unittest.main()
