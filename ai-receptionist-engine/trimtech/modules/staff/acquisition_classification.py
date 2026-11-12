"""Explicit owner classification, recorded in the existing business audit ledger."""
from psycopg2.extras import RealDictCursor

from trimtech.modules.staff import agency
from trimtech.modules.staff.database import transaction


def change(business_id, actor, values):
    action = values.get('action')
    reason = str(values.get('reason') or '').strip()
    if action not in ('mark_test', 'clear_test'):
        raise ValueError('Choose a valid test classification.')
    if not reason or len(reason) > 1000:
        raise ValueError('Enter a reason of up to 1000 characters.')
    if values.get('confirmation') != business_id:
        raise ValueError('Type the business ID to confirm this action.')
    with transaction() as connection:
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            agency.lock_business(cursor, business_id)
            cursor.execute('SELECT id FROM sm_businesses WHERE id=%s FOR UPDATE', (business_id,))
            if not cursor.fetchone():
                raise ValueError('Business unavailable.')
            cursor.execute("""SELECT action FROM staff_audit WHERE business_id=%s
                AND entity_type='acquisition_classification' ORDER BY id DESC LIMIT 1""", (business_id,))
            previous = cursor.fetchone()
            was_test = bool(previous and previous['action'] == 'mark_test')
            agency.audit(cursor, business_id, actor, action, 'acquisition_classification', None,
                         {'is_test': was_test}, {'is_test': action == 'mark_test'}, reason)
