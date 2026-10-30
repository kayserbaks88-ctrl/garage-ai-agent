"""Platform-only aggregate directory over existing Staff records; no tenant impersonation."""
import logging
import hashlib
import os
import hmac
from functools import wraps
from flask import abort, render_template, request, session, redirect, url_for, flash
from psycopg2.extras import RealDictCursor
from trimtech.modules.auth.routes import platform_admin_required as shared_platform_required
from trimtech.modules.staff.database import transaction
from trimtech.modules.staff import migrations, accounts_migration, onboarding_migration, billing_migration
from trimtech.modules.onboarding.service import (
    OnboardingStorageError,
    list_onboarding_businesses,
)
from trimtech.modules.staff.paychaser_integration import fetch_summary

logger = logging.getLogger(__name__)
STATUSES = {'all','active_trial','expired_trial','pending_trial','paid','inactive','legacy'}

def authorized():
    # Dedicated credentials are mandatory: shared dashboard fallback is not Staff authority.
    username = os.getenv('PLATFORM_ADMIN_USERNAME', '').strip()
    return bool(username and os.getenv('PLATFORM_ADMIN_PASSWORD', '')
        and session.get('platform_admin_authenticated') is True
        and session.get('auth_role') == 'platform_admin'
        and hmac.compare_digest(str(session.get('platform_admin_username', '')), username))


def platform_admin_required(function):
    @wraps(function)
    @shared_platform_required
    def protected(*args, **kwargs):
        if not authorized():
            abort(403, description='Dedicated TrimTech platform administrator access is required.')
        return function(*args, **kwargs)
    return protected


def control_centre_required(function):
    @wraps(function)
    @shared_platform_required
    def protected(*args, **kwargs):
        if (
            not authorized()
            or session.get('platform_admin_auth_source') != 'dedicated'
        ):
            abort(
                403,
                description='Dedicated platform administrator credentials are required for the Control Centre.',
            )
        return function(*args, **kwargs)
    return protected


def directory(query='', status='all'):
    if status not in STATUSES:
        raise ValueError('Choose a valid business status.')
    with transaction() as connection:
        connection.set_session(readonly=True, isolation_level='REPEATABLE READ')
        with connection.cursor() as cursor:
            for module in (migrations, accounts_migration, onboarding_migration, billing_migration):
                module.verify(cursor)
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("""SELECT b.id,b.name,b.active,b.created_at,t.starts_at,t.ends_at,
                COALESCE(s.completed,'{}'::jsonb) AS completed,
                COALESCE(e.employees,0) AS employee_count,COALESCE(sh.open_shifts,0) AS open_shifts,
                COALESCE(sh.pending,0) AS pending_approvals,sh.last_activity,
                sub.status AS subscription_status,sub.paid_until,sub.invoice_status,
                sub.cancel_at_period_end,
                CASE WHEN NOT b.active THEN 'inactive'
                     WHEN sub.status='active' AND sub.paid_until>NOW() THEN 'paid'
                     WHEN t.business_id IS NULL THEN 'legacy'
                     WHEN t.starts_at IS NULL THEN 'pending_trial'
                     WHEN t.ends_at<=NOW() OR EXISTS(SELECT 1 FROM staff_audit a WHERE a.business_id=b.id AND a.entity_type='subscription_management' AND a.action='end_trial') THEN 'expired_trial' ELSE 'active_trial' END AS state
                FROM sm_businesses b LEFT JOIN so_trials t ON t.business_id=b.id
                LEFT JOIN so_setup s ON s.business_id=b.id
                LEFT JOIN (SELECT business_id,COUNT(*) FILTER(WHERE status='active') AS employees
                    FROM staff_employees GROUP BY business_id) e ON e.business_id=b.id
                LEFT JOIN (SELECT business_id,COUNT(*) FILTER(WHERE clock_out_at IS NULL) AS open_shifts,
                    COUNT(*) FILTER(WHERE approval_status='pending' AND clock_out_at IS NOT NULL) AS pending,
                    MAX(updated_at) AS last_activity FROM staff_shifts GROUP BY business_id) sh ON sh.business_id=b.id
                LEFT JOIN LATERAL (SELECT status,paid_until,invoice_status,cancel_at_period_end,verified_at
                    FROM sb_subscriptions
                    WHERE business_id=b.id ORDER BY (status='active' AND paid_until>NOW()) DESC,
                    verified_at DESC,id LIMIT 1) sub ON TRUE
                ORDER BY lower(b.name),b.id""")
            rows = [dict(row) for row in cursor.fetchall()]
    text = str(query).strip().casefold()[:160]
    filtered = [row for row in rows if (not text or text in row['name'].casefold()) and
                (status=='all' or row['state']==status)]
    return dict(businesses=filtered,total=len(rows),matching=len(filtered),health='Verified',
                active_trials=sum(row['state']=='active_trial' for row in rows),
                paid=sum(row['state']=='paid' for row in rows))

