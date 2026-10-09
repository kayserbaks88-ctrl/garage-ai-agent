"""Business-scoped subscription state. External writes only follow owner Checkout/Portal POSTs."""
import logging
import uuid
from datetime import datetime, timezone
from urllib.parse import quote

from psycopg2.extras import RealDictCursor

from trimtech.modules.staff import billing_migration
from trimtech.modules.staff.database import fetch_all, fetch_one, transaction
from trimtech.modules.staff.stripe_gateway import (
    APPLICATION, BillingUnavailable, Gateway, configuration, identifier, safe_url,
)

logger = logging.getLogger(__name__)
TERMINAL = {'canceled', 'incomplete_expired'}
STATUSES = {'active','trialing','past_due','unpaid','canceled','incomplete','incomplete_expired','paused'}
EVENTS = {'checkout.session.completed','checkout.session.expired','checkout.session.async_payment_succeeded',
          'checkout.session.async_payment_failed','customer.subscription.created','customer.subscription.updated',
          'customer.subscription.deleted','customer.subscription.paused','customer.subscription.resumed',
          'invoice.paid','invoice.payment_failed','invoice.payment_action_required',
          'invoice.marked_uncollectible','invoice.voided','invoice.finalization_failed'}


def entitlement(business_id):
    """No network requests in authentication. Paid access is bounded by a verified paid invoice period."""
    return fetch_one("""SELECT EXISTS(SELECT 1 FROM sb_subscriptions WHERE business_id=%s) AS managed,
        EXISTS(SELECT 1 FROM sb_subscriptions WHERE business_id=%s AND status='active'
               AND paid_until>NOW()) AS paid""", (business_id,business_id))


def summary(business_id):
    rows = fetch_all('SELECT status,cancel_at_period_end,period_end,paid_until,invoice_status FROM sb_subscriptions WHERE business_id=%s ORDER BY verified_at DESC,id', (business_id,))
    customer = fetch_one('SELECT customer_id IS NOT NULL AS present FROM sb_accounts WHERE business_id=%s', (business_id,))
    pending = fetch_one("SELECT status FROM sb_checkouts WHERE business_id=%s AND status IN ('creating','open')", (business_id,))
    return dict(subscriptions=rows, customer=bool(customer and customer['present']), pending=pending,
                **entitlement(business_id))


def _scope(account, config):
    if account['stripe_account_id'] != config.account or account['livemode'] != config.live:
        raise BillingUnavailable('Billing account configuration has changed. Please contact TrimTech.')


def _customer_scope(value, account):
    meta = value.get('metadata') or {}
    if (not value.get('id') or value.get('deleted') or value.get('livemode') != account['livemode']
            or meta.get('application') != APPLICATION or meta.get('business_id') != account['business_id']):
        raise BillingUnavailable('This billing customer could not be verified.')


def _timestamp(value):
    if type(value) is not int or value <= 0:
        return None
    try:
        return datetime.fromtimestamp(value, timezone.utc)
    except (ValueError, OverflowError, OSError):
        return None


def invoice_subscription(invoice):
    return identifier(invoice.get('subscription') or ((invoice.get('parent') or {}).get('subscription_details') or {}).get('subscription'))


