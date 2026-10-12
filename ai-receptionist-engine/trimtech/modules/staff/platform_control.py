"""Platform-only aggregate directory over existing Staff records; no tenant impersonation."""
import logging
import hashlib
from flask import abort, render_template, request, session
from psycopg2.extras import RealDictCursor
from trimtech.modules.auth.routes import platform_admin_required
from trimtech.modules.staff.database import transaction
from trimtech.modules.staff import migrations, accounts_migration, onboarding_migration, billing_migration

logger = logging.getLogger(__name__)
STATUSES = {'all','active_trial','expired_trial','pending_trial','paid','inactive','legacy'}

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
                CASE WHEN NOT b.active THEN 'inactive'
                     WHEN sub.status='active' AND sub.paid_until>NOW() THEN 'paid'
                     WHEN t.business_id IS NULL THEN 'legacy'
                     WHEN t.starts_at IS NULL THEN 'pending_trial'
                     WHEN t.ends_at<=NOW() THEN 'expired_trial' ELSE 'active_trial' END AS state
                FROM sm_businesses b LEFT JOIN so_trials t ON t.business_id=b.id
                LEFT JOIN so_setup s ON s.business_id=b.id
                LEFT JOIN (SELECT business_id,COUNT(*) FILTER(WHERE status='active') AS employees
                    FROM staff_employees GROUP BY business_id) e ON e.business_id=b.id
                LEFT JOIN (SELECT business_id,COUNT(*) FILTER(WHERE clock_out_at IS NULL) AS open_shifts,
                    COUNT(*) FILTER(WHERE approval_status='pending' AND clock_out_at IS NOT NULL) AS pending,
                    MAX(updated_at) AS last_activity FROM staff_shifts GROUP BY business_id) sh ON sh.business_id=b.id
                LEFT JOIN LATERAL (SELECT status,paid_until,invoice_status FROM sb_subscriptions
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
        return render_template('staff_platform.html',**data,q=query,status_filter=status)
