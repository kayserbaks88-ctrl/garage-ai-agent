import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

import psycopg2.errors
from flask import Flask

from trimtech.modules.auth.routes import auth_blueprint
from trimtech.modules.platform.routes import platform_blueprint
from trimtech.modules.staff import complimentary_access as comp
from trimtech.modules.staff import complimentary_migration, onboarding, paychaser_integration, platform_control
from trimtech.modules.staff.routes import staff_blueprint

API = 'https://paychaser.example.test/api/platform/control-centre/v1/summary'
NOT_CONFIGURED = {'available': False, 'status': 'not_configured', 'message': 'PayChaser service integration is not configured.'}
OK = dict(business_id='acme', days=7, reason='Onboarding delay', confirmation='acme', business_active=True,
          paid=False, trial_state='expired', active_grant=False, granted_days_total=0)


class GrantRuleTests(unittest.TestCase):
    def check(self, **changes):
        return comp.validate_request(**{**OK, **changes})

    def refused(self, **changes):
        with self.assertRaises(comp.GrantRefused):
            self.check(**changes)

    def test_only_listed_durations_are_allowed(self):
        for days in (3, 7, 14, 30, '14'):
            self.assertEqual(self.check(days=days)[0], int(days))
        for days in (0, 1, 5, 31, 90, -7, None, '', 'abc', 7.5 * 0 + 2):
            self.refused(days=days)

    def test_reason_and_exact_confirmation_required(self):
        self.refused(reason='')
        self.refused(reason='   ')
        self.refused(reason='x' * 1001)
        self.assertEqual(self.check(reason='x' * 1000)[1], 'x' * 1000)
        self.refused(confirmation='')
        self.refused(confirmation='ACME')
        self.refused(confirmation='other')

    def test_unpaid_access_cannot_continue_indefinitely(self):
        self.refused(active_grant=True)  # no stacking
        self.refused(granted_days_total=65, days=30)  # lifetime cap of 90 days
        self.check(granted_days_total=60, days=30)
        self.refused(granted_days_total=61, days=30)

    def test_refused_for_paid_inactive_pending_and_legacy_accounts(self):
        self.refused(paid=True)
        self.refused(business_active=False)
        self.refused(trial_state='pending')
        self.refused(trial_state='legacy')

    def test_active_trial_and_expired_trial_are_eligible(self):
        self.check(trial_state='active')
        self.check(trial_state='expired')


class AccessEnforcementTests(unittest.TestCase):
    now = datetime(2026, 11, 1, tzinfo=timezone.utc)

    def access(self, trial, paid=False, managed=False, grant=None):
        with patch.object(onboarding, 'status', return_value=trial), \
             patch('trimtech.modules.staff.billing.entitlement', return_value={'paid': paid, 'managed': managed}), \
             patch.object(comp, 'active_grant', return_value=grant):
            return onboarding.access('acme')

    def grant(self, days_left=5):
        return {'days': 7, 'days_left': days_left, 'expires_at': self.now + timedelta(days=days_left)}

    def test_active_grant_unlocks_expired_trial_with_existing_state_name(self):
        result = self.access({'state': 'expired', 'days': 0, 'ends_at': self.now}, grant=self.grant())
        self.assertEqual(result['state'], 'active')
        self.assertTrue(result['complimentary'])
        self.assertEqual(result['days'], 5)

    def test_expired_or_revoked_grant_returns_no_grant_and_stays_blocked(self):
        result = self.access({'state': 'expired', 'days': 0, 'ends_at': self.now}, grant=None)
        self.assertEqual(result['state'], 'expired')
        self.assertNotIn('complimentary', result)

    def test_paid_subscription_takes_precedence_and_ignores_grant(self):
        result = self.access({'state': 'expired', 'days': 0, 'ends_at': self.now}, paid=True, grant=self.grant())
        self.assertEqual(result['state'], 'paid')
        self.assertNotIn('complimentary', result)

    def test_pending_trial_is_never_unlocked_by_a_grant(self):
        result = self.access({'state': 'pending', 'days': 0, 'ends_at': None}, grant=self.grant())
        self.assertEqual(result['state'], 'pending')

    def test_legacy_business_with_stripe_record_but_unpaid_can_use_grant(self):
        result = self.access({'state': 'legacy', 'days': None, 'ends_at': None}, managed=True, grant=self.grant(3))
        self.assertEqual(result['state'], 'active')

    def test_legacy_without_billing_is_unchanged(self):
        self.assertEqual(self.access({'state': 'legacy', 'days': None, 'ends_at': None}, grant=self.grant())['state'], 'legacy')

    def test_missing_table_before_migration_does_not_break_access(self):
        with patch.object(comp, 'fetch_one', side_effect=psycopg2.errors.UndefinedTable()):
            self.assertIsNone(comp.active_grant('acme'))
        with patch.object(comp, 'fetch_all', side_effect=psycopg2.errors.UndefinedTable()):
            self.assertEqual(comp.history('acme'), [])

    def test_grant_expiry_is_evaluated_in_the_database_on_every_request(self):
        with patch.object(comp, 'fetch_one', return_value=None) as fetch:
            comp.active_grant('acme')
        sql = fetch.call_args[0][0]
        self.assertIn('expires_at>NOW()', sql)
        self.assertIn('revoked_at IS NULL', sql)


