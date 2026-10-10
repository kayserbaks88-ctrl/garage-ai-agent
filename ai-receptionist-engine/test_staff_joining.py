"""Disposable PostgreSQL approval and tenant regression tests; delivery is mocked."""
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from trimtech.modules.staff import joining, joining_migration, database, onboarding, employee_invitations, migrations, accounts_migration, onboarding_migration
import test_staff_agency as fixtures

PASSWORD='  employee secure passphrase  '

@unittest.skipUnless(os.getenv('STAFF_TEST_DATABASE_URL'),'Requires isolated PostgreSQL')
class JoiningTests(unittest.TestCase):
    for name in ('cleanup_schema','connect','insert','client','post','row','gps','enable_agency','assignment_values','assignment','current'):
        locals()[name]=getattr(fixtures.AgencyDatabaseTests,name)

    def setUp(self):
        fixtures.AgencyDatabaseTests.setUp(self)
        with database.transaction() as connection:
            with connection.cursor() as cursor: joining_migration.migrate(cursor)

    def values(self,n=1):
        return dict(full_name='New employee '+str(n),email=f'worker{n}@example.test',phone=f'07700000{n:03}',password=PASSWORD)

    def pending(self,n=1,token=None,business='alpha'):
        joining.register(token or joining.generate(business,7,'manager:test'),self.values(n))
        return database.fetch_one('SELECT * FROM sj_registrations WHERE business_id=%s AND email=%s',(business,self.values(n)['email']))

    def test_many_employees_share_one_link_without_access_until_approval(self):
        token=joining.generate('alpha',7,'manager:test')
        first=self.pending(1,token);second=self.pending(2,token)
        self.assertEqual(joining.preview(token),'Alpha')
        self.assertEqual(joining.counts('alpha'),dict(active=2,awaiting=0,pending=2,rejected=0))
        self.assertNotIn(token,str(database.fetch_all('SELECT * FROM sj_links')))
        self.assertNotIn(PASSWORD,str(first))
        response=self.post(self.client(),'employee/login',dict(phone=first['phone'],payroll_number=PASSWORD))
        self.assertEqual(response.status_code,401)
        self.assertEqual(self.post(self.worker,'employees/onboarding',dict(action='approve',registration_id=first['id'],hourly_rate='15')).status_code,302)
        self.assertEqual(self.row('sj_registrations',first['id'])['status'],'pending')
        joining.review('alpha',[first['id'],second['id']],'approve','19.25','manager:test')
        self.assertEqual(joining.counts('alpha'),dict(active=4,awaiting=0,pending=0,rejected=0))
        approved=self.row('sj_registrations',first['id']);employee=self.row('staff_employees',approved['employee_id'])
        self.assertIsNone(approved['password_hash']);self.assertEqual(employee['role'],'staff')
        self.assertEqual(str(employee['hourly_rate']),'19.25');self.assertIsNone(employee['payroll_number'])
        login=self.post(self.client(),'employee/login',dict(phone=employee['phone'],payroll_number=PASSWORD))
        self.assertEqual(login.status_code,302)
        international=self.post(self.client(),'employee/login',dict(phone='+44'+employee['phone'][1:],payroll_number=PASSWORD))
        self.assertEqual(international.status_code,302)
        self.assertEqual(database.fetch_one('SELECT COUNT(*) AS n FROM sm_memberships')['n'],1)

    def test_tenant_ownership_bulk_review_is_atomic_and_replay_fails(self):
        first=self.pending(1);foreign=self.pending(2,business='beta')
        with self.assertRaises(ValueError): joining.review('alpha',[first['id'],foreign['id']],'approve','12','manager:test')
        self.assertEqual(self.row('sj_registrations',first['id'])['status'],'pending')
        page=self.manager.get('/staff/alpha/employees/onboarding')
        self.assertIn(b'worker1@example.test',page.data);self.assertNotIn(b'worker2@example.test',page.data)
        self.assertEqual(self.manager.get('/staff/beta/employees/onboarding').status_code,404)
        response=self.manager.post('/staff/beta/employees/onboarding',data=dict(csrf_token='test-csrf',action='approve',registration_id=foreign['id'],hourly_rate='12'))
        self.assertEqual(response.status_code,404)
        joining.review('alpha',[first['id']],'reject',None,'manager:test')
        with self.assertRaises(ValueError): joining.review('alpha',[first['id']],'approve','12','manager:test')
        self.assertEqual(joining.counts('alpha')['rejected'],1)
        self.assertEqual(joining.counts('beta')['pending'],1)

    def test_registration_cannot_control_pay_roles_scope_or_approval(self):
        token=joining.generate('alpha',7,'manager:test')
        for key in ('business_id','role','hourly_rate','status','employee_id','approved','permissions'):
            with self.subTest(key=key),self.assertRaises(ValueError): joining.register(token,{**self.values(),key:'owner'})
        self.assertEqual(joining.counts('alpha')['pending'],0)
        for password in ('short','x'*129):
            with self.assertRaises(ValueError): joining.register(token,{**self.values(), 'password':password})

    def test_duplicates_normalization_and_existing_manual_employee_collision(self):
        token=joining.generate('alpha',7,'manager:test');first=self.pending(1,token)
        with self.assertRaises(ValueError): joining.register(token,{**self.values(2),'email':' WORKER1@example.test '})
        with self.assertRaises(ValueError): joining.register(token,{**self.values(2),'phone':'+44'+first['phone'][1:]})
        self.post(self.manager,'employees',dict(full_name='Manual',phone=first['phone'],email=first['email'],hourly_rate='12',role='staff'))
        with self.assertRaises(ValueError): joining.review('alpha',[first['id']],'approve','12','manager:test')
        self.assertEqual(self.row('sj_registrations',first['id'])['status'],'pending')
        joining.review('alpha',[first['id']],'reject',None,'manager:test')
        with self.assertRaises(ValueError): joining.register(token,self.values())

    def test_concurrent_duplicate_registration_creates_one_request(self):
        token=joining.generate('alpha',7,'manager:test')
        def submit(_):
            try: joining.register(token,self.values());return True
            except ValueError: return False
        with ThreadPoolExecutor(max_workers=2) as pool: self.assertEqual(sorted(pool.map(submit,range(2))),[False,True])
        self.assertEqual(joining.counts('alpha')['pending'],1)

    def test_link_expiry_revocation_regeneration_and_existing_pending_review(self):
        old=joining.generate('alpha',1,'manager:test');first=self.pending(1,old)
        new=joining.generate('alpha',30,'manager:test')
        with self.assertRaises(ValueError): joining.register(old,self.values(2))
        joining.revoke('alpha','manager:test')
        with self.assertRaises(ValueError): joining.preview(new)
        joining.review('alpha',[first['id']],'approve','0','manager:test')
        expired=joining.generate('alpha',1,'manager:test')
        database.execute("UPDATE sj_links SET expires_at=NOW()-INTERVAL '1 second' WHERE revoked_at IS NULL")
        with self.assertRaises(ValueError): joining.register(expired,self.values(2))
        for days in ('bad',0,31):
            with self.assertRaises(ValueError): joining.generate('alpha',days,'manager:test')

    def test_public_form_csrf_safe_failure_and_per_ip_rate_limit(self):
        token=joining.generate('alpha',7,'manager:test');client=self.client()
        self.assertEqual(client.get('/staff/join').status_code,200)
        self.assertEqual(client.post('/staff/join',data={**self.values(),'token':token}).status_code,400)
        response=client.post('/staff/join',data={**self.values(),'token':token,'csrf_token':'test-csrf'})
        self.assertEqual(response.status_code,200);self.assertIn(b'pending manager approval',response.data)
        self.assertNotIn(token.encode(),response.data);self.assertNotIn(PASSWORD.encode(),response.data)
        response=client.post('/staff/join',data={**self.values(2),'password':'short','token':token,'csrf_token':'test-csrf'})
        self.assertEqual(response.status_code,400);self.assertIn(token.encode(),response.data)
        # A single link supports more than five employees across separate addresses.
        for n in range(3,10):
            response=self.client().post('/staff/join',data={**self.values(n),'token':token,'csrf_token':'test-csrf'},environ_overrides={'REMOTE_ADDR':f'192.0.2.{n}'})
            self.assertEqual(response.status_code,200)
        with patch('trimtech.modules.staff.joining_routes.accounts.limited',return_value=False),patch.object(joining,'register') as register:
            self.assertEqual(client.post('/staff/join',data={**self.values(20),'token':token,'csrf_token':'test-csrf'}).status_code,429)
            register.assert_not_called()

    def test_invitation_safe_error_categories_and_48_hour_secure_token(self):
        database.execute("UPDATE staff_employees SET email='worker@example.test' WHERE id=%s",(self.employee,))
        for reason,expected in [('email_not_configured','not configured'),('provider_http_403','verified sending domain'),('provider_http_429','rate limiting'),('provider_request_failed','retry later'),('api-secret-token','could not accept')]:
            with self.subTest(reason=reason),patch.object(employee_invitations,'send_staff_email',return_value=(False,reason,None)):
                sent,message=employee_invitations.invite('alpha',self.employee,'https://staff.example.test',detailed=True)
                self.assertFalse(sent);self.assertIn(expected,message);self.assertNotIn('api-secret-token',message)
        row=database.fetch_one('SELECT token_hash,EXTRACT(EPOCH FROM expires_at-created_at) AS seconds,status FROM so_employee_invites ORDER BY created_at DESC LIMIT 1')
        self.assertEqual(len(row['token_hash']),64);self.assertEqual(row['seconds'],172800);self.assertEqual(row['status'],'failed')
        with patch.dict(os.environ,STAFF_PUBLIC_BASE_URL='https://staff.example.test'),patch.object(employee_invitations,'send_staff_email',return_value=(False,'provider_http_403',None)):
            response=self.post(self.manager,'setup/invitations/'+str(self.employee),dict(return_employees='1'))
            self.assertIn(b'verified sending domain',self.manager.get(response.location).data)

    def test_dashboard_counts_and_invitation_acceptance_without_double_counting(self):
        first=self.pending();second=self.pending(2)
        joining.review('alpha',[second['id']],'reject',None,'manager:test')
        database.execute("UPDATE staff_employees SET email='worker@example.test' WHERE id=%s",(self.employee,))
        with patch.object(employee_invitations,'send_staff_email',return_value=(True,None,'provider')) as mail:
            employee_invitations.invite('alpha',self.employee,'https://staff.example.test')
        self.assertEqual(joining.counts('alpha'),dict(active=2,awaiting=1,pending=1,rejected=1))
        token=mail.call_args.args[2].split('#token=')[1].split()[0]
        employee_invitations.accept(token,PASSWORD)
        joining.review('alpha',[first['id']],'approve','15','manager:test')
        self.assertEqual(joining.counts('alpha'),dict(active=3,awaiting=0,pending=0,rejected=1))
        page=self.manager.get('/staff/alpha');self.assertEqual(page.status_code,200)
        for label in (b'Pending registrations',b'Invitations awaiting acceptance',b'Rejected registrations'): self.assertIn(label,page.data)

    def test_combined_stage_preserves_old_progress_and_allows_empty_setup(self):
        with database.transaction() as connection:
            with connection.cursor() as cursor: onboarding.begin(cursor,'alpha','test-manager');onboarding.activate(cursor,'test-manager')
        database.execute("UPDATE staff_employees SET status='inactive' WHERE business_id='alpha'")
        onboarding.save('alpha','company',dict(reviewed='on',business_name='Alpha',business_type='Cleaning',company_address='1 Test Street'))
        onboarding.save('alpha','sites',dict(reviewed='on'))
        response=self.post(self.manager,'setup',dict(step='employees',skip_employees='1'))
        self.assertIn('step=assignments',response.location)
        for step in ('assignments','payroll','review'): onboarding.save('alpha',step,dict(reviewed='on'))
        self.assertEqual(onboarding.checklist('alpha')['display_count'],6)
        page=self.manager.get('/staff/alpha/setup?step=invitations');self.assertEqual(page.status_code,200)
        self.assertIn(b'Employees &amp; Invitations',page.data);self.assertIn(b'Skip for now',page.data)
        self.assertEqual(onboarding.status('alpha')['days'],14)

    def test_additive_migration_is_idempotent_and_preserves_existing_schemas(self):
        before=database.fetch_all('SELECT id,full_name,phone,hourly_rate FROM staff_employees ORDER BY id')
        with database.transaction() as connection:
            with connection.cursor() as cursor:
                joining_migration.migrate(cursor);joining_migration.verify(cursor)
                for module in (migrations,accounts_migration,onboarding_migration): module.verify(cursor)
        self.assertEqual(database.fetch_all('SELECT id,full_name,phone,hourly_rate FROM staff_employees ORDER BY id'),before)

    def test_combined_save_requires_activation_and_retains_legacy_progress_keys(self):
        with database.transaction() as connection:
            with connection.cursor() as cursor: onboarding.begin(cursor,'alpha','test-manager');onboarding.activate(cursor,'test-manager')
        # Separate stored steps from old forms remain supported.
        self.assertEqual(onboarding.save('alpha','employees',dict(reviewed='on')),'invitations')
        database.execute("UPDATE so_setup SET current_step='invitations' WHERE business_id='alpha'")
        self.assertEqual(self.manager.get('/staff/alpha/setup').status_code,200)
        with self.assertRaises(ValueError): onboarding.save('alpha','employees',dict(reviewed='on',combined_employees='1'))
        from trimtech.modules.staff import accounts
        for employee in (self.employee,self.second):
            database.execute("INSERT INTO so_employee_credentials(employee_id,business_id,password_hash,version) VALUES (%s,'alpha',%s,'test')",(employee,accounts.password_hash(PASSWORD)))
        response=self.post(self.manager,'setup',dict(step='employees',reviewed='on',combined_employees='1'))
        self.assertIn('step=assignments',response.location)
        progress=onboarding.checklist('alpha')
        self.assertTrue(progress['completed']['employees']);self.assertTrue(progress['completed']['invitations'])
        self.assertTrue(progress['display_done']['employees'])

    def test_trial_expiry_blocks_public_joining_and_manager_approval(self):
        first=self.pending()
        with database.transaction() as connection:
            with connection.cursor() as cursor: onboarding.begin(cursor,'alpha','test-manager');onboarding.activate(cursor,'test-manager')
        token=joining.generate('alpha',7,'manager:test')
        database.execute("UPDATE so_trials SET starts_at=NOW()-INTERVAL '337 hours',ends_at=NOW()-INTERVAL '1 hour' WHERE business_id='alpha'")
        with self.assertRaises(ValueError): joining.register(token,self.values(2))
        with self.assertRaises(ValueError): joining.preview(token)
        response=self.post(self.manager,'employees/onboarding',dict(action='approve',registration_id=first['id'],hourly_rate='15'))
        self.assertEqual(response.status_code,402)
        self.assertEqual(self.row('sj_registrations',first['id'])['status'],'pending')
