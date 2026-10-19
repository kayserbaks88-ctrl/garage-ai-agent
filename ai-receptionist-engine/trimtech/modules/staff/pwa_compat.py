"""Stable installed-app entry points for the pre-PWA application.

Navigation only: existing employee and manager guards remain authoritative.
This module replaces employee_pwa in the compatibility build, never co-registers.
"""
import json
import re
from pathlib import Path

from flask import Response, abort, redirect, render_template, request, session, url_for


def register_routes(staff):
    bp = staff.staff_blueprint
    workplace_pattern = re.compile(r'[a-z0-9][a-z0-9_-]{0,79}')

    @bp.get('/employee/app')
    def employee_app():
        from trimtech.modules.staff import manager_auth
        role = request.args.get('role', '')
        if role not in ('', 'employee', 'manager'):
            abort(400)
        # A role choice never creates an identity or authorizes a business.
        if role == 'manager':
            return redirect(url_for('staff.account_home'))
        workplace = request.args.get('workplace', '').strip().lower()
        error = ''
        if workplace:
            if workplace_pattern.fullmatch(workplace):
                return redirect(url_for('staff.employee_login', business_slug=workplace))
            error = 'Enter the workplace code supplied by your manager.'
        employee_business = None
        try:
            auth = session.get(staff._EMPLOYEE_SESSION_KEY)
            if isinstance(auth, dict):
                business = auth.get('business_id')
                if isinstance(business, str) and workplace_pattern.fullmatch(business):
                    if staff._current_employee(business) is not None:
                        employee_business = business
            manager = manager_auth.identity() if request.cookies.get(manager_auth.COOKIE) else None
        except (*staff._DB_ERRORS, manager_auth.ProxyConfigurationError):
            abort(503, description='Staff Manager access is temporarily unavailable. Please try again.')
        if employee_business and (role == 'employee' or not manager):
            return redirect(url_for('staff.employee_home', business_slug=employee_business))
        if manager and not employee_business and role != 'employee':
            return redirect(url_for('staff.account_home'))
        return render_template('staff_pwa_compat.html', install=False, error=error,
                               choose_role=bool(employee_business and manager))

    @bp.get('/employee/app/install')
    def employee_app_install():
        return render_template('staff_pwa_compat.html', install=True, error='', choose_role=False)

    @bp.get('/employee/app/manifest.webmanifest')
    def employee_app_manifest():
        manifest = {
            'id': '/staff/employee/app', 'name': 'Staff Manager', 'short_name': 'Staff Manager',
            'start_url': '/staff/employee/app', 'scope': '/staff/', 'display': 'standalone',
            'lang': 'en-GB', 'background_color': '#07111f', 'theme_color': '#07111f',
            'icons': [dict(src=url_for('static', filename=f'staff-pwa/icon-{size}.png'),
                           sizes=f'{size}x{size}', type='image/png', purpose='any')
                      for size in (192, 512)] + [dict(
                          src=url_for('static', filename='staff-pwa/maskable-512.png'),
                          sizes='512x512', type='image/png', purpose='maskable')],
        }
        return Response(json.dumps(manifest), mimetype='application/manifest+json')

    @bp.get('/employee/app/offline')
    def employee_app_offline():
        path = Path(staff.current_app.static_folder) / 'staff-pwa/offline.html'
        return Response(path.read_text(encoding='utf-8'), mimetype='text/html')

    @bp.get('/employee-sw.js')
    def employee_app_worker():
        path = Path(staff.current_app.static_folder) / 'staff_pwa_noop_sw.js'
        response = Response(path.read_text(encoding='utf-8'), mimetype='application/javascript')
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response
