"""Stage 2: disposable PostgreSQL, mocked delivery, no production connections."""
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from psycopg2.errors import CheckViolation, UndefinedTable
import test_staff_agency as fixtures
from trimtech.modules.staff import accounts, accounts_migration, database, migrations
from trimtech.modules.staff import onboarding, onboarding_migration, employee_invitations, agent

PASSWORD = '  an employee chosen passphrase  '


@unittest.skipUnless(os.getenv('STAFF_TEST_DATABASE_URL'), 'Requires isolated PostgreSQL')
class OnboardingTests(unittest.TestCase):
    for name in ('setUp', 'cleanup_schema', 'connect', 'insert', 'client', 'post', 'row',
                 'gps', 'enable_agency', 'assignment_values', 'assignment', 'current'):
        locals()[name] = getattr(fixtures.AgencyDatabaseTests, name)

    def enrol(self):
        with database.transaction() as connection:
            with connection.cursor() as cursor:
                onboarding.begin(cursor, 'alpha', 'test-manager')
                onboarding.activate(cursor, 'test-manager')

    def expire(self):
        database.execute("UPDATE so_trials SET starts_at=NOW()-INTERVAL '337 hours',ends_at=NOW()-INTERVAL '1 hour' WHERE business_id='alpha'")

    def invite(self, employee=None):
        employee = employee or self.employee
        database.execute('UPDATE staff_employees SET email=%s WHERE id=%s', ('worker@example.test', employee))
        with patch.object(employee_invitations, 'send_staff_email', return_value=(True, None, 'provider')) as mail:
            self.assertTrue(employee_invitations.invite('alpha', employee, 'https://staff.example.test'))
        return mail.call_args.args[2].split('Verification code: ')[1]

    def worker_login(self, client=None, password=PASSWORD):
        client = client or self.client()
        response = self.post(client, 'employee/login', {'phone': '07001', 'payroll_number': password})
        return client, response

    def test_trial_is_not_extended_by_concurrent_activation_reset_or_duplicate_registration(self):
        self.enrol()
        before = onboarding.status('alpha')
        def activate(_):
            with database.transaction() as connection:
                with connection.cursor() as cursor:
                    onboarding.activate(cursor, 'test-manager')
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(activate, range(2)))
        self.assertEqual(before, onboarding.status('alpha'))
        details = accounts.request_token('manager@example.test', 'reset')
        self.assertTrue(accounts.consume(details[1], 'reset', PASSWORD))
        self.assertEqual(before, onboarding.status('alpha'))
        self.assertIsNone(accounts.register('Same owner', 'Owner', ' MANAGER@example.test ', PASSWORD))
        self.assertEqual(database.fetch_one('SELECT COUNT(*) AS n FROM so_trial_claims')['n'], 1)
        self.assertEqual(database.fetch_one('SELECT COUNT(*) AS n FROM so_trials')['n'], 1)
        self.assertEqual(onboarding.status('beta')['state'], 'legacy')
        with patch.dict(os.environ, STAFF_REGISTRATION_ENABLED='0'):
            self.assertEqual(self.client().get('/staff/account/register').status_code, 503)

    def test_claim_ledger_prevents_second_business_trial_for_same_verified_identity(self):
        self.enrol()
        with database.transaction() as connection:
            with connection.cursor() as cursor:
                onboarding.begin(cursor, 'beta', 'test-manager')
                onboarding.activate(cursor, 'test-manager')
        self.assertEqual(onboarding.status('beta')['state'], 'pending')
        self.assertEqual(database.fetch_one('SELECT COUNT(*) AS n FROM so_trial_claims')['n'], 1)

    def test_trial_dates_are_server_owned_and_setup_resumes_without_tax_defaults(self):
        self.enrol()
        before = onboarding.status('alpha')
        response = self.post(self.manager, 'setup', dict(step='company', reviewed='on',
            business_name='A & B', business_type='Cleaning', company_address='1 Test Street',
            starts_at='2000-01-01', ends_at='2099-01-01', business_id='beta'))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(onboarding.status('alpha'), before)
        self.assertEqual(database.fetch_one("SELECT name FROM sm_businesses WHERE id='beta'")['name'], 'Beta')
        resumed = self.client(manager=True).get('/staff/alpha/setup')
        self.assertEqual(resumed.status_code, 200)
        self.assertIn(b'Work sites and GPS', resumed.data)
        self.assertIn(b'1 of 7 steps completed', resumed.data)
        self.assertEqual(onboarding.checklist('alpha')['current_step'], 'sites')
        dashboard = self.manager.get('/staff/alpha')
        self.assertIn(b'14 days remaining', dashboard.data)
        self.assertIn(b'Resume setup', dashboard.data)
        self.assertFalse(database.fetch_all('SELECT * FROM staff_payroll_profiles'))
        self.assertEqual(self.manager.get('/staff/beta/setup').status_code, 404)
        self.assertEqual(self.post(self.manager, 'setup', {'step':'bogus','reviewed':'on'}).status_code, 400)

    def test_setup_facts_revalidate_agency_assignments_and_active_employee_access(self):
        self.enrol()
        self.enable_agency()
        self.assertIn(b'Set up Staff Manager', self.manager.get('/staff/alpha/agency').data)
        with self.assertRaises(ValueError):
            onboarding.save('alpha', 'assignments', {'reviewed':'on'})
        self.assignment()
        onboarding.save('alpha', 'assignments', {'reviewed':'on'})
        self.assertTrue(onboarding.checklist('alpha')['done']['assignments'])
        database.execute("UPDATE staff_assignments SET status='cancelled' WHERE business_id='alpha'")
        self.assertFalse(onboarding.checklist('alpha')['done']['assignments'])
        with self.assertRaises(ValueError):
            onboarding.save('alpha', 'review', {'reviewed':'on'})
        self.assertEqual(self.post(self.manager, 'setup/invitations/'+str(self.foreign_employee)).status_code, 302)
        self.assertFalse(database.fetch_all('SELECT * FROM so_employee_invites'))

    def test_invite_password_login_tenant_isolation_and_session_revocation(self):
        self.enrol()
        raw = self.invite()
        self.assertEqual(employee_invitations.accept(raw, PASSWORD), 'alpha')
        _, wrong = self.worker_login(password='111')
        self.assertEqual(wrong.status_code, 401)
        worker, login = self.worker_login()
        self.assertEqual(login.status_code, 302)
        self.assertEqual(worker.get('/staff/alpha/employee/jobs').status_code, 200)
        self.assertEqual(worker.get('/staff/beta/employee/jobs').status_code, 302)
        self.assertEqual(worker.get('/staff/alpha/setup').status_code, 302)
        self.assertEqual(self.worker.get('/staff/alpha/employee/jobs').status_code, 302)
        # A replacement invitation only revokes the existing password/session when accepted.
        replacement = self.invite()
        self.assertEqual(worker.get('/staff/alpha/employee/pay').status_code, 200)
        employee_invitations.accept(replacement, 'replacement secure passphrase')
        self.assertEqual(worker.get('/staff/alpha/employee/pay').status_code, 302)
        worker, login = self.worker_login(password='replacement secure passphrase')
        self.assertEqual(login.status_code, 302)
        database.execute("UPDATE sm_businesses SET active=FALSE WHERE id='alpha'")
        self.assertEqual(worker.get('/staff/alpha/employee/pay').status_code, 302)

    def test_invitation_get_csrf_replay_changed_email_and_concurrent_acceptance(self):
        self.enrol()
        old = self.invite()
        raw = self.invite()
        with self.assertRaises(ValueError):
            employee_invitations.accept(old, PASSWORD)
        client = self.client()
        self.assertEqual(client.get('/staff/employee-invite#token='+raw).status_code, 200)
        self.assertIsNone(employee_invitations.credential('alpha',self.employee))
        self.assertEqual(client.post('/staff/employee-invite',data={'token':raw,'password':PASSWORD}).status_code,400)
        database.execute("UPDATE staff_employees SET email='changed@example.test' WHERE id=%s", (self.employee,))
        with self.assertRaises(ValueError):
            employee_invitations.accept(raw, PASSWORD)
        database.execute("UPDATE staff_employees SET email='worker@example.test' WHERE id=%s", (self.employee,))
        def consume(_):
            try:
                return employee_invitations.accept(raw, PASSWORD)
            except ValueError:
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(consume,range(2)))
        self.assertEqual(results.count('alpha'),1)
        self.assertEqual(database.fetch_one('SELECT count(*) AS n FROM so_employee_credentials')['n'],1)

    def test_notification_failure_is_nonblocking_sanitised_and_retryable(self):
        self.enrol()
        database.execute("UPDATE staff_employees SET email='private@example.test' WHERE id=%s",(self.employee,))
        with patch.object(employee_invitations,'send_staff_email',side_effect=RuntimeError('secret-api-key')):
            with self.assertLogs(employee_invitations.logger,level='INFO') as captured:
                self.assertFalse(employee_invitations.invite('alpha',self.employee,'https://staff.example.test'))
        self.assertIn('attempted',str(captured.output))
        self.assertIn('failed',str(captured.output))
        self.assertNotIn('private@example.test',str(captured.output))
        self.assertNotIn('secret-api-key',str(captured.output))
        self.assertEqual(database.fetch_one('SELECT status FROM so_employee_invites')['status'],'failed')
        self.assertEqual(self.row('staff_employees',self.employee)['full_name'],'Alex')
        raw=self.invite()
        response=self.client().post('/staff/employee-invite',data={'csrf_token':'test-csrf','token':raw,'password':PASSWORD})
        self.assertEqual(response.status_code,302)
        self.assertTrue(response.location.endswith('/staff/alpha/employee/login'))

    def test_employee_rate_limit_uses_verified_proxy_chain_and_shared_storage(self):
        self.enrol()
        employee_invitations.accept(self.invite(),PASSWORD)
        with patch.dict(os.environ,STAFF_TRUSTED_PROXY_CIDRS='10.2.3.4/32'):
            for index in range(6):
                response=self.client().post('/staff/alpha/employee/login',
                    data={'csrf_token':'test-csrf','phone':'07001','payroll_number':'incorrect'},
                    headers={'X-Forwarded-For':f'1.1.1.{index}, 203.0.113.20'},environ_overrides={'REMOTE_ADDR':'10.2.3.4'})
                self.assertEqual(response.status_code,401 if index<5 else 429)
        self.assertEqual(database.fetch_one('SELECT count(*) AS n FROM sm_rate_limits')['n'],2)

    def test_expiry_preserves_records_and_allows_safe_shift_finish_only(self):
        self.enrol()
        employee_invitations.accept(self.invite(),PASSWORD)
        worker, response=self.worker_login()
        self.assertEqual(response.status_code,302)
        self.assertEqual(self.post(worker,'employee/clock-in',{'site_id':self.site,**self.gps()}).status_code,302)
        shift=self.current()
        self.assertIsNotNone(shift)
        self.assertEqual(self.post(worker,'employee/break/start',{'shift_id':shift['id']}).status_code,302)
        pause=database.fetch_one('SELECT id FROM staff_breaks WHERE shift_id=%s',(shift['id'],))
        self.expire()
        for path in ('employee','employee/jobs','employee/hours','employee/pay'):
            self.assertEqual(worker.get('/staff/alpha/'+path).status_code,200)
        for path in ('employee/clock-in','employee/leave','employee/break/start'):
            self.assertEqual(self.post(worker,path).status_code,402)
        self.assertEqual(self.post(worker,'employee/break/end',{'shift_id':shift['id'],'break_id':pause['id']}).status_code,302)
        self.assertIsNotNone(self.row('staff_breaks',pause['id'])['ended_at'])
        # Bad GPS still cannot close an existing shift after expiry.
        self.post(worker,'employee/clock-out',{'shift_id':shift['id'],**self.gps(latitude='0')})
        self.assertIsNotNone(self.current())
        self.post(worker,'employee/clock-out',{'shift_id':shift['id'],**self.gps()})
        self.assertIsNone(self.current())
        self.assertEqual(self.row('staff_shifts',shift['id'])['approval_status'],'pending')
        self.assertEqual(self.post(self.manager,'shifts/'+str(shift['id'])+'/approve').status_code,402)
        self.assertEqual(self.manager.get('/staff/alpha/subscription').status_code,200)
        self.assertIsNotNone(self.row('staff_shifts',self.old_shift))
        with patch.object(agent,'_find_employee',side_effect=AssertionError('Phone-only access must not be used')):
            self.assertIn('secure Staff Manager employee portal',agent.handle_message('alpha','07001','start'))

    def test_onboarding_migration_is_repeatable_and_preserves_existing_fingerprints(self):
        with database.transaction() as connection:
            with connection.cursor() as cursor:
                core=migrations.schema_fingerprint(cursor)
                identity=accounts_migration.fingerprint(cursor)
                onboarding_migration.migrate(cursor)
                onboarding_migration.verify(cursor)
                self.assertEqual(core,migrations.schema_fingerprint(cursor))
                self.assertEqual(identity,accounts_migration.fingerprint(cursor))
        with self.assertRaises(CheckViolation):
            database.execute("INSERT INTO so_trials(business_id,administrator_id,starts_at) VALUES ('alpha','test-manager',NOW())")
        with self.assertRaises(CheckViolation):
            database.execute("INSERT INTO so_trials(business_id,administrator_id,starts_at,ends_at) VALUES ('alpha','test-manager',NOW(),NOW()+INTERVAL '30 days')")

    def test_failed_onboarding_migration_rolls_back_all_ddl_and_registry(self):
        with self.assertRaises(UndefinedTable):
            with database.transaction() as connection:
                with connection.cursor() as cursor:
                    cursor.execute('DROP TABLE so_employee_invites,so_employee_credentials,so_setup,so_trial_claims,so_trials,so_schema_migrations')
                    with patch.object(onboarding_migration,'SQL',onboarding_migration.SQL+'; SELECT * FROM deliberately_missing_onboarding_table'):
                        onboarding_migration.migrate(cursor)
        with database.transaction() as connection:
            with connection.cursor() as cursor:
                onboarding_migration.verify(cursor)
                accounts_migration.verify(cursor)
                migrations.verify(cursor)
        self.assertEqual(database.fetch_one('SELECT count(*) AS n FROM so_schema_migrations')['n'],1)
        self.assertEqual(database.fetch_one('SELECT count(*) AS n FROM staff_employees')['n'],3)