class StripeSeparationTests(unittest.TestCase):
    def test_complimentary_code_never_touches_stripe_tables_or_client(self):
        for module in (comp, complimentary_migration):
            with open(module.__file__, encoding='utf-8') as handle:
                source = handle.read()
            code = source.split('"""', 2)[-1] if module is comp else source
            self.assertNotIn('import stripe', source)
            self.assertNotIn('INSERT INTO sb_', code)
            self.assertNotIn('UPDATE sb_', code)
            self.assertNotIn('DELETE FROM sb_', code)

    def test_migration_is_additive_only(self):
        sql = complimentary_migration.SQL.upper()
        for word in ('DROP ', 'ALTER ', 'DELETE ', 'TRUNCATE'):
            self.assertNotIn(word, sql)
        self.assertIn('CHECK(DAYS IN (3,7,14,30))', sql.replace(' ', '', 0))

    def test_payment_issue_wording_for_stripe_edge_cases(self):
        rows = [{'status': 'past_due', 'invoice_status': 'open'}, {'status': 'unpaid'},
                {'status': 'active', 'invoice_status': 'paid', 'cancel_at_period_end': True},
                {'status': 'incomplete_expired'}, {'status': 'canceled'}]
        issues = platform_control.payment_issues(rows)
        self.assertIn('Subscription status is past due.', issues)
        self.assertIn('Subscription status is unpaid.', issues)
        self.assertIn('Subscription status is incomplete expired.', issues)
        self.assertIn('Cancellation is scheduled at the end of the paid period.', issues)
        self.assertEqual(platform_control.payment_issues([]), [])
        self.assertEqual(platform_control.payment_issues([{'status': 'active', 'invoice_status': 'paid'}]), [])
        self.assertEqual(len(issues), len(set(issues)))


class PayChaserLinkTests(unittest.TestCase):
    def link(self, url):
        with patch.dict(os.environ, {'PAYCHASER_CONTROL_CENTRE_API_URL': url}, clear=False):
            return paychaser_integration.admin_url()

    def test_link_points_to_paychaser_platform_admin_not_customer_dashboard(self):
        self.assertEqual(self.link(API), 'https://paychaser.example.test/platform')

    def test_unsafe_or_unconfigured_urls_give_no_link(self):
        for url in ('', 'http://paychaser.example.test/api/platform/control-centre/v1/summary',
                    'https://u:p@paychaser.example.test' + '/api/platform/control-centre/v1/summary',
                    'https://paychaser.example.test/other', API + '?x=1', 'javascript:alert(1)'):
            self.assertIsNone(self.link(url), url)

    def test_link_never_depends_on_or_reveals_the_token(self):
        with patch.dict(os.environ, {'PAYCHASER_CONTROL_CENTRE_API_URL': API,
                                     'PAYCHASER_CONTROL_CENTRE_API_TOKEN': 'T' * 40}):
            self.assertNotIn('T' * 10, paychaser_integration.admin_url())


