"""Platform review of suspicious Staff Manager registrations.

Deactivation only sets sm_businesses.active=FALSE (already enforced on every sign-in and Staff route).
Nothing is deleted, history is kept in sr_* and staff_audit, and every change is reversible.
Genuine, paying or in-use businesses are protected server-side; the UI is not trusted.
"""
import html
import logging
import os
import re
from urllib.parse import quote, urlsplit

import psycopg2.errors
from psycopg2.extras import RealDictCursor

from integrations.email_helper import send_staff_email
from trimtech.modules.staff import accounts, agency, complimentary_migration, registration_review_migration as migration
from trimtech.modules.staff.database import StaffDatabaseError, fetch_all, fetch_one, transaction

logger = logging.getLogger(__name__)
MAX_BATCH = 100
MAX_REASON = 500
ACTIONS = ('deactivate', 'reactivate')
ENTITY = 'registration_review'

# Facts used both for the list (advisory) and inside the action transaction (authoritative).
FACT_COLUMNS = """(t.business_id IS NULL) AS legacy,
  COALESCE(own.verified,FALSE) AS owner_verified,
  EXISTS(SELECT 1 FROM sb_subscriptions x WHERE x.business_id=b.id) AS has_billing,
  EXISTS(SELECT 1 FROM sb_checkouts x WHERE x.business_id=b.id) AS has_checkout,
  {grant_fact} AS has_grant,
  EXISTS(SELECT 1 FROM staff_employees x WHERE x.business_id=b.id) AS has_employees,
  EXISTS(SELECT 1 FROM staff_shifts x WHERE x.business_id=b.id) AS has_shifts,
  (COALESCE(su.completed,'{{}}'::jsonb) <> '{{}}'::jsonb) AS has_setup"""
FACT_JOINS = """LEFT JOIN so_trials t ON t.business_id=b.id
  LEFT JOIN so_setup su ON su.business_id=b.id
  LEFT JOIN LATERAL (SELECT bool_or(a.verified_at IS NOT NULL) AS verified,min(a.email) AS email
      FROM sm_memberships m JOIN sm_administrators a ON a.id=m.administrator_id
      WHERE m.business_id=b.id AND m.role='owner') own ON TRUE"""


class ReviewRefused(ValueError):
    """Raised with a safe, displayable message."""


def fact_columns(grants_present=True):
    return FACT_COLUMNS.format(grant_fact='EXISTS(SELECT 1 FROM sc_grants x WHERE x.business_id=b.id)'
                               if grants_present else 'FALSE')


def protection_reasons(facts):
    """Why a business must not be bulk-deactivated; an empty list means it is a review candidate."""
    checks = (
        ('legacy', 'Existing business without a signup trial'),
        ('has_billing', 'Has subscription or billing records'),
        ('has_checkout', 'Has started checkout'),
        ('has_grant', 'Has complimentary access history'),
        ('has_employees', 'Has employee records'),
        ('has_shifts', 'Has shift activity'),
        ('has_setup', 'Has completed onboarding steps'),
    )
    reasons = [label for key, label in checks if facts.get(key)]
    if facts.get('owner_verified'):
        reasons.append('Owner has verified their email')
    return reasons


def mask_email(value):
    local, _, domain = str(value or '').partition('@')
    if not local or not domain:
        return 'unknown'
    return local[0] + '***@' + domain


def clean_ids(values):
    ids = []
    for value in values or []:
        value = str(value or '').strip()
        if not value or len(value) > 100 or not re.fullmatch(r'[A-Za-z0-9_.:-]+', value):
            raise ReviewRefused('A selected business ID is invalid.')
        if value not in ids:
            ids.append(value)
        if len(ids) > MAX_BATCH:
            raise ReviewRefused('Select no more than %d businesses at once.' % MAX_BATCH)
    if not ids:
        raise ReviewRefused('Select at least one business.')
    return ids


def confirmation_phrase(action, count):
    return '%s %d' % (action.upper(), count)


def validate(action, ids, reason, confirmation):
    if action not in ACTIONS:
        raise ReviewRefused('Choose a valid action.')
    ids = clean_ids(ids)
    reason = str(reason or '').strip()
    if not reason:
        raise ReviewRefused('A reason is required.')
    if len(reason) > MAX_REASON:
        raise ReviewRefused('The reason must be %d characters or fewer.' % MAX_REASON)
    if str(confirmation or '').strip() != confirmation_phrase(action, len(ids)):
        raise ReviewRefused('Type %s exactly to confirm.' % confirmation_phrase(action, len(ids)))
    return ids, reason


