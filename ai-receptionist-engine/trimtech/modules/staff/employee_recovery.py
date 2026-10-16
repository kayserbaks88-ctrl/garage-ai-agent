"""Employee-only recovery using existing token storage; no startup I/O or DDL."""
import logging
import re
import secrets
import uuid
from concurrent.futures import ThreadPoolExecutor
from html import escape
from threading import BoundedSemaphore
from urllib.parse import quote, urlsplit

from psycopg2.extras import RealDictCursor
from integrations.email_helper import send_staff_email
from trimtech.modules.staff import accounts, agency
from trimtech.modules.staff.database import transaction

logger = logging.getLogger(__name__)
_workers = ThreadPoolExecutor(max_workers=2, thread_name_prefix='staff-recovery')
_slots = BoundedSemaphore(8)


def token_digest(raw):
    # A reset link cannot be accepted by employee invitation or administrator routes.
    return accounts.digest('employee-reset:' + raw)


def enqueue(business, email, phone, base):
    """Bound pending work; lookup and provider latency never reveal account existence."""
    if not _slots.acquire(blocking=False):
        return
    try:
        _workers.submit(_deliver, business, email, phone, base)
    except Exception:
        _slots.release()
        logger.warning('Employee recovery request could not be queued')


def _deliver(business, email, phone, base):
    try:
        issue(business, email, phone, base)
    except Exception:
        # No exception text, identity, raw token or provider response in logs.
        logger.warning('Employee recovery email could not be completed')
    finally:
        _slots.release()


def issue(business, email, phone, base):
    parsed = urlsplit(base)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.path not in ('', '/') or parsed.query or parsed.fragment):
        return
    raw = secrets.token_urlsafe(32)
    with transaction() as connection:
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            agency.lock_business(cursor, business)
            cursor.execute("""SELECT e.id,e.email,c.version FROM staff_employees e
                JOIN sm_businesses b ON b.id=e.business_id AND b.active
                JOIN so_employee_credentials c ON c.employee_id=e.id AND c.business_id=e.business_id
                WHERE e.business_id=%s AND e.status='active' AND lower(btrim(e.email))=%s
                AND e.phone=ANY(%s) LIMIT 2 FOR UPDATE OF e,c""", (business, email, list(phone)))
            employees = cursor.fetchall()
            if len(employees) != 1:
                return
            employee = employees[0]
            # Bind the link to the current password, including changes via manager invitations.
            identifier = 'employee-reset-' + employee['version'] + '-' + uuid.uuid4().hex
            cursor.execute("""INSERT INTO so_employee_invites
                (id,token_hash,employee_id,business_id,email,expires_at)
                VALUES (%s,%s,%s,%s,%s,NOW()+INTERVAL '1 hour')""",
                (identifier, token_digest(raw), employee['id'], business, email))
    # Earlier links and the current password remain usable until a reset succeeds.
    link = base.rstrip('/') + '/staff/' + quote(business, safe='') + '/employee/reset#token=' + raw
    sent, _, _ = send_staff_email(accounts.email_address(employee['email']), 'Reset your Staff Manager employee password',
        f'Reset your employee password: {link}\nThis link expires in one hour. Email code: {raw}\n'
        'If you did not request this, you can ignore this email.',
        f'<p><a href="{escape(link, quote=True)}">Reset your employee password</a></p>'
        '<p>This link expires in one hour. If you did not request it, you can ignore this email.</p>',
        identifier)
    if not sent:
        logger.warning('Employee recovery email was not accepted')


def consume(business, raw, password):
    if not isinstance(raw, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', raw):
        return False
    hashed = accounts.password_hash(password)
    with transaction() as connection:
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            agency.lock_business(cursor, business)
            cursor.execute("""SELECT i.id,i.employee_id FROM so_employee_invites i
                JOIN staff_employees e ON e.id=i.employee_id AND e.business_id=i.business_id
                JOIN sm_businesses b ON b.id=i.business_id AND b.active
                JOIN so_employee_credentials c ON c.employee_id=e.id AND c.business_id=e.business_id
                WHERE i.business_id=%s AND i.token_hash=%s
                AND i.id LIKE 'employee-reset-' || c.version || '-%%'
                AND i.consumed_at IS NULL AND i.expires_at>NOW() AND e.status='active'
                AND lower(btrim(e.email))=i.email FOR UPDATE OF i,e,c""", (business, token_digest(raw)))
            value = cursor.fetchone()
            if not value:
                return False
            # UPDATE only: recovery must never provision credentials or approve an employee.
            cursor.execute("""UPDATE so_employee_credentials SET password_hash=%s,version=%s
                WHERE business_id=%s AND employee_id=%s""",
                (hashed, uuid.uuid4().hex, business, value['employee_id']))
            cursor.execute("""UPDATE so_employee_invites SET consumed_at=NOW(),status='revoked'
                WHERE business_id=%s AND employee_id=%s AND consumed_at IS NULL""",
                (business, value['employee_id']))
            cursor.execute("UPDATE so_employee_invites SET status='accepted' WHERE id=%s", (value['id'],))
    return True