def register_routes(staff):
    @staff.staff_blueprint.get('/platform/control-centre')
    @control_centre_required
    def platform_control_centre():
        garage_available = True
        staff_available = True
        try:
            garage_businesses = list_onboarding_businesses()
        except OnboardingStorageError:
            logger.exception('Control Centre could not read Garage registrations')
            garage_businesses = None
            garage_available = False
        try:
            staff_data = directory()
        except staff._DB_ERRORS:
            logger.exception('Control Centre could not read Staff Manager summaries')
            staff_data = None
            staff_available = False

        summary = build_control_centre_summary(
            garage_businesses,
            staff_data,
            garage_available=garage_available,
            staff_available=staff_available,
            paychaser_data=fetch_summary(),
        )
        logger.info(
            'TrimTech Control Centre viewed: actor_hash=%s',
            hashlib.sha256(
                str(session.get('platform_admin_username', '')).encode()
            ).hexdigest(),
        )
        return render_template('trimtech_control_centre.html', **summary)

    @staff.staff_blueprint.get('/platform/businesses')
    @platform_admin_required
    def platform_businesses():
        query=request.args.get('q','')[:160]
        status=request.args.get('status','all')
        try:
            data=directory(query,status)
        except ValueError:
            abort(400)
        except staff._DB_ERRORS:
            return render_template('staff_platform.html',unavailable=True),503
        # Read-only directory: no impersonation, mutation controls or payroll data.
        actor=hashlib.sha256(str(session.get('platform_admin_username','authenticated-platform-admin')).encode()).hexdigest()
        logger.info('Staff platform directory viewed: actor_hash=%s',actor)
        return render_template('staff_platform.html',**data,q=query,status_filter=status,csrf_token=staff._get_csrf_token)

    @staff.staff_blueprint.get('/platform/businesses/<business_slug>/subscription')
    @platform_admin_required
    def platform_subscription(business_slug):
        from trimtech.modules.staff import subscription_management as management, billing, onboarding
        try:
            business = management.business(business_slug)
            if not business:
                abort(404)
            return render_template('staff_subscription_admin.html', business=business,
                billing=billing.summary(business_slug), trial=onboarding.status(business_slug),
                history=management.history(business_slug), csrf_token=staff._get_csrf_token)
        except staff._DB_ERRORS:
            abort(503)

    @staff.staff_blueprint.post('/platform/businesses/<business_slug>/subscription')
    @platform_admin_required
    def platform_subscription_action(business_slug):
        from trimtech.modules.staff import subscription_management as management
        try:
            management.change(business_slug, 'platform:'+session['platform_admin_username'],
                request.form.get('action'), request.form, platform=True)
            flash('Administrative action recorded. Billing cancellation is not confirmed by this action.', 'success')
        except ValueError as error:
            flash(str(error), 'error')
        except staff._DB_ERRORS:
            abort(503)
        return redirect(url_for('staff.platform_subscription',business_slug=business_slug))


def build_control_centre_summary(
    garage_businesses,
    staff_data,
    *,
    garage_available=True,
    staff_available=True,
    paychaser_data=None,
):
    garage_rows = garage_businesses if garage_available else None
    staff_rows = (
        staff_data['businesses']
        if staff_available and staff_data is not None
        else None
    )
    garage_count = len(garage_rows) if garage_rows is not None else None
    staff_count = len(staff_rows) if staff_rows is not None else None

    active_trials = (
        sum(row.get('state') == 'active_trial' for row in staff_rows)
        if staff_rows is not None
        else None
    )
    active_subscriptions = (
        sum(row.get('state') == 'paid' for row in staff_rows)
        if staff_rows is not None
        else None
    )
    cancellation_statuses = {'active', 'trialing', 'past_due'}
    pending_cancellations = (
        sum(
            bool(row.get('cancel_at_period_end'))
            and row.get('subscription_status') in cancellation_statuses
            for row in staff_rows
        )
        if staff_rows is not None
        else None
    )
    payment_issue_statuses = {'past_due', 'unpaid', 'invalid'}
    payment_issue_invoices = {'open', 'uncollectible', 'failed'}
    payment_issues = (
        sum(
            row.get('subscription_status') in payment_issue_statuses
            or row.get('invoice_status') in payment_issue_invoices
            for row in staff_rows
        )
        if staff_rows is not None
        else None
    )
    employee_count = (
        sum(int(row.get('employee_count') or 0) for row in staff_rows)
        if staff_rows is not None
        else None
    )
    completed_registrations = (
        sum(bool(getattr(row, 'onboarding_complete', False)) for row in garage_rows)
        if garage_rows is not None
        else None
    )
    paychaser_data = paychaser_data or {
        'available': False,
        'status': 'not_configured',
        'message': 'PayChaser service integration is not configured.',
    }
    paychaser_summary = paychaser_data.get('data', {})

    return {
        'products': {
            'garage': {
                'available': garage_available,
                'businesses': garage_count,
                'completed_registrations': completed_registrations,
                'trials': None,
                'subscriptions': None,
                'cancellations': None,
                'payment_issues': None,
                'billing_status': 'Setup pending',
            },
            'staff': {
                'available': staff_available,
                'businesses': staff_count,
                'employees': employee_count,
                'trials': active_trials,
                'subscriptions': active_subscriptions,
                'cancellations': pending_cancellations,
                'payment_issues': payment_issues,
                'billing_status': 'Staff billing records',
            },
            'paychaser': {
                'available': paychaser_data.get('available', False),
                'status': paychaser_data.get('status', 'unavailable'),
                'message': paychaser_data.get('message', ''),
                'businesses': paychaser_summary.get('registered_businesses'),
                'businesses_without_subscription': paychaser_summary.get(
                    'businesses_without_subscription'
                ),
                'trials': paychaser_summary.get('active_trials'),
                'subscriptions': paychaser_summary.get(
                    'subscription_status_counts'
                ),
                'cancellations': paychaser_summary.get(
                    'scheduled_cancellations'
                ),
                'as_of': paychaser_summary.get('as_of'),
                'business_records_updated_at': paychaser_summary.get(
                    'business_records_updated_at'
                ),
                'subscription_records_updated_at': paychaser_summary.get(
                    'subscription_records_updated_at'
                ),
            },
        },
        'revenue': None,
    }
