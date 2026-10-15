"""Checkout parameter regression; no database or Stripe requests."""
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from test_staff_billing import ENV, FakeStripe
from trimtech.modules.staff import billing
from trimtech.modules.staff import stripe_gateway as transport


class CheckoutTaxTests(unittest.TestCase):
    def test_unregistered_staff_checkout_preserves_billing_parameters(self):
        fake = FakeStripe()
        gateway = MagicMock(wraps=fake)
        account = {'customer_id': 'cus_staff', 'livemode': False}
        attempt = {'id': 'attempt', 'status': 'creating', 'session_id': None,
                   'price_id': 'price_staff', 'product_id': 'prod_staff',
                   'return_url': 'https://staff.example.test/staff/alpha/subscription',
                   'expires_at': datetime.now(timezone.utc) + timedelta(hours=1)}
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.side_effect = [attempt, attempt]
        with patch.dict('os.environ', ENV), \
                patch.object(billing, 'Gateway', return_value=gateway), \
                patch.object(billing, 'transaction') as transaction, \
                patch.object(billing, '_prepare_account'), \
                patch.object(billing, '_lock', return_value=account), \
                patch.object(billing, '_refresh_locked', return_value=[]), \
                patch.object(billing, '_sync_checkout'), \
                patch('psycopg2.connect', side_effect=AssertionError('No database allowed')), \
                patch.object(transport.stripe, 'StripeClient', side_effect=AssertionError('No Stripe calls allowed')):
            transaction.return_value.__enter__.return_value = connection
            self.assertTrue(billing.checkout('alpha', 'owner').startswith('https://checkout.stripe.com/'))
        params, key = gateway.create_checkout.call_args.args
        self.assertEqual(params['automatic_tax'], {'enabled': False})
        self.assertEqual(params['mode'], 'subscription')
        self.assertEqual(params['line_items'], [{'price': 'price_staff', 'quantity': 1}])
        self.assertEqual(params['subscription_data'], {'metadata': params['metadata']})
        self.assertEqual(params['metadata']['application'], transport.APPLICATION)
        self.assertEqual(params['billing_address_collection'], 'required')
        self.assertEqual(params['customer_update'], {'address': 'auto', 'name': 'auto'})
        self.assertEqual(params['payment_method_collection'], 'always')
        self.assertEqual(key, 'staff-checkout-attempt')
        self.assertNotIn('tax_rates', params['line_items'][0])
        self.assertNotIn('default_tax_rates', params['subscription_data'])


if __name__ == '__main__':
    unittest.main()
