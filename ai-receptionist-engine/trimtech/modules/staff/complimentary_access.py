"""Time-limited complimentary Staff access granted by platform administrators.

Separate from Stripe: this module never reads or writes sb_* tables and never calls Stripe.
A grant can only extend an expired/ending trial; paid subscriptions always take precedence.
"""
import psycopg2.errors

from trimtech.modules.staff import agency
from trimtech.modules.staff.database import fetch_all, fetch_one, transaction

ALLOWED_DAYS = (3, 7, 14, 30)
MAX_REASON = 1000
LIFETIME_CAP_DAYS = 90
ENTITY = 'complimentary_access'


class GrantRefused(ValueError):
    """Raised with a safe, displayable message."""


def validate_request(*, business_id, days, reason, confirmation, business_active, paid,
                     trial_state, active_grant, granted_days_total):
    """Pure decision logic; returns the normalised (days, reason) or raises GrantRefused."""
    try:
        days = int(days)
    except (TypeError, ValueError):
        raise GrantRefused('Choose 3, 7, 14 or 30 days.')
    if days not in ALLOWED_DAYS:
        raise GrantRefused('Choose 3, 7, 14 or 30 days.')
    reason = str(reason or '').strip()
    if not reason:
        raise GrantRefused('A reason is required.')
    if len(reason) > MAX_REASON:
        raise GrantRefused('The reason must be 1000 characters or fewer.')
    if str(confirmation or '').strip() != str(business_id):
        raise GrantRefused('Type the business ID exactly to confirm.')
    if not business_active:
        raise GrantRefused('This business is inactive.')
    if paid:
        raise GrantRefused('This business already has a paid subscription.')
    if trial_state == 'pending':
        raise GrantRefused('The trial has not started because the owner has not verified their email.')
    if trial_state == 'legacy':
        raise GrantRefused('This account has no trial and does not need complimentary access.')
    if active_grant:
        raise GrantRefused('An active complimentary grant already exists. Revoke it or wait for it to expire.')
    if granted_days_total + days > LIFETIME_CAP_DAYS:
        raise GrantRefused('This would exceed the %d-day lifetime complimentary limit.' % LIFETIME_CAP_DAYS)
    return days, reason


def actor_for(username):
    return 'platform:%s' % username


def active_grant(business_id):
    """Return the unexpired, unrevoked grant, or None. Safe before the migration is applied."""
    try:
        return fetch_one("""SELECT id,days,reason,granted_by,granted_at,starts_at,expires_at,
            CEIL(EXTRACT(EPOCH FROM expires_at-NOW())/86400)::integer AS days_left
            FROM sc_grants WHERE business_id=%s AND revoked_at IS NULL AND expires_at>NOW()
            ORDER BY expires_at DESC LIMIT 1""", (business_id,))
    except psycopg2.errors.UndefinedTable:
        return None


def history(business_id, limit=20):
    try:
        return fetch_all("""SELECT id,days,reason,granted_by,granted_at,starts_at,expires_at,
            revoked_at,revoked_by,revoke_reason,
            CASE WHEN revoked_at IS NOT NULL THEN 'revoked' WHEN expires_at>NOW() THEN 'active' ELSE 'expired' END AS state
            FROM sc_grants WHERE business_id=%s ORDER BY granted_at DESC LIMIT %s""", (business_id, limit))
    except psycopg2.errors.UndefinedTable:
        return []


def apply_to_access(trial, grant):
    """Overlay a grant on an expired trial; callers keep using the existing 'active' state."""
    if not grant or trial.get('state') != 'expired':
        return trial
    days = max(int(grant.get('days_left') or 0), 0)
    return {**trial, 'state': 'active', 'ends_at': grant['expires_at'], 'days': days, 'complimentary': True}


def grant(business_id, actor, days, reason, confirmation):
    from trimtech.modules.staff import onboarding
    from trimtech.modules.staff.billing import entitlement
    business = fetch_one('SELECT id,active FROM sm_businesses WHERE id=%s', (business_id,))
    if not business:
        raise GrantRefused('Business not found.')
    trial = onboarding.status(business_id)
    paid = bool(entitlement(business_id)['paid'])
    with transaction() as connection:
        with connection.cursor() as cursor:
            agency.lock_business(cursor, business_id)
            cursor.execute("""SELECT COUNT(*) FILTER (WHERE revoked_at IS NULL AND expires_at>NOW()),
                COALESCE(SUM(days) FILTER (WHERE revoked_at IS NULL),0) FROM sc_grants WHERE business_id=%s""", (business_id,))
            active_count, total = cursor.fetchone()
            days, reason = validate_request(
                business_id=business_id, days=days, reason=reason, confirmation=confirmation,
                business_active=bool(business['active']), paid=paid, trial_state=trial['state'],
                active_grant=active_count > 0, granted_days_total=int(total))
            # An unexpired trial keeps its own dates; the grant begins when the trial ends.
            if trial['state'] == 'active' and trial['ends_at']:
                cursor.execute("SELECT %s::timestamptz", (trial['ends_at'],))
                starts_at = cursor.fetchone()[0]
            else:
                cursor.execute('SELECT NOW()')
                starts_at = cursor.fetchone()[0]
            cursor.execute("""INSERT INTO sc_grants(business_id,days,reason,granted_by,starts_at,expires_at)
                VALUES (%s,%s,%s,%s,%s,%s+make_interval(days=>%s)) RETURNING id,expires_at""",
                (business_id, days, reason, actor, starts_at, starts_at, days))
            grant_id, expires_at = cursor.fetchone()
            agency.audit(cursor, business_id, actor, 'grant', ENTITY, str(grant_id),
                         {'trial_state': trial['state']}, {'days': days, 'expires_at': expires_at}, reason)
    return {'id': grant_id, 'days': days, 'expires_at': expires_at}


def revoke(business_id, actor, reason):
    reason = str(reason or '').strip()
    if not reason:
        raise GrantRefused('A reason is required.')
    if len(reason) > MAX_REASON:
        raise GrantRefused('The reason must be 1000 characters or fewer.')
    with transaction() as connection:
        with connection.cursor() as cursor:
            agency.lock_business(cursor, business_id)
            cursor.execute("""UPDATE sc_grants SET revoked_at=NOW(),revoked_by=%s,revoke_reason=%s
                WHERE business_id=%s AND revoked_at IS NULL AND expires_at>NOW() RETURNING id""",
                (actor, reason, business_id))
            rows = cursor.fetchall()
            if not rows:
                raise GrantRefused('There is no active complimentary grant to revoke.')
            for (grant_id,) in rows:
                agency.audit(cursor, business_id, actor, 'revoke', ENTITY, str(grant_id), {'revoked': False}, {'revoked': True}, reason)
    return len(rows)