class RouteBase(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(SECRET_KEY='test-only-secret', TESTING=True)
        for blueprint in (auth_blueprint, platform_blueprint, staff_blueprint):
            self.app.register_blueprint(blueprint)
        self.environment = patch.dict(os.environ, PLATFORM_ADMIN_USERNAME='test-platform-admin',
                                      PLATFORM_ADMIN_PASSWORD='test-only-password',
                                      PAYCHASER_CONTROL_CENTRE_API_URL=API)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        context_lookup = patch('trimtech.modules.staff.onboarding_routes.fetch_one', return_value={'name': 'Acme'})
        context_lookup.start()
        self.addCleanup(context_lookup.stop)
        self.client = self.app.test_client()

    def sign_in(self, client=None, source='dedicated'):
        with (client or self.client).session_transaction() as session:
            session['platform_admin_authenticated'] = True
            session['auth_role'] = 'platform_admin'
            session['platform_admin_username'] = 'test-platform-admin'
            session['platform_admin_auth_source'] = source
            session['_staff_csrf_token'] = 'csrf-ok'

    def as_session(self, **values):
        client = self.app.test_client()
        with client.session_transaction() as session:
            session.update(values)
            session['_staff_csrf_token'] = 'csrf-ok'
        return client


MANAGE = '/staff/platform/businesses/acme/manage'
GRANT = '/staff/platform/businesses/acme/complimentary'
REVOKE = '/staff/platform/businesses/acme/complimentary/revoke'
FORM = {'csrf_token': 'csrf-ok', 'days': '7', 'reason': 'Because', 'confirmation': 'acme'}


class ManageSecurityTests(RouteBase):
    def clients(self):
        legacy = self.app.test_client()
        self.sign_in(legacy, source='legacy_dashboard')
        return {
            'anonymous': self.as_session(),
            'business owner': self.as_session(business_user_authenticated=True, business_id='acme'),
            'employee': self.as_session(employee_authenticated=True, employee_id='1', business_id='acme'),
            'manager': self.as_session(auth_role='manager', business_id='acme', business_user_authenticated=True),
            'forged role only': self.as_session(auth_role='platform_admin'),
            'forged flag without username': self.as_session(platform_admin_authenticated=True, auth_role='platform_admin',
                                                           platform_admin_auth_source='dedicated'),
            'wrong admin username': self.as_session(platform_admin_authenticated=True, auth_role='platform_admin',
                                                    platform_admin_username='someone-else', platform_admin_auth_source='dedicated'),
            'legacy dashboard credentials': legacy,
        }

    def test_every_non_platform_session_is_denied_on_all_manage_routes(self):
        with patch.object(comp, 'grant') as grant, patch.object(comp, 'revoke') as revoke:
            for label, client in self.clients().items():
                for method, path in (('get', MANAGE), ('post', GRANT), ('post', REVOKE)):
                    response = getattr(client, method)(path, data=FORM) if method == 'post' else client.get(path)
                    self.assertIn(response.status_code, (302, 401, 403, 404), '%s %s' % (label, path))
                    if response.status_code == 302:
                        self.assertIn('/platform/login', response.headers['Location'])
            grant.assert_not_called()
            revoke.assert_not_called()

    def test_platform_admin_cannot_mutate_without_csrf(self):
        self.sign_in()
        with patch.object(comp, 'grant') as grant:
            response = self.client.post(GRANT, data={k: v for k, v in FORM.items() if k != 'csrf_token'})
            self.assertEqual(response.status_code, 400)
            response = self.client.post(GRANT, data={**FORM, 'csrf_token': 'wrong'})
            self.assertEqual(response.status_code, 400)
            grant.assert_not_called()

    def test_grant_is_attributed_to_the_platform_admin_not_form_input(self):
        self.sign_in()
        with patch.object(comp, 'grant', return_value={'id': 1, 'days': 7, 'expires_at': None}) as grant:
            response = self.client.post(GRANT, data={**FORM, 'actor': 'forged', 'business_id': 'other'})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers['Location'].endswith(MANAGE))
        args = grant.call_args[0]
        self.assertEqual(args[0], 'acme')
        self.assertEqual(args[1], 'platform:test-platform-admin')

    def test_refused_grant_shows_message_and_changes_nothing(self):
        self.sign_in()
        with patch.object(comp, 'grant', side_effect=comp.GrantRefused('Choose 3, 7, 14 or 30 days.')):
            response = self.client.post(GRANT, data={**FORM, 'days': '99'}, follow_redirects=False)
        self.assertEqual(response.status_code, 302)

    def test_revoke_requires_dedicated_admin_and_csrf(self):
        self.sign_in()
        with patch.object(comp, 'revoke', return_value=1) as revoke:
            self.assertEqual(self.client.post(REVOKE, data={'reason': 'x'}).status_code, 400)
            self.assertEqual(self.client.post(REVOKE, data={'csrf_token': 'csrf-ok', 'reason': 'Mistake'}).status_code, 302)
        revoke.assert_called_once()
        self.assertEqual(revoke.call_args[0][1], 'platform:test-platform-admin')


