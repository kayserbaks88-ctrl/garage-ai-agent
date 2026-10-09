"""Operator-only, dry-run-first provisioning of explicitly approved legacy Staff owners.

No web route, legacy account edits, password resets, verification bypass or email sends.
"""
import argparse
import hashlib
import json
import re
import secrets
import uuid
from pathlib import Path

from psycopg2 import Error as PostgreSQLError
from psycopg2.extras import RealDictCursor

from trimtech.modules.staff import accounts, accounts_migration
from trimtech.modules.staff.database import transaction, StaffDatabaseError
from trimtech.modules.staff.migrations import verify as verify_staff


class ProvisionError(ValueError):
    pass


def manifest(document):
    if not isinstance(document,dict) or set(document)!={'operator','reason','owners'}:
        raise ProvisionError('Manifest requires operator, reason and owners only.')
    operator=str(document['operator']).strip()
    reason=str(document['reason']).strip()
    if not 1<=len(operator)<=160 or not 10<=len(reason)<=1000:
        raise ProvisionError('Provide an operator and a meaningful ownership-verification reason.')
    entries=document['owners']
    if not isinstance(entries,list) or not 1<=len(entries)<=100:
        raise ProvisionError('Provide between 1 and 100 explicitly verified owners.')
    owners=[]
    seen=set()
    for entry in entries:
        if not isinstance(entry,dict) or set(entry)!={'business_id','business_name','contact_name','email'}:
            raise ProvisionError('Each owner requires business_id, business_name, contact_name and email only.')
        business_id=str(entry['business_id']).strip()
        if not re.fullmatch('[a-z0-9][a-z0-9_-]{0,99}',business_id) or business_id in seen:
            raise ProvisionError('Business IDs must be unique, exact lowercase existing Staff IDs.')
        name=str(entry['business_name']).strip()
        contact=str(entry['contact_name']).strip()
        if not 1<=len(name)<=160 or not 1<=len(contact)<=160:
            raise ProvisionError('Business and contact names must be 1-160 characters.')
        owners.append(dict(business_id=business_id,business_name=name,contact_name=contact,email=accounts.email_address(entry['email'])))
        seen.add(business_id)
    canonical=dict(operator=operator,reason=reason,owners=sorted(owners,key=lambda entry:entry['business_id']))
    fingerprint=hashlib.sha256(json.dumps(canonical,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return canonical,fingerprint


def _inspect(cursor,entry):
    business_id,email=entry['business_id'],entry['email']
    cursor.execute("""SELECT EXISTS(SELECT 1 FROM staff_employees WHERE business_id=%s)
        OR EXISTS(SELECT 1 FROM staff_sites WHERE business_id=%s)
        OR EXISTS(SELECT 1 FROM staff_business_settings WHERE business_id=%s)
        OR EXISTS(SELECT 1 FROM staff_settings WHERE business_id=%s) AS known""",(business_id,)*4)
    if not cursor.fetchone()['known']:
        raise ProvisionError('A requested business has no existing Staff records; registration or separate review is required.')
    cursor.execute('SELECT * FROM sm_businesses WHERE id=%s',(business_id,))
    business=cursor.fetchone()
    if business and not business['active']:
        raise ProvisionError('Inactive businesses cannot be reactivated by provisioning.')
    cursor.execute('SELECT * FROM sm_administrators WHERE email=%s',(email,))
    administrator=cursor.fetchone()
    if administrator and not administrator['active']:
        raise ProvisionError('Inactive administrators cannot be reactivated by provisioning.')
    cursor.execute("""SELECT a.email,m.active,m.role FROM sm_memberships m
        JOIN sm_administrators a ON a.id=m.administrator_id WHERE m.business_id=%s""",(business_id,))
    memberships=cursor.fetchall()
    if any(row['role']=='owner' and row['email']!=email for row in memberships):
        raise ProvisionError('Business already has a different owner; explicit ownership transfer is required.')
    matched=next((row for row in memberships if row['email']==email),None)
    if matched and (not matched['active'] or matched['role']!='owner'):
        raise ProvisionError('Provisioning cannot reactivate or elevate an existing membership.')
    return business,administrator,matched


def provision(document,apply=False,confirmation=None):
    document,fingerprint=manifest(document)
    if apply and confirmation!=fingerprint:
        raise ProvisionError('Apply requires the exact manifest SHA-256 printed by the dry run.')
    report=[]
    with transaction() as connection:
        with connection.cursor() as cursor:
            if not apply:
                cursor.execute('SET TRANSACTION READ ONLY')
            else:
                # Same lock as identity migration; serializes concurrent provisioning runs.
                cursor.execute('SELECT pg_advisory_xact_lock(731942024)')
            verify_staff(cursor)
            accounts_migration.verify(cursor)
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            for entry in document['owners']:
                business,administrator,matched=_inspect(cursor,entry)
                report.append(dict(business_id=entry['business_id'],
                    account='reuse existing Staff administrator' if administrator else 'create unverified Staff administrator',
                    membership='unchanged' if matched else 'add owner membership',
                    next_action='sign in with existing Staff credentials' if administrator and administrator['verified_at'] else 'owner requests verification and chooses their own password'))
                if not apply:
                    continue
                if not business:
                    cursor.execute('INSERT INTO sm_businesses(id,name) VALUES (%s,%s)',(entry['business_id'],entry['business_name']))
                if not administrator:
                    administrator_id=uuid.uuid4().hex
                    # No usable password is distributed. The owner must verify their email and set one.
                    cursor.execute("""INSERT INTO sm_administrators(id,email,contact_name,password_hash)
                        VALUES (%s,%s,%s,%s) ON CONFLICT(email) DO NOTHING""",
                        (administrator_id,entry['email'],entry['contact_name'],accounts.password_hash(secrets.token_urlsafe(32))))
                cursor.execute('SELECT id,active FROM sm_administrators WHERE email=%s FOR UPDATE',(entry['email'],))
                administrator=cursor.fetchone()
                if not administrator or not administrator['active']:
                    raise ProvisionError('Administrator state changed; repeat the dry run.')
                cursor.execute("""INSERT INTO sm_memberships(administrator_id,business_id,role)
                    VALUES (%s,%s,'owner') ON CONFLICT(administrator_id,business_id) DO NOTHING""",
                    (administrator['id'],entry['business_id']))
                cursor.execute("""INSERT INTO sm_owner_provisions(business_id,administrator_id,operator,reason,manifest_hash)
                    VALUES (%s,%s,%s,%s,%s) ON CONFLICT(business_id,administrator_id) DO NOTHING""",
                    (entry['business_id'],administrator['id'],document['operator'],document['reason'],fingerprint))
        with connection.cursor() as cursor:
            verify_staff(cursor)
            accounts_migration.verify(cursor)
    return dict(mode='applied' if apply else 'read-only dry run',manifest_sha256=fingerprint,owners=report)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',required=True,help='Private reviewed JSON file; never a password file.')
    parser.add_argument('--apply',action='store_true',help='Write only after a reviewed dry run and explicit approval.')
    parser.add_argument('--confirm-sha256',help='Exact manifest hash from dry run.')
    args=parser.parse_args(argv)
    try:
        path=Path(args.manifest)
        if path.stat().st_size>100000:
            raise ProvisionError('Manifest is too large.')
        result=provision(json.loads(path.read_text(encoding='utf-8-sig')),args.apply,args.confirm_sha256)
    except ProvisionError as error:
        print(f'STOP: {error} No changes committed.')
        return 1
    except (ValueError,OSError,StaffDatabaseError,PostgreSQLError):
        # Driver exceptions and manifests can contain private data; never echo them.
        print('STOP: provisioning validation/database check failed. No changes committed. Review the manifest, migration state and ownership conflicts.')
        return 1
    print(json.dumps(result,indent=2))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
