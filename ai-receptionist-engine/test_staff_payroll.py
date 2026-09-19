from datetime import date, datetime, timezone
from decimal import Decimal
import unittest

from trimtech.modules.staff.payroll import calculate_shift_pay, shift_is_eligible


class StaffPayrollTests(unittest.TestCase):
    def setUp(self):
        self.shift = {
            "id": 41,
            "employee_id": 7,
            "clock_in_at": datetime(2026, 9, 14, 9, tzinfo=timezone.utc),
            "clock_out_at": datetime(2026, 9, 14, 17, tzinfo=timezone.utc),
            "approval_status": "approved",
            "hourly_rate": Decimal("15.00"),
        }

    def test_only_completed_approved_unclaimed_shifts_are_eligible(self):
        period = (date(2026, 9, 14), date(2026, 9, 20))
        self.assertTrue(shift_is_eligible(self.shift, *period))
        self.assertFalse(shift_is_eligible({**self.shift, "approval_status": "pending"}, *period))
        self.assertFalse(shift_is_eligible({**self.shift, "clock_out_at": None}, *period))
        self.assertFalse(shift_is_eligible(self.shift, *period, claimed_shift_ids={41}))

    def test_unpaid_break_reduces_payable_minutes_and_gross_pay(self):
        result = calculate_shift_pay(
            self.shift,
            [{
                "started_at": datetime(2026, 9, 14, 12, tzinfo=timezone.utc),
                "ended_at": datetime(2026, 9, 14, 12, 30, tzinfo=timezone.utc),
                "paid": False,
            }],
        )
        self.assertEqual(result.worked_minutes, 480)
        self.assertEqual(result.paid_break_minutes, 0)
        self.assertEqual(result.unpaid_break_minutes, 30)
        self.assertEqual(result.payable_minutes, 450)
        self.assertEqual(result.gross_pay, Decimal("112.50"))
        self.assertEqual(result.net_pay, Decimal("112.50"))

    def test_paid_break_does_not_reduce_payable_minutes(self):
        result = calculate_shift_pay(
            self.shift,
            [{
                "started_at": datetime(2026, 9, 14, 12, tzinfo=timezone.utc),
                "ended_at": datetime(2026, 9, 14, 12, 30, tzinfo=timezone.utc),
                "paid": True,
            }],
        )
        self.assertEqual(result.worked_minutes, 480)
        self.assertEqual(result.paid_break_minutes, 30)
        self.assertEqual(result.unpaid_break_minutes, 0)
        self.assertEqual(result.payable_minutes, 480)
        self.assertEqual(result.gross_pay, Decimal("120.00"))


if __name__ == "__main__":
    unittest.main()