class ManagePageTests(RouteBase):
    def render(self, **overrides):
        self.sign_in()
        now = datetime(2026, 11, 1, tzinfo=timezone.utc)
        ctx = dict(
            business={'id': 'acme', 'name': 'Acme Ltd', 'active': True},
            billing={'subscriptions': [{'status': 'past_due', 'paid_until': None, 'invoice_status': 'open'}],
                     'paid': False, 'managed': True},
            trial={'state': 'expired', 'ends_at': now, 'days': 0},
            access={'state': 'expired', 'days': 0},
            grant=None, grants=[], allowed=(3, 7, 14, 30))
        ctx.update(overrides)
        with patch('trimtech.modules.staff.subscription_management.business', return_value=ctx['business']), \
             patch('trimtech.modules.staff.billing.summary', return_value=ctx['billing']), \
             patch.object(onboarding, 'status', return_value=ctx['trial']), \
             patch.object(onboarding, 'access', return_value=ctx['access']), \
             patch.object(comp, 'active_grant', return_value=ctx['grant']), \
             patch.object(comp, 'history', return_value=ctx['grants']):
            return self.client.get(MANAGE)

    def test_page_shows_status_trial_payment_issue_and_all_durations(self):
        response = self.render()
        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        for text in ('Acme Ltd', 'Expired', 'Trial expiry', 'Subscription status is past due.',
                     '3 days', '7 days', '14 days', '30 days', 'Type acme to confirm', 'csrf-ok'):
            self.assertIn(text, html)
        self.assertNotIn('30 days</option><option value="60"', html)

    def test_page_offers_revoke_instead_of_grant_when_grant_is_active(self):
        now = datetime(2026, 11, 1, tzinfo=timezone.utc)
        grant = {'days': 7, 'days_left': 4, 'reason': 'Support case', 'expires_at': now}
        html = self.render(grant=grant, access={'state': 'active', 'days': 4, 'complimentary': True}).get_data(as_text=True)
        self.assertIn('Revoke complimentary access', html)
        self.assertNotIn('Grant complimentary access', html)
        self.assertIn('(complimentary)', html)

    def test_page_exposes_no_payroll_or_personal_data_fields(self):
        html = self.render().get_data(as_text=True).lower()
        for word in ('payroll', 'salary', 'password', 'stripe_secret', 'customer_email'):
            self.assertNotIn(word, html)

    def test_manage_page_back_links_are_explicit_urls_without_history_or_js(self):
        html = self.render().get_data(as_text=True)
        self.assertIn('href="/staff/platform/control-centre"', html)
        self.assertIn('Back to Control Centre', html)
        self.assertIn('href="/staff/platform/businesses"', html)
        self.assertIn('href="/staff/platform/businesses/acme/subscription"', html)
        for bad in ('history.back', 'javascript:', 'history.go', '<script'):
            self.assertNotIn(bad, html)
        self.assertIn('viewport-fit=cover', html)
        self.assertIn('min-height:44px', html)

    def test_unknown_business_is_404(self):
        self.sign_in()
        with patch('trimtech.modules.staff.subscription_management.business', return_value=None):
            self.assertEqual(self.client.get(MANAGE).status_code, 404)


