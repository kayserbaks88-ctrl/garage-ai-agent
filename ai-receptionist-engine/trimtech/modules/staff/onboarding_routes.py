"""Guided setup around existing Staff tools; no billing implementation."""
import os
from flask import abort, flash, g, redirect, render_template, request, url_for, session
from trimtech.modules.staff import onboarding, employee_invitations, accounts, agency
from trimtech.modules.staff.database import fetch_all, fetch_one
from trimtech.modules.staff.manager_auth import dashboard_login_required, ERRORS
from trimtech.modules.staff.trusted_proxy import client_address

CONTENT={
 'company':('Company details','Confirm your trading name, company address, business type and workforce mode.',None,None),
 'sites':('Work sites and GPS','Add the full UK address, then capture or check the site location and choose its GPS radius. Manual address entry remains available.','staff.setup_sites','Manage work sites'),
 'employees':('Employees & Invitations','Add employees manually, share a company joining link, or invite existing staff. Joining requests need manager approval. You may skip workforce enrolment for now and return later.','staff.employee_onboarding','Manage employees & invitations'),
 'invitations':('Employee invitations','Send each employee an invitation to choose a secure portal password. Links expire after 48 hours; resending replaces earlier unused links. Provider acceptance is not proof of inbox delivery. This step completes when active employees have activated access.',None,None),
 'assignments':('Schedules and weekly rotas','Use existing assignments to record the site, date and UK start/finish times, including overnight jobs. These appear automatically in My rota: no second schedule is needed. Agency mode requires a scheduled assignment; fixed workplaces may review this guidance and schedule later.','staff.agency_dashboard','Manage assignments and rota'),
 'payroll':('Payroll (optional)','Choose a pay-frequency preference and how new breaks are treated, or skip payroll setup for now. Hours and estimated gross wages continue without PAYE, NI or pension configuration. Detailed payroll still requires reviewed employee profiles.','staff.payroll_page','Open detailed payroll'),
 'review':('Final setup review','Review completed steps and optional steps marked Set up later. Finishing setup does not activate detailed payroll, approve payroll, extend your trial or start a subscription.',None,None),
}


