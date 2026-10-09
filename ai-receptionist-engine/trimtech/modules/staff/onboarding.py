"""Card-free trials and a checklist over the existing Staff records."""
from psycopg2.extras import RealDictCursor, Json
from trimtech.modules.staff.database import transaction, fetch_one
from trimtech.modules.staff import onboarding_migration

STEPS=('company','sites','employees','invitations','assignments','payroll','review')


def begin(cursor,business_id,administrator_id):
    # Called in the same transaction as registration; existing provisioned accounts are not enrolled.
    cursor.execute('INSERT INTO so_trials(business_id,administrator_id) VALUES (%s,%s)',(business_id,administrator_id))
    cursor.execute('INSERT INTO so_setup(business_id) VALUES (%s)',(business_id,))


def activate(cursor,administrator_id):
    cursor.execute("""SELECT t.business_id,a.email FROM so_trials t JOIN sm_administrators a ON a.id=t.administrator_id
        WHERE t.administrator_id=%s AND t.starts_at IS NULL AND a.verified_at IS NOT NULL FOR UPDATE OF t""",(administrator_id,))
    rows=cursor.fetchall()
    for business_id,email in rows:
        cursor.execute('INSERT INTO so_trial_claims(email,business_id) VALUES (%s,%s) ON CONFLICT DO NOTHING RETURNING business_id',(email,business_id))
        if cursor.fetchone():
            cursor.execute("UPDATE so_trials SET starts_at=NOW(),ends_at=NOW()+INTERVAL '336 hours' WHERE business_id=%s AND starts_at IS NULL",(business_id,))


def status(business_id):
    row=fetch_one("""SELECT starts_at,ends_at,
        CASE WHEN starts_at IS NULL THEN 'pending' WHEN NOW()>=ends_at THEN 'expired' ELSE 'active' END AS state,
        CASE WHEN ends_at>NOW() THEN CEIL(EXTRACT(EPOCH FROM ends_at-NOW())/86400)::integer ELSE 0 END AS days
        FROM so_trials WHERE business_id=%s""",(business_id,))
    return row or dict(state='legacy',days=None,starts_at=None,ends_at=None)


def access(business_id):
    """Keep the original trial dates; subscription payment never restarts a trial."""
    from trimtech.modules.staff.billing import entitlement
    trial = status(business_id)
    subscription = entitlement(business_id)
    if subscription['paid']:
        return {**trial, 'state':'paid'}
    if trial['state'] == 'legacy' and subscription['managed']:
        return {**trial, 'state':'expired'}
    return trial


def checklist(business_id):
    row=fetch_one('SELECT * FROM so_setup WHERE business_id=%s',(business_id,))
    if row is None:
        return None
    facts=fetch_one("""SELECT
        (SELECT COUNT(*) FROM staff_sites WHERE business_id=%s AND active AND COALESCE(address,'')<>'' AND latitude IS NOT NULL AND longitude IS NOT NULL) AS sites,
        (SELECT COUNT(*) FROM staff_employees WHERE business_id=%s AND status='active') AS employees,
        (SELECT COUNT(*) FROM staff_employees e WHERE e.business_id=%s AND e.status='active' AND NOT EXISTS
            (SELECT 1 FROM so_employee_credentials c WHERE c.business_id=e.business_id AND c.employee_id=e.id)) AS uninvited,
        (SELECT COUNT(*) FROM staff_assignments WHERE business_id=%s AND status='scheduled') AS assignments,
        (SELECT COUNT(*) FROM staff_employees e WHERE e.business_id=%s AND e.status='active' AND NOT EXISTS
            (SELECT 1 FROM staff_payroll_profiles p WHERE p.business_id=e.business_id AND p.employee_id=e.id AND p.reviewed_by<>'')) AS unreviewed
        """,(business_id,)*5)
    mode=fetch_one('SELECT organisation_mode FROM staff_settings WHERE business_id=%s',(business_id,))
    conditions=dict(company=bool(row['business_type'] and row['company_address']),sites=facts['sites']>0,
        employees=facts['employees']>0,invitations=facts['employees']>0 and facts['uninvited']==0,
        assignments=facts['assignments']>0 or not mode or mode['organisation_mode']=='fixed',
        payroll=facts['employees']>0 and facts['unreviewed']==0)
    done={step:bool(row['completed'].get(step)) and conditions[step] for step in STEPS[:-1]}
    done['review']=bool(row['completed'].get('review')) and all(done.values())
    return dict(**row,done=done,count=sum(done.values()),facts=facts)


def save(business_id,step,values):
    if step not in STEPS:
        raise ValueError('Choose a valid setup step.')
    if values.get('reviewed')!='on':
        raise ValueError('Confirm that you have reviewed this step before continuing.')
    with transaction() as connection:
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute('SELECT * FROM so_setup WHERE business_id=%s FOR UPDATE',(business_id,))
            row=cursor.fetchone()
            if not row:
                raise ValueError('Setup is not available for this business.')
            if step=='company':
                name=(values.get('business_name') or '').strip()
                kind=(values.get('business_type') or '').strip()
                address=(values.get('company_address') or '').strip()
                if not 1<=len(name)<=160 or not 1<=len(kind)<=100 or not 1<=len(address)<=1000:
                    raise ValueError('Enter your company name, business type and company address.')
                cursor.execute('UPDATE sm_businesses SET name=%s WHERE id=%s',(name,business_id))
                cursor.execute('UPDATE so_setup SET business_type=%s,company_address=%s WHERE business_id=%s',(kind,address,business_id))
            else:
                progress=checklist(business_id)
                if step=='review':
                    ready=all(progress['done'][key] for key in STEPS[:-1])
                else:
                    f=progress['facts']
                    ready={'sites':f['sites']>0,'employees':f['employees']>0,
                        'invitations':f['employees']>0 and f['uninvited']==0,
                        'assignments':f['assignments']>0 or (fetch_one('SELECT organisation_mode FROM staff_settings WHERE business_id=%s',(business_id,)) or {}).get('organisation_mode','fixed')=='fixed',
                        'payroll':f['employees']>0 and f['unreviewed']==0}[step]
                if not ready:
                    raise ValueError('Complete the required records shown in this step before continuing.')
            completed={**row['completed'],step:True}
            following=STEPS[min(STEPS.index(step)+1,len(STEPS)-1)]
            cursor.execute('UPDATE so_setup SET completed=%s,current_step=%s,updated_at=NOW() WHERE business_id=%s',
                           (Json(completed),following,business_id))
    return following