class NavigationTests(RouteBase):
    def test_control_centre_has_dashboard_product_and_paychaser_links(self):
        self.sign_in()
        with patch.object(platform_control, 'list_onboarding_businesses', return_value=[]), \
             patch.object(platform_control, 'directory', return_value={'businesses': []}), \
             patch.object(platform_control, 'fetch_summary', return_value=NOT_CONFIGURED):
            html = self.client.get('/staff/platform/control-centre').get_data(as_text=True)
        self.assertIn('href="/dashboard">Back to Dashboard', html)
        self.assertIn('href="https://paychaser.example.test/platform"', html)
        self.assertIn('rel="noopener noreferrer"', html)
        self.assertNotIn('/dashboard"', html.replace('href="/dashboard"', ''))

    def test_paychaser_link_is_disabled_when_not_configured(self):
        self.sign_in()
        with patch.dict(os.environ, {'PAYCHASER_CONTROL_CENTRE_API_URL': ''}), \
             patch.object(platform_control, 'list_onboarding_businesses', return_value=[]), \
             patch.object(platform_control, 'directory', return_value={'businesses': []}), \
             patch.object(platform_control, 'fetch_summary', return_value=NOT_CONFIGURED):
            html = self.client.get('/staff/platform/control-centre').get_data(as_text=True)
        self.assertIn('not configured', html)
        self.assertNotIn('paychaser.example.test/platform', html)

    def test_staff_admin_pages_link_back_to_control_centre(self):
        self.sign_in()
        row = {'id': 'acme', 'name': 'Acme', 'active': True, 'created_at': datetime(2026, 1, 1), 'starts_at': None, 'ends_at': None,
               'completed': {}, 'employee_count': 0, 'open_shifts': 0, 'pending_approvals': 0, 'last_activity': None,
               'subscription_status': None, 'state': 'expired_trial'}
        data = dict(businesses=[row], total=1, matching=1, health='Verified', active_trials=0, paid=0)
        with patch.object(platform_control, 'directory', return_value=data):
            html = self.client.get('/staff/platform/businesses').get_data(as_text=True)
        self.assertIn('href="/staff/platform/control-centre"', html)
        self.assertIn('Back to Control Centre', html)
        self.assertIn('/staff/platform/businesses/acme/manage', html)

    def test_subscription_admin_page_links_back_to_control_centre(self):
        self.sign_in()
        with patch('trimtech.modules.staff.subscription_management.business', return_value={'id': 'acme', 'name': 'Acme', 'active': True}), \
             patch('trimtech.modules.staff.subscription_management.history', return_value=[]), \
             patch('trimtech.modules.staff.billing.summary', return_value={'subscriptions': []}), \
             patch.object(onboarding, 'status', return_value={'state': 'expired', 'ends_at': None}):
            html = self.client.get('/staff/platform/businesses/acme/subscription').get_data(as_text=True)
        self.assertIn('href="/staff/platform/control-centre"', html)

    def test_back_link_is_hidden_from_non_platform_viewers(self):
        legacy = self.app.test_client()
        self.sign_in(legacy, source='legacy_dashboard')
        with self.app.test_request_context():
            from flask import render_template, session
            session['platform_admin_auth_source'] = 'legacy_dashboard'
            self.assertNotIn('Back to Control Centre', render_template('_control_centre_back.html'))
            session.clear()
            self.assertNotIn('Back to Control Centre', render_template('_control_centre_back.html'))

    def test_garage_admin_templates_include_back_link(self):
        for name in ('platform/businesses.html', 'platform/business_detail.html'):
            with open(os.path.join(os.path.dirname(__file__), 'templates', name), encoding='utf-8') as handle:
                source = handle.read()
            self.assertIn("{% include '_control_centre_back.html' %}", source)


