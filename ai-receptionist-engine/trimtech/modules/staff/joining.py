"""Company-scoped bearer links; registrations confer no access before manager approval."""
import re
import secrets
import uuid
from decimal import Decimal, InvalidOperation
from psycopg2.extras import RealDictCursor
from trimtech.modules.staff import accounts, agency, onboarding, joining_migration
from trimtech.modules.staff.database import transaction, fetch_all, fetch_one

def phone_number(value):
    value=re.sub(r'[^0-9+]','',str(value or ''))
    if value.startswith('+44'): value='0'+value[3:]
    elif value.startswith('0044'): value='0'+value[4:]
    if not re.fullmatch(r'\+?\d{7,15}',value):
        raise ValueError('Enter a valid phone number with its country code where needed.')
    return value

def _check(cursor):
    joining_migration.verify(cursor)

def _link(cursor,raw):
    if not isinstance(raw,str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}',raw):
        raise ValueError('This joining link is invalid, expired or revoked. Ask your employer for a new link.')
    cursor.execute("""SELECT l.id,l.business_id,b.name FROM sj_links l JOIN sm_businesses b ON b.id=l.business_id
        WHERE l.token_hash=%s AND l.revoked_at IS NULL AND l.expires_at>NOW() AND b.active""",(accounts.digest(raw),))
    row=cursor.fetchone()
    if not row: raise ValueError('This joining link is invalid, expired or revoked. Ask your employer for a new link.')
    return row

def generate(business_id,days,actor):
    try: days=int(days)
    except (ValueError,TypeError): raise ValueError('Choose an expiry between 1 and 30 days.') from None
    if not 1<=days<=30: raise ValueError('Choose an expiry between 1 and 30 days.')
    raw=secrets.token_urlsafe(32)
    with transaction() as connection:
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            _check(cursor); agency.lock_business(cursor,business_id)
            cursor.execute('SELECT id FROM sm_businesses WHERE id=%s AND active',(business_id,))
            if not cursor.fetchone(): raise ValueError('Business is unavailable.')
            cursor.execute('UPDATE sj_links SET revoked_at=NOW() WHERE business_id=%s AND revoked_at IS NULL',(business_id,))
            cursor.execute("INSERT INTO sj_links(id,business_id,token_hash,expires_at) VALUES (%s,%s,%s,NOW()+%s*INTERVAL '1 day')",(uuid.uuid4().hex,business_id,accounts.digest(raw),days))
            agency.audit(cursor,business_id,actor,'joining_link_generated','joining_link',None,None,{'expiry_days':days},'Employer generated employee joining link; previous link revoked.')
    return raw

def revoke(business_id,actor):
    with transaction() as connection:
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            _check(cursor); agency.lock_business(cursor,business_id)
            cursor.execute('UPDATE sj_links SET revoked_at=NOW() WHERE business_id=%s AND revoked_at IS NULL',(business_id,))
            agency.audit(cursor,business_id,actor,'joining_link_revoked','joining_link',None,None,None,'Employer revoked employee joining link.')

def preview(raw):
    with transaction() as connection:
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            _check(cursor)
            row=_link(cursor,raw)
            if onboarding.access(row['business_id'])['state'] in {'expired','pending'}:
                raise ValueError('Employee joining is currently unavailable. Contact your employer.')
            return row['name']

def _duplicate(cursor,business_id,email,phone):
    cursor.execute('SELECT email,phone FROM staff_employees WHERE business_id=%s',(business_id,))
    for employee in cursor.fetchall():
        try: existing=phone_number(employee['phone'])
        except ValueError: existing=employee['phone']
        if (employee['email'] or '').strip().lower()==email or existing==phone:
            raise ValueError('A registration or employee record already exists. Contact your manager.')

def register(raw,values):
    name=str(values.get('full_name') or '').strip()
    email=accounts.email_address(values.get('email'))
    phone=phone_number(values.get('phone'))
    if not 1<=len(name)<=150: raise ValueError('Enter your full name, up to 150 characters.')
    if any(key in values for key in ('business_id','role','hourly_rate','status','employee_id','approved','permissions')):
        raise ValueError('Company access and employment settings are controlled by your manager.')
    hashed=accounts.password_hash(values.get('password'))
    with transaction() as connection:
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            _check(cursor); row=_link(cursor,raw); agency.lock_business(cursor,row['business_id']); row=_link(cursor,raw)
            if onboarding.access(row['business_id'])['state'] in {'expired','pending'}:
                raise ValueError('Employee joining is currently unavailable. Contact your employer.')
            _duplicate(cursor,row['business_id'],email,phone)
            cursor.execute('SELECT id FROM sj_registrations WHERE business_id=%s AND (email=%s OR phone=%s)',(row['business_id'],email,phone))
            if cursor.fetchone(): raise ValueError('A registration or employee record already exists. Contact your manager.')
            cursor.execute("INSERT INTO sj_registrations(id,business_id,link_id,full_name,email,phone,password_hash) VALUES (%s,%s,%s,%s,%s,%s,%s)",(uuid.uuid4().hex,row['business_id'],row['id'],name,email,phone,hashed))

