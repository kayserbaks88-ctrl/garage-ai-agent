"""Audited Staff lifecycle actions; never reports a local request as provider cancellation."""
from psycopg2.extras import RealDictCursor
from trimtech.modules.staff import agency
from trimtech.modules.staff.database import transaction, fetch_one, fetch_all


def business(business_id):
    return fetch_one('SELECT id,name,active FROM sm_businesses WHERE id=%s', (business_id,))


def history(business_id):
    return fetch_all("SELECT id,action,actor,reason,created_at,new_values FROM staff_audit WHERE business_id=%s AND entity_type='subscription_management' ORDER BY id DESC LIMIT 50", (business_id,))


def change(business_id, actor, action, values, platform=False):
    reason = str(values.get('reason', '')).strip()
    if not reason or len(reason)>1000:
        raise ValueError('Enter a reason of up to 1000 characters.')
    if values.get('confirmation') != business_id:
        raise ValueError('Type the business ID to confirm this action.')
    allowed = {'request_cancellation','end_trial'}
    if platform:
        allowed |= {'review_request','deactivate','reactivate'}
    if action not in allowed:
        raise ValueError('Choose an available action.')
    with transaction() as connection:
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            agency.lock_business(cursor,business_id)
            cursor.execute('SELECT active FROM sm_businesses WHERE id=%s FOR UPDATE',(business_id,))
            business = cursor.fetchone()
            if not business:
                raise ValueError('Business unavailable.')
            if not platform:
                cursor.execute("SELECT 1 FROM sm_memberships m JOIN sm_administrators a ON a.id=m.administrator_id WHERE m.business_id=%s AND a.id=%s AND m.active AND m.role='owner' AND a.active AND a.verified_at IS NOT NULL", (business_id,actor))
                if not business['active'] or not cursor.fetchone():
                    raise ValueError('Active business ownership is required.')
            cursor.execute("SELECT id FROM sb_subscriptions WHERE business_id=%s AND status NOT IN ('canceled','incomplete_expired')", (business_id,))
            subscriptions = [r['id'] for r in cursor.fetchall()]
            cursor.execute("SELECT id FROM sb_checkouts WHERE business_id=%s AND status IN ('creating','open')",(business_id,))
            pending = bool(cursor.fetchone())
            result = {'provider_cancellation_confirmed':False}
            if action == 'request_cancellation':
                if not subscriptions:
                    raise ValueError('No ongoing subscription record exists. End a free trial separately; unconfirmed checkouts need billing review.')
                result.update(status='pending_provider_confirmation', subscriptions=subscriptions)
            elif action == 'review_request':
                request_id = str(values.get('request_id',''))
                if not request_id.isdigit():
                    raise ValueError('Enter the cancellation request audit ID.')
                cursor.execute("SELECT id FROM staff_audit WHERE id=%s AND business_id=%s AND action='request_cancellation' AND entity_type='subscription_management'", (int(request_id),business_id))
                if not cursor.fetchone():
                    raise ValueError('Cancellation request not found for this business.')
                result.update(request_id=int(request_id),status='reviewed_pending_provider_confirmation')
            elif action in ('end_trial','deactivate'):
                if subscriptions or pending:
                    raise ValueError('Resolve ongoing subscriptions and unconfirmed checkouts with the billing provider first. This action cannot stop charges.')
                if action == 'end_trial':
                    cursor.execute('SELECT starts_at,ends_at FROM so_trials WHERE business_id=%s FOR UPDATE',(business_id,))
                    trial = cursor.fetchone()
                    if not trial or not trial['starts_at']:
                        raise ValueError('No started free trial exists to end.')
                    result.update(status='trial_ended_immediately', previous_expiry=trial['ends_at'])
                else:
                    cursor.execute('SELECT id FROM staff_shifts WHERE business_id=%s AND clock_out_at IS NULL LIMIT 1',(business_id,))
                    if cursor.fetchone():
                        raise ValueError('Close open shifts before deactivating the business.')
                    cursor.execute('UPDATE sm_businesses SET active=FALSE WHERE id=%s',(business_id,))
                    result.update(status='business_deactivated', previous_active=business['active'])
            elif action == 'reactivate':
                cursor.execute('UPDATE sm_businesses SET active=TRUE WHERE id=%s',(business_id,))
                result.update(status='business_reactivated', previous_active=business['active'])
            agency.audit(cursor,business_id,actor,action,'subscription_management',None,None,result,reason)