def apply(action, ids, actor, reason, confirmation):
    """Deactivate or reactivate in one transaction. Returns {'applied': [...], 'skipped': [(id, why)], 'batch_id': n}."""
    ids, reason = validate(action, ids, reason, confirmation)
    applied, skipped, batch_id = [], [], None
    with transaction() as connection:
        with connection.cursor() as plain:
            complimentary_migration.verify(plain)
            migration.verify(plain)
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("SELECT b.id,b.active," + fact_columns() + " FROM sm_businesses b " + FACT_JOINS +
                           " WHERE b.id=ANY(%s) ORDER BY b.id FOR UPDATE OF b", (ids,))
            rows = {row['id']: row for row in cursor.fetchall()}
            target = action == 'reactivate'
            plan = []
            for business_id in ids:
                row = rows.get(business_id)
                if not row:
                    skipped.append((business_id, 'Business not found'))
                elif row['active'] == target:
                    skipped.append((business_id, 'Already active' if target else 'Already inactive'))
                elif target:
                    cursor.execute("SELECT new_active FROM sr_review_items WHERE business_id=%s ORDER BY id DESC LIMIT 1", (business_id,))
                    last = cursor.fetchone()
                    if last and last['new_active'] is False:
                        plan.append(row)
                    else:
                        skipped.append((business_id, 'Not deactivated by registration review'))
                else:
                    reasons = protection_reasons(row)
                    if reasons:
                        skipped.append((business_id, 'Protected: ' + '; '.join(reasons)))
                    else:
                        plan.append(row)
            if plan:
                cursor.execute("INSERT INTO sr_review_batches(action,actor,reason) VALUES (%s,%s,%s) RETURNING id", (action, actor, reason))
                batch_id = cursor.fetchone()['id']
                for row in plan:
                    cursor.execute("INSERT INTO sr_review_items(batch_id,business_id,previous_active,new_active) VALUES (%s,%s,%s,%s)",
                                   (batch_id, row['id'], row['active'], target))
                    cursor.execute("UPDATE sm_businesses SET active=%s WHERE id=%s", (target, row['id']))
                    agency.audit(cursor, row['id'], actor, 'registration_review_' + action, ENTITY, str(batch_id),
                                 {'active': row['active']}, {'active': target}, reason)
                    applied.append(row['id'])
    return {'applied': applied, 'skipped': skipped, 'batch_id': batch_id}


def history(limit=50):
    try:
        return fetch_all("""SELECT b.id,b.action,b.actor,b.reason,b.created_at,
            (SELECT COUNT(*) FROM sr_review_items i WHERE i.batch_id=b.id) AS business_count
            FROM sr_review_batches b ORDER BY b.id DESC LIMIT %s""", (limit,))
    except psycopg2.errors.UndefinedTable:
        return []


def ready():
    """True once both the complimentary and registration-review schemas exist."""
    row = fetch_one("SELECT to_regclass('sr_review_items') IS NOT NULL AND to_regclass('sc_grants') IS NOT NULL AS ok")
    return bool(row and row['ok'])


# ---- platform administrator notifications ---------------------------------

def _public_base():
    base = os.getenv('STAFF_PUBLIC_BASE_URL', '').strip() or os.getenv('RENDER_EXTERNAL_URL', '').strip()
    parsed = urlsplit(base)
    if parsed.scheme != 'https' or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
        return ''
    return base.rstrip('/')


def _recipient():
    try:
        return accounts.email_address(os.getenv('PLATFORM_ADMIN_NOTIFY_EMAIL', ''))
    except ValueError:
        return ''


def build_message(business, event, base):
    """Subject, text and HTML. Contains no secrets: the review link is behind platform-admin login."""
    name = re.sub(r'[\r\n\t]+', ' ', str(business['name']))[:160]
    verified = bool(business['verified'])
    status = 'Email verified' if verified else 'Email NOT verified'
    link = '%s/staff/platform/businesses/%s/manage' % (
        base, quote(str(business['id']), safe='')) if base else ''
    headline = 'Business verified their email' if event == 'verified' else 'New Staff Manager registration'
    lines = ['%s: %s' % (headline, name), 'Verification status: %s' % status,
             'Owner email: %s' % mask_email(business.get('email'))]
    text = '\n'.join(lines + (['Review (platform admin sign-in required): ' + link] if link else []))
    safe = html.escape
    body = '<p><strong>%s</strong><br>%s<br>Verification status: %s<br>Owner email: %s</p>' % (
        safe(headline), safe(name), safe(status), safe(mask_email(business.get('email'))))
    if link:
        body += '<p><a href="%s">Review this business</a> (platform admin sign-in required)</p>' % safe(link, quote=True)
    return '[TrimTech] %s: %s' % (headline, name[:80]), text, body


def notify(email, event='registered'):
    """Best effort and de-duplicated per (business, event). Never raises: signup must not depend on it."""
    if event not in ('registered', 'verified'):
        return 'invalid_event'
    if event == 'verified' and os.getenv('PLATFORM_ADMIN_NOTIFY_VERIFIED', '0') != '1':
        return 'disabled'
    recipient = _recipient()
    if not recipient:
        return 'not_configured'
    try:
        business = fetch_one("""SELECT b.id,b.name,a.email,(a.verified_at IS NOT NULL) AS verified
            FROM sm_administrators a JOIN sm_memberships m ON m.administrator_id=a.id
            JOIN sm_businesses b ON b.id=m.business_id WHERE a.email=%s ORDER BY b.created_at DESC LIMIT 1""", (email,))
        if not business:
            return 'no_business'
        with transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute("""INSERT INTO sr_registration_notices(business_id,event) VALUES (%s,%s)
                    ON CONFLICT DO NOTHING RETURNING 1""", (business['id'], event))
                if not cursor.fetchone():
                    return 'duplicate'
    except psycopg2.errors.UndefinedTable:
        logger.info('Registration notification skipped: review migration not applied.')
        return 'not_migrated'
    except (StaffDatabaseError, psycopg2.Error):
        logger.warning('Registration notification could not claim a notice.', exc_info=True)
        return 'error'

    subject, text, body = build_message(business, event, _public_base())
    sent, reason, _ = send_staff_email(recipient, subject, text, body, 'staff-registration-%s-%s' % (event, business['id']))
    status = 'sent' if sent else 'failed'
    try:
        with transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute("UPDATE sr_registration_notices SET status=%s WHERE business_id=%s AND event=%s",
                               (status, business['id'], event))
    except (StaffDatabaseError, psycopg2.Error):
        logger.warning('Registration notification status could not be recorded.', exc_info=True)
        return 'error'
    if not sent:
        logger.warning('Registration notification failed: reason=%s', reason)
    return status
