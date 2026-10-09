"""Official HMRC fixtures plus statutory payroll isolation and lifecycle checks."""
import json
import os
import unittest
from pathlib import Path
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D
from unittest.mock import patch
import test_staff_agency as fixtures
from concurrent.futures import ThreadPoolExecutor
from trimtech.modules.staff import statutory, database, payslips, attendance_exceptions
from trimtech.modules.staff.payroll import PayrollError, UK_TIMEZONE


class StatutoryCalculationTests(unittest.TestCase):
    def test_hmrc_paye_fixtures(self):
        rows=json.loads((Path(__file__).parent/'testdata/payroll_2026_tax.json').read_text())
        self.assertEqual(len(rows),168)
        for r in rows:
            with self.subTest(case=r):
                actual=statutory.paye(r['gross'],r['code'],r['frequency'],r['period'],r['basis'],r['previous_pay'],r['previous_tax'])
                self.assertLessEqual(abs(actual-D(r['expected'])),D('.01'))

    def test_hmrc_ni_fixtures(self):
        rows=json.loads((Path(__file__).parent/'testdata/payroll_2026_ni.json').read_text())
        self.assertEqual(len(rows),448)
        for r in rows:
            with self.subTest(case=r):
                self.assertEqual(statutory.national_insurance(r['gross'],r['category'],r['frequency']), (D(r['employee']),D(r['employer'])))

    def test_pensions_refunds_caps_year_and_period_boundaries(self):
        p=dict(tax_year='2026/27',tax_code='1257L',tax_basis='noncumulative',frequency='monthly',ni_category='A',
               pension_method='net_pay',pension_basis='qualifying',employee_pension_rate='5',employer_pension_rate='3')
        net=statutory.calculate('3000',p,date(2026,4,30))
        self.assertEqual(net['employee_pension'],D('124'))
        self.assertEqual(net['employer_pension'],D('74.40'))
        self.assertEqual(net['taxable_pay'],D('2876'))
        relief=statutory.calculate('3000',{**p,'pension_method':'relief_at_source'},date(2026,4,30))
        self.assertEqual(relief['employee_pension'],D('99.20'))
        self.assertEqual(relief['taxable_pay'],D('3000'))
        self.assertEqual(net['employee_ni'],relief['employee_ni'])
        self.assertEqual(statutory.paye(100,'K9999','weekly',1),D('50'))
        self.assertEqual(statutory.paye(100,'NT','monthly',3,previous_tax=100),D('-100'))
        self.assertEqual(statutory.tax_period(date(2026,5,5),'monthly'),1)
        self.assertEqual(statutory.tax_period(date(2026,5,6),'monthly'),2)
        self.assertEqual(statutory.tax_period(date(2027,4,5),'weekly'),53)
        self.assertEqual(statutory.paye(500,'1257L','weekly',53,previous_pay=50000,previous_tax=10000),statutory.paye(500,'1257L','weekly',1))
        for value in ('NaN','Infinity','-1'):
            with self.assertRaises(PayrollError): statutory.money(value)
        for code in ('SNT','CNT','D2','K0','1257L W1','INVALID'):
            with self.assertRaises(PayrollError): statutory.parse_code(code)
        with self.assertRaises(PayrollError): statutory.calculate(100,p,date(2027,4,6))