def _sync_subscription(cursor, gateway, account, subscription_id):
    """Retrieve AFTER the business lock, so old/out-of-order events cannot overwrite a newer snapshot."""
    subscription = gateway.subscription(subscription_id)
    meta = subscription.get('metadata') or {}
    if (subscription.get('id') != subscription_id or subscription.get('livemode') != account['livemode']
            or identifier(subscription.get('customer')) != account['customer_id']
            or meta.get('application') != APPLICATION or meta.get('business_id') != account['business_id']):
        raise BillingUnavailable('Subscription ownership could not be verified.')
    cursor.execute('SELECT * FROM sb_checkouts WHERE id=%s AND business_id=%s', (meta.get('checkout_attempt'),account['business_id']))
    attempt = cursor.fetchone()
    if not attempt:
        raise BillingUnavailable('Subscription checkout could not be verified.')
    cursor.execute('SELECT id FROM sb_subscriptions WHERE checkout_id=%s', (attempt['id'],))
    previous = cursor.fetchone()
    if previous and previous['id'] != subscription_id:
        raise BillingUnavailable('More than one subscription was reported for this checkout.')
    items = subscription.get('items') or {}
    lines = items.get('data') or []
    item = lines[0] if len(lines) == 1 else {}
    price = item.get('price') or {}
    valid = (not items.get('has_more') and len(lines) == 1 and item.get('quantity') == 1
             and price.get('id') == attempt['price_id'] and identifier(price.get('product')) == attempt['product_id']
             and not subscription.get('transfer_data') and not subscription.get('on_behalf_of')
             and not subscription.get('application_fee_percent') and subscription.get('collection_method') == 'charge_automatically')
    state = subscription.get('status') if subscription.get('status') in STATUSES and valid else 'invalid'
    if subscription.get('pause_collection'):
        state = 'paused'
    end = _timestamp(item.get('current_period_end') or subscription.get('current_period_end'))
    invoice = subscription.get('latest_invoice')
    paid_until = None
    invoice_id = None
    invoice_status = None
    if isinstance(invoice, dict):
        invoice_id, invoice_status = invoice.get('id'), invoice.get('status')
        invoice_lines = invoice.get('lines') or {}
        if (valid and invoice_status == 'paid' and invoice.get('amount_remaining') == 0
                and invoice_subscription(invoice) == subscription_id
                and identifier(invoice.get('customer')) == account['customer_id']
                and invoice.get('livemode') == account['livemode'] and not invoice_lines.get('has_more')):
            ends = []
            for line in invoice_lines.get('data', []):
                line_price = identifier(line.get('price')) or ((line.get('pricing') or {}).get('price_details') or {}).get('price')
                period = _timestamp((line.get('period') or {}).get('end'))
                if line_price == attempt['price_id'] and period and end:
                    ends.append(min(period,end))
            if ends:
                paid_until = max(ends)
    cursor.execute("""INSERT INTO sb_subscriptions(id,business_id,checkout_id,status,cancel_at_period_end,
        period_end,paid_until,latest_invoice_id,invoice_status) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT(id) DO UPDATE SET status=EXCLUDED.status,cancel_at_period_end=EXCLUDED.cancel_at_period_end,
        period_end=EXCLUDED.period_end,paid_until=EXCLUDED.paid_until,latest_invoice_id=EXCLUDED.latest_invoice_id,
        invoice_status=EXCLUDED.invoice_status,verified_at=NOW()
        WHERE sb_subscriptions.business_id=EXCLUDED.business_id AND sb_subscriptions.checkout_id=EXCLUDED.checkout_id""",
        (subscription_id,account['business_id'],attempt['id'],state,bool(subscription.get('cancel_at_period_end')),
         end,paid_until,invoice_id,invoice_status))
    if cursor.rowcount != 1:
        raise BillingUnavailable('Subscription ownership conflicts with an existing record.')
    cursor.execute("UPDATE sb_checkouts SET status='complete' WHERE id=%s", (attempt['id'],))
    return state


def _list(values):
    # Do not make a partial list look authoritative when checking customer isolation.
    if values.get('has_more'):
        raise BillingUnavailable('Billing history needs review. Please contact TrimTech.')
    return values.get('data', [])


def _refresh_locked(cursor, gateway, account):
    _customer_scope(gateway.customer(account['customer_id']), account)
    current_ids = set()
    for value in _list(gateway.subscriptions(account['customer_id'])):
        current_ids.add(value['id'])
    cursor.execute('SELECT id FROM sb_subscriptions WHERE business_id=%s', (account['business_id'],))
    current_ids.update(row['id'] for row in cursor.fetchall())
    states = [_sync_subscription(cursor,gateway,account,key) for key in sorted(current_ids)]
    return states


def _prepare_account(business_id, administrator_id, config):
    # Durable before external creation: a lost API/DB response cannot lose the idempotency key.
    with transaction() as connection:
        with connection.cursor() as cursor:
            billing_migration.verify(cursor)
            cursor.execute("""INSERT INTO sb_accounts(business_id,stripe_account_id,livemode,customer_key,customer_name,customer_email)
                SELECT b.id,%s,%s,%s,b.name,a.email FROM sm_businesses b JOIN sm_memberships m ON m.business_id=b.id
                JOIN sm_administrators a ON a.id=m.administrator_id WHERE b.id=%s AND a.id=%s
                AND b.active AND m.active AND m.role='owner' AND a.active AND a.verified_at IS NOT NULL
                ON CONFLICT(business_id) DO NOTHING""", (config.account,config.live,uuid.uuid4().hex,business_id,administrator_id))


def _lock(cursor, business_id, config):
    cursor.execute('SELECT * FROM sb_accounts WHERE business_id=%s FOR UPDATE', (business_id,))
    account = cursor.fetchone()
    if not account:
        raise BillingUnavailable('No billing account is available for this business.')
    _scope(account,config)
    return account


