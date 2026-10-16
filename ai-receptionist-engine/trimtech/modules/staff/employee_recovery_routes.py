"""Tenant-scoped employee recovery; administrator identities are never modified."""
import os

from flask import abort, current_app, redirect, render_template, request, session, url_for
from trimtech.modules.staff import accounts, employee_recovery, joining
from trimtech.modules.staff.manager_auth import ERRORS
from trimtech.modules.staff.trusted_proxy import client_address


def register_routes(staff):
    bp = staff.staff_blueprint

    def page(business_slug, mode, error='', code=200):
        if request.content_length and request.content_length > 16384:
            abort(413)
        return render_template('staff_employee_recovery.html', business_slug=business_slug,
                               mode=mode, error=error, csrf_token=staff._get_csrf_token), code

    @bp.route('/<business_slug>/employee/recover', methods=['GET', 'POST'])
    def employee_recover(business_slug):
        if request.method == 'GET':
            return page(business_slug, 'request')
        if request.content_length and request.content_length > 16384:
            abort(413)
        business = staff._business_id(business_slug)
        email = request.form.get('email', '')[:254].strip().lower()
        raw_phone = request.form.get('phone', '')[:100]
        try:
            email = accounts.email_address(email)
            phone = joining.phone_number(raw_phone)
        except ValueError:
            phone = None
        try:
            allowed = accounts.limited('employee-recover', business + ':' + email + ':' + (phone or ''),
                                       client_address(), str(current_app.secret_key))
            if allowed and phone:
                phones = {phone, ''.join(c for c in raw_phone if c.isdigit() or c == '+')}
                if phone.startswith('0'):
                    phones.update(('+44' + phone[1:], '0044' + phone[1:]))
                employee_recovery.enqueue(business, email, tuple(sorted(phones)),
                    os.getenv('STAFF_PUBLIC_BASE_URL', '').strip() or os.getenv('RENDER_EXTERNAL_URL', '').strip())
        except ERRORS:
            return page(business_slug, 'request', 'Recovery is temporarily unavailable. Please try again.', 503)
        # Same navigation and acknowledgement for unknown, inactive, ambiguous and limited identities.
        return redirect(url_for('staff.employee_recover_sent', business_slug=business_slug), code=303)

    @bp.get('/<business_slug>/employee/recover/sent')
    def employee_recover_sent(business_slug):
        return page(business_slug, 'sent')

    @bp.route('/<business_slug>/employee/reset', methods=['GET', 'POST'])
    def employee_reset(business_slug):
        if request.method == 'GET':
            return page(business_slug, 'reset')
        if request.content_length and request.content_length > 16384:
            abort(413)
        business = staff._business_id(business_slug)
        raw = request.form.get('token', '')[:128]
        try:
            if not accounts.limited('employee-reset', business + ':' + accounts.digest(raw),
                                    client_address(), str(current_app.secret_key)):
                abort(429)
            if not employee_recovery.consume(business, raw, request.form.get('password')):
                return page(business_slug, 'unavailable', code=400)
        except ValueError as error:
            return page(business_slug, 'reset', str(error), 400)
        except ERRORS:
            return page(business_slug, 'reset', 'Recovery is temporarily unavailable. Please try again.', 503)
        auth = session.get(staff._EMPLOYEE_SESSION_KEY)
        if isinstance(auth, dict) and auth.get('business_id') == business:
            session.pop(staff._EMPLOYEE_SESSION_KEY, None)
        return redirect(url_for('staff.employee_reset_success', business_slug=business_slug), code=303)

    @bp.get('/<business_slug>/employee/reset/success')
    def employee_reset_success(business_slug):
        return page(business_slug, 'success')
