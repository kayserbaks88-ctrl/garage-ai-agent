"""Targeted mobile attendance and automatic period-payroll regression tests."""
import os
import unittest
from datetime import datetime, timezone
from html.parser import HTMLParser

import test_staff_statutory as fixtures
from trimtech.modules.staff import attendance, database


class Cards(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.cards = []
        self.controls = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if 'data-attendance-person' in values:
            self.cards.append(values)
        if tag in {'input', 'select'}:
            self.controls.append(values)


class MobileGroupingTests(unittest.TestCase):
    def test_hundred_staff_and_repeated_shifts_group_by_identity(self):
        shifts = [dict(id=i, employee_id=i, full_name=f'Employee {i}', site_name='Site',
                       clock_out_at=None, approval_status='pending', late_minutes=None)
                  for i in range(1, 101)]
        shifts.append({**shifts[0], 'id': 101, 'clock_out_at': datetime.now(timezone.utc)})
        cards = attendance.mobile_cards(shifts, [])
        self.assertEqual(len(cards), 100)
        self.assertEqual(len(next(c for c in cards if c['employee_id']==1)['shifts']), 2)


@unittest.skipUnless(os.getenv('STAFF_TEST_DATABASE_URL'), 'Requires disposable local PostgreSQL')
class MobilePayrollDatabaseTests(unittest.TestCase):
    for _name in ('setUp', 'cleanup_schema', 'connect', 'insert', 'client', 'post', 'row',
                  'assignment', 'assignment_values', 'profile', 'shift', 'generate'):
        locals()[_name] = getattr(fixtures.StatutoryDatabaseTests, _name)

    def test_mobile_cards_collapsed_filters_and_desktop_preserved(self):
        now = datetime.now(timezone.utc)
        from datetime import timedelta
        self.assignment(start=now-timedelta(minutes=30), end=now+timedelta(hours=1))
        self.insert("""INSERT INTO staff_shifts(business_id,employee_id,site_id,site_name,clock_in_at)
            VALUES('alpha',%s,%s,'First site',NOW()) RETURNING id""", (self.second, self.site))
        page = self.manager.get('/staff/alpha/attendance')
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        parsed = Cards(html)
        self.assertEqual(len(parsed.cards), 2)
        self.assertTrue(all('open' not in card for card in parsed.cards))
        self.assertTrue(any(card['data-missed']=='1' for card in parsed.cards))
        self.assertIn('table-wrap attendance-desktop', html)
        self.assertIn('Mark reviewed', html)
        self.assertIn('Attendance timeline', html)
        self.assertIn('Location unavailable/stale', html)
        for key in ('data-attendance-search', 'data-attendance-site', 'data-attendance-status', 'data-attendance-alert'):
            self.assertTrue(any(key in c for c in parsed.controls))
        self.assertNotIn('Private site', html)
        self.assertEqual(self.worker.get('/staff/alpha/attendance').status_code, 302)

    def test_automatic_multi_employee_draft_and_named_exclusions(self):
        values = self.profile()
        self.post(self.manager, f'payroll/profiles/{self.second}', values)
        first = self.shift()
        second = self.shift(employee=self.second)
        pending = self.shift('2026-04-21')
        database.execute("UPDATE staff_shifts SET approval_status='pending' WHERE id=%s", (pending,))
        rejected = self.shift('2026-04-23')
        database.execute("UPDATE staff_shifts SET approval_status='rejected' WHERE id=%s", (rejected,))
        opened = self.shift('2026-04-24')
        database.execute("UPDATE staff_shifts SET clock_out_at=NULL WHERE id=%s", (opened,))
        empty = self.shift('2026-04-22')
        database.execute("UPDATE staff_shifts SET clock_out_at=clock_in_at WHERE id=%s", (empty,))
        response = self.post(self.manager, 'payroll/generate', dict(period_start='2026-04-01',
            period_end='2026-04-30', payment_date='2026-04-30', frequency='monthly',
            employer_name='Alpha Limited', employee_ids=str(self.employee)))
        run = database.fetch_one('SELECT * FROM staff_payroll_runs')
        self.assertEqual(run['status'], 'draft')
        self.assertTrue(response.location.endswith(f"/payroll/{run['id']}"))
        slips = database.fetch_all('SELECT * FROM staff_payslips ORDER BY employee_id')
        self.assertEqual({s['employee_id'] for s in slips}, {self.employee, self.second})
        self.assertEqual({r['shift_id'] for r in database.fetch_all('SELECT shift_id FROM staff_payslip_shifts')}, {first, second})
        page = self.manager.get(response.location).get_data(as_text=True)
        for text in ('Alex', 'Blair', 'Shift not approved (pending)', 'Shift not approved (rejected)',
                     'Shift still open', 'No payable minutes after breaks', '2 employees included automatically'):
            self.assertIn(text, page)
        self.assertEqual(database.fetch_one('SELECT COUNT(*) AS n FROM staff_payroll_calculations')['n'], 2)
        self.generate()
        self.assertEqual(database.fetch_one('SELECT COUNT(*) AS n FROM staff_payroll_runs')['n'], 1)

    def test_missing_profile_rolls_back_every_employee(self):
        self.profile()
        self.shift(); self.shift(employee=self.second)
        self.generate()
        self.assertFalse(database.fetch_all('SELECT id FROM staff_payroll_runs'))
        self.assertFalse(database.fetch_all('SELECT shift_id FROM staff_payslip_shifts'))
        self.assertIn(b'Blair', self.manager.get('/staff/alpha/payroll').data)

    def test_other_frequency_excluded_and_defaults_reused_without_tax_defaults(self):
        values = self.profile()
        initial = self.manager.get('/staff/alpha/payroll').get_data(as_text=True)
        self.assertIn('value="monthly" selected', initial)
        self.assertNotIn('value="Alpha Limited"', initial)
        self.post(self.manager, f'payroll/profiles/{self.second}', {**values, 'frequency': 'weekly'})
        self.shift(); other = self.shift(employee=self.second)
        self.generate()
        run = database.fetch_one('SELECT * FROM staff_payroll_runs')
        self.assertFalse(database.fetch_all('SELECT * FROM staff_payslip_shifts WHERE shift_id=%s', (other,)))
        page = self.manager.get(f"/staff/alpha/payroll/{run['id']}").get_data(as_text=True)
        self.assertIn('Different reviewed pay frequency: weekly', page)
        settings = self.manager.get('/staff/alpha/payroll').get_data(as_text=True)
        self.assertIn('value="Alpha Limited"', settings)
        self.assertIn('value="monthly" selected', settings)
        self.assertEqual(self.manager.get('/staff/beta/payroll').status_code,404)
        # Explicit multi-business membership is required before checking Beta defaults.
        database.execute("INSERT INTO sm_memberships(administrator_id,business_id) VALUES ('test-manager','beta')")
        fresh = self.manager.get('/staff/beta/payroll').get_data(as_text=True)
        self.assertNotIn('value="Alpha Limited"', fresh)
        self.assertIn('Select pay frequency', fresh)

    def test_existing_allocation_remains_excluded_from_overlapping_period(self):
        self.profile(); first = self.shift(); self.generate()
        run = database.fetch_one('SELECT * FROM staff_payroll_runs')
        self.post(self.manager, f"payroll/{run['id']}/approve")
        second = self.shift('2026-05-02')
        response = self.generate('2026-04-15', '2026-05-31', '2026-05-31')
        self.assertEqual(database.fetch_one('SELECT COUNT(*) AS n FROM staff_payroll_runs')['n'], 2)
        allocated = database.fetch_all('SELECT shift_id FROM staff_payslip_shifts')
        self.assertEqual({r['shift_id'] for r in allocated}, {first, second})
        self.assertIn(b'Already allocated to another payroll run', self.manager.get(response.location).data)

    def test_fully_unpaid_shift_excluded_without_requiring_unused_tax_profile(self):
        self.profile(); self.shift()
        unpaid = self.shift(employee=self.second)
        database.execute("""INSERT INTO staff_breaks(business_id,shift_id,employee_id,started_at,ended_at,paid)
            SELECT business_id,id,employee_id,clock_in_at,clock_out_at,FALSE FROM staff_shifts WHERE id=%s""", (unpaid,))
        response = self.generate()
        self.assertEqual(database.fetch_one('SELECT COUNT(*) AS n FROM staff_payslips')['n'], 1)
        self.assertFalse(database.fetch_all('SELECT * FROM staff_payslip_shifts WHERE shift_id=%s', (unpaid,)))
        self.assertIn(b'No payable minutes after breaks', self.manager.get(response.location).data)
