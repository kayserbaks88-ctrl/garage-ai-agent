"""Authenticated payslip downloads and explicit, idempotent email notices."""
import os
import uuid
import logging
from html import escape
from urllib.parse import urlsplit, quote
from psycopg2.extras import RealDictCursor
from integrations.email_helper import send_staff_email
from trimtech.modules.staff.database import transaction
from trimtech.modules.staff.agency import lock_business, audit
from trimtech.modules.staff.payroll import PayrollError


logger = logging.getLogger(__name__)


def queue(cursor, business_id, slip_id, *, retry=False):
    lock_business(cursor, business_id)
    cursor.execute("""SELECT p.id,e.email FROM staff_payslips p
        JOIN staff_payroll_runs r ON r.id=p.payroll_run_id AND r.business_id=p.business_id
        JOIN staff_employees e ON e.id=p.employee_id AND e.business_id=p.business_id
        JOIN staff_payroll_calculations c ON c.payslip_id=p.id AND c.business_id=p.business_id
        WHERE p.id=%s AND p.business_id=%s AND r.status IN ('approved','sent','paid') AND NOT r.needs_recalculation""",
                   (slip_id, business_id))
    row = cursor.fetchone()
    if not row:
        raise PayrollError("Only approved statutory payslips can be sent.")
    recipient = (row['email'] or '').strip()
    valid = bool(recipient and '@' in recipient and not any(c.isspace() for c in recipient))
    status, error = ('pending', None) if valid else ('failed', 'employee_email_missing_or_invalid')
    if retry:
        cursor.execute("SELECT * FROM staff_payslip_notifications WHERE business_id=%s AND payslip_id=%s FOR UPDATE",
                       (business_id, slip_id))
        previous = cursor.fetchone()
        if not previous or previous['status'] not in {'failed', 'disabled'}:
            raise PayrollError('Only failed or disabled payslip emails can be retried. Sent and pending notices are unchanged.')
        # Keep the provider idempotency key for retries of an uncertain send.
        key = previous['event_key'] if previous['recipient'] == recipient else 'staff-payslip-'+uuid.uuid4().hex
        cursor.execute("""UPDATE staff_payslip_notifications SET recipient=%s,status=%s,error_code=%s,
            event_key=%s,provider_id=NULL,attempted_at=NULL WHERE business_id=%s AND payslip_id=%s""",
                       (recipient,status,error,key,business_id,slip_id))
        return
    cursor.execute("""INSERT INTO staff_payslip_notifications(payslip_id,business_id,recipient,status,event_key)
        VALUES (%s,%s,%s,%s,%s) ON CONFLICT(payslip_id) DO NOTHING""",
                   (slip_id, business_id, recipient, status, "staff-payslip-"+uuid.uuid4().hex))
    if not valid:
        cursor.execute("""UPDATE staff_payslip_notifications SET error_code=%s
            WHERE business_id=%s AND payslip_id=%s AND status='failed' AND error_code IS NULL""",
                       (error,business_id,slip_id))


def approve_and_queue(cursor, business_id, run_id, actor):
    """Atomically finalize the run and persist a notice for every statutory slip."""
    lock_business(cursor, business_id)
    cursor.execute("SELECT * FROM staff_payroll_runs WHERE id=%s AND business_id=%s FOR UPDATE", (run_id,business_id))
    run = cursor.fetchone()
    if not run or run['needs_recalculation'] or run['status'] not in {'draft','approved','sent','paid'}:
        raise PayrollError('That payroll run is unavailable or needs recalculation.')
    cursor.execute("""SELECT p.id,c.payslip_id FROM staff_payslips p
        LEFT JOIN staff_payroll_calculations c ON c.payslip_id=p.id AND c.business_id=p.business_id
          AND c.employee_id=p.employee_id AND c.payroll_run_id=p.payroll_run_id
        WHERE p.payroll_run_id=%s AND p.business_id=%s ORDER BY p.id""", (run_id,business_id))
    slips = cursor.fetchall()
    if run['calculation_version'] and (not slips or any(s['payslip_id'] is None for s in slips)):
        raise PayrollError('Every included employee must have a calculated payslip before approval.')
    if run['status'] == 'draft':
        cursor.execute("UPDATE staff_payroll_runs SET status='approved',approved_at=NOW(),updated_at=NOW() WHERE id=%s AND business_id=%s",
                       (run_id,business_id))
        audit(cursor,business_id,actor,'payroll_approved_and_issued' if run['calculation_version'] else 'legacy_payroll_approved',
              'payroll',run_id,{'status':'draft'},{'status':'approved','payslip_count':len(slips)},'Manager approved payroll run')
    if not run['calculation_version']:
        return False  # Preserve approval of historical gross-only runs.
    for slip in slips:
        queue(cursor,business_id,slip['id'])
    return True


def dispatch_next(business_id, run_id):
    """One bounded request per notice; remaining notices survive interrupted pages."""
    with transaction() as connection:
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("""SELECT n.payslip_id FROM staff_payslip_notifications n
                JOIN staff_payslips p ON p.id=n.payslip_id AND p.business_id=n.business_id
                JOIN staff_payroll_runs r ON r.id=p.payroll_run_id AND r.business_id=p.business_id
                WHERE n.business_id=%s AND r.id=%s AND r.status IN ('approved','sent','paid')
                  AND NOT r.needs_recalculation AND n.status='pending' ORDER BY n.payslip_id LIMIT 1""", (business_id,run_id))
            row = cursor.fetchone()
    if row:
        dispatch(business_id,row['payslip_id'])


def dispatch(business_id, slip_id):
    # The queue is committed before transport. Row locking prevents concurrent sends.
    with transaction() as connection:
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("""SELECT * FROM staff_payslip_notifications WHERE business_id=%s AND payslip_id=%s
                FOR UPDATE SKIP LOCKED""", (business_id, slip_id))
            row = cursor.fetchone()
            if not row or row["status"] != "pending":
                return (row or {}).get("status", "pending")
            base = (os.getenv("STAFF_PUBLIC_BASE_URL", "").strip() or os.getenv("RENDER_EXTERNAL_URL", "").strip()).rstrip("/")
            parsed = urlsplit(base)
            status, error, provider = "failed", None, None
            if os.getenv("STAFF_PAYSLIP_EMAIL_ENABLED", "1").lower() not in {"1","true","yes","on"}:
                status, error = "disabled", "email_disabled"
            elif parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.query or parsed.fragment:
                error = "portal_url_not_configured"
            else:
                link = base + "/staff/" + quote(business_id, safe="") + "/employee/pay"
                text = "Your payslip is ready. Sign in to Staff Manager to view and download it: " + link
                logger.info('Staff payslip email attempted: payslip=%s', slip_id)
                try:
                    success, error, provider = send_staff_email(row["recipient"], "Your TrimTech payslip is ready", text,
                        '<p>Your payslip is ready.</p><p><a href="'+escape(link, quote=True)+'">Sign in to download your payslip</a></p>', row["event_key"])
                except Exception:
                    success, error, provider = False, 'email_transport_failed', None
                status = "sent" if success else "failed"
            logger.info('Staff payslip email outcome: payslip=%s status=%s', slip_id, status)
            cursor.execute("""UPDATE staff_payslip_notifications SET status=%s,error_code=%s,provider_id=%s,attempted_at=NOW()
                WHERE payslip_id=%s AND business_id=%s""", (status, error, provider, slip_id, business_id))
            if status == "sent":
                cursor.execute("UPDATE staff_payslips SET emailed_at=NOW() WHERE id=%s AND business_id=%s", (slip_id,business_id))
            return status
