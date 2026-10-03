"""Authenticated payslip downloads and explicit, idempotent email notices."""
import os
import uuid
from html import escape
from urllib.parse import urlsplit, quote
from psycopg2.extras import RealDictCursor
from integrations.email_helper import send_staff_email
from trimtech.modules.staff.database import transaction
from trimtech.modules.staff.agency import lock_business
from trimtech.modules.staff.payroll import PayrollError


def queue(cursor, business_id, slip_id):
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
    if not row["email"] or "@" not in row["email"]:
        raise PayrollError("Add a valid employee email address first.")
    cursor.execute("""INSERT INTO staff_payslip_notifications(payslip_id,business_id,recipient,status,event_key)
        VALUES (%s,%s,%s,'pending',%s) ON CONFLICT(payslip_id) DO NOTHING""",
                   (slip_id, business_id, row["email"], "staff-payslip-"+uuid.uuid4().hex))


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
                success, error, provider = send_staff_email(row["recipient"], "Your TrimTech payslip is ready", text,
                    '<p>Your payslip is ready.</p><p><a href="'+escape(link, quote=True)+'">Sign in to download your payslip</a></p>', row["event_key"])
                status = "sent" if success else "failed"
            cursor.execute("""UPDATE staff_payslip_notifications SET status=%s,error_code=%s,provider_id=%s,attempted_at=NOW()
                WHERE payslip_id=%s AND business_id=%s""", (status, error, provider, slip_id, business_id))
            if status == "sent":
                cursor.execute("UPDATE staff_payslips SET emailed_at=NOW() WHERE id=%s AND business_id=%s", (slip_id,business_id))
            return status
