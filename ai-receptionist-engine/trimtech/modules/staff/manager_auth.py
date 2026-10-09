"""Staff-only login and membership checks; shared dashboard sessions never authorize these routes."""
import os
import secrets
from functools import wraps

from flask import abort, current_app, g, jsonify, redirect, render_template, request, session, url_for
from psycopg2 import Error as PostgreSQLError

from trimtech.modules.staff import accounts, onboarding
from trimtech.modules.staff.trusted_proxy import client_address, ProxyConfigurationError
from trimtech.modules.staff.database import StaffDatabaseError, fetch_all

COOKIE = '__Host-staff_admin'
ERRORS = (StaffDatabaseError, PostgreSQLError, ProxyConfigurationError)


def identity():
    if not hasattr(g,'staff_administrator'):
        g.staff_administrator = accounts.current(request.cookies.get(COOKIE))
    return g.staff_administrator


def _required(function, api=False, billing=False):
    @wraps(function)
    def protected(business_slug, *args, **kwargs):
        try:
            administrator = identity()
            if not administrator:
                if api:
                    return jsonify(error='authentication_required'),401
                return redirect(url_for('staff.account_login'))
            # Never authorize a tenant chosen only from a URL, form or session field.
            membership = accounts.membership(administrator['id'],business_slug)
            if not membership:
                abort(404)
            if billing and membership['role'] != 'owner':
                abort(403,description='Only a business owner can manage subscriptions.')
            g.staff_trial=onboarding.access(business_slug)
            if not billing and request.method=='POST' and g.staff_trial['state'] in ('expired','pending'):
                if api:
                    return jsonify(error='subscription_required'),402
                return render_template('staff_access_required.html',business_slug=business_slug,csrf_token=lambda:session.get('_staff_csrf_token','')),402
        except ERRORS:
            abort(503,description='Staff Manager access is temporarily unavailable.')
        return function(business_slug,*args,**kwargs)
    return protected


def dashboard_login_required(function):
    return _required(function)


def dashboard_api_login_required(function):
    return _required(function,api=True)


def billing_owner_required(function):
    return _required(function,billing=True)


def register_routes(staff):
    bp = staff.staff_blueprint

    def page(mode,message='',error='',code=200,**values):
        return render_template('staff_account.html',mode=mode,message=message,error=error,
                               csrf_token=staff._get_csrf_token,**values),code

    def allowed(action):
        key = request.form.get('email','').strip().lower()[:254] if action in ('register','login','resend','recover') else request.form.get('token','')[:128]
        if not accounts.limited(action,key,client_address(),str(current_app.secret_key)):
            abort(429,description='Too many attempts. Please try again in 15 minutes.')

    def deliver(details,purpose):
        accounts.send_link(details,purpose,os.getenv('STAFF_PUBLIC_BASE_URL','').strip() or os.getenv('RENDER_EXTERNAL_URL','').strip())

    @bp.after_request
    def account_headers(response):
        response.headers['Referrer-Policy']='no-referrer'
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['X-Frame-Options']='DENY'
        return response

    @bp.route('/account/register',methods=['GET','POST'])
    def account_register():
        # Stage 1 can be tested privately; public launch awaits trials/setup and explicit enablement.
        if os.getenv('STAFF_REGISTRATION_ENABLED','0')!='1':
            return page('closed',message='New business registration is not open yet.',code=503)
        if request.method=='GET':
            return page('register')
        try:
            allowed('register')
            details=accounts.register(request.form.get('business_name'),request.form.get('contact_name'),
                                      request.form.get('email'),request.form.get('password'))
            deliver(details,'verify')
            return page('register',message='Request received. If eligible, check your inbox for a verification link. If none arrives, use resend verification. Already registered? Sign in.')
        except ValueError as error:
            return page('register',error=str(error),code=400)
        except ERRORS:
            return page('register',error='Registration is temporarily unavailable. Please try again.',code=503)

    @bp.route('/account/login',methods=['GET','POST'])
    def account_login():
        if request.method=='GET':
            return page('login')
        try:
            allowed('login')
            raw=accounts.authenticate(request.form.get('email'),request.form.get('password'))
            if not raw:
                return page('login',error='Unable to sign in. Check your details and verify your email.',code=401)
            accounts.revoke(request.cookies.get(COOKIE))
            session['_staff_csrf_token']=secrets.token_urlsafe(32)
            response=redirect(url_for('staff.account_home'))
            response.set_cookie(COOKIE,raw,max_age=8*60*60,secure=True,httponly=True,samesite='Lax',path='/')
            return response
        except ValueError:
            return page('login',error='Unable to sign in. Check your details and verify your email.',code=401)
        except ERRORS:
            return page('login',error='Sign-in is temporarily unavailable. Please try again.',code=503)

    @bp.post('/account/logout')
    def account_logout():
        try:
            accounts.revoke(request.cookies.get(COOKIE))
        except ERRORS:
            abort(503,description='Could not sign out securely. Please try again.')
        response=redirect(url_for('staff.account_login'))
        response.delete_cookie(COOKIE,secure=True,httponly=True,samesite='Lax',path='/')
        session.pop('_staff_csrf_token',None)
        return response

    @bp.get('/account')
    def account_home():
        try:
            administrator=identity()
            if not administrator:
                return redirect(url_for('staff.account_login'))
            businesses=fetch_all("""SELECT b.id,b.name FROM sm_businesses b JOIN sm_memberships m ON m.business_id=b.id
                WHERE m.administrator_id=%s AND m.active AND b.active ORDER BY b.name""",(administrator['id'],))
            return page('home',businesses=businesses)
        except ERRORS:
            return page('closed',error='Staff Manager access is temporarily unavailable.',code=503)

    @bp.route('/account/resend',methods=['GET','POST'])
    def account_resend():
        return request_email('verify','resend')

    @bp.route('/account/recover',methods=['GET','POST'])
    def account_recover():
        return request_email('reset','recover')

    def request_email(purpose,mode):
        if request.method=='GET':
            return page(mode)
        try:
            allowed(mode)
            details=accounts.request_token(request.form.get('email'),purpose)
            deliver(details,purpose)
            return page(mode,message='Request received. If the account is eligible, check your inbox. If no email arrives, please try again later.')
        except ValueError as error:
            return page(mode,error=str(error),code=400)
        except ERRORS:
            return page(mode,error='This request is temporarily unavailable. Please try again.',code=503)

    @bp.route('/account/verify',methods=['GET','POST'])
    def account_verify():
        return consume_token('verify')

    @bp.route('/account/reset',methods=['GET','POST'])
    def account_reset():
        return consume_token('reset')

    def consume_token(purpose):
        if request.method=='GET':
            return page(purpose)
        try:
            allowed(purpose)
            if not accounts.consume(request.form.get('token'),purpose,request.form.get('password')):
                return page(purpose,error='This link is invalid, expired or already used. Request a new email.',code=400)
            return page('login',message='Email verified. You can now sign in.' if purpose=='verify' else 'Password changed. Please sign in again.')
        except ValueError as error:
            return page(purpose,error=str(error),code=400)
        except ERRORS:
            return page(purpose,error='This request is temporarily unavailable. Please try again.',code=503)
