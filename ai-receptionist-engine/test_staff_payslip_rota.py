"""Payslip navigation/download and assignment-backed weekly rota regressions."""
import os
import unittest
from datetime import datetime, timezone

import test_staff_statutory as fixtures
from trimtech.modules.staff import database


@unittest.skipUnless(os.getenv('STAFF_TEST_DATABASE_URL'), 'Requires disposable local PostgreSQL')
class PayslipRotaTests(unittest.TestCase):
    for _name in ('setUp','cleanup_schema','connect','insert','client','post','row',
                  'profile','shift','generate','assignment','assignment_values'):
        locals()[_name] = getattr(fixtures.StatutoryDatabaseTests, _name)

    def payroll(self):
        self.profile(); self.shift(); self.generate()
        return database.fetch_one('SELECT * FROM staff_payroll_runs'), database.fetch_one('SELECT * FROM staff_payslips')

    def test_manager_view_and_genuine_pdf_download_have_separate_navigation(self):
        run,slip=self.payroll()
        before=self.row('staff_payslips',slip['id'])
        base=f"/staff/alpha/payroll/payslips/{slip['id']}"
        pdf=self.manager.get(base+'/download')
        self.assertEqual(pdf.status_code,200)
        self.assertEqual(pdf.mimetype,'application/pdf')
        self.assertTrue(pdf.data.startswith(b'%PDF-'))
        self.assertEqual(pdf.headers['Content-Disposition'],'attachment; filename="TrimTech-Payslip-2026-04-30.pdf"')
        self.assertIn('no-store',pdf.headers['Cache-Control'])
        page=self.manager.get(base+'/view')
        self.assertEqual(page.mimetype,'text/html')
        self.assertIn(b'Back to payroll review',page.data)
        self.assertIn(f'/staff/alpha/payroll/{run["id"]}'.encode(),page.data)
        self.assertIn(b'Back to payroll',page.data)
        self.assertIn(b'Download draft PDF',page.data)
        self.assertIn(b'150.00',page.data)
        self.assertEqual(before,self.row('staff_payslips',slip['id']))
        self.assertFalse(database.fetch_all('SELECT * FROM staff_payslip_notifications'))

    def test_employee_view_download_and_isolation(self):
        run,slip=self.payroll()
        base=f"/staff/alpha/employee/payslips/{slip['id']}"
        for action in ('view','download'):
            self.assertEqual(self.worker.get(base+'/'+action).status_code,404)
        self.post(self.manager,f"payroll/{run['id']}/approve")
        notices=database.fetch_all('SELECT * FROM staff_payslip_notifications')
        for action in ('view','download'):
            response=self.worker.get(base+'/'+action)
            self.assertEqual(response.status_code,200)
            self.assertIn('no-store',response.headers['Cache-Control'])
            self.assertEqual(self.worker2.get(base+'/'+action).status_code,404)
            self.assertEqual(self.client().get(base+'/'+action).status_code,302)
            self.assertEqual(self.manager.get(base+'/'+action).status_code,302)
            self.assertEqual(self.worker.get(base.replace('/alpha/','/beta/')+'/'+action).status_code,302)
            self.assertEqual(self.manager.get(f"/staff/beta/payroll/payslips/{slip['id']}/{action}").status_code,404)
        page=self.worker.get(base+'/view').get_data(as_text=True)
        self.assertIn('Back to Pay / payslips',page)
        self.assertIn('href="/staff/alpha/employee/pay"',page)
        self.assertNotIn('Back to payroll review',page)
        self.assertIn('Download PDF',page)
        pdf=self.worker.get(base+'/download')
        self.assertTrue(pdf.data.startswith(b'%PDF-'))
        self.assertEqual(pdf.headers['Content-Disposition'],'attachment; filename="TrimTech-Payslip-2026-04-30.pdf"')
        self.assertEqual(notices,database.fetch_all('SELECT * FROM staff_payslip_notifications'))
        for url,client in ((f"/staff/alpha/payroll/{run['id']}",self.manager),('/staff/alpha/employee/pay',self.worker)):
            content=client.get(url).get_data(as_text=True)
            self.assertIn('View payslip',content)
            self.assertIn('Download PDF',content)
        database.execute('UPDATE staff_payroll_runs SET needs_recalculation=TRUE WHERE id=%s',(run['id'],))
        self.assertEqual(self.worker.get(base+'/view').status_code,404)
        self.assertEqual(self.manager.get(base.replace('/employee/','/payroll/')+'/download').status_code,404)

    def test_rota_monday_to_sunday_overnight_and_employee_scope(self):
        start=datetime(2026,10,11,21,tzinfo=timezone.utc)
        end=datetime(2026,10,12,5,tzinfo=timezone.utc)
        carry=self.assignment(start=start,end=end)
        self.assignment(start=datetime(2026,10,14,21,tzinfo=timezone.utc),end=datetime(2026,10,15,5,tzinfo=timezone.utc))
        self.assignment(employee=self.second,site=self.second_site,start=datetime(2026,10,14,9,tzinfo=timezone.utc),end=datetime(2026,10,14,10,tzinfo=timezone.utc))
        before=database.fetch_all('SELECT * FROM staff_assignments ORDER BY id')
        page=self.worker.get('/staff/alpha/employee/rota?week=2026-10-14&employee_id='+str(self.second))
        self.assertEqual(page.status_code,200)
        html=page.get_data(as_text=True)
        for day in ('Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'):
            self.assertIn('<h2>'+day,html)
        self.assertIn('12 Oct 2026',html)
        self.assertIn('18 Oct 2026',html)
        self.assertIn(f'data-assignment-id="{carry}"',html)
        self.assertIn('Continues from previous day',html)
        self.assertIn('Wed 14 Oct 2026, 22:00 BST',html)
        self.assertIn('Thu 15 Oct 2026, 06:00 BST',html)
        self.assertNotIn('Second site',html)
        self.assertNotIn('Private site',html)
        self.assertIn('week=2026-10-05',html)
        self.assertIn('week=2026-10-19',html)
        self.assertIn('This week',html)
        self.assertEqual(before,database.fetch_all('SELECT * FROM staff_assignments ORDER BY id'))
        self.assertIn('no-store',page.headers['Cache-Control'])

    def test_rota_dst_cancelled_and_week_end_boundary(self):
        overnight=self.assignment(start=datetime(2026,10,25,0,30,tzinfo=timezone.utc),end=datetime(2026,10,25,2,30,tzinfo=timezone.utc))
        database.execute("UPDATE staff_assignments SET status='cancelled' WHERE id=%s",(overnight,))
        page=self.worker.get('/staff/alpha/employee/rota?week=2026-10-19').get_data(as_text=True)
        self.assertIn('Sun 25 Oct 2026, 01:30 BST',page)
        self.assertIn('Sun 25 Oct 2026, 02:30 GMT',page)
        self.assertIn('Cancelled',page)
        following=self.worker.get('/staff/alpha/employee/rota?week=2026-10-26').get_data(as_text=True)
        self.assertNotIn(f'data-assignment-id="{overnight}"',following)

    def test_rota_auth_invalid_dates_empty_week_and_links(self):
        for client in (self.client(),self.manager):
            self.assertEqual(client.get('/staff/alpha/employee/rota').status_code,302)
        for week in ('not-a-date','2026-02-30','0001-01-01','9999-12-31'):
            self.assertEqual(self.worker.get('/staff/alpha/employee/rota?week='+week).status_code,400)
        self.assertEqual(self.worker.get('/staff/beta/employee/rota').status_code,302)
        page=self.worker.get('/staff/alpha/employee/rota?week=2026-10-12')
        self.assertEqual(page.data.count(b'No assignments'),7)
        self.assertIn(b'My rota',self.worker.get('/staff/alpha/employee').data)
