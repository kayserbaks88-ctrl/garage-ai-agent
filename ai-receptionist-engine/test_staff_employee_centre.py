"""Employee control-centre regressions using only disposable Staff test schemas."""
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import test_staff_agency as fixtures
from trimtech.modules.staff import agency, database, notifications


@unittest.skipUnless(os.getenv('STAFF_TEST_DATABASE_URL'), 'Requires disposable local PostgreSQL')
class EmployeeCentreTests(unittest.TestCase):
    setUp = fixtures.AgencyDatabaseTests.setUp
    cleanup_schema = fixtures.AgencyDatabaseTests.cleanup_schema
    connect = fixtures.AgencyDatabaseTests.connect
    insert = fixtures.AgencyDatabaseTests.insert
    client = fixtures.AgencyDatabaseTests.client
    post = fixtures.AgencyDatabaseTests.post
    row = fixtures.AgencyDatabaseTests.row
    assignment = fixtures.AgencyDatabaseTests.assignment
    assignment_values = fixtures.AgencyDatabaseTests.assignment_values
    enable_agency = fixtures.AgencyDatabaseTests.enable_agency
    gps = fixtures.AgencyDatabaseTests.gps
    current = fixtures.AgencyDatabaseTests.current
    payroll = fixtures.AgencyDatabaseTests.payroll

    def test_fixed_business_employee_can_see_their_scheduled_job(self):
        now = datetime.now(timezone.utc)
        self.assignment(start=now+timedelta(days=1), end=now+timedelta(days=1, hours=2))
        self.assertEqual(agency.settings('alpha')['organisation_mode'], 'fixed')
        page = self.worker.get('/staff/alpha/employee').get_data(as_text=True)
        self.assertIn('First site', page)
        self.assertIn('1 Test Street', page)
        jobs = self.worker.get('/staff/alpha/employee/jobs').get_data(as_text=True)
        self.assertIn('1 Test Street', jobs)
        self.assertNotIn('name="assignment_id"', self.worker.get('/staff/alpha/employee/clocking').get_data(as_text=True))

    def test_home_is_compact_and_tools_are_separate_authenticated_pages(self):
        self.enable_agency()
        home = self.worker.get('/staff/alpha/employee').get_data(as_text=True)
        for page in ('jobs', 'clocking', 'hours', 'leave', 'pay', 'profile'):
            with self.subTest(page=page):
                path = '/staff/alpha/employee/' + page
                self.assertIn(path, home)
                response = self.worker.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertIn(b'Back to home', response.data)
                self.assertIn('no-store', response.headers['Cache-Control'])
                self.assertEqual(self.client().get(path).status_code, 302)
                self.assertEqual(self.manager.get(path).status_code, 302)
                self.assertEqual(self.worker.get('/staff/beta/employee/' + page).status_code, 302)
        for marker in ('Optional travel origin', 'data-location-form', 'id="leave-form"', 'Statutory deductions', 'Shift history'):
            self.assertNotIn(marker, home)
        self.assertIn(b'Optional travel origin', self.worker.get('/staff/alpha/employee/profile').data)
        self.assertIn(b'id="leave-form"', self.worker.get('/staff/alpha/employee/leave').data)
        self.assertIn(b'Approved payroll records', self.worker.get('/staff/alpha/employee/pay').data)

    def test_home_shows_only_current_or_next_job_and_jobs_keep_history(self):
        now = datetime.now(timezone.utc)
        current = self.assignment()
        upcoming = self.assignment(site=self.second_site, start=now+timedelta(days=1), end=now+timedelta(days=1,hours=1))
        past = self.assignment(start=now-timedelta(days=2), end=now-timedelta(days=1))
        home = self.worker.get('/staff/alpha/employee').get_data(as_text=True)
        self.assertIn('Current job', home)
        self.assertIn('First site', home)
        self.assertNotIn('Second site', home)
        jobs = self.worker.get('/staff/alpha/employee/jobs').get_data(as_text=True)
        self.assertIn(f'data-job-id="{current}"', jobs)
        self.assertIn(f'data-job-id="{upcoming}"', jobs)
        self.assertIn(f'data-history-job-id="{past}"', jobs)
        self.post(self.manager, f'assignments/{current}/cancel', {'reason': 'Cancelled'})
        home = self.worker.get('/staff/alpha/employee').get_data(as_text=True)
        self.assertIn('Next upcoming job', home)
        self.assertIn('Second site', home)

    def test_hours_leave_profile_and_pay_are_employee_scoped(self):
        self.insert("""INSERT INTO staff_shifts (business_id,employee_id,site_id,site_name,clock_in_at,clock_out_at)
            VALUES ('alpha',%s,%s,'PRIVATE SHIFT',NOW()-INTERVAL '2 hours',NOW()-INTERVAL '1 hour') RETURNING id""", (self.second, self.site))
        self.post(self.worker2, 'employee/leave', {'leave_type': 'holiday', 'start_date': '2030-05-01', 'end_date': '2030-05-02', 'employee_note': 'PRIVATE LEAVE'})
        for page, marker in (('hours', 'PRIVATE SHIFT'), ('leave', 'PRIVATE LEAVE'), ('profile', 'Blair')):
            self.assertNotIn(marker, self.worker.get('/staff/alpha/employee/' + page + '?employee_id=' + str(self.second)).get_data(as_text=True))
        self.post(self.worker, 'employee/clock-in', {'site_id': self.site, **self.gps()})
        shift = self.current()
        self.post(self.worker, 'employee/clock-out', {'shift_id': shift['id'], **self.gps()})
        self.post(self.manager, 'shifts/approve-selected', {'shift_ids': [shift['id']]})
        run = self.payroll(shift['id'])
        self.assertNotIn(b'Gross:', self.worker.get('/staff/alpha/employee/pay').data)
        self.post(self.manager, f"payroll/{run['id']}/approve")
        self.assertIn(b'Gross:', self.worker.get('/staff/alpha/employee/pay').data)
        self.assertNotIn(b'Gross:', self.worker2.get('/staff/alpha/employee/pay').data)
        self.assertIn(b'Old shift', self.worker.get('/staff/alpha/employee/hours').data)

    def test_employee_actions_redirect_to_their_tool_without_weakening_csrf(self):
        response = self.post(self.worker, 'employee/clock-in', {'site_id': self.site, **self.gps()})
        self.assertTrue(response.location.endswith('/employee/clocking'))
        shift = self.current()
        response = self.post(self.worker, 'employee/break/start', {'shift_id': shift['id']})
        self.assertTrue(response.location.endswith('/employee/clocking'))
        self.assertIn(b'End break', self.worker.get('/staff/alpha/employee/clocking').data)
        response = self.post(self.worker, 'employee/clock-out', {'shift_id': shift['id'], **self.gps()})
        self.assertTrue(response.location.endswith('/employee/clocking'))
        response = self.post(self.worker, 'employee/leave', {'leave_type': 'holiday', 'start_date': '2030-05-01', 'end_date': '2030-05-02'})
        self.assertTrue(response.location.endswith('/employee/leave'))
        response = self.post(self.worker, 'employee/travel-origin', {'disable': 'on'})
        self.assertTrue(response.location.endswith('/employee/profile'))
        self.assertEqual(self.worker.post('/staff/alpha/employee/leave', data={}).status_code, 400)

    def test_email_confirmation_reflects_current_action_and_partial_reassignment(self):
        database.execute("UPDATE staff_employees SET email='worker@example.test' WHERE business_id='alpha'")
        with patch.dict(os.environ, {'STAFF_ASSIGNMENT_EMAIL_ENABLED': '1', 'STAFF_PUBLIC_BASE_URL': 'https://staff.example.test'}), patch.object(notifications, 'send_staff_email', return_value=(True,None,'provider')) as send:
            response = self.post(self.manager, 'assignments', self.assignment_values())
            page = self.manager.get(response.location).get_data(as_text=True)
            self.assertIn('Employee notification sent', page)
            self.assertIn('inbox delivery is not confirmed', page)
            assignment = database.fetch_one('SELECT id FROM staff_assignments')['id']
            send.return_value = (False, 'provider_http_429', None)
            response = self.post(self.manager, f'assignments/{assignment}/edit', self.assignment_values())
            page = self.manager.get(response.location).get_data(as_text=True)
            self.assertIn('Email failed', page)
            self.assertNotIn('Employee notification sent', page)
            send.side_effect = [(True,None,'provider'), (False,'provider_http_429',None)]
            response = self.post(self.manager, f'assignments/{assignment}/edit', self.assignment_values(employee=self.second))
            self.assertIn(b'Email failed', self.manager.get(response.location).data)
            self.assertEqual(self.row('staff_assignments',assignment)['employee_id'],self.second)

    def test_email_disabled_queue_error_pending_and_unknown_are_never_success(self):
        response = self.post(self.manager, 'assignments', self.assignment_values())
        self.assertIn(b'Email is disabled', self.manager.get(response.location).data)
        assignment = database.fetch_one('SELECT id FROM staff_assignments')['id']
        with patch.object(notifications, '_queue', side_effect=ValueError('private details')):
            response = self.post(self.manager, f'assignments/{assignment}/cancel', {'reason': 'Cancelled'})
        self.assertIn(b'Email failed to queue', self.manager.get(response.location).data)
        self.assertEqual(self.row('staff_assignments', assignment)['status'],'cancelled')
        with patch.object(notifications, 'dispatch'):
            response = self.post(self.manager, f'assignments/{assignment}/edit', self.assignment_values())
        self.assertIn(b'Email pending', self.manager.get(response.location).data)
        with patch.object(notifications, 'transaction', side_effect=RuntimeError('private details')):
            message, category = notifications.confirmation('alpha',assignment,[1])
        self.assertIn('Email status unavailable', message)
        self.assertNotIn('private details', message)
        self.assertNotEqual(category,'success')

    def test_manager_minute_controls_and_human_uk_roster_preserve_legacy_seconds(self):
        now = datetime.now(timezone.utc).replace(microsecond=123456,second=35)
        assignment_id = self.assignment(start=now, end=now+timedelta(hours=2))
        original = self.row('staff_assignments', assignment_id)
        page = self.manager.get(f'/staff/alpha/agency?assignment={assignment_id}').get_data(as_text=True)
        self.assertIn('step="60"',page)
        self.assertIn(agency.uk_display(original['starts_at']),page)
        values = {**agency.assignment_form_values(original),'employee_id':self.employee,'site_id':self.site,'reason':'No time change'}
        self.post(self.manager,f'assignments/{assignment_id}/edit',values)
        saved = self.row('staff_assignments',assignment_id)
        self.assertEqual(saved['starts_at'],original['starts_at'])
        self.assertEqual(saved['ends_at'],original['ends_at'])


if __name__ == '__main__':
    unittest.main()
