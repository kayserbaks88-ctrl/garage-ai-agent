"""Shared PWA presentation. Existing employee and manager guards own access."""
import json
import re
from pathlib import Path

from flask import Response, abort, redirect, render_template, request, session, url_for


def register_routes(staff):
    bp = staff.staff_blueprint

    @bp.get('/employee/app')
    def employee_app():
        from trimtech.modules.staff import manager_auth
        role = request.args.get('role', '')
        if role not in ('', 'employee', 'manager'):
            abort(400)
        workplace = request.args.get('workplace', '').strip().lower()
        error = ''
        # Selection is navigation only. Destination routes independently verify
        # session validity, active employee status and manager membership.
        if role == 'manager':
            return redirect(url_for('staff.account_home'))
        if workplace:
            if re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,79}', workplace):
                return redirect(url_for('staff.employee_login', business_slug=workplace))
            error = 'Enter the workplace code supplied by your manager.'
        employee_business = None
        try:
            auth = session.get(staff._EMPLOYEE_SESSION_KEY)
            if isinstance(auth, dict):
                business = auth.get('business_id')
                if isinstance(business, str) and re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,79}', business):
                    if staff._current_employee(business) is not None:
                        employee_business = business
            manager = manager_auth.identity() if request.cookies.get(manager_auth.COOKIE) else None
        except (*staff._DB_ERRORS, manager_auth.ProxyConfigurationError):
            abort(503, description='Staff Manager access is temporarily unavailable. Please try again.')
        if employee_business and (role == 'employee' or not manager):
            return redirect(url_for('staff.employee_home', business_slug=employee_business))
        if manager and not employee_business and role != 'employee':
            return redirect(url_for('staff.account_home'))
        return render_template('staff_employee_app.html', install=False, error=error,
                               role=role, choose_role=bool(employee_business and manager))

    @bp.get('/employee/app/install')
    def employee_app_install():
        return render_template('staff_employee_app.html', install=True, error='')

    @bp.get('/employee/app/manifest.webmanifest')
    def employee_app_manifest():
        return Response(json.dumps({
            'id': '/staff/employee/app', 'name': 'Staff Manager',
            'short_name': 'Staff Manager', 'start_url': '/staff/employee/app',
            'scope': '/staff/', 'display': 'standalone', 'lang': 'en-GB',
            'background_color': '#07111f', 'theme_color': '#07111f',
            'icons': [dict(src=url_for('static', filename=f'staff-pwa/icon-{size}.png'),
                           sizes=f'{size}x{size}', type='image/png', purpose='any')
                      for size in (192, 512)] + [dict(
                          src=url_for('static', filename='staff-pwa/maskable-512.png'),
                          sizes='512x512', type='image/png', purpose='maskable')],
        }), mimetype='application/manifest+json')

    def offline_html():
        return (Path(staff.current_app.static_folder) / 'staff-pwa/offline.html').read_text(encoding='utf-8')

    @bp.get('/employee/app/offline')
    def employee_app_offline():
        return Response(offline_html(), mimetype='text/html')

    @bp.get('/employee-sw.js')
    def employee_app_worker():
        source = (Path(staff.current_app.static_folder) / 'staff_pwa_sw.js').read_text(encoding='utf-8')
        response = Response(source.replace('__STAFF_OFFLINE_HTML__', json.dumps(offline_html())),
                            mimetype='application/javascript')
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response