@unittest.skipUnless(os.getenv('STAFF_TEST_DATABASE_URL'),'Requires disposable local PostgreSQL')
class StatutoryDatabaseTests(unittest.TestCase):
    setUp=fixtures.AgencyDatabaseTests.setUp
    cleanup_schema=fixtures.AgencyDatabaseTests.cleanup_schema
    connect=fixtures.AgencyDatabaseTests.connect
    insert=fixtures.AgencyDatabaseTests.insert
    client=fixtures.AgencyDatabaseTests.client
    post=fixtures.AgencyDatabaseTests.post
    row=fixtures.AgencyDatabaseTests.row
    assignment=fixtures.AgencyDatabaseTests.assignment
    assignment_values=fixtures.AgencyDatabaseTests.assignment_values

    def profile(self, **changes):
        values=dict(tax_code='1257L',tax_basis='noncumulative',frequency='monthly',ni_category='A',pension_method='net_pay',
                    pension_basis='qualifying',employee_pension_rate='5',employer_pension_rate='3',opening_taxable_pay='0',
                    opening_paye='0',opening_through='2026-04-05',scope_confirmed='yes')
        values.update(changes)
        self.post(self.manager,f'payroll/profiles/{self.employee}',values)
        return values

    def shift(self, when='2026-04-20', employee=None):
        return self.insert("""INSERT INTO staff_shifts(business_id,employee_id,site_id,site_name,clock_in_at,clock_out_at,approval_status)
            VALUES('alpha',%s,%s,'First site',%s::date+interval '8 hours',%s::date+interval '18 hours','approved') RETURNING id""",
            (employee or self.employee,self.site,when,when))

    def generate(self, start='2026-04-01',end='2026-04-30',payment='2026-04-30'):
        return self.post(self.manager,'payroll/generate',dict(period_start=start,period_end=end,payment_date=payment,frequency='monthly',employer_name='Alpha Limited'))

    def test_settings_required_atomic_generation_and_secure_downloads(self):
        self.shift()
        self.generate()
        self.assertFalse(database.fetch_all('SELECT * FROM staff_payroll_runs'))
        self.assertFalse(database.fetch_all('SELECT * FROM staff_payslip_shifts'))
        self.profile()
        self.generate()
        run=database.fetch_one('SELECT * FROM staff_payroll_runs')
        self.assertEqual(run['calculation_version'],statutory.VERSION)
        slip=database.fetch_one('SELECT * FROM staff_payslips')
        route=f"/staff/alpha/employee/payslips/{slip['id']}/download"
        self.assertEqual(self.worker.get(route).status_code,404)
        self.assertEqual(self.manager.get(f"/staff/alpha/payroll/{run['id']}").status_code,200)
        self.post(self.manager,f"payroll/{run['id']}/approve")
        response=self.worker.get(route)
        self.assertEqual(response.status_code,200)
        self.assertIn('attachment',response.headers['Content-Disposition'])
        self.assertTrue(response.data.startswith(b'%PDF-'))
        self.assertEqual(response.mimetype,'application/pdf')
        self.assertEqual(self.worker2.get(route).status_code,404)
        self.assertEqual(self.client().get(route).status_code,302)
        self.assertEqual(self.manager.get(f"/staff/beta/payroll/payslips/{slip['id']}/download").status_code,404)
        self.assertIn(b'Download PDF',self.worker.get('/staff/alpha/employee/pay').data)
        self.assertEqual(database.fetch_one('SELECT status FROM staff_payslip_notifications')['status'], 'failed')

    def test_profile_change_recalculates_and_finalized_snapshots_are_immutable(self):
        self.profile(); self.shift(); self.generate()
        run=database.fetch_one('SELECT * FROM staff_payroll_runs')
        self.profile(tax_code='BR')
        self.post(self.manager,f"payroll/{run['id']}/approve")
        self.assertEqual(self.row('staff_payroll_runs',run['id'])['status'],'draft')
        self.post(self.manager,f"payroll/{run['id']}/recalculate")
        self.assertEqual(database.fetch_one('SELECT result FROM staff_payroll_calculations')['result']['paye'],'30.00')
        self.post(self.manager,f"payroll/{run['id']}/approve")
        snapshot=database.fetch_one('SELECT * FROM staff_payroll_calculations')
        self.profile(tax_code='NT')
        self.assertEqual(snapshot,database.fetch_one('SELECT * FROM staff_payroll_calculations'))
        self.profile(opening_paye='100')
        self.assertEqual(database.fetch_one('SELECT opening_paye FROM staff_payroll_profiles')['opening_paye'],D(0))

    def test_cumulative_ytd_refund_duplicate_period_and_chronology(self):
        self.profile(tax_code='BR',tax_basis='cumulative'); self.shift(); self.generate()
        run=database.fetch_one('SELECT * FROM staff_payroll_runs')
        self.post(self.manager,f"payroll/{run['id']}/approve")
        self.profile(tax_code='NT',tax_basis='cumulative'); self.shift('2026-05-20')
        self.generate('2026-05-01','2026-05-31','2026-05-31')
        result=database.fetch_one('SELECT result FROM staff_payroll_calculations ORDER BY payment_date DESC LIMIT 1')['result']
        self.assertEqual(result['paye'],'-30.00')
        self.assertEqual(result['net_pay'],'180.00')
        self.assertEqual(result['taxable_pay_ytd'],'300.00')
        self.shift('2026-06-01'); self.generate('2026-06-01','2026-06-01','2026-06-02')
        self.assertEqual(len(database.fetch_all('SELECT id FROM staff_payroll_runs')),2)

    def test_email_explicit_once_and_failures_do_not_change_payroll(self):
        self.profile(); self.shift(); self.generate()
        run=database.fetch_one('SELECT * FROM staff_payroll_runs')
        slip=database.fetch_one('SELECT * FROM staff_payslips')
        database.execute("UPDATE staff_employees SET email='worker@example.test' WHERE id=%s",(self.employee,))
        with patch.dict(os.environ,{'STAFF_PAYSLIP_EMAIL_ENABLED':'1','STAFF_PUBLIC_BASE_URL':'https://staff.example.test'}),patch.object(payslips,'send_staff_email',return_value=(True,None,'synthetic')) as send:
            self.post(self.manager,f"payroll/payslips/{slip['id']}/send")
            send.assert_not_called()
            self.post(self.manager,f"payroll/{run['id']}/approve")
            self.post(self.manager,f"payroll/payslips/{slip['id']}/send")
            self.post(self.manager,f"payroll/payslips/{slip['id']}/send")
            send.assert_called_once()
            self.assertNotIn('150.00',send.call_args.args[2])
        self.assertEqual(database.fetch_one('SELECT status FROM staff_payslip_notifications')['status'],'sent')
        self.assertEqual(self.row('staff_payroll_runs',run['id'])['status'],'approved')

    def test_profile_tenant_scope_csrf_and_invalid_values(self):
        self.profile()
        values=self.profile(tax_code='bad')
        self.assertEqual(database.fetch_one('SELECT tax_code FROM staff_payroll_profiles')['tax_code'],'1257L')
        values['tax_code']='BR'
        self.post(self.manager,f'payroll/profiles/{self.foreign_employee}',values)
        self.assertEqual(len(database.fetch_all('SELECT * FROM staff_payroll_profiles')),1)
        self.assertEqual(self.manager.post(f'/staff/alpha/payroll/profiles/{self.employee}',data=values).status_code,400)
        self.post(self.worker,f'payroll/profiles/{self.employee}',values)
        self.assertEqual(database.fetch_one('SELECT tax_code FROM staff_payroll_profiles')['tax_code'],'1257L')

    def test_attendance_missed_late_site_alerts_review_and_cancel(self):
        now=datetime.now(timezone.utc)
        assignment=self.assignment(start=now-timedelta(minutes=30),end=now+timedelta(hours=2))
        events=attendance_exceptions.collect('alpha',now=now)
        missed=next(e for e in events if e['kind']=='Missed clock-in')
        self.assertFalse(attendance_exceptions.collect('beta',now=now))
        self.post(self.manager,'attendance/review',{'event_key':missed['event_key'],'note':'Contacted employee'})
        self.assertIsNotNone(database.fetch_one('SELECT * FROM staff_attendance_reviews'))
        self.post(self.worker,'attendance/review',{'event_key':missed['event_key'],'note':'Unauthorized'})
        self.assertEqual(database.fetch_one('SELECT note FROM staff_attendance_reviews')['note'],'Contacted employee')
        shift=self.insert("""INSERT INTO staff_shifts(business_id,employee_id,site_id,site_name,clock_in_at,assignment_id,planned_start_at,planned_end_at)
            VALUES('alpha',%s,%s,'First site',%s,%s,%s,%s) RETURNING id""",
            (self.employee,self.site,now,assignment,now-timedelta(minutes=30),now+timedelta(hours=2)))
        events=attendance_exceptions.collect('alpha',{shift:{'status':'left_site'}},now)
        self.assertNotIn('Missed clock-in',[e['kind'] for e in events])
        self.assertIn('Late clock-in',[e['kind'] for e in events])
        self.assertIn('Left site',[e['kind'] for e in events])
        self.assertEqual(self.manager.get('/staff/alpha/attendance').status_code,200)

    def test_discard_releases_shifts_and_retains_audit_only_for_drafts(self):
        self.profile(); self.shift(); self.generate()
        run=database.fetch_one('SELECT * FROM staff_payroll_runs')
        self.post(self.manager,f"payroll/{run['id']}/discard",{'reason':''})
        self.assertIsNotNone(self.row('staff_payroll_runs',run['id']))
        self.post(self.manager,f"payroll/{run['id']}/discard",{'reason':'Wrong payment date'})
        self.assertFalse(database.fetch_all('SELECT * FROM staff_payroll_runs'))
        self.assertFalse(database.fetch_all('SELECT * FROM staff_payslip_shifts'))
        self.assertIsNotNone(database.fetch_one("SELECT * FROM staff_audit WHERE action='payroll_draft_discarded'"))
        self.generate()
        run=database.fetch_one('SELECT * FROM staff_payroll_runs')
        self.post(self.manager,f"payroll/{run['id']}/approve")
        self.post(self.manager,f"payroll/{run['id']}/discard",{'reason':'Cannot discard finalized payroll'})
        self.assertEqual(self.row('staff_payroll_runs',run['id'])['status'],'approved')

    def test_concurrent_generation_claims_shifts_once(self):
        self.profile(); self.shift()
        def generate(_):
            return self.post(self.client(manager=True),'payroll/generate',dict(period_start='2026-04-01',period_end='2026-04-30',
                payment_date='2026-04-30',frequency='monthly',employer_name='Alpha Ltd')).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(list(pool.map(generate,range(2))),[302,302])
        self.assertEqual(len(database.fetch_all('SELECT * FROM staff_payroll_runs')),1)
        self.assertEqual(len(database.fetch_all('SELECT * FROM staff_payslip_shifts')),1)

    def test_duplicate_tax_period_and_backdated_payments_roll_back(self):
        self.profile(); self.shift(); self.generate()
        run=database.fetch_one('SELECT * FROM staff_payroll_runs')
        self.post(self.manager,f"payroll/{run['id']}/approve")
        self.shift('2026-05-01')
        self.generate('2026-05-01','2026-05-01','2026-05-02')
        self.assertEqual(len(database.fetch_all('SELECT * FROM staff_payroll_runs')),1)
        self.assertEqual(len(database.fetch_all('SELECT * FROM staff_payslip_shifts')),1)
        self.generate('2026-05-01','2026-05-01','2026-04-25')
        self.assertEqual(len(database.fetch_all('SELECT * FROM staff_payroll_runs')),1)

    def test_failed_or_disabled_notice_keeps_payroll_approved(self):
        self.profile(); self.shift(); self.generate()
        run=database.fetch_one('SELECT * FROM staff_payroll_runs')
        slip=database.fetch_one('SELECT * FROM staff_payslips')
        self.post(self.manager,f"payroll/{run['id']}/approve")
        database.execute("UPDATE staff_employees SET email='worker@example.test' WHERE id=%s",(self.employee,))
        with patch.dict(os.environ,{'STAFF_PAYSLIP_EMAIL_ENABLED':'1','STAFF_PUBLIC_BASE_URL':'https://staff.example.test'}),patch.object(payslips,'send_staff_email',return_value=(False,'provider_http_429',None)):
            self.post(self.manager,f"payroll/payslips/{slip['id']}/send")
        self.assertEqual(database.fetch_one('SELECT status FROM staff_payslip_notifications')['status'],'failed')
        self.assertEqual(self.row('staff_payroll_runs',run['id'])['status'],'approved')
        with patch.dict(os.environ,{'STAFF_PAYSLIP_EMAIL_ENABLED':'0'}),patch.object(payslips,'send_staff_email') as send:
            self.post(self.manager,f"payroll/payslips/{slip['id']}/send")
            send.assert_not_called()
        self.assertEqual(database.fetch_one('SELECT status FROM staff_payslip_notifications')['status'],'disabled')

    def test_attendance_cancel_leave_fixed_clocking_and_grace_boundaries(self):
        # Keep assignment start and approved leave on the same UK date,
        # including when this test runs just after midnight.
        now=datetime.now(UK_TIMEZONE).replace(hour=12,minute=0,second=0,microsecond=0).astimezone(timezone.utc)
        assignment=self.assignment(start=now-timedelta(minutes=15),end=now+timedelta(hours=2))
        self.assertNotIn('Missed clock-in',[e['kind'] for e in attendance_exceptions.collect('alpha',now=now-timedelta(seconds=1))])
        self.assertIn('Missed clock-in',[e['kind'] for e in attendance_exceptions.collect('alpha',now=now)])
        database.execute("UPDATE staff_assignments SET status='cancelled' WHERE id=%s",(assignment,))
        self.assertFalse(attendance_exceptions.collect('alpha',now=now))
        database.execute("UPDATE staff_assignments SET status='scheduled' WHERE id=%s",(assignment,))
        self.insert("""INSERT INTO staff_shifts(business_id,employee_id,site_id,site_name,clock_in_at,clock_out_at)
            VALUES('alpha',%s,%s,'First site',%s,%s) RETURNING id""",(self.employee,self.site,now-timedelta(minutes=14),now))
        self.assertNotIn('Missed clock-in',[e['kind'] for e in attendance_exceptions.collect('alpha',now=now)])
        today=now.astimezone(UK_TIMEZONE).date()
        self.insert("""INSERT INTO staff_leave_requests(business_id,employee_id,start_date,end_date,total_days,approval_status)
            VALUES('alpha',%s,%s,%s,1,'approved') RETURNING id""",(self.employee,today,today))
        self.assertIn('Assignment / approved leave conflict',[e['kind'] for e in attendance_exceptions.collect('alpha',now=now)])
