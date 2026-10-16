"""Tenant-scoped employee identifiers; never resolve ambiguous email/phone matches."""
import re
from trimtech.modules.staff import accounts
from trimtech.modules.staff.database import fetch_all

PHONE_SQL = r"regexp_replace(regexp_replace(COALESCE(e.phone,''), '[^0-9+]', '', 'g'), '^(\+44|0044)', '0')"


def phone(value):
    value = re.sub(r'[^0-9+]', '', str(value or ''))
    if value.startswith('+44'):
        value = '0' + value[3:]
    elif value.startswith('0044'):
        value = '0' + value[4:]
    return value


def identifier(value):
    value = str(value or '').strip()
    if '@' in value:
        return 'email', accounts.email_address(value)
    normalized = phone(value)
    if not normalized or len(normalized) > 40 or not any(c.isdigit() for c in normalized):
        raise ValueError('Enter your email address or phone number.')
    return 'phone', normalized


def find(business, kind, value):
    condition = 'lower(btrim(e.email))=%s' if kind == 'email' else PHONE_SQL + '=%s'
    rows = fetch_all("SELECT e.id,e.payroll_number FROM staff_employees e WHERE e.business_id=%s "
                     "AND e.status='active' AND " + condition + ' LIMIT 2', (business, value))
    return rows[0] if len(rows) == 1 else None
