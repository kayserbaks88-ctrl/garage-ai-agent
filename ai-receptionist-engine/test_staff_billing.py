"""Real disposable PostgreSQL plus mocked Stripe; real SDK webhook signature verification."""
import copy
import hashlib
import hmac
import json
import os
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import stripe
from psycopg2.errors import UndefinedTable
import test_staff_agency as fixtures
from trimtech.modules.staff import billing, billing_migration, billing_routes, onboarding
from trimtech.modules.staff import accounts_migration, onboarding_migration, migrations, database
from trimtech.modules.staff import stripe_gateway as transport

ENV = dict(STAFF_STRIPE_ENABLED='1',STAFF_STRIPE_MODE='test',STAFF_STRIPE_SECRET_KEY='sk_test_fakeOnly',
           STAFF_STRIPE_WEBHOOK_SECRET='whsec_fakeOnly',STAFF_STRIPE_ACCOUNT_ID='acct_trimtech',
           STAFF_STRIPE_PRICE_ID='price_staff',STAFF_STRIPE_PRODUCT_ID='prod_staff',
           STAFF_STRIPE_PORTAL_CONFIGURATION_ID='bpc_staff',STAFF_PUBLIC_BASE_URL='https://staff.example.test')


class FakeStripe:
    def __init__(self):
        self.customers = {}
        self.sessions = {}
        self.subs = {}
        self.extra_invoices = []
        self.customer_keys = {}
        self.session_keys = {}
        self.configuration = {'active':True,'livemode':False,'metadata':{'application':transport.APPLICATION},
            'login_page':{'enabled':False},'features':{'payment_method_update':{'enabled':True},
            'subscription_cancel':{'enabled':True,'mode':'at_period_end'},'subscription_update':{'enabled':False},
            'customer_update':{'enabled':False},'invoice_history':{'enabled':False}}}

    def merchant(self):
        return None

    def price(self):
        return dict(id='price_staff',product='prod_staff',amount='49.00',interval='month',tax_behavior='exclusive')

    def create_customer(self, business, name, email, key):
        if key not in self.customer_keys:
            identifier='cus_'+business
            self.customer_keys[key]=identifier
            self.customers[identifier]={'id':identifier,'name':name,'email':email,'livemode':False,
                'metadata':{'application':transport.APPLICATION,'business_id':business}}
        return copy.deepcopy(self.customers[self.customer_keys[key]])

    def customer(self, identifier):
        return copy.deepcopy(self.customers[identifier])

    def create_checkout(self, params, key):
        if key not in self.session_keys:
            identifier='cs_'+str(len(self.sessions)+1)
            self.session_keys[key]=identifier
            self.sessions[identifier]={'id':identifier,'customer':params['customer'],'livemode':False,
                'mode':'subscription','metadata':params['metadata'],'status':'open',
                'url':'https://checkout.stripe.com/c/pay/'+identifier,'subscription':None}
        return copy.deepcopy(self.sessions[self.session_keys[key]])

    def checkout(self, identifier):
        return copy.deepcopy(self.sessions[identifier])

    def checkouts(self, customer):
        return {'has_more':False,'data':[copy.deepcopy(x) for x in self.sessions.values() if x['customer']==customer]}

    def subscription(self, identifier):
        return copy.deepcopy(self.subs[identifier])

    def subscriptions(self, customer):
        return {'has_more':False,'data':[copy.deepcopy(x) for x in self.subs.values() if x['customer']==customer]}

    def invoices(self, customer):
        return {'has_more':False,'data':[copy.deepcopy(x['latest_invoice']) for x in self.subs.values() if x['customer']==customer]+self.extra_invoices}

    def portal_configuration(self):
        return copy.deepcopy(self.configuration)

    def create_portal(self, customer, return_url):
        return {'url':'https://billing.stripe.com/p/session/test-only'}

    def complete(self, session_id='cs_1', state='active', invoice_status='paid'):
        session=self.sessions[session_id]
        identifier='sub_'+session_id
        end=int(time.time())+30*86400
        self.subs[identifier]={'id':identifier,'customer':session['customer'],'livemode':False,
            'metadata':copy.deepcopy(session['metadata']),'status':state,'cancel_at_period_end':False,
            'collection_method':'charge_automatically',
            'items':{'has_more':False,'data':[{'quantity':1,'current_period_end':end,
                'price':{'id':'price_staff','product':'prod_staff'}}]},
            'latest_invoice':{'id':'in_'+identifier,'customer':session['customer'],'livemode':False,
                'status':invoice_status,'amount_remaining':0 if invoice_status=='paid' else 4900,
                'parent':{'subscription_details':{'subscription':identifier}},
                'lines':{'has_more':False,'data':[{'pricing':{'price_details':{'price':'price_staff'}},'period':{'end':end}}]}}}
        session.update(status='complete',subscription=identifier,url=None)
        return self.subs[identifier]


