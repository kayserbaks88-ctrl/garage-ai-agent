"""PostgreSQL lifecycle and platform isolation regressions. No provider network calls."""
import os
import unittest
from unittest.mock import patch
import test_staff_agency as fixture
from trimtech.modules.staff import database, onboarding, subscription_management as management

@unittest.skipUnless(os.getenv('STAFF_TEST_DATABASE_URL'), 'Requires isolated PostgreSQL')
class SubscriptionManagementTests(unittest.TestCase):
    for name in ('cleanup_schema','connect','insert','client','post','row'):
        locals()[name]=getattr(fixture.AgencyDatabaseTests,name)

    def setUp(self):
        fixture.AgencyDatabaseTests.setUp(self)
        from trimtech.modules.auth.routes import auth_blueprint
        self.app.register_blueprint(auth_blueprint)
        env=patch.dict(os.environ,STAFF_STRIPE_ENABLED='0', PLATFORM_ADMIN_USERNAME='explicit-admin', PLATFORM_ADMIN_PASSWORD='test-only')
        env.start();self.addCleanup(env.stop)
        self.platform=self.client()
        with self.platform.session_transaction() as session:
            session.update(platform_admin_authenticated=True,platform_admin_username='explicit-admin',auth_role='platform_admin')
        with database.transaction() as connection:
            with connection.cursor() as cursor:
                onboarding.begin(cursor,'alpha','test-manager')
                onboarding.activate(cursor,'test-manager')

    def action(self, client, action, **values):
        return client.post('/staff/platform/businesses/alpha/subscription',data=dict(csrf_token='test-csrf', action=action,reason='Customer request',confirmation='alpha',**values))

    def test_platform_routes_require_explicit_identity_on_every_request(self):
        for client in (self.manager,self.worker,self.client()):
            self.assertEqual(client.get('/staff/platform/businesses').status_code,302)
            self.assertEqual(client.get('/staff/platform/businesses/alpha/subscription').status_code,302)
            self.assertEqual(self.action(client,'deactivate').status_code,302)
        with self.manager.session_transaction() as session:
            session['platform_admin_authenticated']=True
            session['platform_admin_username']='dashboard-fallback'
        self.assertEqual(self.manager.get('/staff/platform/businesses').status_code,403)
        self.assertNotIn(b'All Staff businesses', self.manager.get('/staff/account').data)
        self.assertEqual(self.platform.get('/staff/platform/businesses').status_code,200)
        self.assertEqual(self.platform.get('/staff/platform/businesses/alpha/subscription').status_code,200)
        with patch.dict(os.environ,PLATFORM_ADMIN_PASSWORD=''):
            self.assertEqual(self.platform.get('/staff/platform/businesses').status_code,403)
        self.assertEqual(self.platform.get('/staff/alpha/subscription').status_code,302)

    def test_owner_and_cross_business_billing_isolation(self):
        page=self.manager.get('/staff/alpha/subscription')
        self.assertEqual(page.status_code,200)
        self.assertIn(b'Subscription &amp; Billing',page.data)
        self.assertIn(b'Online billing is not available yet',page.data)
        database.execute("INSERT INTO sm_businesses(id,name) VALUES ('unrelated','Private tenant')")
        for path in ('/staff/unrelated','/staff/unrelated/subscription'):
            self.assertEqual(self.manager.get(path).status_code,404)
        self.assertEqual(self.manager.post('/staff/unrelated/subscription/request',data=dict(csrf_token='test-csrf',action='end_trial')).status_code,404)
        self.assertNotIn(b'Private tenant', self.manager.get('/staff/account').data)
        database.execute("UPDATE sm_memberships SET role='administrator' WHERE business_id='alpha'")
        self.assertEqual(self.manager.get('/staff/alpha/subscription').status_code,403)

    def test_end_trial_preserves_dates_records_and_blocks_writes(self):
        before=onboarding.status('alpha')
        self.assertEqual(self.manager.post('/staff/alpha/subscription/request',data=dict(action='end_trial')).status_code,400)
        response=self.post(self.manager,'subscription/request',dict(action='end_trial',reason='No longer needed',confirmation='alpha'))
        self.assertEqual(response.status_code,302)
        after=onboarding.status('alpha')
        self.assertEqual(after['state'],'expired')
        self.assertEqual(before['ends_at'],after['ends_at'])
        self.assertEqual(self.post(self.manager,'settings/break-policy',dict(break_policy='paid')).status_code,402)
        self.assertTrue(management.business('alpha')['active'])
        self.assertEqual(management.history('alpha')[0]['action'],'end_trial')
        self.assertEqual(self.manager.get('/staff/alpha/subscription').status_code,200)

    def test_no_subscription_cannot_claim_cancellation_and_requires_confirmation(self):
        for action,values in [('request_cancellation',{}),('deactivate',{'confirmation':'wrong'}),('review_request',{'request_id':'999'})]:
            with self.assertRaises(ValueError):
                management.change('alpha','platform:explicit-admin',action,dict(reason='Review',confirmation=values.get('confirmation','alpha'),request_id=values.get('request_id','')),platform=True)
        self.assertEqual(management.history('alpha'),[])

    def test_deactivation_reactivation_and_legacy_employee_access(self):
        self.assertEqual(self.action(self.platform,'deactivate').status_code,302)
        self.assertFalse(management.business('alpha')['active'])
        self.assertEqual(self.manager.get('/staff/alpha').status_code,404)
        self.assertEqual(self.worker.get('/staff/alpha/employee').status_code,302)
        self.assertEqual(self.action(self.platform,'reactivate').status_code,302)
        self.assertTrue(management.business('alpha')['active'])
        self.assertEqual(len(management.history('alpha')),2)
        self.assertEqual(self.platform.post('/staff/platform/businesses/alpha/subscription',data=dict(action='deactivate')).status_code,400)

    def test_open_shifts_block_deactivation(self):
        database.execute("INSERT INTO staff_shifts(business_id,employee_id,site_name,clock_in_at) VALUES ('alpha',%s,'Local',NOW())",(self.employee,))
        with self.assertRaisesRegex(ValueError,'Close open shifts'):
            management.change('alpha','platform:explicit-admin','deactivate',dict(reason='Review',confirmation='alpha'),platform=True)
        self.assertTrue(management.business('alpha')['active'])

    def test_dedicated_platform_login_remains_available(self):
        client=self.client()
        response=client.post('/platform/login',data=dict(username='explicit-admin',password='test-only',next='/staff/platform/businesses'))
        self.assertEqual(response.status_code,302)
        self.assertEqual(client.get('/staff/platform/businesses').status_code,200)
        self.assertEqual(client.get('/staff/alpha').status_code,302)
        self.assertNotIn(b'All Staff businesses',self.manager.get('/staff/account').data)

    def test_staff_signin_clears_stale_platform_identity(self):
        with self.manager.session_transaction() as session:
            session.update(platform_admin_authenticated=True,platform_admin_username='explicit-admin',auth_role='platform_admin')
        with patch('trimtech.modules.staff.accounts.authenticate',return_value='x'*43), patch('trimtech.modules.staff.accounts.limited',return_value=True):
            response=self.manager.post('/staff/account/login',data=dict(csrf_token='test-csrf',email='owner@example.test',password='test-only'))
        self.assertEqual(response.status_code,302)
        with self.manager.session_transaction() as session:
            self.assertNotIn('platform_admin_authenticated',session)


