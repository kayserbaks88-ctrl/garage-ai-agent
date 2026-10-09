"""Staff-only Stripe client. No global keys, Connect transfers or arbitrary prices."""
import os
import re
from dataclasses import dataclass
from decimal import Decimal
from urllib.parse import urlsplit

import stripe

APPLICATION = 'trimtech_staff_manager'
MERCHANT = 'TrimTech AI LTD'


class BillingUnavailable(RuntimeError):
    """Safe generic failure; never expose provider exception messages or keys."""


@dataclass(frozen=True, repr=False)
class Configuration:
    secret: str
    webhook_secret: str
    account: str
    price: str
    product: str
    portal: str
    base_url: str
    live: bool


def configuration():
    if os.getenv('STAFF_STRIPE_ENABLED', '0') != '1':
        raise BillingUnavailable('Online billing is not available yet.')
    values = {key: os.getenv('STAFF_STRIPE_'+key, '').strip() for key in
              ('SECRET_KEY', 'WEBHOOK_SECRET', 'ACCOUNT_ID', 'PRICE_ID', 'PRODUCT_ID', 'PORTAL_CONFIGURATION_ID', 'MODE')}
    base = os.getenv('STAFF_PUBLIC_BASE_URL', '').strip().rstrip('/')
    parsed = urlsplit(base)
    mode = values['MODE']
    if (mode not in ('test', 'live') or not re.fullmatch(r'(sk|rk)_'+mode+r'_[A-Za-z0-9]+', values['SECRET_KEY'])
            or not values['WEBHOOK_SECRET'].startswith('whsec_')
            or parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.path not in ('', '/')):
        raise BillingUnavailable('Online billing needs configuration. Please try again later.')
    for key, prefix in (('ACCOUNT_ID','acct_'),('PRICE_ID','price_'),('PRODUCT_ID','prod_'),('PORTAL_CONFIGURATION_ID','bpc_')):
        if not re.fullmatch(prefix+r'[A-Za-z0-9]+', values[key]):
            raise BillingUnavailable('Online billing needs configuration. Please try again later.')
    return Configuration(values['SECRET_KEY'], values['WEBHOOK_SECRET'], values['ACCOUNT_ID'],
                         values['PRICE_ID'], values['PRODUCT_ID'], values['PORTAL_CONFIGURATION_ID'], base, mode == 'live')


def identifier(value):
    return value.get('id') if isinstance(value, dict) else value


def safe_url(value, hostname):
    parsed = urlsplit(value or '')
    if parsed.scheme != 'https' or parsed.hostname != hostname or parsed.username or parsed.password or parsed.port not in (None,443):
        raise BillingUnavailable('Stripe did not return a valid billing link. Please try again.')
    return value


class Gateway:
    def __init__(self, config):
        self.config = config
        # Isolated client options; never changes any other integration's Stripe configuration.
        self.client = stripe.StripeClient(config.secret, max_network_retries=0,
            http_client=stripe.RequestsClient(timeout=8))

    def merchant(self):
        account = self.client.v1.accounts.retrieve_current().to_dict()
        legal_name = ' '.join((account.get('company', {}).get('name') or '').upper().split())
        if account['id'] != self.config.account or legal_name != MERCHANT.upper() or not account.get('charges_enabled'):
            raise BillingUnavailable('The TrimTech billing account has not been verified.')

    def price(self):
        value = self.client.v1.prices.retrieve(self.config.price, {'expand':['product']}).to_dict()
        product = value.get('product') or {}
        recurring = value.get('recurring') or {}
        if (not value.get('active') or value.get('livemode') != self.config.live or value.get('currency') != 'gbp'
                or not isinstance(product,dict) or product.get('id') != self.config.product or not product.get('active')
                or product.get('metadata',{}).get('application') != APPLICATION
                or value.get('type') != 'recurring' or value.get('billing_scheme') != 'per_unit'
                or type(value.get('unit_amount')) is not int or value['unit_amount'] <= 0
                or value.get('transform_quantity') or recurring.get('usage_type') != 'licensed'
                or recurring.get('interval') not in ('month','year') or recurring.get('interval_count') != 1
                or recurring.get('trial_period_days') or value.get('tax_behavior') not in ('inclusive','exclusive')):
            raise BillingUnavailable('The Staff Manager subscription price has not been verified.')
        return dict(id=value['id'], product=product['id'], amount=f"{Decimal(value['unit_amount'])/100:.2f}",
                    interval=recurring['interval'], tax_behavior=value['tax_behavior'])

    def customer(self, customer_id):
        return self.client.v1.customers.retrieve(customer_id).to_dict()

    def create_customer(self, business, name, email, key):
        return self.client.v1.customers.create({'name':name,'email':email,
            'metadata':{'application':APPLICATION,'business_id':business}},
            {'idempotency_key':key}).to_dict()

    def create_checkout(self, params, key):
        return self.client.v1.checkout.sessions.create(params, {'idempotency_key':key}).to_dict()

    def checkout(self, session_id):
        return self.client.v1.checkout.sessions.retrieve(session_id).to_dict()

    def checkouts(self, customer):
        return self.client.v1.checkout.sessions.list({'customer':customer,'limit':100}).to_dict()

    def subscription(self, subscription_id):
        return self.client.v1.subscriptions.retrieve(subscription_id, {'expand':['latest_invoice']}).to_dict()

    def subscriptions(self, customer):
        return self.client.v1.subscriptions.list({'customer':customer,'status':'all','limit':100}).to_dict()

    def invoices(self, customer):
        return self.client.v1.invoices.list({'customer':customer,'limit':100}).to_dict()

    def portal_configuration(self):
        return self.client.v1.billing_portal.configurations.retrieve(self.config.portal).to_dict()

    def create_portal(self, customer, return_url):
        return self.client.v1.billing_portal.sessions.create({'customer':customer,
            'configuration':self.config.portal,'return_url':return_url,'locale':'en-GB'}).to_dict()


def verified_event(raw, signature, config):
    # The SDK verifies the unmodified raw body and a five-minute timestamp tolerance.
    return stripe.Webhook.construct_event(raw, signature, config.webhook_secret, tolerance=300).to_dict()
