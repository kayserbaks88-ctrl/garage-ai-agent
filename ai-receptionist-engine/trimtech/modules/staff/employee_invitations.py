"""Single-use employee password invitations through the existing Resend transport."""
import logging
import secrets
import uuid
from html import escape
from urllib.parse import urlsplit
from psycopg2.extras import RealDictCursor
from werkzeug.security import check_password_hash
from trimtech.modules.staff import accounts, agency
from trimtech.modules.staff.database import transaction, fetch_one
from integrations.email_helper import send_staff_email

logger=logging.getLogger(__name__)


def invite(business_id,employee_id,base):
    parsed=urlsplit(base)
    if parsed.scheme!='https' or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('Invitation email is temporarily unavailable. Please try again later.')
    raw=secrets.token_urlsafe(32); identifier=uuid.uuid4().hex
    with transaction() as connection:
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            agency.lock_business(cursor,business_id)
            cursor.execute("SELECT id,email,full_name FROM staff_employees WHERE business_id=%s AND id=%s AND status='active' FOR UPDATE",(business_id,employee_id))
            employee=cursor.fetchone()
            if not employee:
                raise ValueError('Choose an active employee in this business.')
            email=accounts.email_address(employee['email'])
            cursor.execute("UPDATE so_employee_invites SET status='revoked',consumed_at=NOW() WHERE business_id=%s AND employee_id=%s AND consumed_at IS NULL",(business_id,employee_id))
            cursor.execute("""INSERT INTO so_employee_invites(id,token_hash,employee_id,business_id,email,expires_at)
                VALUES (%s,%s,%s,%s,%s,NOW()+INTERVAL '48 hours')""",(identifier,accounts.digest(raw),employee_id,business_id,email))
    link=base.rstrip('/')+'/staff/employee-invite#token='+raw
    logger.info('Staff employee invitation attempted: invitation=%s',identifier)
    try:
        sent,_,_=send_staff_email(email,'Your Staff Manager invitation',
            f'Set your Staff Manager password: {link}\nThis link expires in 48 hours. Verification code: {raw}',
            f'<p>You have been invited to Staff Manager.</p><p><a href="{escape(link,quote=True)}">Set your password</a></p><p>This link expires in 48 hours.</p>',
            'staff-employee-invite-'+identifier)
    except Exception:
        sent=False
    with transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute("UPDATE so_employee_invites SET status=%s WHERE id=%s AND status='pending'",('accepted_by_provider' if sent else 'failed',identifier))
    logger.info('Staff employee invitation %s: invitation=%s','accepted_by_provider' if sent else 'failed',identifier)
    return sent


def accept(raw,password):
    if not isinstance(raw,str) or len(raw)!=43:
        raise ValueError('This invitation is invalid or expired. Ask your manager for a new invitation.')
    hashed=accounts.password_hash(password)
    with transaction() as connection:
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute('SELECT business_id FROM so_employee_invites WHERE token_hash=%s',(accounts.digest(raw),))
            scope=cursor.fetchone()
            if not scope:
                raise ValueError('This invitation is invalid or expired.')
            agency.lock_business(cursor,scope['business_id'])
            cursor.execute("""SELECT i.* FROM so_employee_invites i JOIN staff_employees e ON e.id=i.employee_id AND e.business_id=i.business_id
                JOIN sm_businesses b ON b.id=i.business_id WHERE i.token_hash=%s AND i.consumed_at IS NULL
                AND i.expires_at>NOW() AND e.status='active' AND b.active AND lower(btrim(e.email))=i.email FOR UPDATE OF i,e""",(accounts.digest(raw),))
            invitation=cursor.fetchone()
            if not invitation:
                raise ValueError('This invitation is invalid, expired or already used.')
            cursor.execute("""INSERT INTO so_employee_credentials(employee_id,business_id,password_hash,version)
                VALUES (%s,%s,%s,%s) ON CONFLICT(employee_id) DO UPDATE SET password_hash=EXCLUDED.password_hash,
                version=EXCLUDED.version,activated_at=NOW()""",(invitation['employee_id'],invitation['business_id'],hashed,uuid.uuid4().hex))
            cursor.execute("UPDATE so_employee_invites SET consumed_at=NOW(),status='accepted' WHERE id=%s",(invitation['id'],))
            return invitation['business_id']


def credential(business_id,employee_id):
    return fetch_one('SELECT password_hash,version FROM so_employee_credentials WHERE business_id=%s AND employee_id=%s',(business_id,employee_id))


def matches(credential,password):
    if not isinstance(password,str) or len(password)>128:
        return False
    return check_password_hash(credential['password_hash'] if credential else accounts.DUMMY_HASH,password) and bool(credential)
