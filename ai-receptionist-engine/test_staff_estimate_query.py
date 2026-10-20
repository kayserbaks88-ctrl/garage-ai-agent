"""Estimate-query scope stays identical while filtering the indexed shift side."""
import os
import unittest

import test_staff_agency as fixtures
from trimtech.modules.staff import database, wages_estimate


@unittest.skipUnless(os.getenv('STAFF_TEST_DATABASE_URL'), 'Requires disposable PostgreSQL')
class EstimateQueryTests(unittest.TestCase):
    for name in ['setUp', 'cleanup_schema', 'connect', 'insert', 'client', 'post', 'row']:
        locals()[name] = getattr(fixtures.AgencyDatabaseTests, name)

    def test_approved_estimate_excludes_foreign_and_mismatched_breaks(self):
        shift = self.insert("""INSERT INTO staff_shifts(business_id,employee_id,site_id,site_name,
            clock_in_at,clock_out_at,approval_status) VALUES ('alpha',%s,%s,'Synthetic',
            NOW()-INTERVAL '2 hours',NOW()-INTERVAL '1 hour','approved') RETURNING id""", (self.employee, self.site))
        database.execute("""INSERT INTO staff_breaks(business_id,employee_id,shift_id,started_at,ended_at,paid)
            SELECT 'alpha',%s,%s,NOW()-INTERVAL '110 minutes',NOW()-INTERVAL '100 minutes',FALSE""", (self.employee, shift))
        before = wages_estimate.approved_weekly('alpha')
        for business, employee in [('beta',self.foreign_employee), ('alpha',self.second)]:
            database.execute("""INSERT INTO staff_breaks(business_id,employee_id,shift_id,started_at,ended_at,paid)
                SELECT %s,%s,%s,NOW()-INTERVAL '100 minutes',NOW()-INTERVAL '70 minutes',FALSE""", (business, employee, shift))
        self.assertEqual(wages_estimate.approved_weekly('alpha'), before)
        self.assertEqual(wages_estimate.approved_weekly('beta')['estimated_gross'], 0)

    def test_filtering_shift_side_preserves_original_break_rows(self):
        ids = [self.old_shift]
        database.execute("""INSERT INTO staff_breaks(business_id,employee_id,shift_id,started_at,ended_at,paid)
            SELECT 'alpha',%s,id,clock_in_at+INTERVAL '5 minutes',clock_in_at+INTERVAL '15 minutes',FALSE
            FROM staff_shifts WHERE id=%s AND business_id='alpha'""", (self.employee, self.old_shift))
        query = """SELECT b.shift_id,b.started_at,b.ended_at,b.paid FROM staff_breaks b
            JOIN staff_shifts s ON s.id=b.shift_id AND s.business_id=b.business_id AND s.employee_id=b.employee_id
            WHERE b.business_id=%s AND {filter} ORDER BY b.shift_id,b.started_at,b.id"""
        old = database.fetch_all(query.format(filter='b.shift_id=ANY(%s)'), ('alpha', ids))
        new = database.fetch_all(query.format(filter='s.id=ANY(%s::bigint[])'), ('alpha', ids))
        self.assertEqual(old, new)
        self.assertEqual(len(new), 1)