@unittest.skipUnless(os.getenv('STAFF_TEST_DATABASE_URL'),'Requires isolated PostgreSQL')
class BillingTests(unittest.TestCase):
    for name in ('cleanup_schema','connect','insert','client','post','row'):
        locals()[name]=getattr(fixtures.AgencyDatabaseTests,name)

    def setUp(self):
        fixtures.AgencyDatabaseTests.setUp(self)
        self.env=patch.dict(os.environ,ENV)
        self.env.start();self.addCleanup(self.env.stop)
        self.fake=FakeStripe()
        self.gateway=MagicMock(wraps=self.fake,spec=transport.Gateway)
        for module in (billing,billing_routes):
            replacement=patch.object(module,'Gateway',return_value=self.gateway)
            replacement.start();self.addCleanup(replacement.stop)
        with database.transaction() as connection:
            with connection.cursor() as cursor:
                onboarding.begin(cursor,'alpha','test-manager')
                onboarding.activate(cursor,'test-manager')
        database.execute("UPDATE so_trials SET starts_at=NOW()-INTERVAL '337 hours',ends_at=NOW()-INTERVAL '1 hour' WHERE business_id='alpha'")

    def start(self):
        response=self.post(self.manager,'subscription/checkout',{'subscription_consent':'yes'})
        self.assertEqual(response.status_code,303,response.data)
        return response

    def event(self, kind='customer.subscription.updated', value=None, key='evt_test'):
        value=value or self.fake.subs['sub_cs_1']
        return {'id':key,'object':'event','type':kind,'livemode':False,'created':int(time.time()),'data':{'object':copy.deepcopy(value)}}

    def deliver(self,event,timestamp=None,signature=None,body=None):
        raw=body if body is not None else json.dumps(event).encode()
        timestamp=int(time.time()) if timestamp is None else timestamp
        expected=hmac.new(ENV['STAFF_STRIPE_WEBHOOK_SECRET'].encode(),str(timestamp).encode()+b'.'+raw,hashlib.sha256).hexdigest()
        header=signature or f't={timestamp},v1={expected}'
        return self.client().post('/staff/billing/webhook',data=raw,content_type='application/json',headers={'Stripe-Signature':header})

    def paid(self):
        self.start()
        subscription=self.fake.complete()
        self.assertEqual(self.deliver(self.event()).status_code,200)
        return subscription

    def test_expired_owner_can_checkout_only_after_csrf_and_explicit_consent(self):
        self.assertEqual(self.manager.post('/staff/alpha/subscription/checkout',data={'subscription_consent':'yes'}).status_code,400)
        self.assertEqual(self.post(self.manager,'subscription/checkout').status_code,400)
        self.gateway.create_customer.assert_not_called()
        before=onboarding.status('alpha')
        self.start()
        params=self.gateway.create_checkout.call_args.args[0]
        self.assertEqual(params['mode'],'subscription')
        self.assertEqual(params['line_items'],[{'price':'price_staff','quantity':1}])
        self.assertEqual(params['subscription_data'],{'metadata':params['metadata']})
        self.assertNotIn('trial_end',params['subscription_data'])
        self.assertNotIn('transfer_data',params['subscription_data'])
        self.assertNotIn('payment_intent_data',params)
        self.assertEqual(before,onboarding.status('alpha'))
        self.assertFalse(billing.entitlement('alpha')['paid'])
        self.assertIn(b'TrimTech AI LTD',self.manager.get('/staff/alpha/subscription').data)

    def test_repeated_and_concurrent_checkout_reuses_customer_and_session(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            links=list(pool.map(lambda _:billing.checkout('alpha','test-manager'),range(2)))
        self.assertEqual(links[0],links[1])
        self.assertEqual(self.gateway.create_customer.call_count,1)
        self.assertEqual(self.gateway.create_checkout.call_count,1)
        self.assertEqual(database.fetch_one('SELECT count(*) AS n FROM sb_checkouts')['n'],1)
        self.assertEqual(database.fetch_one('SELECT count(*) AS n FROM sb_accounts')['n'],1)
        self.assertEqual(len(self.fake.customers),1)

    def test_customer_timeout_reuses_durable_idempotency_key_and_never_blindly_retries_after_retention(self):
        keys=[]
        def lost(*args):
            keys.append(args[-1])
            result=self.fake.create_customer(*args)
            if len(keys)==1:
                raise stripe.APIConnectionError('private provider message')
            return result
        self.gateway.create_customer.side_effect=lost
        self.assertEqual(self.post(self.manager,'subscription/checkout',{'subscription_consent':'yes'}).status_code,302)
        self.assertIsNone(database.fetch_one('SELECT customer_id FROM sb_accounts')['customer_id'])
        self.start()
        self.assertEqual(keys[0],keys[1])
        self.assertEqual(len(self.fake.customers),1)
        # An unresolved older intent is blocked rather than using an expired idempotency key.
        database.execute("UPDATE sb_accounts SET customer_id=NULL,customer_requested_at=NOW()-INTERVAL '25 hours'")
        with self.assertRaises(transport.BillingUnavailable):
            billing.checkout('alpha','test-manager')
        self.assertEqual(len(keys),2)

    def test_checkout_timeout_recovers_session_without_second_charge_or_customer(self):
        def lost(params,key):
            self.fake.create_checkout(params,key)
            raise stripe.APIConnectionError('secret request detail')
        self.gateway.create_checkout.side_effect=lost
        with self.assertLogs(billing_routes.logger,level='WARNING') as logged:
            self.assertEqual(self.post(self.manager,'subscription/checkout',{'subscription_consent':'yes'}).status_code,302)
        self.assertNotIn('secret request detail',str(logged.output))
        self.assertIsNone(database.fetch_one('SELECT session_id FROM sb_checkouts')['session_id'])
        self.start()
        self.assertEqual(self.gateway.create_checkout.call_count,1)
        self.assertEqual(len(self.fake.sessions),1)

    def test_signature_raw_body_tolerance_mode_and_connected_account_checks(self):
        self.start();self.fake.complete()
        event=self.event()
        for response in (self.deliver(event,signature='t=1,v1=wrong'),self.deliver(event,timestamp=int(time.time())-600),
                         self.deliver(event,body=b'not json'),self.client().post('/staff/billing/webhook',data=b'{}')):
            self.assertEqual(response.status_code,400)
        for changes in ({'livemode':True},{'account':'acct_other'},{'context':'acct_other'}):
            response=self.deliver({**event,**changes})
            self.assertEqual(response.json['result'],'ignored')
        self.assertFalse(database.fetch_all('SELECT * FROM sb_events'))
        self.assertFalse(billing.entitlement('alpha')['paid'])
        self.assertEqual(self.client().post('/staff/billing/webhook',data=b'x'*262145).status_code,413)
        self.assertEqual(self.deliver(event).status_code,200)
        self.assertTrue(billing.entitlement('alpha')['paid'])

    def test_event_duplicates_and_out_of_order_payloads_use_current_stripe_state(self):
        subscription=self.paid()
        old=self.event(key='evt_old')
        subscription.update(status='past_due')
        subscription['latest_invoice'].update(status='open',amount_remaining=4900)
        self.assertEqual(self.deliver(old).status_code,200)
        self.assertFalse(billing.entitlement('alpha')['paid'])
        subscription.update(status='active')
        subscription['latest_invoice'].update(status='paid',amount_remaining=0)
        failed=self.event('invoice.payment_failed',subscription['latest_invoice'],key='evt_late_failure')
        self.assertEqual(self.deliver(failed).status_code,200)
        self.assertTrue(billing.entitlement('alpha')['paid'])
        before=self.gateway.subscription.call_count
        self.assertEqual(self.deliver(failed).json['result'],'duplicate')
        self.assertEqual(self.gateway.subscription.call_count,before)
        # Event creation timestamps, including equal timestamps, are not used as ordering cursors.
        old['id']='evt_same_time'
        self.assertEqual(self.deliver(old).status_code,200)
        self.assertTrue(billing.entitlement('alpha')['paid'])

    def test_concurrent_duplicate_webhooks_process_once(self):
        self.start();self.fake.complete()
        event=self.event()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:billing.process_event(event,transport.configuration()),range(2)))
        self.assertEqual(sorted(results),['duplicate','processed'])
        self.assertEqual(database.fetch_one('SELECT count(*) AS n FROM sb_events')['n'],1)
        self.assertEqual(self.gateway.subscription.call_count,1)

    def test_webhook_failure_rolls_back_event_receipt_and_can_retry(self):
        self.start();self.fake.complete()
        self.gateway.subscription.side_effect=stripe.APIConnectionError('private failure')
        self.assertEqual(self.deliver(self.event()).status_code,503)
        self.assertFalse(database.fetch_all('SELECT * FROM sb_events'))
        self.assertFalse(database.fetch_all('SELECT * FROM sb_subscriptions'))
        self.gateway.subscription.side_effect=None
        self.assertEqual(self.deliver(self.event()).status_code,200)
        self.assertTrue(billing.entitlement('alpha')['paid'])

    def test_subscription_statuses_and_paid_period_expiry_preserve_business_data(self):
        subscription=self.paid()
        before=database.fetch_all('SELECT * FROM staff_employees ORDER BY id')
        for index,status in enumerate(('past_due','unpaid','incomplete','incomplete_expired','canceled','paused','trialing')):
            subscription['status']=status
            self.assertEqual(self.deliver(self.event(key='evt_status'+str(index))).status_code,200)
            self.assertFalse(billing.entitlement('alpha')['paid'],status)
            self.assertEqual(self.manager.get('/staff/alpha').status_code,200)
            self.assertEqual(self.post(self.manager,'setup',{'step':'company','reviewed':'on'}).status_code,402)
        subscription.update(status='active',cancel_at_period_end=True)
        self.assertEqual(self.deliver(self.event(key='evt_cancel_scheduled')).status_code,200)
        self.assertTrue(billing.entitlement('alpha')['paid'])
        database.execute("UPDATE sb_subscriptions SET paid_until=NOW()-INTERVAL '1 second'")
        self.assertFalse(billing.entitlement('alpha')['paid'])
        self.assertEqual(before,database.fetch_all('SELECT * FROM staff_employees ORDER BY id'))
        self.assertIsNotNone(self.row('staff_shifts',self.old_shift))

    def test_paid_access_restores_writes_without_restarting_trial_and_return_url_is_not_authority(self):
        before=onboarding.status('alpha')
        self.start()
        self.assertEqual(self.manager.get('/staff/alpha/subscription?checkout=returned&session_id=cs_foreign').status_code,200)
        self.assertEqual(onboarding.access('alpha')['state'],'expired')
        self.fake.complete()
        self.assertEqual(self.post(self.manager,'subscription/refresh').status_code,302)
        self.assertEqual(onboarding.access('alpha')['state'],'paid')
        self.assertEqual(onboarding.status('alpha'),before)
        self.assertEqual(self.post(self.manager,'setup',dict(step='company',reviewed='on',business_name='Alpha',business_type='Garage',company_address='1 Test Street')).status_code,302)
        self.assertEqual(self.gateway.create_checkout.call_count,1)
        self.assertIsNone(billing.checkout('alpha','test-manager'))
        self.assertEqual(self.gateway.create_checkout.call_count,1)

    def test_owner_only_billing_tenant_isolation_and_server_chosen_price(self):
        for path in ('subscription','subscription/checkout','subscription/portal','subscription/refresh'):
            method=self.manager.get if path=='subscription' else self.manager.post
            self.assertEqual(method('/staff/beta/'+path,data={'csrf_token':'test-csrf','subscription_consent':'yes'}).status_code,404)
        self.assertEqual(self.worker.get('/staff/alpha/subscription').status_code,302)
        database.execute("UPDATE sm_memberships SET role='administrator' WHERE business_id='alpha'")
        self.assertEqual(self.manager.get('/staff/alpha/subscription').status_code,403)
        self.gateway.create_customer.assert_not_called()
        database.execute("UPDATE sm_memberships SET role='owner' WHERE business_id='alpha'")
        response=self.post(self.manager,'subscription/checkout',{'subscription_consent':'yes','price_id':'price_paychaser',
            'customer':'cus_beta','business_id':'beta','return_url':'https://evil.example'})
        self.assertEqual(response.status_code,303)
        params=self.gateway.create_checkout.call_args.args[0]
        self.assertEqual(params['customer'],'cus_alpha')
        self.assertEqual(params['line_items'][0]['price'],'price_staff')
        self.assertTrue(params['success_url'].startswith(ENV['STAFF_PUBLIC_BASE_URL']))

    def test_paychaser_and_unbound_subscription_events_never_grant_staff_access(self):
        self.start()
        subscription=self.fake.complete()
        foreign=copy.deepcopy(subscription);foreign['customer']='cus_paychaser'
        self.assertEqual(self.deliver(self.event(value=foreign)).json['result'],'ignored')
        subscription['metadata']['application']='paychaser'
        self.assertEqual(self.deliver(self.event()).status_code,503)
        self.assertFalse(billing.entitlement('alpha')['paid'])
        subscription['metadata']['application']=transport.APPLICATION
        subscription['metadata']['business_id']='beta'
        self.assertEqual(self.deliver(self.event()).status_code,503)
        self.assertFalse(database.fetch_all('SELECT * FROM sb_subscriptions'))

    def test_wrong_price_pause_or_unpaid_invoice_cannot_grant_access(self):
        self.start();subscription=self.fake.complete()
        subscription['items']['data'][0]['price']['id']='price_paychaser'
        self.assertEqual(self.deliver(self.event()).status_code,200)
        self.assertFalse(billing.entitlement('alpha')['paid'])
        subscription['items']['data'][0]['price']['id']='price_staff'
        subscription['pause_collection']={'behavior':'void'}
        self.assertEqual(self.deliver(self.event(key='evt_pause')).status_code,200)
        self.assertFalse(billing.entitlement('alpha')['paid'])
        subscription.pop('pause_collection')
        subscription['latest_invoice'].update(status='open',amount_remaining=4900)
        self.assertEqual(self.deliver(self.event(key='evt_unpaid')).status_code,200)
        self.assertFalse(billing.entitlement('alpha')['paid'])

    def test_portal_is_staff_only_and_reuses_customer(self):
        self.paid()
        self.assertEqual(self.post(self.manager,'subscription/portal').status_code,303)
        self.gateway.create_portal.assert_called_once_with('cus_alpha','https://staff.example.test/staff/alpha/subscription')
        self.assertEqual(self.gateway.create_customer.call_count,1)
        self.fake.extra_invoices=[{'id':'in_client','subscription':None}]
        with self.assertRaises(transport.BillingUnavailable):
            billing.portal('alpha')
        self.fake.extra_invoices=[]
        self.fake.configuration['features']['subscription_update']['enabled']=True
        with self.assertRaises(transport.BillingUnavailable):
            billing.portal('alpha')
        self.assertEqual(self.gateway.create_portal.call_count,1)

    def test_expired_checkout_can_be_replaced_but_unknown_outcome_cannot(self):
        self.start()
        self.fake.sessions['cs_1']['status']='expired'
        event=self.event('checkout.session.expired',self.fake.sessions['cs_1'])
        self.assertEqual(self.deliver(event).status_code,200)
        self.start()
        self.assertEqual(len(self.fake.sessions),2)
        self.assertEqual(len(self.fake.customers),1)
        database.execute("UPDATE sb_checkouts SET session_id=NULL,expires_at=NOW()-INTERVAL '2 hours' WHERE status='open'")
        self.gateway.checkouts.return_value={'data':[],'has_more':False}
        with self.assertRaises(transport.BillingUnavailable):
            billing.checkout('alpha','test-manager')
        self.assertEqual(len(self.fake.sessions),2)

    def test_billing_migration_repeatability_and_rollback_preserve_all_earlier_schemas(self):
        with database.transaction() as connection:
            with connection.cursor() as cursor:
                before=(migrations.schema_fingerprint(cursor),accounts_migration.fingerprint(cursor),onboarding_migration.fingerprint(cursor))
                billing_migration.migrate(cursor)
                billing_migration.verify(cursor)
                self.assertEqual(before,(migrations.schema_fingerprint(cursor),accounts_migration.fingerprint(cursor),onboarding_migration.fingerprint(cursor)))
        with self.assertRaises(UndefinedTable):
            with database.transaction() as connection:
                with connection.cursor() as cursor:
                    cursor.execute('DROP TABLE sb_events,sb_subscriptions,sb_checkouts,sb_accounts,sb_schema_migrations')
                    with patch.object(billing_migration,'SQL',billing_migration.SQL+'; SELECT * FROM deliberately_missing_billing_table'):
                        billing_migration.migrate(cursor)
        with database.transaction() as connection:
            with connection.cursor() as cursor:
                billing_migration.verify(cursor)
                migrations.verify(cursor)
                accounts_migration.verify(cursor)
                onboarding_migration.verify(cursor)