import test_staff_billing as billing_fixture

@unittest.skipUnless(os.getenv('STAFF_TEST_DATABASE_URL'), 'Requires isolated PostgreSQL')
class PaidCancellationRequestTests(unittest.TestCase):
    for name in ('cleanup_schema','connect','insert','client','post','row','setUp','start','event','deliver','paid'):
        locals()[name]=getattr(billing_fixture.BillingTests,name)

    def test_paid_request_is_audited_without_provider_changes(self):
        self.paid()
        with patch.dict(os.environ,STAFF_STRIPE_ENABLED='0'):
            response=self.post(self.manager,'subscription/request',dict(action='request_cancellation',reason='End service',confirmation='alpha'))
            self.assertEqual(response.status_code,302)
            record=management.history('alpha')[0]
            self.assertFalse(record['new_values']['provider_cancellation_confirmed'])
            self.assertEqual(record['new_values']['status'],'pending_provider_confirmation')
            self.assertEqual(self.fake.subs['sub_cs_1']['status'],'active')
            management.change('alpha','platform:reviewer','review_request',dict(reason='Sent to billing operator',confirmation='alpha',request_id=str(record['id'])),platform=True)
            self.assertEqual(management.history('alpha')[0]['new_values']['status'],'reviewed_pending_provider_confirmation')
            for action in ('deactivate','end_trial'):
                with self.assertRaisesRegex(ValueError,'billing provider first'):
                    management.change('alpha','platform:reviewer',action,dict(reason='Request',confirmation='alpha'),platform=True)
            self.assertTrue(management.business('alpha')['active'])
            self.assertEqual(self.manager.get('/staff/alpha/subscription').status_code,200)

    def test_request_review_cannot_cross_businesses(self):
        self.paid()
        management.change('alpha','test-manager','request_cancellation',dict(reason='End service',confirmation='alpha'))
        record=management.history('alpha')[0]
        database.execute("INSERT INTO sm_businesses(id,name) VALUES ('other','Other')")
        with self.assertRaisesRegex(ValueError,'not found for this business'):
            management.change('other','platform:reviewer','review_request',dict(reason='Review',confirmation='other',request_id=str(record['id'])),platform=True)

    def test_pending_checkout_blocks_deactivation_and_inactive_business_cannot_checkout(self):
        self.start()
        with self.assertRaisesRegex(ValueError,'unconfirmed checkouts'):
            management.change('alpha','platform:reviewer','deactivate',dict(reason='Review',confirmation='alpha'),platform=True)
        database.execute("UPDATE sm_businesses SET active=FALSE WHERE id='alpha'")
        from trimtech.modules.staff import billing
        from trimtech.modules.staff.stripe_gateway import BillingUnavailable
        with self.assertRaisesRegex(BillingUnavailable,'inactive'):
            billing.checkout('alpha','test-manager')
        self.assertEqual(len(self.fake.sessions),1)
