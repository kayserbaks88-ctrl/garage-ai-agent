"""Platform-owner edits of a business name and contact email.

Touches only sm_businesses.name and sd_contacts for the given business; never employee,
payroll or login (sm_administrators) records.
"""
from psycopg2.extras import RealDictCursor

from trimtech.modules.staff import accounts, agency, business_contact_migration as contact_migration
from trimtech.modules.staff.database import transaction

NAME_MAX = 160


def _contact(cursor, business_id):
    if not contact_migration.present(cursor):
        return None
    cursor.execute('SELECT contact_email FROM sd_contacts WHERE business_id=%s', (business_id,))
    row = cursor.fetchone()
    return row['contact_email'] if row else None


def current(business_id):
    with transaction() as connection:
        connection.set_session(readonly=True)
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute('SELECT id,name FROM sm_businesses WHERE id=%s', (business_id,))
            row = cursor.fetchone()
            if not row:
                return None
            ready = contact_migration.present(cursor)
            return dict(row, contact_email=_contact(cursor, business_id), contact_ready=ready)


def update(business_id, actor, values):
    name = str(values.get('name') or '').strip()
    email_text = str(values.get('contact_email') or '').strip()
    reason = str(values.get('reason') or '').strip()
    if not 1 <= len(name) <= NAME_MAX or any(ord(c) < 32 for c in name):
        raise ValueError('Enter a business name of 1 to %d characters.' % NAME_MAX)
    email = accounts.email_address(email_text) if email_text else None
    if not reason or len(reason) > 1000:
        raise ValueError('Enter a reason of up to 1000 characters.')
    with transaction() as connection:
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            agency.lock_business(cursor, business_id)
            cursor.execute('SELECT name FROM sm_businesses WHERE id=%s FOR UPDATE', (business_id,))
            row = cursor.fetchone()
            if not row:
                raise ValueError('Business unavailable.')
            ready = contact_migration.present(cursor)
            if ready:
                with connection.cursor() as plain:
                    contact_migration.verify(plain)
            old = {'name': row['name'], 'contact_email': _contact(cursor, business_id)}
            if email != old['contact_email'] and not ready:
                raise ValueError('Contact email storage is not installed yet; apply the business contact migration.')
            new = {'name': name, 'contact_email': email if ready else None}
            if new == old:
                raise ValueError('No changes to save.')
            if name != old['name']:
                cursor.execute('UPDATE sm_businesses SET name=%s WHERE id=%s', (name, business_id))
            if ready and email != old['contact_email']:
                if email is None:
                    cursor.execute('DELETE FROM sd_contacts WHERE business_id=%s', (business_id,))
                else:
                    cursor.execute("""INSERT INTO sd_contacts(business_id,contact_email,updated_by) VALUES (%s,%s,%s)
                        ON CONFLICT(business_id) DO UPDATE SET contact_email=EXCLUDED.contact_email,
                        updated_by=EXCLUDED.updated_by,updated_at=NOW()""", (business_id, email, actor))
            agency.audit(cursor, business_id, actor, 'business_details_updated', 'business_details',
                         None, old, new, reason)
    return new
