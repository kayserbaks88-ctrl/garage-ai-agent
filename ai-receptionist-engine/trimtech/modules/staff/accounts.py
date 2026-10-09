"""Staff-only PostgreSQL identities. No legacy dashboard privileges or automatic DDL."""
import hashlib
import hmac
import logging
import re
import secrets
import uuid
from html import escape
from urllib.parse import urlsplit

from psycopg2.extras import RealDictCursor
from werkzeug.security import check_password_hash, generate_password_hash

from integrations.email_helper import send_staff_email
from trimtech.modules.staff.database import transaction, fetch_one, execute
from trimtech.modules.staff.accounts_migration import verify as verify_identity
from trimtech.modules.staff import onboarding, onboarding_migration

logger = logging.getLogger(__name__)
# Equal password-hash work for unknown and known login identities.
DUMMY_HASH = generate_password_hash(secrets.token_urlsafe(32))


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def email_address(value):
    value = str(value or '').strip().lower()
    if len(value)>254 or not re.fullmatch(r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.[a-z]{2,63}", value):
        raise ValueError('Enter a valid email address.')
    return value


def password_hash(value):
    if not isinstance(value,str) or not 12 <= len(value) <= 128:
        raise ValueError('Use a password between 12 and 128 characters.')
    return generate_password_hash(value)


def limited(action, identity, address, secret):
    """Shared fixed-window limits, atomically incremented across web workers."""
    keys = [(action+':address:'+address,30), (action+':identity:'+identity,5)]
    allowed = True
    with transaction() as connection:
        with connection.cursor() as cursor:
            verify_identity(cursor)
            cursor.execute("DELETE FROM sm_rate_limits WHERE window_started < NOW()-INTERVAL '1 day'")
            for key, limit in sorted(keys):
                key_hash = hmac.new(secret.encode(), key.encode(), hashlib.sha256).hexdigest()
                cursor.execute("""INSERT INTO sm_rate_limits(key_hash,window_started,attempts) VALUES (%s,NOW(),1)
                    ON CONFLICT(key_hash) DO UPDATE SET
                    attempts=CASE WHEN sm_rate_limits.window_started<NOW()-INTERVAL '15 minutes'
                        THEN 1 ELSE sm_rate_limits.attempts+1 END,
                    window_started=CASE WHEN sm_rate_limits.window_started<NOW()-INTERVAL '15 minutes'
                        THEN NOW() ELSE sm_rate_limits.window_started END RETURNING attempts""", (key_hash,))
                allowed = cursor.fetchone()[0] <= limit and allowed
    return allowed


def _token(cursor, administrator_id, purpose):
    raw = secrets.token_urlsafe(32)
    # Keep previous verification links usable until expiry; delivery failures must not invalidate them.
    cursor.execute("""INSERT INTO sm_tokens(token_hash,administrator_id,purpose,expires_at)
        VALUES (%s,%s,%s,NOW()+INTERVAL '1 hour')""", (digest(raw),administrator_id,purpose))
    return raw


def register(name, contact, email, password):
    name, contact = str(name or '').strip(), str(contact or '').strip()
    if not 1 <= len(name) <=160 or not 1 <= len(contact) <=160:
        raise ValueError('Enter a business name and contact name, each up to 160 characters.')
    email = email_address(email)
    hashed = password_hash(password)
    administrator_id = uuid.uuid4().hex
    business_id = 'sm-' + uuid.uuid4().hex
    with transaction() as connection:
        with connection.cursor() as cursor:
            onboarding_migration.verify(cursor)
            cursor.execute("""INSERT INTO sm_administrators(id,email,contact_name,password_hash)
                VALUES (%s,%s,%s,%s) ON CONFLICT(email) DO NOTHING RETURNING id""",
                (administrator_id,email,contact,hashed))
            if not cursor.fetchone():
                return None
            cursor.execute('INSERT INTO sm_businesses(id,name) VALUES (%s,%s)',(business_id,name))
            cursor.execute('INSERT INTO sm_memberships(administrator_id,business_id) VALUES (%s,%s)',
                           (administrator_id,business_id))
            onboarding.begin(cursor,business_id,administrator_id)
            token = _token(cursor,administrator_id,'verify')
    return email, token


def request_token(email, purpose):
    email = email_address(email)
    with transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute('SELECT id,verified_at FROM sm_administrators WHERE email=%s AND active FOR UPDATE',(email,))
            row = cursor.fetchone()
            if not row or (purpose=='verify' and row[1]) or (purpose=='reset' and not row[1]):
                return None
            return email, _token(cursor,row[0],purpose)


def consume(raw, purpose, password=None):
    if not isinstance(raw,str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}',raw):
        return False
    hashed = password_hash(password)
    with transaction() as connection:
        with connection.cursor() as cursor:
            # Serialize on the administrator before testing tokens, including different tokens for one identity.
            cursor.execute("""SELECT a.id FROM sm_administrators a JOIN sm_tokens t ON t.administrator_id=a.id
                WHERE t.token_hash=%s AND t.purpose=%s AND a.active FOR UPDATE OF a""",(digest(raw),purpose))
            row = cursor.fetchone()
            if not row:
                return False
            administrator_id = row[0]
            cursor.execute("""UPDATE sm_tokens SET consumed_at=NOW() WHERE token_hash=%s AND purpose=%s
                AND consumed_at IS NULL AND expires_at>NOW() RETURNING administrator_id""",(digest(raw),purpose))
            if not cursor.fetchone():
                return False
            if purpose=='verify':
                cursor.execute('UPDATE sm_administrators SET verified_at=COALESCE(verified_at,NOW()),password_hash=%s WHERE id=%s', (hashed,administrator_id))
                onboarding.activate(cursor,administrator_id)
            else:
                cursor.execute('UPDATE sm_administrators SET password_hash=%s WHERE id=%s AND verified_at IS NOT NULL',
                               (hashed,administrator_id))
                cursor.execute('DELETE FROM sm_sessions WHERE administrator_id=%s',(administrator_id,))
            cursor.execute('UPDATE sm_tokens SET consumed_at=NOW() WHERE administrator_id=%s AND purpose=%s AND consumed_at IS NULL',
                           (administrator_id,purpose))
    return True


def authenticate(email, password):
    email = email_address(email)
    if not isinstance(password,str) or len(password)>128:
        return None
    with transaction() as connection:
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute('SELECT * FROM sm_administrators WHERE email=%s FOR UPDATE',(email,))
            administrator = cursor.fetchone()
            matches = check_password_hash(administrator['password_hash'] if administrator else DUMMY_HASH,password)
            if not matches or not administrator or not administrator['active'] or not administrator['verified_at']:
                return None
            raw = secrets.token_urlsafe(32)
            cursor.execute("DELETE FROM sm_sessions WHERE expires_at<=NOW()")
            cursor.execute("""INSERT INTO sm_sessions(token_hash,administrator_id,expires_at)
                VALUES (%s,%s,NOW()+INTERVAL '8 hours')""",(digest(raw),administrator['id']))
            return raw


def current(raw):
    if not isinstance(raw,str) or len(raw)!=43:
        return None
    with transaction() as connection:
        with connection.cursor() as cursor:
            verify_identity(cursor)
    return fetch_one("""SELECT a.id,a.contact_name FROM sm_sessions s
        JOIN sm_administrators a ON a.id=s.administrator_id WHERE s.token_hash=%s
        AND s.expires_at>NOW() AND a.active AND a.verified_at IS NOT NULL""",(digest(raw),))


def membership(administrator_id,business_id):
    return fetch_one("""SELECT m.role,b.name FROM sm_memberships m JOIN sm_businesses b ON b.id=m.business_id
        WHERE m.administrator_id=%s AND m.business_id=%s AND m.active AND b.active""",(administrator_id,business_id))


def revoke(raw):
    if isinstance(raw,str):
        execute('DELETE FROM sm_sessions WHERE token_hash=%s',(digest(raw),))


def send_link(details,purpose,base):
    if not details:
        return
    email, token = details
    parsed = urlsplit(base)
    if parsed.scheme!='https' or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
        logger.warning('Staff account email failed: reason=public_url_configuration')
        return
    action = 'Verify your email' if purpose=='verify' else 'Reset your password'
    # Fragments are not sent to servers or included in HTTP access logs/referrers.
    link = base.rstrip('/')+'/staff/account/'+purpose+'#token='+token
    logger.info('Staff account email attempted: purpose=%s',purpose)
    try:
        sent, _, _ = send_staff_email(email,action+' - TrimTech Staff Manager',
            f'{action}: {link}\nThis link expires in one hour. If needed, paste this code into the form: {token}',
            f'<p><a href="{escape(link,quote=True)}">{action}</a></p><p>This link expires in one hour. Ignore this email if you did not request it.</p>',
            'staff-account-'+purpose+'-'+digest(token))
    except Exception:
        sent = False
    logger.info('Staff account email %s: purpose=%s', 'accepted_by_provider' if sent else 'failed',purpose)
