"""Run-level payslip issuing, durable notices and isolated retry failures."""
import os
import unittest
from unittest.mock import patch

import test_staff_statutory as fixtures
from trimtech.modules.staff import database, payslips


@unittest.skipUnless(os.getenv('STAFF_TEST_DATABASE_URL'), 'Requires disposable local PostgreSQL')
class PayslipIssuingTests(unittest.TestCase):
    for _name in ('setUp','cleanup_schema','connect','insert','client','post','row','profile','shift','generate'):
        locals()[_name] = getattr(fixtures.StatutoryDatabaseTests, _name)

    def prepare(self):
        values=self.profile()
        self.post(self.manager,f'payroll/profiles/{self.second}',values)
        self.shift(); self.shift(employee=self.second); self.generate()
        database.execute("UPDATE staff_employees SET email='first@example.test' WHERE id=%s",(self.employee,))
        database.execute("UPDATE staff_employees SET email='second@example.test' WHERE id=%s",(self.second,))
        run=database.fetch_one('SELECT * FROM staff_payroll_runs')
        slips=database.fetch_all('SELECT * FROM staff_payslips ORDER BY employee_id')
        return run,slips

    def environment(self):
        return patch.dict(os.environ,{'STAFF_PAYSLIP_EMAIL_ENABLED':'1','STAFF_PUBLIC_BASE_URL':'https://staff.example.test'})

    def test_one_action_finalises_all_portals_then_sends_individually(self):
        run,slips=self.prepare()
        def deliver(*args):
            # A separate connection sees committed approval and ALL queue records.
            self.assertEqual(self.row('staff_payroll_runs',run['id'])['status'],'approved')
            self.assertEqual(len(database.fetch_all('SELECT * FROM staff_payslip_notifications')),2)
            return True,None,'provider-id'
        with self.environment(), patch.object(payslips,'send_staff_email',side_effect=deliver) as send:
            response=self.post(self.manager,f"payroll/{run['id']}/approve")
            self.assertTrue(response.location.endswith(f"/payroll/{run['id']}"))
            self.assertEqual(self.worker.get(f"/staff/alpha/employee/payslips/{slips[0]['id']}/download").status_code,200)
            self.assertEqual(self.worker2.get(f"/staff/alpha/employee/payslips/{slips[1]['id']}/download").status_code,200)
            self.assertEqual(self.worker.get(f"/staff/alpha/employee/payslips/{slips[1]['id']}/download").status_code,404)
            result=self.post(self.manager,f"payroll/{run['id']}/issue-pending")
            self.assertEqual(result.json['pending'],0)
            self.assertEqual(send.call_count,2)
            self.post(self.manager,f"payroll/{run['id']}/approve")
            self.post(self.manager,f"payroll/{run['id']}/issue-pending")
            self.post(self.manager,f"payroll/payslips/{slips[0]['id']}/send")
            self.assertEqual(send.call_count,2)
            self.assertEqual({call.args[0] for call in send.call_args_list},{'first@example.test','second@example.test'})
            self.assertTrue(all('150.00' not in call.args[2] for call in send.call_args_list))
        self.assertTrue(all(row['status']=='sent' for row in database.fetch_all('SELECT * FROM staff_payslip_notifications')))

    def test_transport_failure_does_not_rollback_success_and_retry_is_individual(self):
        run,slips=self.prepare()
        with self.environment(), patch.object(payslips,'send_staff_email',side_effect=[(True,None,'first-id'), RuntimeError('SECRET should not appear')]):
            self.post(self.manager,f"payroll/{run['id']}/approve")
            self.post(self.manager,f"payroll/{run['id']}/issue-pending")
        before=database.fetch_all('SELECT * FROM staff_payslip_notifications ORDER BY payslip_id')
        self.assertEqual([r['status'] for r in before],['sent','failed'])
        self.assertEqual(self.row('staff_payroll_runs',run['id'])['status'],'approved')
        html=self.manager.get(f"/staff/alpha/payroll/{run['id']}").get_data(as_text=True)
        self.assertIn('Retry email',html)
        self.assertNotIn('Send payslip notice',html)
        self.assertNotIn('SECRET',html)
        with self.environment(), patch.object(payslips,'send_staff_email',return_value=(True,None,'second-id')) as send:
            self.post(self.manager,f"payroll/payslips/{slips[1]['id']}/send")
            send.assert_called_once()
            self.assertEqual(send.call_args.args[0],'second@example.test')
            self.assertEqual(send.call_args.args[4],before[1]['event_key'])
        after=database.fetch_all('SELECT * FROM staff_payslip_notifications ORDER BY payslip_id')
        self.assertEqual(after[0],before[0])
        self.assertEqual(after[1]['status'],'sent')

    def test_missing_email_does_not_block_run_or_other_notices(self):
        run,slips=self.prepare()
        database.execute('UPDATE staff_employees SET email=NULL WHERE id=%s',(self.employee,))
        with self.environment(), patch.object(payslips,'send_staff_email',return_value=(True,None,'ok')) as send:
            self.post(self.manager,f"payroll/{run['id']}/approve")
            send.assert_called_once()
        self.assertEqual(self.row('staff_payroll_runs',run['id'])['status'],'approved')
        self.assertEqual(database.fetch_one('SELECT status FROM staff_payslip_notifications WHERE payslip_id=%s',(slips[0]['id'],))['status'],'failed')
        database.execute("UPDATE staff_employees SET email='corrected@example.test' WHERE id=%s",(self.employee,))
        with self.environment(), patch.object(payslips,'send_staff_email',return_value=(True,None,'corrected')) as send:
            self.post(self.manager,f"payroll/payslips/{slips[0]['id']}/send")
            self.assertEqual(send.call_args.args[0],'corrected@example.test')

    def test_incomplete_or_flagged_draft_cannot_issue_and_tenant_csrf_checks(self):
        run,slips=self.prepare()
        database.execute('UPDATE staff_payroll_runs SET needs_recalculation=TRUE WHERE id=%s',(run['id'],))
        self.post(self.manager,f"payroll/{run['id']}/approve")
        self.assertEqual(self.row('staff_payroll_runs',run['id'])['status'],'draft')
        self.assertFalse(database.fetch_all('SELECT * FROM staff_payslip_notifications'))
        self.assertEqual(self.manager.post(f"/staff/alpha/payroll/{run['id']}/issue-pending").status_code,400)
        denied=self.post(self.worker,f"payroll/{run['id']}/issue-pending")
        self.assertEqual(denied.status_code,302)
        self.assertIn('/login',denied.location)
        self.assertEqual(self.manager.post(f"/staff/beta/payroll/{run['id']}/issue-pending",data={'csrf_token':'test-csrf'}).status_code,404)
        database.execute('UPDATE staff_payroll_runs SET needs_recalculation=FALSE WHERE id=%s',(run['id'],))
        database.execute('DELETE FROM staff_payroll_calculations WHERE payslip_id=%s',(slips[1]['id'],))
        self.post(self.manager,f"payroll/{run['id']}/approve")
        self.assertEqual(self.row('staff_payroll_runs',run['id'])['status'],'draft')

    def test_pending_queue_survives_interrupted_processing_and_resumes(self):
        run,slips=self.prepare()
        with patch.object(payslips,'dispatch_next',side_effect=RuntimeError('temporary outage')):
            self.post(self.manager,f"payroll/{run['id']}/approve")
        self.assertEqual(self.row('staff_payroll_runs',run['id'])['status'],'approved')
        self.assertTrue(all(r['status']=='pending' for r in database.fetch_all('SELECT status FROM staff_payslip_notifications')))
        page=self.manager.get(f"/staff/alpha/payroll/{run['id']}")
        self.assertIn(b'data-pending="2"',page.data)
        with self.environment(), patch.object(payslips,'send_staff_email',return_value=(True,None,'ok')) as send:
            self.post(self.manager,f"payroll/{run['id']}/issue-pending")
            self.post(self.manager,f"payroll/{run['id']}/issue-pending")
            self.assertEqual(send.call_count,2)
