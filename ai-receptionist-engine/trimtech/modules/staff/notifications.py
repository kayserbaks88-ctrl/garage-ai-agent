"""Transactional assignment outbox; email is attempted only after assignment commit."""
import logging
import os
import uuid
from datetime import datetime
from html import escape
from urllib.parse import quote, urlsplit

from psycopg2.extras import Json, RealDictCursor
from integrations.email_helper import send_staff_email
from trimtech.modules.staff.database import transaction
from trimtech.modules.staff.payroll import UK_TIMEZONE

logger = logging.getLogger(__name__)
# Keep Staff email lifecycle visible without changing shared application logging.
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger.addHandler(handler)
logger.propagate = False


def queue(cursor, business_id, assignment_id, action, assignment):
    """An outbox error must not roll back an otherwise valid assignment."""
    cursor.execute("SAVEPOINT staff_email_queue")
    try:
        return _queue(cursor, business_id, assignment_id, action, assignment)
    except Exception:
        cursor.execute("ROLLBACK TO SAVEPOINT staff_email_queue")
        logger.error("Staff assignment email failed: assignment=%s reason=notification_queue_failed", assignment_id)
    finally:
        cursor.execute("RELEASE SAVEPOINT staff_email_queue")


def _queue(cursor, business_id, assignment_id, action, assignment):
    cursor.execute("SELECT full_name,email FROM staff_employees WHERE id=%s AND business_id=%s",
                   (assignment["employee_id"], business_id))
    employee = cursor.fetchone()
    cursor.execute("SELECT name,address,client_reference FROM staff_sites WHERE id=%s AND business_id=%s",
                   (assignment["site_id"], business_id))
    site = cursor.fetchone()
    details = {"employee_name": employee["full_name"], "site_name": site["name"],
               "address": site["address"], "client_reference": site["client_reference"],
               "starts_at": assignment["starts_at"].isoformat(), "ends_at": assignment["ends_at"].isoformat()}
    cursor.execute("""INSERT INTO staff_assignment_notifications
        (business_id,assignment_id,employee_id,event_key,action,recipient,details)
        VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id""", (business_id, assignment_id, assignment["employee_id"],
        "staff-assignment-" + uuid.uuid4().hex, action, employee["email"], Json(details)))
    return cursor.fetchone()["id"]


def message(row):
    base = (os.getenv("STAFF_PUBLIC_BASE_URL", "").strip()
            or os.getenv("RENDER_EXTERNAL_URL", "").strip()).rstrip("/")
    parsed = urlsplit(base)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.query or parsed.fragment:
        raise ValueError("portal_url_not_configured")
    portal = base + "/staff/" + quote(row["business_id"], safe="") + "/employee"
    detail = row["details"]
    action = {"created": "Assignment created", "updated": "Assignment updated",
              "cancelled": "Assignment cancelled", "reassigned_away": "Assignment reassigned — you are no longer scheduled"}[row["action"]]
    lines = [action, "Employee: " + detail["employee_name"], "Site: " + detail["site_name"],
             "Address: " + (detail["address"] or "Not supplied")]
    for label, key in (("Start", "starts_at"), ("End", "ends_at")):
        stamp = datetime.fromisoformat(detail[key]).astimezone(UK_TIMEZONE)
        lines.append(f"{label}: {stamp:%A %d %B %Y, %H:%M %Z} (UK)")
    if detail.get("client_reference"):
        lines.append("Client / job reference: " + detail["client_reference"])
    text = "\n".join(lines) + "\n\nOpen Staff Manager: " + portal
    html = "<div style='font-family:Arial,sans-serif;line-height:1.6'>" + "".join(
        "<p>" + escape(line) + "</p>" for line in lines)
    html += f'<p><a href="{escape(portal, quote=True)}" style="display:inline-block;background:#166534;color:white;padding:12px 20px;text-decoration:none;border-radius:6px">Open Staff Manager</a></p></div>'
    return action, text, html


def dispatch(business_id, assignment_id, notification_ids=None):
    """Failure here never propagates to the already committed assignment action.

    SKIP LOCKED avoids concurrent dispatch; provider idempotency handles a process
    crash after acceptance but before the result is committed.
    """
    try:
        for _ in range(20):
            with transaction() as connection:
                with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                    cursor.execute("""SELECT * FROM staff_assignment_notifications WHERE business_id=%s
                        AND assignment_id=%s AND status='pending'
                        AND (%s IS NULL OR id=ANY(%s)) ORDER BY id FOR UPDATE SKIP LOCKED LIMIT 1""",
                        (business_id, assignment_id, notification_ids, notification_ids))
                    row = cursor.fetchone()
                    if not row:
                        return
                    status, error, provider_id = "failed", None, None
                    enabled = os.getenv("STAFF_ASSIGNMENT_EMAIL_ENABLED", "1").strip().lower()
                    if enabled not in {"1", "true", "yes", "on"}:
                        status, error = "disabled", "email_disabled"
                    elif not row["recipient"] or "@" not in row["recipient"]:
                        error = "employee_email_missing_or_invalid"
                    else:
                        try:
                            subject, text, html = message(row)
                            logger.info("Staff assignment email attempted: notification=%s assignment=%s action=%s",
                                        row["id"], assignment_id, row["action"])
                            sent, error, provider_id = send_staff_email(row["recipient"], subject, text, html, row["event_key"])
                            status = "sent" if sent else "failed"
                        except ValueError:
                            error = "portal_url_not_configured"
                        except Exception:
                            error = "message_or_delivery_failed"
                    log = logger.info if status == "sent" else logger.warning
                    log("Staff assignment email %s: notification=%s assignment=%s reason=%s",
                        status, row["id"], assignment_id, error or "provider_accepted_not_delivery_confirmed")
                    cursor.execute("""UPDATE staff_assignment_notifications SET status=%s,error_code=%s,
                        provider_id=%s,attempted_at=NOW() WHERE id=%s""", (status, error, provider_id, row["id"]))
    except Exception:
        logger.error("Staff assignment notification dispatch could not record its outcome; pending outbox requires review")


def confirmation(business_id, assignment_id, notification_ids):
    """Report this action's notices only; earlier successes cannot mask a failure."""
    if not notification_ids or any(value is None for value in notification_ids):
        return "Assignment saved. Email failed to queue; review the assignment email log.", "error"
    try:
        with transaction() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("""SELECT status FROM staff_assignment_notifications
                    WHERE business_id=%s AND assignment_id=%s AND id=ANY(%s)""",
                    (business_id, assignment_id, notification_ids))
                statuses = [row["status"] for row in cursor.fetchall()]
        if len(statuses) != len(notification_ids):
            return "Assignment saved. Email status unavailable; review the assignment email log.", "error"
        if all(status == "sent" for status in statuses):
            return "Assignment saved. Employee notification sent: accepted by the email provider; inbox delivery is not confirmed.", "success"
        if "failed" in statuses:
            return "Assignment saved. Email failed for one or more notifications; review the assignment email log.", "error"
        if "disabled" in statuses:
            return "Assignment saved. Email is disabled; not all employees were notified.", "error"
        return "Assignment saved. Email pending; employee notification is not yet confirmed.", "warning"
    except Exception:
        logger.error("Staff assignment email status unavailable: assignment=%s", assignment_id)
        return "Assignment saved. Email status unavailable; review the assignment email log.", "error"
