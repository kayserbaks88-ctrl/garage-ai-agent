"""Owner-only acquisition reporting and existing-baseline business lifecycle regressions."""
from datetime import date
import json
import os
import unittest
from unittest.mock import patch

from trimtech.modules.staff import acquisition, acquisition_classification, database, platform_control
from trimtech.modules.staff import registration_review, subscription_management as management
import test_staff_control_centre_db as fixture


class AcquisitionUnitTests(unittest.TestCase):
    def test_report_reads_authenticated_marketing_aggregates(self):
        payload=dict(available=True,started_at='2026-01-02T12:00:00+00:00',days=[
            dict(day='2026-01-01',landing_requests=None,trial_clicks=None,coverage='unavailable'),
            dict(day='2026-01-02',landing_requests=4,trial_clicks=2,coverage='partial')])
        accounts={'2026-01-01':dict(registrations=1,verifications=0,activations=0),
                  '2026-01-02':dict(registrations=0,verifications=1,activations=1)}
        with patch.dict(os.environ,STAFF_MARKETING_REPORT_URL='https://marketing.example.test/internal/staff-acquisition',MARKETING_ACQUISITION_REPORT_TOKEN='x'*32):
            with patch.object(acquisition,'build_opener') as opener, patch.object(acquisition,'account_metrics',return_value=accounts):
                response=opener.return_value.open.return_value.__enter__.return_value
                response.read.return_value=json.dumps(payload).encode()
                report=acquisition.report(date(2026,1,1),date(2026,1,2))
                self.assertEqual(report['totals'],dict(registrations=1,verifications=1,activations=1,landing_requests=4,trial_clicks=2))
                self.assertIsNone(report['days'][0]['landing_requests'])
                self.assertFalse(report['complete'])
                request=opener.return_value.open.call_args.args[0]
                self.assertEqual(request.get_header('Authorization'),'Bearer '+'x'*32)
                self.assertIn('start=2026-01-01&end=2026-01-02',request.full_url)
                self.assertEqual(opener.return_value.open.call_args.kwargs['timeout'],2)

    def test_date_validation(self):
        self.assertEqual(acquisition.date_range('2026-01-01','2026-01-02'), (date(2026,1,1),date(2026,1,2)))
        for start,end in [('invalid','2026-01-01'),('2026-01-03','2026-01-01'),('2020-01-01','2026-01-01'),('2026-01-01','2099-01-01')]:
            with self.assertRaises(ValueError):
                acquisition.date_range(start,end)

    def test_bridge_failure_and_malformed_data_are_unavailable(self):
        with patch.dict(os.environ,STAFF_MARKETING_REPORT_URL='https://[invalid',MARKETING_ACQUISITION_REPORT_TOKEN='x'*32):
            self.assertFalse(acquisition.marketing_metrics(date(2026,1,1),date(2026,1,1))['available'])
        with patch.dict(os.environ, STAFF_MARKETING_REPORT_URL='https://marketing.example.test/internal/staff-acquisition',MARKETING_ACQUISITION_REPORT_TOKEN='x'*32):
            with patch.object(acquisition,'build_opener') as opener:
                opener.return_value.open.side_effect=TimeoutError()
                self.assertFalse(acquisition.marketing_metrics(date(2026,1,1),date(2026,1,1))['available'])
                opener.return_value.open.side_effect=None
                response=opener.return_value.open.return_value.__enter__.return_value
                response.read.return_value=b'{invalid'
                self.assertFalse(acquisition.marketing_metrics(date(2026,1,1),date(2026,1,1))['available'])