def review(business_id,ids,decision,rate,actor):
    ids=list(ids)
    if not 1<=len(ids)<=100 or any(not isinstance(value,str) or not re.fullmatch('[a-f0-9]{32}',value) for value in ids) or len(set(ids))!=len(ids):
        raise ValueError('Select between 1 and 100 different pending registrations.')
    if decision not in {'approve','reject'}: raise ValueError('Choose approve or reject.')
    amount=None
    if decision=='approve':
        try: amount=Decimal(str(rate))
        except (InvalidOperation,ValueError): raise ValueError('Enter a valid employer-approved hourly rate.') from None
        if not amount.is_finite() or not 0<=amount<=Decimal('99999999.99') or amount!=amount.quantize(Decimal('.01')):
            raise ValueError('Enter a nonnegative hourly rate with at most two decimal places.')
    with transaction() as connection:
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            _check(cursor); agency.lock_business(cursor,business_id)
            cursor.execute("SELECT * FROM sj_registrations WHERE business_id=%s AND id=ANY(%s) AND status='pending' ORDER BY id FOR UPDATE",(business_id,ids))
            rows=cursor.fetchall()
            if len(rows)!=len(ids): raise ValueError('One or more selections are unavailable or already reviewed. Refresh before trying again.')
            # Existing manual creation/edit uses normal table writes, not our business lock.
            # Serialize approval with those writes before checking for duplicates.
            if decision=='approve': cursor.execute('LOCK TABLE staff_employees IN SHARE ROW EXCLUSIVE MODE')
            for row in rows:
                employee_id=None
                if decision=='approve':
                    _duplicate(cursor,business_id,row['email'],row['phone'])
                    cursor.execute("INSERT INTO staff_employees(business_id,full_name,phone,email,role,hourly_rate,status) VALUES (%s,%s,%s,%s,'staff',%s,'active') RETURNING id",(business_id,row['full_name'],row['phone'],row['email'],amount))
                    employee_id=cursor.fetchone()['id']
                    cursor.execute('INSERT INTO so_employee_credentials(employee_id,business_id,password_hash,version) VALUES (%s,%s,%s,%s)',(employee_id,business_id,row['password_hash'],uuid.uuid4().hex))
                cursor.execute('UPDATE sj_registrations SET status=%s,employee_id=%s,password_hash=NULL,reviewed_by=%s,reviewed_at=NOW() WHERE id=%s AND business_id=%s',('approved' if decision=='approve' else 'rejected',employee_id,actor,row['id'],business_id))
                agency.audit(cursor,business_id,actor,'employee_registration_'+decision,'registration',None,None,{'registration_id':row['id'],'employee_id':employee_id},'Manager reviewed employee joining request.')

def available():
    return bool(fetch_one("SELECT to_regclass('sj_schema_migrations') IS NOT NULL AS installed")['installed'])

def manager_data(business_id):
    if not available(): return {'available':False,'registrations':[],'link':None}
    with transaction() as connection:
        with connection.cursor() as cursor: _check(cursor)
    return dict(available=True,registrations=fetch_all('SELECT id,full_name,email,phone,status,created_at FROM sj_registrations WHERE business_id=%s ORDER BY (status=\'pending\') DESC,created_at DESC',(business_id,)),link=fetch_one('SELECT expires_at FROM sj_links WHERE business_id=%s AND revoked_at IS NULL AND expires_at>NOW()',(business_id,)))

def counts(business_id):
    counts=fetch_one("""SELECT (SELECT COUNT(*) FROM staff_employees WHERE business_id=%s AND status='active') AS active,
        (SELECT COUNT(*) FROM staff_employees e WHERE e.business_id=%s AND e.status='active' AND NOT EXISTS (SELECT 1 FROM so_employee_credentials c WHERE c.employee_id=e.id AND c.business_id=e.business_id) AND EXISTS (SELECT 1 FROM so_employee_invites i WHERE i.business_id=e.business_id AND i.employee_id=e.id AND i.consumed_at IS NULL AND i.expires_at>NOW() AND i.status='accepted_by_provider')) AS awaiting""",(business_id,business_id))
    counts.update(pending=0,rejected=0)
    if available():
        counts.update(fetch_one("SELECT COUNT(*) FILTER(WHERE status='pending') AS pending,COUNT(*) FILTER(WHERE status='rejected') AS rejected FROM sj_registrations WHERE business_id=%s",(business_id,)))
    return counts
