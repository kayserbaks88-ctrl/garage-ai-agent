"""Joining requests and manager approval, using existing Staff authentication and CSRF."""
import os
from urllib.parse import urlsplit
from flask import abort, flash, jsonify, redirect, render_template, request, url_for
from trimtech.modules.staff import joining, accounts
from trimtech.modules.staff.database import fetch_all
from trimtech.modules.staff.manager_auth import dashboard_login_required, ERRORS
from trimtech.modules.staff.trusted_proxy import client_address

def register_routes(staff):
    bp=staff.staff_blueprint

    def limited(action,key,limit=5):
        if not accounts.limited(action,key,client_address(),str(staff.current_app.secret_key),identity_limit=limit):
            abort(429,description='Too many attempts. Please try again in 15 minutes.')

    @bp.route('/<business_slug>/employees/onboarding',methods=['GET','POST'])
    @dashboard_login_required
    def employee_onboarding(business_slug):
        link=None
        try:
            if request.method=='POST':
                limited('joining-manager',business_slug)
                action=request.form.get('action')
                if action=='generate':
                    base=os.getenv('STAFF_PUBLIC_BASE_URL','').strip() or os.getenv('RENDER_EXTERNAL_URL','').strip()
                    parsed=urlsplit(base)
                    if parsed.scheme!='https' or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
                        raise ValueError('A secure public Staff URL must be configured before creating joining links.')
                    token=joining.generate(business_slug,request.form.get('expiry_days'),staff._manager_actor())
                    link=base.rstrip('/')+'/staff/join#token='+token
                    flash('Joining link created. Copy it now; generating another link revokes this one.','success')
                elif action=='revoke':
                    joining.revoke(business_slug,staff._manager_actor())
                    flash('Joining link revoked. Existing pending requests can still be reviewed.','success')
                elif action in {'approve','reject'}:
                    joining.review(business_slug,request.form.getlist('registration_id'),action,request.form.get('hourly_rate'),staff._manager_actor())
                    flash('Selected registrations '+('approved.' if action=='approve' else 'rejected.'),'success')
                else: raise ValueError('Choose a valid employee onboarding action.')
                if not link: return redirect(url_for('staff.employee_onboarding',business_slug=business_slug))
            data=joining.manager_data(business_slug)
        except ValueError as error:
            flash(str(error),'error');data=joining.manager_data(business_slug)
        except ERRORS:
            abort(503,description='Employee onboarding is temporarily unavailable. The joining schema must be installed before enabling joining links.')
        employees=fetch_all("""SELECT e.id,e.full_name,e.email,c.activated_at,i.status AS invitation_status
            FROM staff_employees e LEFT JOIN so_employee_credentials c ON c.employee_id=e.id AND c.business_id=e.business_id
            LEFT JOIN LATERAL (SELECT status FROM so_employee_invites WHERE employee_id=e.id AND business_id=e.business_id ORDER BY created_at DESC,id DESC LIMIT 1) i ON TRUE
            WHERE e.business_id=%s AND e.status='active' ORDER BY e.full_name""",(business_slug,))
        return render_template('staff_employee_onboarding.html',business_slug=business_slug,joining=data,joining_url=link,employees=employees,csrf_token=staff._get_csrf_token)

    @bp.post('/join/preview')
    def joining_preview():
        try:
            limited('joining-preview',client_address(),30)
            return jsonify(company=joining.preview(request.form.get('token')))
        except ValueError as error: return jsonify(error=str(error)),400
        except ERRORS: return jsonify(error='Employee joining is temporarily unavailable.'),503

    @bp.route('/join',methods=['GET','POST'])
    def employee_join():
        error='';message='';code=200
        if request.method=='POST':
            try:
                # The IP bucket is shared across links; rotating a link cannot evade it.
                limited('joining-register',client_address(),30)
                limited('joining-email',request.form.get('email','').strip().lower()[:254])
                joining.register(request.form.get('token'),request.form)
                message='Your registration is pending manager approval. You have no workforce access yet. Your employer will provide the company portal address after approval.'
            except ValueError as failure: error=str(failure);code=400
            except ERRORS: error='Employee joining is temporarily unavailable. Please try again later.';code=503
        return render_template('staff_join.html',error=error,message=message,csrf_token=staff._get_csrf_token),code