def checkout(business_id, administrator_id):
    config = configuration()
    gateway = Gateway(config)
    gateway.merchant()
    price = gateway.price()
    _prepare_account(business_id,administrator_id,config)
    with transaction() as connection:
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            account = _lock(cursor,business_id,config)
            if not account['customer_id']:
                if (datetime.now(timezone.utc)-account['customer_requested_at']).total_seconds() > 23*3600:
                    raise BillingUnavailable('A previous billing request needs reconciliation. Please contact TrimTech before trying again.')
                customer = gateway.create_customer(business_id,account['customer_name'],account['customer_email'],
                                                   'staff-customer-'+account['customer_key'])
                _customer_scope(customer,account)
                account['customer_id'] = customer['id']
                cursor.execute('UPDATE sb_accounts SET customer_id=%s WHERE business_id=%s', (customer['id'],business_id))
            states = _refresh_locked(cursor,gateway,account)
            if any(state not in TERMINAL for state in states):
                # Commit the authoritative refresh, then show the owner their existing subscription.
                return None
            cursor.execute("SELECT * FROM sb_checkouts WHERE business_id=%s AND status IN ('creating','open')", (business_id,))
            attempt = cursor.fetchone()
            if attempt and attempt['price_id'] != price['id']:
                raise BillingUnavailable('An earlier checkout uses a different price. Please contact TrimTech before starting another.')
            if not attempt:
                cursor.execute("""INSERT INTO sb_checkouts(id,business_id,actor_id,price_id,product_id,return_url,expires_at)
                    VALUES (%s,%s,%s,%s,%s,%s,date_trunc('second',NOW())+INTERVAL '1 hour') RETURNING *""",
                    (uuid.uuid4().hex,business_id,administrator_id,price['id'],price['product'],
                     config.base_url+'/staff/'+quote(business_id,safe='')+'/subscription'))
                attempt = cursor.fetchone()
    # Intent is committed before the Checkout API call. The same attempt is reused on retries.
    with transaction() as connection:
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            account = _lock(cursor,business_id,config)
            cursor.execute('SELECT * FROM sb_checkouts WHERE id=%s', (attempt['id'],))
            attempt = cursor.fetchone()
            if attempt['status'] in ('complete','expired'):
                return None
            if not attempt['session_id']:
                matches = [value for value in _list(gateway.checkouts(account['customer_id']))
                           if (value.get('metadata') or {}).get('checkout_attempt') == attempt['id']]
                if len(matches) > 1:
                    raise BillingUnavailable('Checkout needs reconciliation. Please contact TrimTech.')
                if matches:
                    session = gateway.checkout(matches[0]['id'])
                else:
                    if attempt['expires_at'] <= datetime.now(timezone.utc):
                        raise BillingUnavailable('A previous checkout could not be confirmed. Please contact TrimTech before starting another.')
                    metadata = {'application':APPLICATION,'business_id':business_id,'checkout_attempt':attempt['id']}
                    session = gateway.create_checkout({'mode':'subscription','customer':account['customer_id'],
                        'line_items':[{'price':attempt['price_id'],'quantity':1}],
                        'payment_method_types':['card'],'payment_method_collection':'always',
                        'success_url':attempt['return_url']+'?checkout=returned','cancel_url':attempt['return_url']+'?checkout=cancelled',
                        'client_reference_id':business_id,'metadata':metadata,'subscription_data':{'metadata':metadata},
                        'expires_at':int(attempt['expires_at'].timestamp()),'locale':'en-GB',
                        'automatic_tax':{'enabled':True},'billing_address_collection':'required',
                        'customer_update':{'address':'auto','name':'auto'}}, 'staff-checkout-'+attempt['id'])
            else:
                session = gateway.checkout(attempt['session_id'])
            _sync_checkout(cursor,gateway,account,attempt,session)
            return safe_url(session.get('url'),'checkout.stripe.com') if session.get('status') == 'open' else None


def _sync_checkout(cursor,gateway,account,attempt,value):
    meta = value.get('metadata') or {}
    if (value.get('livemode') != account['livemode'] or identifier(value.get('customer')) != account['customer_id']
            or meta.get('application') != APPLICATION or meta.get('business_id') != account['business_id']
            or meta.get('checkout_attempt') != attempt['id'] or value.get('mode') != 'subscription'
            or (attempt['session_id'] and attempt['session_id'] != value.get('id'))):
        raise BillingUnavailable('Checkout ownership could not be verified.')
    state = value.get('status')
    if state not in ('open','complete','expired') or not value.get('id'):
        raise BillingUnavailable('Checkout status could not be verified.')
    cursor.execute('UPDATE sb_checkouts SET session_id=%s,status=%s WHERE id=%s', (value['id'],state,attempt['id']))
    if state == 'complete' and identifier(value.get('subscription')):
        _sync_subscription(cursor,gateway,account,identifier(value['subscription']))


