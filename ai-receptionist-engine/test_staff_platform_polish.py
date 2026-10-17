"""Existing-schema platform authorization, location, break and estimate regressions."""
import os
import unittest
from datetime import datetime,timedelta,timezone
from decimal import Decimal
from unittest.mock import patch
import test_staff_agency as fixture
from trimtech.modules.staff import database,presence,platform_control,wages_estimate

class LocationClassificationTests(unittest.TestCase):
    def test_fresh_inside_outside_uncertain_and_stale_are_distinct(self):
        now=datetime.now(timezone.utc)
        state={'radius_metres':100}
        self.assertEqual(presence.classify_sample(state,now,20,10,now,120),'on_site')
        self.assertEqual(presence.classify_sample(state,now,200,10,now,120),'outside_site')
        for captured,distance,accuracy in [(now,105,10),(now,10,150),(now-timedelta(seconds=121),200,10),(None,200,10),(now,float('nan'),10),(now,20,0)]:
            self.assertEqual(presence.classify_sample(state,captured,distance,accuracy,now,120),'location_unverified')

@unittest.skipUnless(os.getenv('STAFF_TEST_DATABASE_URL'),'Requires disposable PostgreSQL')
class PlatformPolishTests(unittest.TestCase):
    for name in ('cleanup_schema','connect','insert','client','post','row','gps','current'):
        locals()[name]=getattr(fixture.AgencyDatabaseTests,name)

    def setUp(self):
        fixture.AgencyDatabaseTests.setUp(self)
        from trimtech.modules.auth.routes import auth_blueprint
        self.app.register_blueprint(auth_blueprint)
        env=patch.dict(os.environ,PLATFORM_ADMIN_USERNAME='local-platform-reviewer',PLATFORM_ADMIN_PASSWORD='test-only')
        env.start();self.addCleanup(env.stop)
        self.platform=self.client()
        with self.platform.session_transaction() as session:
            session['platform_admin_authenticated']=True
            session['auth_role']='platform_admin'
            session['platform_admin_username']='local-platform-reviewer'

    def test_platform_directory_includes_unrelated_self_service_business(self):
        database.execute("INSERT INTO sm_businesses(id,name) VALUES ('oakfield','Oakfield Property Maintenance Ltd')")
        page=self.platform.get('/staff/platform/businesses')
        self.assertEqual(page.status_code,200)
        self.assertIn(b'Oakfield Property Maintenance Ltd',page.data)
        self.assertNotIn(b'payroll_number',page.data)
        self.assertNotIn(b'/staff/oakfield/payroll',page.data)
        self.assertIn(b'Oakfield',self.platform.get('/staff/platform/businesses?q=Oakfield').data)
        self.assertNotIn(b'Oakfield Property',self.platform.get('/staff/platform/businesses?status=paid').data)
        self.assertEqual(self.platform.get('/staff/platform/businesses?status=invalid').status_code,400)
        self.assertEqual(self.platform.get('/staff/oakfield').status_code,302)
        self.assertNotIn(b'Oakfield',self.manager.get('/staff/account').data)

    def test_only_platform_identity_authorizes_directory(self):
        for client in (self.manager,self.worker,self.client()):
            self.assertEqual(client.get('/staff/platform/businesses').status_code,302)
        shared=self.client()
        with shared.session_transaction() as session:session['dashboard_authenticated']=True
        self.assertEqual(shared.get('/staff/platform/businesses').status_code,302)
        self.assertEqual(self.platform.post('/staff/platform/businesses',data={'csrf_token':'test-csrf'}).status_code,405)

    def test_live_break_status_changes_without_changing_shift_approval(self):
        self.post(self.worker,'employee/clock-in',{'site_id':self.site,**self.gps()})
        shift=self.current()
        self.post(self.worker,'employee/break/start',{'shift_id':shift['id']})
        overview=presence.overview('alpha')
        self.assertIsNotNone(overview[shift['id']]['break_started_at'])
        self.assertIn(b'On break',self.manager.get('/staff/alpha/attendance').data)
        br=database.fetch_one('SELECT id FROM staff_breaks WHERE shift_id=%s AND ended_at IS NULL',(shift['id'],))
        self.post(self.worker,'employee/break/end',{'shift_id':shift['id'],'break_id':br['id']})
        self.assertIsNone(presence.overview('alpha')[shift['id']]['break_started_at'])
        self.assertEqual(self.row('staff_shifts',shift['id'])['approval_status'],'pending')

    def test_approved_estimate_deducts_unpaid_breaks_only(self):
        self.insert("INSERT INTO staff_shifts(business_id,employee_id,site_name,clock_in_at,clock_out_at,approval_status) VALUES ('alpha',%s,'Local',NOW()-INTERVAL '1 hour',NOW(),'approved') RETURNING id",(self.employee,))
        shift=database.fetch_one("SELECT * FROM staff_shifts WHERE business_id='alpha' AND approval_status='approved'")
        self.insert("INSERT INTO staff_breaks(business_id,employee_id,shift_id,started_at,ended_at,paid) VALUES ('alpha',%s,%s,%s,%s,FALSE) RETURNING id",(self.employee,shift['id'],shift['clock_in_at'],shift['clock_in_at']+timedelta(minutes=19)))
        database.execute('UPDATE staff_employees SET hourly_rate=12 WHERE id=%s',(self.employee,))
        estimate=wages_estimate.weekly('alpha',approved_only=True)
        self.assertEqual(estimate['estimated_gross'],Decimal('8.20'))
        self.assertEqual(database.fetch_one('SELECT count(*) AS n FROM staff_payroll_runs')['n'],0)

    def test_dashboard_names_settings_and_mobile_evidence(self):
        page=self.manager.get('/staff/alpha')
        self.assertEqual(page.status_code,200)
        self.assertIn(b'<h1>Alpha</h1>',page.data)
        self.assertIn(b'Approved gross estimate',page.data)
        self.assertNotIn(b'?0.00',page.data)
        self.assertEqual(self.manager.get('/staff/alpha/settings').status_code,200)
        review=self.manager.get('/staff/alpha/approvals?edit_shift='+str(self.old_shift))
        self.assertIn(b'gps-evidence-table mobile-cards',review.data)
        self.assertIn(b'Technical GPS details',review.data)

if __name__=='__main__':unittest.main()
