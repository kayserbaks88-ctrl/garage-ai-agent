"""Stage 1 accounts tested only with disposable PostgreSQL and mocked delivery."""
import os
import secrets
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from psycopg2.errors import UndefinedTable
from urllib.parse import urlsplit

import test_staff_agency as fixtures
from trimtech.modules.staff import accounts, accounts_migration, database, migrations
from trimtech.modules.staff.manager_auth import COOKIE

PASSWORD='a long unique test passphrase'


@unittest.skipUnless(os.getenv('STAFF_TEST_DATABASE_URL'),'Requires isolated PostgreSQL')
class AccountTests(unittest.TestCase):
    for name in ('cleanup_schema','connect','insert','client','post','row'):
        locals()[name]=getattr(fixtures.AgencyDatabaseTests,name)

    def setUp(self):
        fixtures.AgencyDatabaseTests.setUp(self)
        self.env=patch.dict(os.environ,STAFF_REGISTRATION_ENABLED='1',STAFF_PUBLIC_BASE_URL='https://staff.example.test')
        self.env.start(); self.addCleanup(self.env.stop)
        self.mail=patch.object(accounts,'send_staff_email',return_value=(True,None,'test-provider-id'))
        self.send=self.mail.start(); self.addCleanup(self.mail.stop)

    def submit(self,client,action,**data):
        with client.session_transaction() as session:
            csrf=session.setdefault('_staff_csrf_token','test-csrf')
        return client.post('/staff/account/'+action,data={'csrf_token':csrf,**data})

    def registered(self,email='owner@example.test'):
        details=accounts.register('New business','Owner',email,PASSWORD)
        self.assertTrue(accounts.consume(details[1],'verify',PASSWORD))
        business=database.fetch_one('SELECT business_id FROM sm_memberships WHERE administrator_id=(SELECT id FROM sm_administrators WHERE email=%s)',(email,))['business_id']
        client=self.client()
        self.assertEqual(self.submit(client,'login',email=email,password=PASSWORD).status_code,302)
        return client,business

    def test_registration_verification_login_cookie_and_duplicate(self):
        client=self.client()
        fields=dict(business_name='Business <name>',contact_name='Owner',email=' OWNER@example.test ',password=PASSWORD)
        response=self.submit(client,'register',**fields)
        self.assertEqual(response.status_code,200)
        self.assertEqual(self.send.call_count,1)
        mail=self.send.call_args.args
        self.assertIn('#token=',mail[2])
        token=mail[2].split('#token=')[1].split()[0]
        administrator=database.fetch_one("SELECT * FROM sm_administrators WHERE email='owner@example.test'")
        self.assertNotEqual(administrator['password_hash'],PASSWORD)
        self.assertNotIn(token,str(database.fetch_all('SELECT * FROM sm_tokens')))
        self.assertEqual(self.submit(client,'login',email=fields['email'],password=PASSWORD).status_code,401)
        self.assertEqual(client.get('/staff/account/verify#token='+token).status_code,200)
        self.assertIsNone(database.fetch_one('SELECT verified_at FROM sm_administrators WHERE id=%s',(administrator['id'],))['verified_at'])
        self.assertEqual(self.submit(client,'verify',token=token,password=PASSWORD).status_code,200)
        self.assertEqual(self.submit(client,'verify',token=token,password=PASSWORD).status_code,400)
        login=self.submit(client,'login',email=fields['email'],password=PASSWORD)
        self.assertEqual(login.status_code,302)
        cookie=next(c for c in login.headers.getlist('Set-Cookie') if c.startswith(COOKIE+'='))
        for attribute in ('Secure','HttpOnly','SameSite=Lax','Path=/','Max-Age=28800'):
            self.assertIn(attribute,cookie)
        self.assertIn(b'Business &lt;name&gt;',client.get('/staff/account').data)
        with client.session_transaction() as session:
            self.assertNotIn('dashboard_authenticated',session)
            self.assertNotEqual(session['_staff_csrf_token'],'test-csrf')
        duplicate=self.submit(self.client(),'register',**fields)
        self.assertEqual(duplicate.data,response.data)
        self.assertEqual(self.send.call_count,1)
        self.assertEqual(database.fetch_one("SELECT count(*) AS n FROM sm_administrators WHERE email='owner@example.test'")['n'],1)

    def test_concurrent_duplicate_registration_has_one_business_and_membership(self):
        def attempt(_):
            return accounts.register('Concurrent business','Owner','SAME@example.test',PASSWORD)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(attempt,range(2)))
        self.assertEqual(sum(r is not None for r in results),1)
        self.assertEqual(database.fetch_one("SELECT count(*) AS n FROM sm_businesses WHERE name='Concurrent business'")['n'],1)
        self.assertEqual(database.fetch_one("SELECT count(*) AS n FROM sm_memberships WHERE administrator_id=(SELECT id FROM sm_administrators WHERE email='same@example.test')")['n'],1)

    def test_all_manager_routes_reject_other_tenant_before_read_or_write(self):
        owner,business=self.registered()
        self.assertEqual(owner.get('/staff/'+business).status_code,200)
        self.assertEqual(owner.get('/staff/alpha').status_code,404)
        before=database.fetch_all('SELECT * FROM staff_employees ORDER BY id')
        checked=0
        for rule in self.app.url_map.iter_rules():
            view=self.app.view_functions[rule.endpoint]
            # Both Staff authentication decorators use this wrapper; employee decorators are distinct.
            if '<business_slug>' not in rule.rule or '/employee/' in rule.rule or rule.rule.endswith('/employee'):
                continue
            self.assertTrue(view.__code__.co_filename.endswith('manager_auth.py'),rule.rule)
            if getattr(view,'__code__',None) is None:
                continue
            url=rule.rule.replace('<business_slug>','alpha')
            import re
            url=re.sub(r'<int:[^>]+>','1',url)
            with owner.session_transaction() as session:
                csrf=session['_staff_csrf_token']
            response=owner.post(url,data={'csrf_token':csrf}) if 'POST' in rule.methods else owner.get(url)
            self.assertEqual(response.status_code,404,(rule.rule,response.status_code))
            checked+=1
        self.assertGreater(checked,30)
        self.assertEqual(before,database.fetch_all('SELECT * FROM staff_employees ORDER BY id'))
        self.assertEqual(owner.get('/staff/'+business.upper()).status_code,404)
        self.assertEqual(self.worker.get('/staff/alpha').status_code,302)
        legacy=self.client()
        with legacy.session_transaction() as session:
            session['dashboard_authenticated']=True
            session['platform_admin_authenticated']=True
            session['business_user_authenticated']=True
        self.assertEqual(legacy.get('/staff/alpha').status_code,302)
        self.assertEqual(legacy.get('/staff/'+business).status_code,302)

    def test_logout_expiry_revocation_and_membership_inactivation(self):
        owner,business=self.registered()
        raw=owner.get_cookie(COOKIE).value
        database.execute('UPDATE sm_memberships SET active=FALSE WHERE business_id=%s',(business,))
        self.assertEqual(owner.get('/staff/'+business).status_code,404)
        database.execute('UPDATE sm_memberships SET active=TRUE WHERE business_id=%s',(business,))
        database.execute("UPDATE sm_sessions SET expires_at=NOW()-INTERVAL '1 second' WHERE token_hash=%s",(accounts.digest(raw),))
        self.assertEqual(owner.get('/staff/'+business).status_code,302)
        self.submit(owner,'login',email='owner@example.test',password=PASSWORD)
        raw=owner.get_cookie(COOKIE).value
        self.assertEqual(self.submit(owner,'logout').status_code,302)
        owner.set_cookie(COOKIE,raw)
        self.assertEqual(owner.get('/staff/'+business).status_code,302)
        self.assertFalse(database.fetch_one('SELECT * FROM sm_sessions WHERE token_hash=%s',(accounts.digest(raw),)))

    def test_password_reset_invalidates_all_sessions_and_other_reset_tokens(self):
        owner,business=self.registered()
        second=self.client();self.submit(second,'login',email='owner@example.test',password=PASSWORD)
        details=accounts.request_token('owner@example.test','reset')
        older=accounts.request_token('owner@example.test','reset')
        new='another long unique passphrase'
        self.assertFalse(accounts.consume(details[1],'verify',new))
        self.assertEqual(self.submit(self.client(),'reset',token=details[1],password=new).status_code,200)
        self.assertFalse(accounts.consume(older[1],'reset',new))
        self.assertEqual(owner.get('/staff/'+business).status_code,302)
        self.assertEqual(second.get('/staff/'+business).status_code,302)
        self.assertIsNone(accounts.authenticate('owner@example.test',PASSWORD))
        self.assertIsNotNone(accounts.authenticate('owner@example.test',new))

    def test_expired_tokens_single_use_race_and_email_owner_controls_password(self):
        details=accounts.register('A','B','verify@example.test',PASSWORD)
        database.execute("UPDATE sm_tokens SET expires_at=NOW()-INTERVAL '1 second'")
        self.assertFalse(accounts.consume(details[1],'verify',PASSWORD))
        details=accounts.request_token('verify@example.test','verify')
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:accounts.consume(details[1],'verify','email owner chosen passphrase'),range(2)))
        self.assertEqual(results.count(True),1)
        self.assertIsNone(accounts.authenticate('verify@example.test',PASSWORD))
        self.assertIsNotNone(accounts.authenticate('verify@example.test','email owner chosen passphrase'))

    def test_csrf_input_limits_shared_rate_limits_and_registration_gate(self):
        client=self.client()
        self.assertEqual(client.post('/staff/account/register',data={}).status_code,400)
        self.assertEqual(client.post('/staff/account/register',data={'x':'a'*17000}).status_code,413)
        self.assertEqual(self.submit(client,'register',business_name='A',contact_name='B',email='bad',password=PASSWORD).status_code,400)
        self.assertEqual(self.submit(client,'register',business_name='A',contact_name='B',email='a@example.test',password='short').status_code,400)
        for _ in range(5):
            self.assertEqual(self.submit(self.client(),'login',email='unknown@example.test',password=PASSWORD).status_code,401)
        self.assertEqual(self.submit(self.client(),'login',email='unknown@example.test',password=PASSWORD).status_code,429)
        with patch.dict(os.environ,STAFF_REGISTRATION_ENABLED='0'):
            self.assertEqual(client.get('/staff/account/register').status_code,503)
        self.assertEqual(database.fetch_one("SELECT count(*) AS n FROM sm_businesses")['n'],2)

    def test_delivery_failure_is_recoverable_and_logs_do_not_contain_secrets(self):
        details=accounts.register('A','B','secret-recipient@example.test',PASSWORD)
        self.send.side_effect=RuntimeError('secret token credential')
        with self.assertLogs(accounts.logger,level='INFO') as output:
            accounts.send_link(details,'verify','https://staff.example.test')
        for secret in (details[0],details[1],PASSWORD,'secret token credential'):
            self.assertNotIn(secret,str(output.output))
        self.assertIn('failed',str(output.output))
        self.assertIsNotNone(accounts.request_token(details[0],'verify'))
        self.assertEqual(self.submit(self.client(),'resend',email=details[0]).status_code,200)

    def test_migration_repeatability_rollback_and_operational_fingerprint(self):
        with database.transaction() as connection:
            with connection.cursor() as cursor:
                before=migrations.schema_fingerprint(cursor)
                accounts_migration.migrate(cursor)
                accounts_migration.verify(cursor)
                migrations.verify(cursor)
                self.assertEqual(before,migrations.schema_fingerprint(cursor))
        # DDL and registry updates are rolled back by the shared transaction helper.
        with self.assertRaises(RuntimeError):
            with database.transaction() as connection:
                with connection.cursor() as cursor:
                    cursor.execute('CREATE TABLE sm_rollback_probe(id INTEGER)')
                    cursor.execute("UPDATE sm_schema_migrations SET checksum='broken'")
                    raise RuntimeError('simulated failure')
        self.assertIsNone(database.fetch_one("SELECT to_regclass('sm_rollback_probe') AS name")['name'])
        with database.transaction() as connection:
            with connection.cursor() as cursor:
                accounts_migration.verify(cursor)

    def test_failed_identity_migration_rolls_back_all_ddl(self):
        # Remove only this fixture's identity tables inside a transaction that will fail.
        with self.assertRaises(UndefinedTable):
            with database.transaction() as connection:
                with connection.cursor() as cursor:
                    cursor.execute('DROP TABLE sb_events,sb_subscriptions,sb_checkouts,sb_accounts,sb_schema_migrations')
                    cursor.execute('DROP TABLE so_employee_invites,so_employee_credentials,so_setup,so_trial_claims,so_trials,so_schema_migrations')
                    cursor.execute('DROP TABLE sm_owner_provisions,sm_tokens,sm_sessions,sm_memberships,sm_administrators,sm_businesses,sm_rate_limits,sm_schema_migrations')
                    with patch.object(accounts_migration,'SQL',accounts_migration.SQL+'; SELECT * FROM deliberately_missing_identity_table'):
                        accounts_migration.migrate(cursor)
        self.assertEqual(database.fetch_one('SELECT count(*) AS n FROM sm_businesses')['n'],2)
        self.assertEqual(database.fetch_one('SELECT count(*) AS n FROM sm_administrators')['n'],1)
        with database.transaction() as connection:
            with connection.cursor() as cursor:
                accounts_migration.verify(cursor)
                migrations.verify(cursor)

    def test_staff_login_does_not_grant_shared_dashboard_or_employee_access(self):
        from dashboard_auth import dashboard_login_required
        self.app.add_url_rule('/shared-dashboard-probe',view_func=dashboard_login_required(lambda:'shared dashboard'))
        owner,business=self.registered()
        self.assertEqual(owner.get('/shared-dashboard-probe').status_code,302)
        self.assertEqual(owner.get('/staff/alpha/employee/pay').status_code,302)
        self.assertEqual(owner.get('/staff/'+business+'/employee/pay').status_code,302)
        database.execute("UPDATE sm_administrators SET active=FALSE WHERE email='owner@example.test'")
        self.assertEqual(owner.get('/staff/'+business).status_code,302)

    def test_trial_starts_on_verification_and_expires_after_exactly_fourteen_days(self):
        from datetime import timedelta
        from trimtech.modules.staff import onboarding
        details=accounts.register('Trial business','Owner','trial@example.test',PASSWORD)
        business=database.fetch_one("SELECT business_id FROM sm_memberships WHERE administrator_id=(SELECT id FROM sm_administrators WHERE email='trial@example.test')")['business_id']
        pending=database.fetch_one('SELECT starts_at,ends_at FROM so_trials WHERE business_id=%s',(business,))
        self.assertIsNone(pending['starts_at'])
        self.assertIsNone(pending['ends_at'])
        self.assertEqual(onboarding.status(business)['state'],'pending')
        self.assertTrue(accounts.consume(details[1],'verify',PASSWORD))
        active=database.fetch_one('SELECT starts_at,ends_at FROM so_trials WHERE business_id=%s',(business,))
        self.assertEqual(active['ends_at']-active['starts_at'],timedelta(hours=336))
        self.assertEqual(onboarding.status(business)['state'],'active')
        database.execute("UPDATE so_trials SET starts_at=NOW()-INTERVAL '336 hours'-INTERVAL '1 second',ends_at=NOW()-INTERVAL '1 second' WHERE business_id=%s",(business,))
        self.assertEqual(onboarding.status(business)['state'],'expired')

    def test_expired_trial_keeps_reads_but_blocks_manager_writes(self):
        owner,business=self.registered('expired@example.test')
        database.execute("UPDATE so_trials SET starts_at=NOW()-INTERVAL '336 hours'-INTERVAL '1 second',ends_at=NOW()-INTERVAL '1 second' WHERE business_id=%s",(business,))
        self.assertEqual(owner.get('/staff/'+business).status_code,200)
        with owner.session_transaction() as session:
            csrf=session['_staff_csrf_token']
        response=owner.post('/staff/'+business+'/setup',data={'csrf_token':csrf,'step':'company','reviewed':'on','business_name':'Changed','business_type':'garage','company_address':'1 Test Road'})
        self.assertEqual(response.status_code,402)
        self.assertEqual(database.fetch_one('SELECT name FROM sm_businesses WHERE id=%s',(business,))['name'],'New business')

    def test_guided_setup_requires_activated_employees_and_reviewed_pay_profiles(self):
        from trimtech.modules.staff import onboarding
        _,business=self.registered('setup@example.test')
        database.fetch_one("""INSERT INTO staff_sites(business_id,name,address,latitude,longitude)
            VALUES (%s,'Setup site','1 Test Road',51.5,-0.12) RETURNING id""",(business,))
        employee=database.fetch_one("""INSERT INTO staff_employees(business_id,full_name,phone,email,hourly_rate)
            VALUES (%s,'Setup employee','07000900001','employee@example.test',15) RETURNING id""",(business,))['id']
        onboarding.save(business,'company',dict(reviewed='on',business_name='Setup business',business_type='garage',company_address='1 Test Road'))
        onboarding.save(business,'sites',dict(reviewed='on'))
        onboarding.save(business,'employees',dict(reviewed='on'))
        with self.assertRaises(ValueError):
            onboarding.save(business,'invitations',dict(reviewed='on'))
        database.execute("""INSERT INTO so_employee_credentials(employee_id,business_id,password_hash,version)
            VALUES (%s,%s,%s,'activated')""",(employee,business,accounts.password_hash(PASSWORD)))
        onboarding.save(business,'invitations',dict(reviewed='on'))
        onboarding.save(business,'assignments',dict(reviewed='on'))
        with self.assertRaises(ValueError):
            onboarding.save(business,'payroll',dict(reviewed='on'))
        database.execute("""INSERT INTO staff_payroll_profiles(business_id,employee_id,tax_year,tax_code,tax_basis,frequency,
            ni_category,pension_method,pension_basis,employee_pension_rate,employer_pension_rate,opening_through,reviewed_by)
            VALUES (%s,%s,'2026/27','1257L','cumulative','monthly','A','none','qualifying',0,0,'2026-04-05','manager')""",
            (business,employee))
        onboarding.save(business,'payroll',dict(reviewed='on'))
        onboarding.save(business,'review',dict(reviewed='on'))
        progress=onboarding.checklist(business)
        self.assertTrue(all(progress['done'].values()))
        self.assertEqual(progress['count'],len(onboarding.STEPS))

    def test_employee_invitation_is_single_use_expiring_and_tenant_bound(self):
        from trimtech.modules.staff import employee_invitations
        _,business=self.registered('invite@example.test')
        employee=database.fetch_one("""INSERT INTO staff_employees(business_id,full_name,phone,email)
            VALUES (%s,'Invited employee','07000900002','invitee@example.test') RETURNING id""",(business,))['id']
        with patch.object(employee_invitations,'send_staff_email',return_value=(True,None,'provider-id')) as send:
            self.assertTrue(employee_invitations.invite(business,employee,'https://staff.example.test'))
        raw=send.call_args.args[2].split('Verification code: ')[1]
        invitation=database.fetch_one('SELECT token_hash,status FROM so_employee_invites WHERE employee_id=%s',(employee,))
        self.assertEqual(invitation['status'],'accepted_by_provider')
        self.assertNotEqual(invitation['token_hash'],raw)
        self.assertEqual(employee_invitations.accept(raw,PASSWORD),business)
        with self.assertRaises(ValueError):
            employee_invitations.accept(raw,PASSWORD)
        self.assertIsNotNone(employee_invitations.credential(business,employee))
        with self.assertRaises(ValueError):
            employee_invitations.invite(business,self.foreign_employee,'https://staff.example.test')
        with patch.object(employee_invitations,'send_staff_email',return_value=(True,None,'provider-id')) as send:
            self.assertTrue(employee_invitations.invite(business,employee,'https://staff.example.test'))
        expired_raw=send.call_args.args[2].split('Verification code: ')[1]
        database.execute("UPDATE so_employee_invites SET expires_at=NOW()-INTERVAL '1 second' WHERE employee_id=%s AND consumed_at IS NULL",(employee,))
        with self.assertRaises(ValueError):
            employee_invitations.accept(expired_raw,PASSWORD)
