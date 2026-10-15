"""Read-only approved estimate uses exactly the production payroll calculator."""
import unittest
from datetime import datetime,timedelta,timezone
from decimal import Decimal
from unittest.mock import patch
from trimtech.modules.staff import wages_estimate
from trimtech.modules.staff.payroll import calculate_shift_pay

class ApprovedEstimateRoundingTests(unittest.TestCase):
    def estimate(self,shifts,breaks):
        with patch.object(wages_estimate,'fetch_all',side_effect=[shifts,breaks] if shifts else [shifts]) as fetch,patch.object(wages_estimate,'fetch_one',side_effect=AssertionError('Raw seconds estimate must not run')):
            result=wages_estimate.weekly('local-business',approved_only=True)
        self.assertTrue(all(call.args[0].lstrip().startswith(('WITH','SELECT')) for call in fetch.call_args_list))
        self.assertEqual(fetch.call_args_list[0].args[1][1],'local-business')
        return result
    def shift(self,seconds,identifier=1,rate='12'):
        start=datetime(2026,10,13,10,tzinfo=timezone.utc)
        return dict(id=identifier,employee_id=identifier,approval_status='approved',hourly_rate=Decimal(rate),clock_in_at=start,clock_out_at=start+timedelta(seconds=seconds))
    def test_fractional_minutes_reproduce_818_and_match_payroll_820(self):
        shift=self.shift(2454) # 40m54s: old seconds-based estimate £8.18.
        self.assertEqual(Decimal('2454')/3600*12,Decimal('8.18'))
        self.assertEqual(calculate_shift_pay(shift,[]).payable_minutes,41)
        self.assertEqual(self.estimate([shift],[])['estimated_gross'],Decimal('8.20'))
    def test_break_rounding_merging_and_paid_treatment_match_payroll(self):
        shift=self.shift(3599.123456)
        start=shift['clock_in_at']
        breaks=[dict(shift_id=1,started_at=start,ended_at=start+timedelta(seconds=1145),paid=False),
                dict(shift_id=1,started_at=start+timedelta(seconds=600),ended_at=start+timedelta(seconds=1145),paid=False),
                dict(shift_id=1,started_at=start+timedelta(seconds=1800),ended_at=start+timedelta(seconds=2100),paid=True)]
        expected=calculate_shift_pay(shift,breaks)
        self.assertEqual(expected.payable_minutes,41)
        self.assertEqual(self.estimate([shift],breaks)['estimated_gross'],expected.gross_pay)
    def test_half_minute_boundary_and_microseconds(self):
        for seconds,minutes in [(29.999999,0),(30,1),(30.000001,1),(89.999999,1),(90,2)]:
            with self.subTest(seconds=seconds):
                shift=self.shift(seconds)
                self.assertEqual(calculate_shift_pay(shift,[]).payable_minutes,minutes)
                self.assertEqual(self.estimate([shift],[])['estimated_gross'],calculate_shift_pay(shift,[]).gross_pay)
    def test_per_shift_penny_rounding_not_rounding_week_total(self):
        shifts=[self.shift(60,i,'10') for i in (1,2,3)]
        self.assertEqual(self.estimate(shifts,[])['estimated_gross'],Decimal('.51'))
    def test_empty_week(self):
        self.assertEqual(self.estimate([],[])['estimated_gross'],Decimal('0.00'))