class GatewayTests(unittest.TestCase):
    def setUp(self):
        env=patch.dict(os.environ,ENV);env.start();self.addCleanup(env.stop)

    def test_missing_or_mixed_configuration_never_falls_back_to_shared_stripe_key(self):
        for changes in ({'STAFF_STRIPE_ENABLED':'0'},{'STAFF_STRIPE_SECRET_KEY':'','STRIPE_SECRET_KEY':'sk_live_other'},
                        {'STAFF_STRIPE_SECRET_KEY':'sk_live_other'},{'STAFF_PUBLIC_BASE_URL':'https://evil@example.test'}):
            with patch.dict(os.environ,changes),self.assertRaises(transport.BillingUnavailable):
                transport.configuration()
        for target in ('http://checkout.stripe.com/x','https://checkout.stripe.com.evil.test/x','https://evil@checkout.stripe.com/x'):
            with self.assertRaises(transport.BillingUnavailable):
                transport.safe_url(target,'checkout.stripe.com')

    def test_real_sdk_adapter_options_and_verified_merchant_price(self):
        config=transport.configuration()
        with patch.object(stripe,'StripeClient') as constructor:
            gateway=transport.Gateway(config)
        client=constructor.return_value
        account={'id':config.account,'company':{'name':'TrimTech AI LTD'},'charges_enabled':True}
        client.v1.accounts.retrieve_current.return_value.to_dict.return_value=account
        gateway.merchant()
        account['company']['name']='Someone Else Ltd'
        with self.assertRaises(transport.BillingUnavailable):gateway.merchant()
        price={'id':config.price,'active':True,'livemode':False,'currency':'gbp','type':'recurring',
            'billing_scheme':'per_unit','unit_amount':4900,'tax_behavior':'exclusive',
            'recurring':{'interval':'month','interval_count':1,'usage_type':'licensed'},
            'product':{'id':config.product,'active':True,'metadata':{'application':transport.APPLICATION}}}
        client.v1.prices.retrieve.return_value.to_dict.return_value=price
        self.assertEqual(gateway.price()['amount'],'49.00')
        price['product']['metadata']['application']='paychaser'
        with self.assertRaises(transport.BillingUnavailable):gateway.price()
        gateway.create_customer('alpha','Alpha','owner@example.test','durable-key')
        self.assertEqual(client.v1.customers.create.call_args.args[1],{'idempotency_key':'durable-key'})
        self.assertNotIn('stripe_account',constructor.call_args.kwargs)
