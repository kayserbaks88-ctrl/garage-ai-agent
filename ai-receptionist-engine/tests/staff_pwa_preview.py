"""Opt-in synthetic loopback preview; never imported by production startup."""
import os, secrets, socket, sys, time
from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest.mock import patch


@contextmanager
def synthetic_preview():
    keep={k:v for k,v in os.environ.items() if k.upper() in {'SYSTEMROOT','WINDIR','PATH','TEMP','TMP','USERPROFILE','APPDATA','LOCALAPPDATA','COMSPEC'}}
    with patch.dict(os.environ,{**keep,'PYTHON_DOTENV_DISABLED':'1','STAFF_STRIPE_ENABLED':'0','STAFF_ASSIGNMENT_EMAIL_ENABLED':'0','STAFF_REGISTRATION_ENABLED':'0'},clear=True),ExitStack() as stack:
        stack.enter_context(patch('dotenv.load_dotenv',return_value=False))
        for method in ('connect','connect_ex'):
            stack.enter_context(patch.object(socket.socket,method,side_effect=AssertionError('Preview outbound network blocked')))
        stack.enter_context(patch.object(socket,'create_connection',side_effect=AssertionError('Preview outbound network blocked')))
        import psycopg2,requests,stripe
        stack.enter_context(patch.object(psycopg2,'connect',side_effect=AssertionError('Preview databases blocked')))
        stack.enter_context(patch.object(requests.sessions.Session,'request',side_effect=AssertionError('Preview providers blocked')))
        stack.enter_context(patch.object(stripe,'StripeClient',side_effect=AssertionError('Preview Stripe blocked')))
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
        from flask import abort,redirect,request,session
        from werkzeug.middleware.proxy_fix import ProxyFix
        from test_staff_pwa import EmployeePwaTests
        from trimtech.modules.staff import routes as staff,manager_auth,rota,agency_routes
        case=EmployeePwaTests();case.setUp();app=case.app
        app.secret_key=secrets.token_hex(32);app.testing=False
        app.config.update(DEBUG=False,TEMPLATES_AUTO_RELOAD=True,SESSION_COOKIE_SECURE=True,SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SAMESITE='Lax',MAX_CONTENT_LENGTH=16384)
        app.wsgi_app=ProxyFix(app.wsgi_app,x_for=0,x_proto=1,x_host=0,x_port=0,x_prefix=0)

        @app.before_request
        def preview_only():
            if request.remote_addr!='127.0.0.1':abort(403)
            if request.method not in ('GET','HEAD'):abort(409,description='Synthetic preview: all submissions disabled.')
            if not (request.path.startswith(('/staff/','/static/','/qa/')) or request.path=='/healthz'):abort(404)
            if request.path.startswith(('/staff/platform','/staff/account/register')):abort(404)

        @app.after_request
        def preview_headers(response):
            response.headers['Cache-Control']='no-store, private'
            response.headers['Referrer-Policy']='no-referrer'
            response.headers['X-Content-Type-Options']='nosniff'
            response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
            if response.mimetype=='text/html':
                modes=' '.join(f'<a style="color:white;margin:8px" href="/staff/employee/app/preview/{role}">{label}</a>' for role,label in (
                    ('employee','Employee test mode'),('manager','Manager test mode'),('both','Both sessions'),('login','Logged-out test mode')))
                response.set_data(response.get_data(as_text=True).replace('</body>','<aside style="padding:12px;background:#123d2d;color:white">SYNTHETIC PREVIEW ONLY. No real accounts or records. All submissions disabled.<nav aria-label="Synthetic session modes">'+modes+'</nav></aside></body>'))
            return response

        @app.get('/qa/<role>')
        @app.get('/staff/employee/app/preview/<role>')
        def choose_role(role):
            if role not in ('employee','manager','both','login'):abort(404)
            session.clear();session['_staff_csrf_token']='preview-only-csrf'
            if role in ('employee','both'):
                session[staff._EMPLOYEE_SESSION_KEY]={'business_id':'alpha','employee_id':7,'issued_at':int(time.time())}
            response=redirect('/staff/employee/app')
            if role in ('manager','both'):
                session['preview_manager']=True
                response.set_cookie(manager_auth.COOKIE,'M'*43,secure=True,httponly=True,samesite='Lax')
            else:response.delete_cookie(manager_auth.COOKIE,secure=True,httponly=True,samesite='Lax')
            return response

        @app.get('/healthz')
        def health():return {'synthetic_only':True,'database':'blocked','stripe':'blocked','mutations':'blocked'}

        def current_manager(raw):
            return {'id':'synthetic-manager','contact_name':'Demo Manager'} if raw=='M'*43 and session.get('preview_manager') else None
        def membership(administrator,business):
            return {'role':'owner','name':'Synthetic workplace'} if administrator=='synthetic-manager' and business=='alpha' else None
        stack.enter_context(case.employee())
        def employee_sites(query,parameters):
            if 'FROM staff_sites' in query:
                return [{'id':2,'name':'Synthetic site','address':'Example workplace',
                         'photo_required':False,'allowed_radius_metres':100}]
            return []
        stack.enter_context(patch.object(staff,'fetch_all',side_effect=employee_sites))
        for target,name,value in (
            (staff,'init_staff_database',None),
            (manager_auth,'fetch_all',[{'id':'alpha','name':'Synthetic workplace'}]),
            (staff.onboarding,'checklist',None),
            (staff.joining,'counts',{'pending':0,'awaiting':0,'rejected':0}),
            (staff.wages_estimate,'weekly',None),(staff.presence,'overview',{}),
            (staff.attendance_exceptions,'collect',[]),(staff.agency,'assignment_history',[]),
            (rota,'fetch_all',[]),(agency_routes,'fetch_all',[])):
            stack.enter_context(patch.object(target,name,return_value=value))
        stack.enter_context(patch.object(staff.accounts,'current',side_effect=current_manager))
        stack.enter_context(patch.object(staff.accounts,'membership',side_effect=membership))
        yield app


def main():
    port=int(os.environ.get('STAFF_PWA_PREVIEW_PORT','55510'))
    with synthetic_preview() as app:
        app.run(host='127.0.0.1',port=port,use_reloader=False,threaded=False)


if __name__=='__main__':main()