def register_routes(staff):
    bp=staff.staff_blueprint

    @bp.context_processor
    def setup_context():
        trial=getattr(g,'staff_trial',None)
        progress=None
        if trial and trial['state']!='legacy' and request.view_args and request.view_args.get('business_slug'):
            progress=onboarding.checklist(request.view_args['business_slug'])
        business=None
        if request.view_args and request.view_args.get('business_slug'):
            business=fetch_one('SELECT name FROM sm_businesses WHERE id=%s',(request.view_args['business_slug'],))
        return {'staff_trial':trial,'staff_setup':progress,'staff_business_name':business['name'] if business else 'Staff Manager'}

    @bp.get('/<business_slug>/settings')
    @dashboard_login_required
    def settings_page(business_slug):
        return render_template('staff_settings.html',business_slug=business_slug,csrf_token=staff._get_csrf_token)

    @bp.route('/<business_slug>/setup',methods=['GET','POST'])
    @dashboard_login_required
    def setup(business_slug):
        progress=onboarding.checklist(business_slug)
        if not progress:
            abort(404)
        step=request.form.get('step') if request.method=='POST' else request.args.get('step',progress['current_step'])
        if step not in onboarding.STEPS:
            abort(400)
        if request.method=='POST':
            try:
                following=onboarding.save(business_slug,step,request.form,staff._manager_actor())
                flash('Setup progress saved.','success')
                if step=='company' and request.form.get('use_company_site')=='on':
                    return redirect(url_for('staff.setup_sites',business_slug=business_slug,use_company='1'))
                return redirect(url_for('staff.setup',business_slug=business_slug,step=following))
            except ValueError as error:
                flash(str(error),'error')
            except staff._DB_ERRORS:
                abort(503,description='Setup could not be saved. Please try again.')
        if step=='invitations': step='employees'
        employees=fetch_all("""SELECT e.id,e.full_name,e.email,c.activated_at,i.status AS invitation_status
            FROM staff_employees e LEFT JOIN so_employee_credentials c ON c.employee_id=e.id AND c.business_id=e.business_id
            LEFT JOIN LATERAL (SELECT status FROM so_employee_invites WHERE employee_id=e.id AND business_id=e.business_id ORDER BY created_at DESC,id DESC LIMIT 1) i ON TRUE
            WHERE e.business_id=%s AND e.status='active' ORDER BY e.full_name""",(business_slug,)) if step=='invitations' else []
        return render_template('staff_setup.html',business_slug=business_slug,progress=progress,steps=onboarding.DISPLAY_STEPS,
            step=step,content=CONTENT,employees=employees,break_settings=fetch_one('SELECT break_policy FROM staff_business_settings WHERE business_id=%s',(business_slug,)) or {'break_policy':'unpaid'},config=agency.settings(business_slug),business=fetch_one('SELECT name FROM sm_businesses WHERE id=%s',(business_slug,)),csrf_token=staff._get_csrf_token)

    @bp.get('/<business_slug>/setup/sites')
    @dashboard_login_required
    def setup_sites(business_slug):
        progress=onboarding.checklist(business_slug)
        if not progress:
            abort(404)
        sites=fetch_all('SELECT * FROM staff_sites WHERE business_id=%s ORDER BY name',(business_slug,))
        draft=None
        if request.args.get('use_company')=='1' and progress['company_address']:
            if not any((site['address'] or '').strip().casefold()==progress['company_address'].strip().casefold() for site in sites):
                business=fetch_one('SELECT name FROM sm_businesses WHERE id=%s',(business_slug,))
                draft=dict(draft=True,name=business['name'],address=progress['company_address'],latitude='',longitude='',allowed_radius_metres=250,client_reference='')
            else:
                flash('The company address is already saved as a work site. Edit that site below.','success')
        return render_template('staff_setup_sites.html',business_slug=business_slug,sites=sites,draft=draft,csrf_token=staff._get_csrf_token)

    @bp.post('/<business_slug>/setup/invitations/<int:employee_id>')
    @dashboard_login_required
    def invite_employee(business_slug,employee_id):
        try:
            if not accounts.limited('employee-invite',business_slug+':'+str(employee_id),client_address(),str(staff.current_app.secret_key)):
                abort(429)
            sent,message=employee_invitations.invite(business_slug,employee_id,os.getenv('STAFF_PUBLIC_BASE_URL','').strip() or os.getenv('RENDER_EXTERNAL_URL','').strip(),detailed=True)
            flash('Invitation accepted by email provider; inbox delivery is not yet confirmed. Awaiting employee activation. If it does not arrive, check spam or contact TrimTech.' if sent else message,'success' if sent else 'error')
        except ValueError as error:
            flash(str(error),'error')
        except ERRORS:
            abort(503,description='Invitations are temporarily unavailable.')
        if request.form.get('return_employees')=='1' or not onboarding.checklist(business_slug):
            return redirect(url_for('staff.employee_onboarding',business_slug=business_slug))
        return redirect(url_for('staff.setup',business_slug=business_slug,step='employees'))

    @bp.route('/employee-invite',methods=['GET','POST'])
    def accept_employee_invite():
        error=''
        code=200
        if request.method=='POST':
            try:
                if not accounts.limited('accept-invite',request.form.get('token','')[:128],client_address(),str(staff.current_app.secret_key)):
                    abort(429)
                business=employee_invitations.accept(request.form.get('token'),request.form.get('password'))
                session.pop(staff._EMPLOYEE_SESSION_KEY,None)
                return redirect(url_for('staff.employee_login',business_slug=business))
            except ValueError as failure:
                error=str(failure);code=400
            except ERRORS:
                error='Invitation access is temporarily unavailable.';code=503
        return render_template('staff_account.html',mode='invite',error=error,message='',csrf_token=staff._get_csrf_token),code