def refresh(business_id):
    config = configuration()
    gateway = Gateway(config)
    gateway.merchant()
    with transaction() as connection:
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            account = _lock(cursor,business_id,config)
            if account['customer_id']:
                _refresh_locked(cursor,gateway,account)
                cursor.execute("SELECT * FROM sb_checkouts WHERE business_id=%s AND status IN ('creating','open')", (business_id,))
                attempt = cursor.fetchone()
                if attempt:
                    if attempt['session_id']:
                        _sync_checkout(cursor,gateway,account,attempt,gateway.checkout(attempt['session_id']))
                    else:
                        for value in _list(gateway.checkouts(account['customer_id'])):
                            if (value.get('metadata') or {}).get('checkout_attempt') == attempt['id']:
                                _sync_checkout(cursor,gateway,account,attempt,gateway.checkout(value['id']))


def portal(business_id):
    config = configuration()
    gateway = Gateway(config)
    gateway.merchant()
    with transaction() as connection:
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            account = _lock(cursor,business_id,config)
            if not account['customer_id']:
                raise BillingUnavailable('Start a subscription before opening billing management.')
            _customer_scope(gateway.customer(account['customer_id']),account)
            subscriptions = _list(gateway.subscriptions(account['customer_id']))
            ids = set()
            for value in subscriptions:
                meta = value.get('metadata') or {}
                if meta.get('application') != APPLICATION or meta.get('business_id') != business_id:
                    raise BillingUnavailable('This customer contains unrelated subscriptions. Please contact TrimTech.')
                ids.add(value['id'])
            # A portal session must not show another product's client invoices or balances.
            if any(invoice_subscription(value) not in ids for value in _list(gateway.invoices(account['customer_id']))):
                raise BillingUnavailable('This customer contains unrelated invoices. Please contact TrimTech.')
            setting = gateway.portal_configuration()
            features = setting.get('features') or {}
            cancel = features.get('subscription_cancel') or {}
            if (not setting.get('active') or setting.get('livemode') != config.live
                    or setting.get('metadata',{}).get('application') != APPLICATION
                    or setting.get('login_page',{}).get('enabled')
                    or not features.get('payment_method_update',{}).get('enabled')
                    or not cancel.get('enabled') or cancel.get('mode') != 'at_period_end'
                    or features.get('subscription_update',{}).get('enabled')
                    or features.get('customer_update',{}).get('enabled')
                    or features.get('invoice_history',{}).get('enabled')):
                raise BillingUnavailable('The Staff billing portal configuration needs review.')
            result = gateway.create_portal(account['customer_id'],config.base_url+'/staff/'+quote(business_id,safe='')+'/subscription')
            return safe_url(result.get('url'),'billing.stripe.com')


def process_event(event, config):
    """Process only our persisted customer/Checkout bindings; no trust in browser-provided IDs."""
    if (event.get('type') not in EVENTS or event.get('livemode') != config.live or event.get('account')
            or event.get('context') not in (None,config.account)):
        return 'ignored'
    value = (event.get('data') or {}).get('object') or {}
    customer = identifier(value.get('customer'))
    account = fetch_one('SELECT business_id FROM sb_accounts WHERE customer_id=%s AND stripe_account_id=%s AND livemode=%s',
                        (customer,config.account,config.live))
    if not account:
        return 'ignored'
    if not event.get('id') or not value.get('id'):
        raise ValueError('Invalid event envelope')
    gateway = Gateway(config)
    with transaction() as connection:
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            account = _lock(cursor,account['business_id'],config)
            cursor.execute('INSERT INTO sb_events(id,business_id,event_type,object_id) VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING id',
                           (event['id'],account['business_id'],event['type'],value['id']))
            if not cursor.fetchone():
                return 'duplicate'
            gateway.merchant()
            if event['type'].startswith('checkout.session.'):
                cursor.execute('SELECT * FROM sb_checkouts WHERE business_id=%s AND (session_id=%s OR id=%s)',
                               (account['business_id'],value['id'],(value.get('metadata') or {}).get('checkout_attempt')))
                attempt = cursor.fetchone()
                if not attempt:
                    return 'ignored'
                _sync_checkout(cursor,gateway,account,attempt,gateway.checkout(value['id']))
            else:
                subscription_id = value['id'] if event['type'].startswith('customer.subscription.') else invoice_subscription(value)
                if not subscription_id:
                    return 'ignored'
                _sync_subscription(cursor,gateway,account,subscription_id)
    logger.info('Staff billing webhook processed: event=%s',event['id'])
    return 'processed'