@unittest.skipUnless(os.getenv('STAFF_TEST_DATABASE_URL'), 'Requires isolated PostgreSQL')
class AcquisitionDatabaseTests(unittest.TestCase):
    for name in ('setUp','cleanup_schema','connect','apply_control_centre_migrations','business','paid','billing_snapshot','platform_client','active','audit_actions','apply_contact_migration'):
        locals()[name]=getattr(fixture.ControlCentreDatabaseTests,name)

    def action(self,client,bid,action):
        return client.post('/staff/platform/businesses/'+bid+'/subscription',data=dict(csrf_token='csrf-ok',action=action,reason='Synthetic lifecycle review',confirmation=bid))

    def dated_business(self,bid,active=True):
        self.business(bid,trial='pending',verified=True,active=active)
        database.execute("UPDATE sm_businesses SET created_at='2026-01-01T23:59:59Z' WHERE id=%s",(bid,))
        database.execute("UPDATE sm_administrators SET verified_at='2026-01-02T00:00:00Z' WHERE id=%s",(bid+'-admin',))
        database.execute("UPDATE so_trials SET starts_at='2026-01-03T00:00:00Z',ends_at='2026-01-17T00:00:00Z' WHERE business_id=%s",(bid,))

    def totals(self):
        days=acquisition.account_metrics(date(2026,1,1),date(2026,1,3))
        return tuple(sum(row[key] for row in days.values()) for key in ('registrations','verifications','activations'))

    def test_events_use_separate_dates_and_expired_trials_are_retained(self):
        self.dated_business('real-expired')
        self.dated_business('genuine-inactive',active=False)
        self.business('legacy',trial='none')
        self.assertEqual(self.totals(),(2,2,2))
        daily=acquisition.account_metrics(date(2026,1,1),date(2026,1,3))
        self.assertEqual(daily['2026-01-01'],dict(registrations=2,verifications=0,activations=0))
        self.assertEqual(daily['2026-01-02']['verifications'],2)
        self.assertEqual(daily['2026-01-03']['activations'],2)
        self.assertEqual(acquisition.account_metrics(date(2025,12,31),date(2025,12,31))['2025-12-31']['registrations'],0)

    def test_shared_administrator_verification_counts_once(self):
        self.dated_business('first')
        self.dated_business('second')
        database.execute("UPDATE so_trials SET administrator_id='first-admin' WHERE business_id='second'")
        self.assertEqual(self.totals(),(2,1,2))

    def test_excludes_explicit_tests_archives_and_discarded_registrations(self):
        for bid in ('normal','test-account','archived','reviewed'):
            self.dated_business(bid)
        acquisition_classification.change('test-account','platform:reviewer',dict(action='mark_test',reason='Explicit test',confirmation='test-account'))
        management.change('archived','platform:reviewer','archive',dict(reason='Explicit archive',confirmation='archived'),platform=True)
        database.execute("UPDATE sm_administrators SET verified_at=NULL WHERE id='reviewed-admin'")
        registration_review.apply('deactivate',['reviewed'],'platform:reviewer','Discarded signup','DEACTIVATE 1')
        self.assertEqual(self.totals(),(1,1,1))
        acquisition_classification.change('test-account','platform:reviewer',dict(action='clear_test',reason='Reclassified',confirmation='test-account'))
        self.assertEqual(self.totals(),(2,2,2))
        self.assertEqual(database.fetch_one("SELECT COUNT(*) AS n FROM staff_audit WHERE entity_type='acquisition_classification'")['n'],2)

    def test_archive_restore_counts_and_review_cannot_reactivate_archive(self):
        self.business('review-test',trial='pending')
        self.business('real-expired')
        registration_review.apply('deactivate',['review-test'],'platform:reviewer','Discarded signup','DEACTIVATE 1')
        client=self.platform_client()
        self.assertEqual(self.action(client,'review-test','archive').status_code,302)
        self.assertTrue(management.business('review-test')['archived'])
        result=registration_review.apply('reactivate',['review-test'],'platform:reviewer','Review restore','REACTIVATE 1')
        self.assertEqual(result['applied'],[])
        self.assertFalse(self.active('review-test'))
        data=platform_control.directory()
        self.assertEqual(data['total'],len(data['businesses']))
        self.assertEqual(data['total'],1)
        self.assertEqual(data['businesses'][0]['state'],'expired_trial')
        self.assertEqual(platform_control.directory(status='inactive_archived')['matching'],1)
        self.action(client,'review-test','reactivate')
        self.assertFalse(self.active('review-test'))
        self.action(client,'review-test','restore')
        self.assertFalse(self.active('review-test'))
        self.assertFalse(management.business('review-test')['archived'])
        self.action(client,'review-test','reactivate')
        self.assertEqual(platform_control.directory()['total'],2)
        summary=platform_control.build_control_centre_summary([],platform_control.directory(status='all'))
        self.assertEqual(summary['products']['staff']['businesses'],2)

    def test_ongoing_billing_blocks_archive_and_preserves_records(self):
        self.business('paid',trial='expired')
        self.paid('paid')
        before=self.billing_snapshot()
        with self.assertRaisesRegex(ValueError,'billing provider first'):
            management.change('paid','platform:reviewer','archive',dict(reason='Archive test',confirmation='paid'),platform=True)
        self.assertEqual(self.billing_snapshot(),before)
        self.assertTrue(self.active('paid'))

    def test_normal_owner_routes_deny_reporting_and_classification(self):
        self.dated_business('alpha')
        owner=self.platform_client()
        anonymous=owner.application.test_client()
        self.assertEqual(anonymous.get('/staff/platform/acquisition').status_code,302)
        with owner.session_transaction() as session:
            session['platform_admin_auth_source']='dashboard_fallback'
        self.assertEqual(owner.get('/staff/platform/acquisition').status_code,403)
        self.assertEqual(owner.post('/staff/platform/businesses/alpha/classification',data=dict(csrf_token='csrf-ok',action='mark_test',reason='Test',confirmation='alpha')).status_code,403)
        self.assertFalse(management.business('alpha')['is_test'])

    def test_report_date_filter_unavailable_counter_and_csrf(self):
        self.dated_business('alpha')
        client=self.platform_client()
        with patch.object(acquisition,'marketing_metrics',return_value=dict(available=False,started_at=None,days=[])):
            page=client.get('/staff/platform/acquisition?start=2026-01-01&end=2026-01-03')
            self.assertEqual(page.status_code,200)
            self.assertIn(b'Unavailable',page.data)
            self.assertIn(b'2026-01-03',page.data)
            self.assertNotIn(b'ad conversion',page.data)
            self.assertEqual(client.get('/staff/platform/acquisition?start=invalid').status_code,400)
        base='/staff/platform/businesses/alpha/classification'
        self.assertEqual(client.post(base,data=dict(action='mark_test')).status_code,400)
        self.assertEqual(client.post(base,data=dict(csrf_token='csrf-ok',action='mark_test',reason='Explicit test',confirmation='alpha')).status_code,302)
        self.assertTrue(management.business('alpha')['is_test'])
        self.assertEqual(self.totals(),(0,0,0))


if __name__ == '__main__':
    unittest.main()
