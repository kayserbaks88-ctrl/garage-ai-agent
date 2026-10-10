"""Optional setup never creates tax profiles, payroll runs or final wages."""
import os
import unittest
from decimal import Decimal
from trimtech.modules.staff import database, onboarding, wages_estimate
import test_staff_agency as fixtures

@unittest.skipUnless(os.getenv('STAFF_TEST_DATABASE_URL'),'Requires isolated PostgreSQL')
class PayrollOnboardingTests(unittest.TestCase):
    for name in ('setUp','cleanup_schema','connect','insert','client','post','row','gps','enable_agency','assignment_values','assignment','current'):
        locals()[name]=getattr(fixtures.AgencyDatabaseTests,name)

    def enrol(self):
        with database.transaction() as connection:
            with connection.cursor() as cursor:
                onboarding.begin(cursor,'alpha','test-manager');onboarding.activate(cursor,'test-manager')

    def other_steps(self):
        onboarding.save('alpha','company',dict(reviewed='on',business_name='Alpha',business_type='Cleaning',company_address='1 Test Street'))
        onboarding.save('alpha','sites',dict(reviewed='on'))
        onboarding.save('alpha','employees',dict(skip_employees='1'))
        onboarding.save('alpha','assignments',dict(reviewed='on'))

    def test_skip_and_final_review_accept_set_up_later_without_tax_configuration(self):
        self.enrol();self.other_steps();before=onboarding.status('alpha')
        response=self.post(self.manager,'setup',dict(step='payroll',skip_payroll='1',business_id='beta'))
        self.assertEqual(response.location,'/staff/alpha/setup?step=review')
        progress=onboarding.checklist('alpha')
        self.assertFalse(progress['done']['payroll']);self.assertTrue(progress['ready']['payroll'])
        self.assertTrue(progress['payroll_deferred'])
        review=self.manager.get(response.location)
        self.assertIn(b'Payroll (optional): Set up later',review.data)
        response=self.post(self.manager,'setup',dict(step='review',reviewed='on'))
        self.assertEqual(response.status_code,302)
        self.assertTrue(onboarding.checklist('alpha')['done']['review'])
        self.assertEqual(onboarding.checklist('alpha')['display_count'],6)
        self.assertEqual(onboarding.status('alpha'),before)
        for table in ('staff_payroll_profiles','staff_payroll_runs','staff_payslips'):
            self.assertEqual(database.fetch_one('SELECT COUNT(*) AS n FROM '+table)['n'],0)
        dashboard=self.manager.get('/staff/alpha')
        self.assertIn(b'Activate Payroll Later',dashboard.data)
        self.assertIn(b'not final net pay or completed payroll',dashboard.data)
        self.assertIsNone(onboarding.checklist('beta'))

    def test_basic_frequency_and_break_policy_preserve_historical_breaks(self):
        self.enrol()
        break_id=self.insert("INSERT INTO staff_breaks(business_id,employee_id,shift_id,started_at,ended_at,paid) VALUES ('alpha',%s,%s,NOW()-INTERVAL '5 days',NOW()-INTERVAL '5 days'+INTERVAL '10 minutes',FALSE) RETURNING id",(self.employee,self.old_shift))
        response=self.post(self.manager,'setup',dict(step='payroll',payroll_basics='1',pay_frequency='monthly',break_policy='paid',reviewed='on'))
        self.assertEqual(response.status_code,302)
        self.assertEqual(onboarding.checklist('alpha')['payroll_preferences'],{'frequency':'monthly'})
        self.assertEqual(database.fetch_one("SELECT break_policy FROM staff_business_settings WHERE business_id='alpha'")['break_policy'],'paid')
        self.assertFalse(self.row('staff_breaks',break_id)['paid'])
        self.assertEqual(database.fetch_one('SELECT COUNT(*) AS n FROM staff_payroll_profiles')['n'],0)
        self.assertIn(b'Detailed payroll: Set up later',self.manager.get('/staff/alpha/payroll').data)
        self.assertIsNone(database.fetch_one("SELECT break_policy FROM staff_business_settings WHERE business_id='beta'"))

    def test_invalid_basics_are_atomic_and_cannot_be_saved_by_an_employee_or_other_tenant(self):
        self.enrol()
        for frequency,policy in [('daily','paid'),('weekly','optional')]:
            with self.assertRaises(ValueError): onboarding.save('alpha','payroll',dict(payroll_basics='1',reviewed='on',pay_frequency=frequency,break_policy=policy))
        self.assertFalse(onboarding.checklist('alpha')['payroll_deferred'])
        values=dict(step='payroll',payroll_basics='1',reviewed='on',pay_frequency='weekly',break_policy='paid',csrf_token='test-csrf')
        self.assertEqual(self.post(self.worker,'setup',values).status_code,302)
        self.assertEqual(self.manager.post('/staff/beta/setup',data=values).status_code,404)
        self.assertEqual(self.manager.post('/staff/alpha/setup',data={'step':'payroll','skip_payroll':'1'}).status_code,400)
        self.assertIsNone(database.fetch_one("SELECT break_policy FROM staff_business_settings WHERE business_id='alpha'"))

    def test_defer_does_not_bypass_detailed_activation_or_required_company_and_site_steps(self):
        self.enrol()
        onboarding.save('alpha','payroll',dict(skip_payroll='1'))
        with self.assertRaises(ValueError): onboarding.save('alpha','review',dict(reviewed='on'))
        with self.assertRaises(ValueError): onboarding.save('alpha','payroll',dict(reviewed='on'))
        self.assertTrue(onboarding.checklist('alpha')['payroll_deferred'])
        self.assertEqual(database.fetch_one('SELECT COUNT(*) AS n FROM staff_payroll_runs')['n'],0)

    def test_estimates_deduct_recorded_unpaid_breaks_exclude_rejected_and_other_business(self):
        self.enrol();onboarding.save('alpha','payroll',dict(skip_payroll='1'))
        database.execute("DELETE FROM staff_shifts WHERE business_id='alpha'")
        # A fixed Saturday keeps this regression independent of the current week boundary.
        def record(query,params):
            return self.insert(query.replace('NOW()',"TIMESTAMPTZ '2026-10-10 12:00:00+00'"),params)
        shift=record("INSERT INTO staff_shifts(business_id,employee_id,site_name,clock_in_at,clock_out_at,approval_status) VALUES ('alpha',%s,'Test site',NOW()-INTERVAL '3 hours',NOW()-INTERVAL '1 hour','pending') RETURNING id",(self.employee,))
        record("INSERT INTO staff_shifts(business_id,employee_id,site_name,clock_in_at,clock_out_at,approval_status) VALUES ('alpha',%s,'Test site',NOW()-INTERVAL '3 hours',NOW()-INTERVAL '1 hour','approved') RETURNING id",(self.second,))
        record("INSERT INTO staff_shifts(business_id,employee_id,site_name,clock_in_at,clock_out_at,approval_status) VALUES ('beta',%s,'Other site',NOW()-INTERVAL '3 hours',NOW()-INTERVAL '1 hour','approved') RETURNING id",(self.foreign_employee,))
        record("INSERT INTO staff_shifts(business_id,employee_id,site_name,clock_in_at,clock_out_at,approval_status) VALUES ('alpha',%s,'Test site',NOW()-INTERVAL '3 hours',NOW()-INTERVAL '1 hour','rejected') RETURNING id",(self.employee,))
        record("INSERT INTO staff_breaks(business_id,employee_id,shift_id,started_at,ended_at,paid) VALUES ('alpha',%s,%s,NOW()-INTERVAL '2 hours',NOW()-INTERVAL '90 minutes',FALSE) RETURNING id",(self.employee,shift))
        record("INSERT INTO staff_breaks(business_id,employee_id,shift_id,started_at,ended_at,paid) VALUES ('alpha',%s,%s,NOW()-INTERVAL '150 minutes',NOW()-INTERVAL '130 minutes',TRUE) RETURNING id",(self.employee,shift))
        estimate=wages_estimate.weekly('alpha',as_of='2026-10-10 12:00:00+00')
        self.assertEqual(estimate['hours'],Decimal('4.00'))
        self.assertEqual(estimate['unpaid_break_hours'],Decimal('0.50'))
        self.assertEqual(estimate['estimated_gross'],Decimal('62.50'))
        self.assertEqual(database.fetch_one('SELECT COUNT(*) AS n FROM staff_payroll_runs')['n'],0)
        # UK Monday midnight is 23:00 UTC on this October date: only three hours count.
        record("INSERT INTO staff_shifts(business_id,employee_id,site_name,clock_in_at,clock_out_at) VALUES ('alpha',%s,'Overnight site','2026-10-04 22:00:00+00','2026-10-05 02:00:00+00') RETURNING id",(self.employee,))
        opened=record("INSERT INTO staff_shifts(business_id,employee_id,site_name,clock_in_at) VALUES ('alpha',%s,'Open site',NOW()-INTERVAL '2 hours') RETURNING id",(self.second,))
        record("INSERT INTO staff_breaks(business_id,employee_id,shift_id,started_at,paid) VALUES ('alpha',%s,%s,NOW()-INTERVAL '1 hour',FALSE) RETURNING id",(self.second,opened))
        estimate=wages_estimate.weekly('alpha',as_of='2026-10-10 12:00:00+00')
        self.assertEqual(estimate['hours'],Decimal('9.00'))
        self.assertEqual(estimate['unpaid_break_hours'],Decimal('1.50'))
        self.assertEqual(estimate['estimated_gross'],Decimal('127.50'))

    def test_old_reviewed_payroll_remains_completed_without_a_defer_flag(self):
        self.enrol()
        database.execute("INSERT INTO staff_payroll_profiles(business_id,employee_id,frequency,tax_code,tax_basis,ni_category,pension_method,reviewed_by,tax_year,pension_basis,employee_pension_rate,employer_pension_rate,opening_through) VALUES ('alpha',%s,'weekly','1257L','cumulative','A','none','manager:test','2026/27','all',0,0,'2026-04-05')",(self.employee,))
        database.execute("INSERT INTO staff_payroll_profiles(business_id,employee_id,frequency,tax_code,tax_basis,ni_category,pension_method,reviewed_by,tax_year,pension_basis,employee_pension_rate,employer_pension_rate,opening_through) VALUES ('alpha',%s,'weekly','1257L','cumulative','A','none','manager:test','2026/27','all',0,0,'2026-04-05')",(self.second,))
        onboarding.save('alpha','payroll',dict(reviewed='on'))
        self.assertTrue(onboarding.checklist('alpha')['done']['payroll'])
        self.assertFalse(onboarding.checklist('alpha')['payroll_deferred'])
        profiles=database.fetch_all('SELECT * FROM staff_payroll_profiles ORDER BY employee_id')
        onboarding.save('alpha','payroll',dict(skip_payroll='1'))
        self.assertFalse(onboarding.checklist('alpha')['done']['payroll'])
        onboarding.save('alpha','payroll',dict(reviewed='on'))
        self.assertFalse(onboarding.checklist('alpha')['payroll_deferred'])
        self.assertTrue(onboarding.checklist('alpha')['done']['payroll'])
        self.assertEqual(database.fetch_all('SELECT * FROM staff_payroll_profiles ORDER BY employee_id'),profiles)
