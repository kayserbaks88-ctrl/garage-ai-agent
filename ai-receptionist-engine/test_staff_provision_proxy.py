"""Owner provisioning and proxy spoof-resistance regression tests."""
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from flask import Flask
from psycopg2.errors import UndefinedTable

import test_staff_agency as fixtures
from trimtech.modules.staff import accounts, database, provision_owners as owners
from trimtech.modules.staff.trusted_proxy import resolve, trusted_networks, client_address, ProxyConfigurationError


class TrustedProxyTests(unittest.TestCase):
    def test_untrusted_peer_and_default_ignore_all_forwarding(self):
        self.assertEqual(resolve('203.0.113.20','1.2.3.4',()),'203.0.113.20')
        self.assertEqual(resolve('203.0.113.20','1.2.3.4',trusted_networks('10.2.3.4/32')),'203.0.113.20')
        self.assertEqual(resolve('invalid','1.2.3.4',()),'unknown')

    def test_rightmost_untrusted_address_stops_before_spoofed_prefix(self):
        networks=trusted_networks('10.2.3.4/32,192.0.2.10/32')
        for prefix in ('1.2.3.4','garbage','1.1.1.1, 2.2.2.2'):
            self.assertEqual(resolve('10.2.3.4',prefix+', 203.0.113.20, 192.0.2.10',networks),'203.0.113.20')
        self.assertEqual(resolve('10.2.3.4','1.2.3.4, 192.0.2.11',networks),'192.0.2.11')

    def test_malformed_incomplete_and_oversized_chain_falls_back_to_peer(self):
        networks=trusted_networks('10.2.3.4/32,192.0.2.10/32')
        for header in ('','192.0.2.10','203.0.113.20, invalid','203.0.113.20,','a'*2049,','.join(['1.2.3.4']*21)):
            self.assertEqual(resolve('10.2.3.4',header,networks),'10.2.3.4')

    def test_ipv6_and_mapped_ipv4_normalise_and_scopes_are_rejected(self):
        networks=trusted_networks('2001:db8::1/128,10.2.3.4/32')
        self.assertEqual(resolve('2001:db8::1','2001:db8:1::123',networks),'2001:db8:1::123')
        self.assertEqual(resolve('::ffff:10.2.3.4','::ffff:203.0.113.20',networks),'203.0.113.20')
        self.assertEqual(resolve('2001:db8::1','fe80::1%eth0',networks),'2001:db8::1')

    def test_invalid_config_is_not_silently_trusted(self):
        for value in ('*','0.0.0.0/0','::/0','10.0.0.0/8','10.2.3.4/24','not-an-address'):
            with self.assertRaises(ProxyConfigurationError):
                trusted_networks(value)

    def test_staff_resolver_does_not_rewrite_shared_request_or_trust_other_headers(self):
        app=Flask(__name__)
        with patch.dict(os.environ,STAFF_TRUSTED_PROXY_CIDRS='10.2.3.4/32'):
            with app.test_request_context('/',headers={'X-Forwarded-For':'203.0.113.20','CF-Connecting-IP':'1.2.3.4','X-Real-IP':'5.6.7.8'},environ_overrides={'REMOTE_ADDR':'10.2.3.4'}):
                from flask import request
                self.assertEqual(client_address(),'203.0.113.20')
                self.assertEqual(request.remote_addr,'10.2.3.4')
            with app.test_request_context('/',headers={'X-Forwarded-For':'1.2.3.4'},environ_overrides={'REMOTE_ADDR':'1.2.3.4','werkzeug.proxy_fix.orig':{'REMOTE_ADDR':'203.0.113.20'}}):
                self.assertEqual(client_address(),'203.0.113.20')


