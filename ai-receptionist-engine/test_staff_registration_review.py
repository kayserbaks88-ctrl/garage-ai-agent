"""Staff registration review rules and administrator notification behavior."""
import os
import unittest
from unittest.mock import MagicMock, patch

from trimtech.modules.staff import registration_review as review


class RegistrationReviewRuleTests(unittest.TestCase):
    def setUp(self):
        self.facts = {
            'legacy': False,
            'owner_verified': False,
            'has_billing': False,
            'has_checkout': False,
            'has_grant': False,
            'has_employees': False,
            'has_shifts': False,
            'has_setup': False,
        }

    def test_only_unverified_unused_trial_businesses_are_candidates(self):
        self.assertEqual(review.protection_reasons(self.facts), [])
        for key in ('legacy', 'owner_verified', 'has_billing', 'has_checkout',
                    'has_grant', 'has_employees', 'has_shifts', 'has_setup'):
            with self.subTest(key=key):
                self.assertTrue(review.protection_reasons({**self.facts, key: True}))

    def test_owner_email_is_masked(self):
        self.assertEqual(review.mask_email('owner@example.test'), 'o***@example.test')
        self.assertEqual(review.mask_email('invalid'), 'unknown')

    def test_ids_are_validated_deduplicated_and_capped(self):
        self.assertEqual(review.clean_ids(['business-1', 'business-1', 'business.2']), ['business-1', 'business.2'])
        for values in ([], ['bad id'], ['x' * 101]):
            with self.subTest(values=values), self.assertRaises(review.ReviewRefused):
                review.clean_ids(values)
        with self.assertRaises(review.ReviewRefused):
            review.clean_ids(['business-%d' % index for index in range(review.MAX_BATCH + 1)])

    def test_action_requires_reason_and_exact_count_confirmation(self):
        ids = ['business-1', 'business-2']
        with self.assertRaises(review.ReviewRefused):
            review.validate('delete', ids, 'reason', 'DELETE 2')
        with self.assertRaises(review.ReviewRefused):
            review.validate('deactivate', ids, '', 'DEACTIVATE 2')
        with self.assertRaises(review.ReviewRefused):
            review.validate('deactivate', ids, 'reason', 'DEACTIVATE 1')
        self.assertEqual(
            review.validate('deactivate', ids, ' reason ', 'DEACTIVATE 2'),
            (ids, 'reason'),
        )

    def test_notification_message_escapes_business_name_and_masks_owner(self):
        subject, text, body = review.build_message(
            {'id': 'business-1', 'name': '<script>bad</script>', 'verified': False, 'email': 'owner@example.test'},
            'registered',
            'https://staff.example.test',
        )
        self.assertNotIn('\n', subject)
        self.assertNotIn('\r', subject)
        self.assertIn('o***@example.test', text)
        self.assertIn('&lt;script&gt;', body)
        self.assertIn('https://staff.example.test/staff/platform/businesses/', body)
        self.assertNotIn('owner@example.test', body)


class RegistrationNotificationTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {
            'PLATFORM_ADMIN_NOTIFY_EMAIL': 'platform@example.test',
            'STAFF_PUBLIC_BASE_URL': 'https://staff.example.test',
            'PLATFORM_ADMIN_NOTIFY_VERIFIED': '1',
        }, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def transaction_manager(self, claimed=True):
        cursor = MagicMock()
        cursor.fetchone.return_value = (1,) if claimed else None
        connection = MagicMock()
        connection.cursor.return_value.__enter__.return_value = cursor
        manager = MagicMock()
        manager.__enter__.return_value = connection
        return manager, cursor

    def test_notice_is_sent_once_and_status_is_recorded(self):
        business = {'id': 'business-1', 'name': 'New business', 'email': 'owner@example.test', 'verified': False}
        manager, cursor = self.transaction_manager()
        with patch.object(review, 'fetch_one', return_value=business), \
             patch.object(review, 'transaction', return_value=manager), \
             patch.object(review, 'send_staff_email', return_value=(True, None, 'provider-id')) as send:
            result = review.notify('owner@example.test', 'registered')
        self.assertEqual(result, 'sent')
        send.assert_called_once()
        self.assertEqual(send.call_args.args[0], 'platform@example.test')
        self.assertEqual(cursor.execute.call_count, 2)
        self.assertIn('INSERT INTO sr_registration_notices', cursor.execute.call_args_list[0].args[0])
        self.assertIn('UPDATE sr_registration_notices', cursor.execute.call_args_list[1].args[0])

    def test_duplicate_notice_is_not_sent_again(self):
        manager, _ = self.transaction_manager(claimed=False)
        with patch.object(review, 'fetch_one', return_value={
            'id': 'business-1', 'name': 'New business', 'email': 'owner@example.test', 'verified': False,
        }), patch.object(review, 'transaction', return_value=manager), \
             patch.object(review, 'send_staff_email') as send:
            self.assertEqual(review.notify('owner@example.test'), 'duplicate')
        send.assert_not_called()

    def test_delivery_failure_is_recorded_and_not_sent_twice(self):
        business = {'id': 'business-1', 'name': 'New business', 'email': 'owner@example.test', 'verified': False}
        manager, cursor = self.transaction_manager()
        with patch.object(review, 'fetch_one', return_value=business), \
             patch.object(review, 'transaction', return_value=manager), \
             patch.object(review, 'send_staff_email', return_value=(False, 'provider_http_503', None)) as send:
            self.assertEqual(review.notify('owner@example.test'), 'failed')
        self.assertEqual(cursor.execute.call_count, 2)
        self.assertIn("SET status=%s", cursor.execute.call_args_list[1].args[0])
        self.assertEqual(cursor.execute.call_args_list[1].args[1][0], 'failed')
        send.assert_called_once()

    def test_verified_notifications_are_opt_in(self):
        with patch.dict(os.environ, {'PLATFORM_ADMIN_NOTIFY_VERIFIED': '0'}), \
             patch.object(review, 'fetch_one') as fetch:
            self.assertEqual(review.notify('owner@example.test', 'verified'), 'disabled')
        fetch.assert_not_called()

    def test_notification_is_inert_when_no_recipient_is_configured(self):
        with patch.dict(os.environ, {'PLATFORM_ADMIN_NOTIFY_EMAIL': ''}), \
             patch.object(review, 'fetch_one') as fetch:
            self.assertEqual(review.notify('owner@example.test'), 'not_configured')
        fetch.assert_not_called()


if __name__ == '__main__':
    unittest.main()