class ComplimentaryListTests(RouteBase):
    ROW = {'id': 'acme', 'name': 'Acme', 'active': True, 'created_at': datetime(2026, 1, 1), 'starts_at': None, 'ends_at': datetime(2026, 10, 1),
           'completed': {}, 'employee_count': 2, 'open_shifts': 0, 'pending_approvals': 0, 'last_activity': None,
           'subscription_status': None, 'state': 'complimentary', 'complimentary_until': datetime(2026, 11, 8, 9, 30)}

    def page(self, row):
        self.sign_in()
        data = dict(businesses=[row], total=1, matching=1, health='Verified', active_trials=0, paid=0)
        with patch.object(platform_control, 'directory', return_value=data):
            return self.client.get('/staff/platform/businesses').get_data(as_text=True)

    def test_active_grant_is_shown_in_staff_business_list(self):
        html = self.page(self.ROW)
        self.assertIn('Complimentary', html)
        self.assertIn('Complimentary access ends (UTC)', html)
        self.assertIn('08 Nov 2026 09:30', html)
        self.assertIn('value="complimentary"', html)

    def test_business_without_grant_shows_no_complimentary_row(self):
        html = self.page({**self.ROW, 'state': 'expired_trial', 'complimentary_until': None})
        self.assertNotIn('Complimentary access ends', html)
        self.assertIn('Expired Trial', html)

    def directory_sql(self, grants_present):
        cursor = MagicMock()
        cursor.fetchone.return_value = {'present': grants_present}
        cursor.fetchall.return_value = []
        connection = MagicMock()
        connection.cursor.return_value.__enter__.return_value = cursor
        manager = MagicMock()
        manager.__enter__.return_value = connection
        with patch.object(platform_control, 'transaction', return_value=manager), \
             patch.object(platform_control.migrations, 'verify'), patch.object(platform_control.accounts_migration, 'verify'), \
             patch.object(platform_control.onboarding_migration, 'verify'), patch.object(platform_control.billing_migration, 'verify'):
            platform_control.directory(status='complimentary')
        return [call[0][0] for call in cursor.execute.call_args_list if 'FROM sm_businesses' in call[0][0]][0]

    def test_directory_reads_grants_only_when_table_exists(self):
        self.assertIn('FROM sc_grants', self.directory_sql(True))
        before_migration = self.directory_sql(False)
        self.assertNotIn('FROM sc_grants', before_migration)
        self.assertIn('NULL::timestamptz', before_migration)

    def test_directory_filter_excludes_revoked_and_expired_grants_in_sql(self):
        sql = self.directory_sql(True)
        self.assertIn('revoked_at IS NULL', sql)
        self.assertIn('expires_at>NOW()', sql)
        self.assertNotIn('sb_subscriptions SET', sql)


class MigrationTests(unittest.TestCase):
    def test_migration_is_not_applied_by_the_app_at_import_or_request_time(self):
        cursor = MagicMock()
        # importing and enforcing never executes migrations
        self.assertTrue(callable(complimentary_migration.migrate))
        cursor.execute.assert_not_called()
        self.assertEqual(complimentary_migration.VERSION, '20261101_staff_complimentary_v1')


if __name__ == '__main__':
    unittest.main()