@unittest.skipUnless(os.getenv('STAFF_TEST_DATABASE_URL'),'Requires isolated PostgreSQL')
class OwnerProvisionTests(unittest.TestCase):
    for name in ('cleanup_schema','connect','insert','client','post','row'):
        locals()[name]=getattr(fixtures.AgencyDatabaseTests,name)

    def setUp(self):
        fixtures.AgencyDatabaseTests.setUp(self)
        database.execute("INSERT INTO staff_business_settings(business_id) VALUES ('legacy-owner')")
        self.document={'operator':'test-operator','reason':'Owner identity checked against approved records',
            'owners':[{'business_id':'legacy-owner','business_name':'Existing company','contact_name':'Owner','email':'owner@example.test'}]}
        self.send=patch.object(accounts,'send_staff_email')
        self.mail=self.send.start();self.addCleanup(self.send.stop)

    def test_read_only_default_then_repeatable_apply_and_owner_verification(self):
        rows=database.fetch_all('SELECT * FROM staff_business_settings ORDER BY business_id')
        with patch.object(owners,'_inspect',wraps=owners._inspect) as inspection:
            report=owners.provision(self.document)
            self.assertEqual(inspection.call_count,1)
        self.assertEqual(report['mode'],'read-only dry run')
        self.assertIsNone(database.fetch_one("SELECT * FROM sm_administrators WHERE email='owner@example.test'"))
        owners.provision(self.document,True,report['manifest_sha256'])
        snapshot=database.fetch_all('SELECT * FROM sm_administrators ORDER BY id')
        audit=database.fetch_all('SELECT * FROM sm_owner_provisions')
        owners.provision(self.document,True,report['manifest_sha256'])
        self.assertEqual(snapshot,database.fetch_all('SELECT * FROM sm_administrators ORDER BY id'))
        self.assertEqual(audit,database.fetch_all('SELECT * FROM sm_owner_provisions'))
        self.assertEqual(rows,database.fetch_all('SELECT * FROM staff_business_settings ORDER BY business_id'))
        self.assertIsNone(accounts.authenticate('owner@example.test','unknown password'))
        details=accounts.request_token('owner@example.test','verify')
        self.assertTrue(accounts.consume(details[1],'verify','owner chooses a secure password'))
        raw=accounts.authenticate('owner@example.test','owner chooses a secure password')
        client=self.client();client.set_cookie('__Host-staff_admin',raw)
        self.assertEqual(client.get('/staff/legacy-owner').status_code,200)
        self.assertEqual(client.get('/staff/alpha').status_code,404)
        self.mail.assert_not_called()

    def test_existing_credentials_sessions_and_memberships_are_preserved(self):
        details=accounts.register('Other company','Original name','owner@example.test','original long password')
        accounts.consume(details[1],'verify','original long password')
        raw=accounts.authenticate('owner@example.test','original long password')
        before=database.fetch_one("SELECT * FROM sm_administrators WHERE email='owner@example.test'")
        existing=database.fetch_all('SELECT * FROM sm_memberships WHERE administrator_id=%s',(before['id'],))
        report=owners.provision(self.document)
        owners.provision(self.document,True,report['manifest_sha256'])
        self.assertEqual(before,database.fetch_one('SELECT * FROM sm_administrators WHERE id=%s',(before['id'],)))
        self.assertIsNotNone(accounts.current(raw))
        for membership in existing:
            self.assertIn(membership,database.fetch_all('SELECT * FROM sm_memberships WHERE administrator_id=%s',(before['id'],)))
        self.assertEqual(database.fetch_one('SELECT count(*) AS n FROM sm_administrators')['n'],2)

    def test_conflicts_unknown_ids_inactive_accounts_and_hash_mismatch_fail_closed(self):
        with self.assertRaises(owners.ProvisionError):
            owners.provision(self.document,True,'wrong')
        for business in ('unknown','alpha'):
            document={**self.document,'owners':[{**self.document['owners'][0],'business_id':business}]}
            with self.assertRaises(owners.ProvisionError):
                owners.provision(document)
        report=owners.provision(self.document)
        owners.provision(self.document,True,report['manifest_sha256'])
        database.execute("UPDATE sm_memberships SET active=FALSE WHERE business_id='legacy-owner'")
        with self.assertRaises(owners.ProvisionError):
            owners.provision(self.document,True,report['manifest_sha256'])
        database.execute("UPDATE sm_memberships SET active=TRUE WHERE business_id='legacy-owner'")
        database.execute("UPDATE sm_administrators SET active=FALSE WHERE email='owner@example.test'")
        with self.assertRaises(owners.ProvisionError):
            owners.provision(self.document)

    def test_batch_conflict_rolls_back_earlier_provisioning_and_preserves_other_tables(self):
        database.execute('CREATE TABLE garage_probe(id INTEGER PRIMARY KEY)')
        database.execute('CREATE TABLE paychaser_probe(id INTEGER PRIMARY KEY)')
        database.execute('INSERT INTO garage_probe VALUES (1)')
        database.execute('INSERT INTO paychaser_probe VALUES (1)')
        # First entry is valid, later entry unknown: nothing in the batch can commit.
        document={**self.document,'owners':self.document['owners']+[{**self.document['owners'][0],'business_id':'zzz-unknown'}]}
        _,fingerprint=owners.manifest(document)
        with self.assertRaises(owners.ProvisionError):
            owners.provision(document,True,fingerprint)
        self.assertIsNone(database.fetch_one("SELECT * FROM sm_businesses WHERE id='legacy-owner'"))
        self.assertFalse(database.fetch_all('SELECT * FROM sm_owner_provisions'))
        for table in ('garage_probe','paychaser_probe'):
            self.assertEqual(database.fetch_one('SELECT count(*) AS n FROM '+table)['n'],1)

    def test_concurrent_retries_do_not_duplicate_owners(self):
        report=owners.provision(self.document)
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda _:owners.provision(self.document,True,report['manifest_sha256']),range(2)))
        self.assertEqual(database.fetch_one("SELECT count(*) AS n FROM sm_memberships WHERE business_id='legacy-owner'")['n'],1)
        self.assertEqual(database.fetch_one('SELECT count(*) AS n FROM sm_owner_provisions')['n'],1)

    def test_proxy_spoofing_cannot_bypass_persistent_account_rate_limits(self):
        with patch.dict(os.environ,STAFF_TRUSTED_PROXY_CIDRS='10.2.3.4/32'):
            for index in range(6):
                response=self.client().post('/staff/account/login',data={'csrf_token':'test-csrf','email':'unknown@example.test','password':'a long fake password'},
                    headers={'X-Forwarded-For':f'1.1.1.{index}, 203.0.113.20'},environ_overrides={'REMOTE_ADDR':'10.2.3.4'})
                self.assertEqual(response.status_code,401 if index<5 else 429)
        # One address bucket despite a different forged prefix for every request.
        self.assertEqual(database.fetch_one('SELECT count(*) AS n FROM sm_rate_limits')['n'],2)
        with patch.dict(os.environ,STAFF_TRUSTED_PROXY_CIDRS='*'):
            response=self.client().post('/staff/account/login',data={'csrf_token':'test-csrf','email':'someone@example.test','password':'a long fake password'})
            self.assertEqual(response.status_code,503)
