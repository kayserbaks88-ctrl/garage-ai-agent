from __future__ import annotations

import hmac
import math
import secrets
import threading
import time
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from functools import wraps
from typing import Any

from flask import (
    Blueprint, abort, current_app, flash, g, redirect, render_template,
    request, session, url_for, jsonify, make_response,
)
from psycopg2 import Error as PostgreSQLError
from psycopg2.extras import RealDictCursor

from dashboard_auth import dashboard_login_required, dashboard_api_login_required
from trimtech.modules.staff.database import (
    StaffDatabaseError, execute, fetch_all, fetch_one,
    init_staff_database, transaction,
)
from trimtech.modules.staff.payroll import (
    PayrollError, generate_payroll_run, parse_shift_datetime, period_dates,
    validate_shift_edit,
)
from trimtech.modules.staff import agency, presence, attendance_exceptions, payroll_ledger, payslips as payslip_delivery
from trimtech.modules.staff.address_lookup import lookup as lookup_address, AddressLookupError


staff_blueprint = Blueprint("staff", __name__, url_prefix="/staff")
staff_bp = staff_blueprint
_DB_ERRORS = (StaffDatabaseError, PostgreSQLError)
_LEAVE_TYPES = {"holiday", "sickness", "unpaid", "compassionate", "parental", "other"}


def _get_csrf_token() -> str:
    token = session.get("_staff_csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_staff_csrf_token"] = token
    return token


@staff_blueprint.before_request
def _protect_staff_forms():
    if request.method != "POST":
        return None
    expected = session.get("_staff_csrf_token", "")
    received = request.form.get("csrf_token", "")
    if (not isinstance(expected, str) or not expected or not received
            or not hmac.compare_digest(expected.encode(), received.encode())):
        abort(400, description="This form has expired. Refresh the page and try again.")
    return None


def _business_id(business_slug: str) -> str:
    return str(business_slug or "").strip().lower()


def _clean_text(value: Any, maximum_length: int = 255) -> str:
    return str(value or "").strip()[:maximum_length]


def _clean_phone(value: Any) -> str:
    return "".join(c for c in _clean_text(value, 30) if c.isdigit() or c == "+")


def _parse_hourly_rate(value: Any) -> Decimal:
    try:
        rate = Decimal(str(value or "").strip().replace(",", ""))
        if not rate.is_finite() or rate < 0 or rate > Decimal("99999999.99"):
            raise ValueError("Enter a nonnegative hourly rate below £100,000,000.")
        return rate.quantize(Decimal("0.01"))
    except InvalidOperation as error:
        raise ValueError("Enter a valid hourly rate.") from error


def _parse_coordinate(value: Any, label: str, minimum: Decimal, maximum: Decimal) -> Decimal:
    try:
        coordinate = Decimal(str(value if value is not None else "").strip())
        if not coordinate.is_finite() or not minimum <= coordinate <= maximum:
            raise ValueError(f"{label.capitalize()} must be between {minimum} and {maximum}.")
        return coordinate.quantize(Decimal("0.0000001"))
    except InvalidOperation as error:
        raise ValueError(f"Enter a valid {label}.") from error


def _parse_radius(value: Any) -> int:
    try:
        radius = int(str(value or "").strip())
    except (TypeError, ValueError) as error:
        raise ValueError("Enter a valid GPS radius.") from error
    if not 10 <= radius <= 10000:
        raise ValueError("GPS radius must be between 10 and 10,000 metres.")
    return radius


def _parse_date(value: Any, label: str) -> date:
    try:
        return date.fromisoformat(str(value or "").strip())
    except ValueError as error:
        raise ValueError(f"Enter a valid {label}.") from error


def _working_days(start_date: date, end_date: date) -> Decimal:
    # Equivalent to the existing Monday-Friday calculation, without a long loop.
    days = (end_date - start_date).days + 1
    if days <= 0:
        return Decimal(0)
    weeks, extra = divmod(days, 7)
    return Decimal(weeks * 5 + sum((start_date.weekday() + i) % 7 < 5 for i in range(extra)))


def _page_redirect(endpoint: str, business_slug: str):
    return redirect(url_for(endpoint, business_slug=business_slug))


def _employee_redirect(business_slug: str):
    endpoint = request.endpoint or ""
    if endpoint in {"staff.employee_clock_in", "staff.employee_clock_out", "staff.employee_break_start", "staff.employee_break_end"}:
        destination = "staff.employee_clocking"
    elif endpoint in {"staff.employee_request_leave", "staff.employee_cancel_leave"}:
        destination = "staff.employee_leave"
    elif endpoint == "staff.employee_travel_origin":
        destination = "staff.employee_profile"
    else:
        destination = "staff.employee_home"
    return redirect(url_for(destination, business_slug=business_slug))


def _database_message():
    # Keep database details out of browser messages.
    current_app.logger.exception("Staff Manager database operation failed")
    flash("Staff Manager could not save that change. Please try again.", "error")


@staff_blueprint.get("/<business_slug>")
@dashboard_login_required
def dashboard(business_slug: str):
    # Concise control centre: summary cards and navigation only. Each section's
    # full tools, forms and filters live on its own dedicated page below.
    business_id = _business_id(business_slug)
    summary = dict(active_employees=0, staff_clocked_in=0, shifts_waiting_approval=0,
                   hours_this_week=0, on_holiday_today=0)
    agency_settings = {"organisation_mode": "fixed", "travel_enabled": False}
    try:
        init_staff_database()
        agency_settings = agency.settings(business_id)
        summary = fetch_one("""
            SELECT
              (SELECT COUNT(*) FROM staff_employees
               WHERE business_id=%s AND status='active') AS active_employees,
              (SELECT COUNT(*) FROM staff_shifts
               WHERE business_id=%s AND clock_out_at IS NULL) AS staff_clocked_in,
              (SELECT COUNT(*) FROM staff_shifts
               WHERE business_id=%s AND approval_status='pending' AND clock_out_at IS NOT NULL) AS shifts_waiting_approval,
              (SELECT COALESCE(ROUND(SUM(EXTRACT(EPOCH FROM
                 (COALESCE(clock_out_at,NOW())-clock_in_at))/3600)::numeric,1),0)
               FROM staff_shifts WHERE business_id=%s
               AND clock_in_at >= DATE_TRUNC('week',NOW())) AS hours_this_week,
              (SELECT COUNT(*) FROM staff_leave_requests WHERE business_id=%s
               AND leave_type='holiday' AND approval_status='approved'
               AND CURRENT_DATE BETWEEN start_date AND end_date) AS on_holiday_today
        """, (business_id,) * 5) or summary
    except _DB_ERRORS:
        current_app.logger.exception("Staff dashboard could not load")
        flash("Staff Manager data is temporarily unavailable. Please refresh to try again.", "error")
    return render_template(
        "staff_dashboard.html", business_slug=business_slug, summary=summary,
        csrf_token=_get_csrf_token, agency_settings=agency_settings,
    )


@staff_blueprint.get("/<business_slug>/approvals")
@dashboard_login_required
def approvals_page(business_slug: str):
    business_id = _business_id(business_slug)
    sites = []
    review = _review_options()
    approval_total = 0
    pending_shifts = []
    edit_shift = None
    try:
        init_staff_database()
        sites = fetch_all("""
            SELECT id, name, address, latitude, longitude, allowed_radius_metres,
                   photo_required, active, created_at, client_reference
            FROM staff_sites WHERE business_id=%s
            ORDER BY CASE WHEN active THEN 0 ELSE 1 END, name
        """, (business_id,))
        where, params = _review_where(business_id, review)
        approval_total = (fetch_one("SELECT COUNT(*) AS total FROM staff_shifts AS shift "
            "JOIN staff_employees AS employee ON employee.id=shift.employee_id "
            "AND employee.business_id=shift.business_id WHERE " + where, params) or {}).get("total", 0)
        review["page"] = min(review["page"], max(1, (approval_total + 19) // 20))
        pending_shifts = fetch_all(_SHIFT_REVIEW_SQL + " WHERE " + where +
            " ORDER BY shift.clock_in_at, shift.id LIMIT 20 OFFSET %s",
            params + ((review["page"] - 1) * 20,))
        edit_shift_id = request.args.get("edit_shift", type=int)
        if edit_shift_id:
            edit_shift = fetch_one("""
                SELECT shift.*,employee.full_name
                FROM staff_shifts AS shift
                JOIN staff_employees AS employee
                  ON employee.id=shift.employee_id AND employee.business_id=shift.business_id
                WHERE shift.id=%s AND shift.business_id=%s
                  AND shift.clock_out_at IS NOT NULL
            """, (edit_shift_id, business_id))
            if edit_shift:
                edit_shift["travel"] = fetch_one("SELECT * FROM staff_shift_travel WHERE shift_id=%s AND business_id=%s",
                                                (edit_shift_id, business_id))
                edit_shift["audit"] = fetch_all("SELECT * FROM staff_audit WHERE business_id=%s AND entity_type='shift' AND entity_id=%s ORDER BY id DESC LIMIT 20",
                                               (business_id, edit_shift_id))
                edit_shift["breaks"] = fetch_all("""
                    SELECT id,started_at,ended_at,paid,note
                    FROM staff_breaks WHERE business_id=%s AND shift_id=%s
                    ORDER BY started_at,id
                """, (business_id, edit_shift_id))
    except _DB_ERRORS:
        current_app.logger.exception("Staff approvals could not load")
        flash("Staff Manager data is temporarily unavailable. Please refresh to try again.", "error")
    return render_template(
        "staff_approvals.html", business_slug=business_slug, sites=sites,
        review=review, approval_total=approval_total, pending_shifts=pending_shifts,
        edit_shift=edit_shift, page_link=_approvals_page_link,
        csrf_token=_get_csrf_token, uk_input=agency.uk_input,
    )


@staff_blueprint.get("/<business_slug>/employees")
@dashboard_login_required
def employees_page(business_slug: str):
    business_id = _business_id(business_slug)
    employees = []
    profile = None
    profile_shifts, profile_leave = [], []
    profile_total = 0
    profile_page = _page_arg("profile_page")
    try:
        init_staff_database()
        employees = fetch_all("""
            SELECT id, full_name, phone, email, role, hourly_rate, status, payroll_number, created_at
            FROM staff_employees WHERE business_id=%s
            ORDER BY CASE WHEN status='active' THEN 0 ELSE 1 END, full_name
        """, (business_id,))
        profile_id = request.args.get("employee", type=int)
        if profile_id:
            profile = next((e for e in employees if e["id"] == profile_id), None)
            if profile is None:
                abort(404)
            profile_total = (fetch_one("SELECT COUNT(*) AS total FROM staff_shifts "
                "WHERE business_id=%s AND employee_id=%s", (business_id, profile_id)) or {}).get("total", 0)
            profile_page = min(profile_page, max(1, (profile_total + 19) // 20))
            profile_shifts = fetch_all(_SHIFT_REVIEW_SQL +
                " WHERE shift.business_id=%s AND shift.employee_id=%s "
                "ORDER BY shift.clock_in_at DESC,shift.id DESC LIMIT 20 OFFSET %s",
                (business_id, profile_id, (profile_page - 1) * 20))
            profile_leave = fetch_all("SELECT * FROM staff_leave_requests WHERE business_id=%s "
                "AND employee_id=%s ORDER BY start_date DESC,id DESC LIMIT 30", (business_id, profile_id))
    except _DB_ERRORS:
        current_app.logger.exception("Staff employees page could not load")
        flash("Staff Manager data is temporarily unavailable. Please refresh to try again.", "error")
    return render_template(
        "staff_employees.html", business_slug=business_slug, employees=employees,
        profile=profile, profile_shifts=profile_shifts, profile_leave=profile_leave,
        profile_total=profile_total, profile_page=profile_page,
        page_link=_profile_page_link, csrf_token=_get_csrf_token,
    )


@staff_blueprint.get("/<business_slug>/attendance")
@dashboard_login_required
def attendance_page(business_slug: str):
    business_id = _business_id(business_slug)
    live_shifts = []
    exceptions = []
    try:
        init_staff_database()
        shift_query = """
            SELECT shift.id, shift.employee_id, employee.full_name, employee.role,
                   shift.site_name, shift.clock_in_at, shift.clock_out_at,
                   shift.approval_status, shift.manager_note,
                   ROUND((EXTRACT(EPOCH FROM
                     (COALESCE(shift.clock_out_at,NOW())-shift.clock_in_at))/3600)::numeric,2)
                     AS hours_worked
            FROM staff_shifts AS shift JOIN staff_employees AS employee
              ON employee.id=shift.employee_id AND employee.business_id=shift.business_id
            WHERE shift.business_id=%s
        """
        live_shifts = fetch_all(shift_query + """
            AND (shift.clock_out_at IS NULL OR shift.clock_in_at::date=CURRENT_DATE)
            ORDER BY CASE WHEN shift.clock_out_at IS NULL THEN 0 ELSE 1 END,
                     shift.clock_in_at DESC
        """, (business_id,))
        current_presence = presence.overview(business_id)
        exceptions = attendance_exceptions.collect(business_id, current_presence)
        for live_shift in live_shifts:
            live_shift["presence"] = current_presence.get(live_shift["id"])
    except _DB_ERRORS:
        current_app.logger.exception("Staff attendance page could not load")
        flash("Staff Manager data is temporarily unavailable. Please refresh to try again.", "error")
    return render_template(
        "staff_attendance.html", business_slug=business_slug, live_shifts=live_shifts,
        csrf_token=_get_csrf_token, exceptions=exceptions,
    )


@staff_blueprint.post("/<business_slug>/attendance/review")
@dashboard_login_required
def review_attendance_exception(business_slug):
    business_id = _business_id(business_slug)
    try:
        key = request.form.get("event_key", "")
        note = _clean_text(request.form.get("note"), 1000)
        if not note:
            raise ValueError("Enter a review note.")
        with transaction() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                agency.lock_business(cursor, business_id)
                events = attendance_exceptions.collect(business_id, presence.overview(business_id))
                if key not in {event['event_key'] for event in events}:
                    raise ValueError("That attendance exception is no longer available.")
                cursor.execute("""INSERT INTO staff_attendance_reviews(business_id,event_key,note,reviewed_by)
                    VALUES (%s,%s,%s,'manager') ON CONFLICT(business_id,event_key) DO NOTHING""",(business_id,key,note))
                agency.audit(cursor,business_id,"manager","attendance_reviewed","attendance",None,None,
                             {"event_key":key},note)
        flash("Attendance exception reviewed. Pay and attendance records are unchanged.","success")
    except ValueError as error:
        flash(str(error),"error")
    except _DB_ERRORS:
        _database_message()
    return _page_redirect("staff.attendance_page",business_slug)


@staff_blueprint.get("/<business_slug>/leave")
@dashboard_login_required
def leave_page(business_slug: str):
    business_id = _business_id(business_slug)
    employees, current_leave, upcoming_leave, pending_leave = [], [], [], []
    try:
        init_staff_database()
        employees = fetch_all("""
            SELECT id, full_name, phone, email, role, hourly_rate, status, payroll_number, created_at
            FROM staff_employees WHERE business_id=%s
            ORDER BY CASE WHEN status='active' THEN 0 ELSE 1 END, full_name
        """, (business_id,))
        leave_query = """
            SELECT leave_request.id, leave_request.employee_id, employee.full_name,
                   employee.role, leave_request.leave_type, leave_request.start_date,
                   leave_request.end_date, leave_request.total_days,
                   leave_request.employee_note, leave_request.manager_note,
                   leave_request.approval_status
            FROM staff_leave_requests AS leave_request JOIN staff_employees AS employee
              ON employee.id=leave_request.employee_id
             AND employee.business_id=leave_request.business_id
            WHERE leave_request.business_id=%s
        """
        current_leave = fetch_all(leave_query + """
            AND leave_request.approval_status='approved'
            AND CURRENT_DATE BETWEEN leave_request.start_date AND leave_request.end_date
            ORDER BY employee.full_name
        """, (business_id,))
        upcoming_leave = fetch_all(leave_query + """
            AND leave_request.approval_status='approved' AND leave_request.start_date>CURRENT_DATE
            ORDER BY leave_request.start_date, employee.full_name LIMIT 20
        """, (business_id,))
        pending_leave = fetch_all(leave_query + """
            AND leave_request.approval_status='pending'
            ORDER BY leave_request.start_date, employee.full_name LIMIT 20
        """, (business_id,))
    except _DB_ERRORS:
        current_app.logger.exception("Staff leave page could not load")
        flash("Staff Manager data is temporarily unavailable. Please refresh to try again.", "error")
    return render_template(
        "staff_leave.html", business_slug=business_slug, employees=employees,
        current_leave=current_leave, upcoming_leave=upcoming_leave,
        pending_leave=pending_leave, csrf_token=_get_csrf_token,
    )


@staff_blueprint.get("/<business_slug>/payroll")
@dashboard_login_required
def payroll_page(business_slug: str):
    business_id = _business_id(business_slug)
    break_policy = "unpaid"
    payroll_runs = []
    payroll_employees = []
    try:
        init_staff_database()
        settings = fetch_one("SELECT break_policy FROM staff_business_settings WHERE business_id=%s", (business_id,))
        break_policy = (settings or {}).get("break_policy") or "unpaid"
        payroll_runs = fetch_all("""
            SELECT *
            FROM staff_payroll_runs WHERE business_id=%s ORDER BY period_end DESC,id DESC LIMIT 20
        """, (business_id,))
        payroll_employees = fetch_all("""SELECT e.id,e.full_name,p.* FROM staff_employees e
            LEFT JOIN staff_payroll_profiles p ON p.employee_id=e.id AND p.business_id=e.business_id
            WHERE e.business_id=%s ORDER BY e.full_name""", (business_id,))
    except _DB_ERRORS:
        current_app.logger.exception("Staff payroll page could not load")
        flash("Staff Manager data is temporarily unavailable. Please refresh to try again.", "error")
    return render_template(
        "staff_payroll_page.html", business_slug=business_slug,
        break_policy=break_policy, payroll_runs=payroll_runs, payroll_employees=payroll_employees, csrf_token=_get_csrf_token,
    )


@staff_blueprint.post("/<business_slug>/employees")
@dashboard_login_required
def add_employee(business_slug: str):
    business_id = _business_id(business_slug)
    full_name = _clean_text(request.form.get("full_name"), 150)
    phone = _clean_phone(request.form.get("phone"))
    email = _clean_text(request.form.get("email"), 254).lower()
    role = _clean_text(request.form.get("role"), 20).lower() or "staff"
    payroll = _clean_text(request.form.get("payroll_number"), 50)
    try:
        if not full_name:
            raise ValueError("Enter the employee’s full name.")
        if not phone or not any(c.isdigit() for c in phone):
            raise ValueError("Enter the employee’s phone number.")
        if role not in {"owner", "manager", "staff"}:
            raise ValueError("Select a valid staff role.")
        rate = _parse_hourly_rate(request.form.get("hourly_rate"))
        if fetch_one("SELECT id FROM staff_employees WHERE business_id=%s AND phone=%s",
                     (business_id, phone)):
            raise ValueError("A staff member with that phone number already exists.")
        execute("""
            INSERT INTO staff_employees
              (business_id,full_name,phone,email,role,hourly_rate,status,payroll_number)
            VALUES (%s,%s,%s,NULLIF(%s,''),%s,%s,'active',NULLIF(%s,''))
        """, (business_id, full_name, phone, email, role, rate, payroll))
        flash(f"{full_name} has been added to Staff Manager.", "success")
    except ValueError as error:
        flash(str(error), "error")
    except _DB_ERRORS:
        _database_message()
    return _page_redirect("staff.employees_page", business_slug)


@staff_blueprint.post("/<business_slug>/employees/<int:employee_id>/status")
@dashboard_login_required
def change_employee_status(business_slug: str, employee_id: int):
    status = _clean_text(request.form.get("status"), 20).lower()
    if status not in {"active", "inactive"}:
        flash("Select a valid employee status.", "error")
        return _page_redirect("staff.employees_page", business_slug)
    try:
        count = execute("""UPDATE staff_employees SET status=%s,updated_at=NOW()
            WHERE id=%s AND business_id=%s""", (status, employee_id, _business_id(business_slug)))
        flash("Employee status updated." if count else "That employee could not be found.",
              "success" if count else "error")
    except _DB_ERRORS:
        _database_message()
    return _page_redirect("staff.employees_page", business_slug)


_address_lookup_requests = {}
_address_lookup_lock = threading.Lock()


@staff_blueprint.post("/<business_slug>/sites/address-lookup")
@dashboard_api_login_required
def address_lookup(business_slug):
    # Bounded per-business, per-worker limit in addition to provider account limits.
    now = time.monotonic()
    with _address_lookup_lock:
        for key, (started, _) in list(_address_lookup_requests.items()):
            if now - started >= 60:
                del _address_lookup_requests[key]
        key = _business_id(business_slug)
        started, count = _address_lookup_requests.get(key, (now, 0))
        if count >= 60 or (key not in _address_lookup_requests and len(_address_lookup_requests) >= 1024):
            response = jsonify(error="Too many address searches. Wait a minute and try again.")
            response.status_code = 429
            response.headers["Retry-After"] = "60"
        else:
            _address_lookup_requests[key] = (started, count + 1)
            response = None
    if response is None:
        try:
            response = jsonify(lookup_address(query=request.form.get("query"),
                address_id=request.form.get("address_id")))
        except ValueError as error:
            response = jsonify(error=str(error))
            response.status_code = 400
        except AddressLookupError as error:
            response = jsonify(error=str(error))
            response.status_code = 503
    response.headers["Cache-Control"] = "no-store"
    return response


def _site_values(values):
    if values.get("address_lookup_selected") == "1" and values.get("coordinates_reviewed") != "on":
        raise ValueError("Capture your location at the site or verify its coordinates before saving.")
    name = _clean_text(values.get("name"), 150)
    if not name:
        raise ValueError("Enter the site name.")
    return (name, _clean_text(values.get("address"), 1000),
            _parse_coordinate(values.get("latitude"), "latitude", Decimal(-90), Decimal(90)),
            _parse_coordinate(values.get("longitude"), "longitude", Decimal(-180), Decimal(180)),
            _parse_radius(values.get("allowed_radius_metres")),
            _clean_text(values.get("client_reference"), 160))


@staff_blueprint.post("/<business_slug>/sites")
@dashboard_login_required
def add_site(business_slug: str):
    business_id = _business_id(business_slug)
    inline = request.accept_mimetypes.best == "application/json"
    try:
        name, address, latitude, longitude, radius, reference = _site_values(request.form)
        if inline and not address:
            raise ValueError("Enter an address for the assigned work site.")
        with transaction() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                agency.lock_business(cursor, business_id)
                cursor.execute("SELECT id FROM staff_sites WHERE business_id=%s AND LOWER(name)=LOWER(%s)",
                               (business_id, name))
                if cursor.fetchone():
                    raise ValueError("A site with that name already exists.")
                cursor.execute("""INSERT INTO staff_sites
                    (business_id,name,address,latitude,longitude,allowed_radius_metres,photo_required,active,client_reference)
                    VALUES (%s,%s,NULLIF(%s,''),%s,%s,%s,%s,TRUE,NULLIF(%s,''))
                    RETURNING id,name,client_reference""",
                    (business_id, name, address, latitude, longitude, radius,
                     request.form.get("photo_required") == "on", reference))
                site = dict(cursor.fetchone())
        if inline:
            return jsonify(site=site), 201
        flash(f"{name} has been added as a work site.", "success")
    except ValueError as error:
        if inline:
            return jsonify(error=str(error)), 400
        flash(str(error), "error")
    except _DB_ERRORS:
        if inline:
            return jsonify(error="Could not save the work site. Please try again."), 503
        _database_message()
    return _page_redirect("staff.agency_dashboard", business_slug)


@staff_blueprint.post("/<business_slug>/sites/<int:site_id>/edit")
@dashboard_login_required
def edit_site(business_slug: str, site_id: int):
    business_id = _business_id(business_slug)
    try:
        name, address, latitude, longitude, radius, reference = _site_values(request.form)
        status = request.form.get("status")
        if status not in {"active", "inactive"}:
            raise ValueError("Select a valid site status.")
        with transaction() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                agency.lock_business(cursor, business_id)
                cursor.execute("SELECT id FROM staff_sites WHERE id=%s AND business_id=%s FOR UPDATE",
                               (site_id, business_id))
                if not cursor.fetchone():
                    abort(404)
                cursor.execute("SELECT id FROM staff_sites WHERE business_id=%s AND LOWER(name)=LOWER(%s) AND id<>%s",
                               (business_id, name, site_id))
                if cursor.fetchone():
                    raise ValueError("A site with that name already exists.")
                # Preserve photo policy and historical assignment/GPS snapshots.
                cursor.execute("""UPDATE staff_sites SET name=%s,address=NULLIF(%s,''),latitude=%s,
                    longitude=%s,allowed_radius_metres=%s,client_reference=NULLIF(%s,''),
                    active=%s,updated_at=NOW() WHERE id=%s AND business_id=%s""",
                    (name, address, latitude, longitude, radius, reference,
                     status == "active", site_id, business_id))
        flash("Work site updated. Historical shift evidence is unchanged.", "success")
    except ValueError as error:
        flash(str(error), "error")
    except _DB_ERRORS:
        _database_message()
    return redirect(url_for("staff.agency_dashboard", business_slug=business_slug, _anchor="sites"))


@staff_blueprint.post("/<business_slug>/sites/<int:site_id>/status")
@dashboard_login_required
def change_site_status(business_slug: str, site_id: int):
    status = _clean_text(request.form.get("status"), 20).lower()
    if status not in {"active", "inactive"}:
        flash("Select a valid site status.", "error")
        return _page_redirect("staff.agency_dashboard", business_slug)
    try:
        count = execute("""UPDATE staff_sites SET active=%s,updated_at=NOW()
            WHERE id=%s AND business_id=%s""", (status == "active", site_id, _business_id(business_slug)))
        flash("Work site status updated." if count else "That work site could not be found.",
              "success" if count else "error")
    except _DB_ERRORS:
        _database_message()
    return _page_redirect("staff.agency_dashboard", business_slug)


@staff_blueprint.post("/<business_slug>/settings/break-policy")
@dashboard_login_required
def update_break_policy(business_slug: str):
    policy = _clean_text(request.form.get("break_policy"), 20).lower()
    if policy not in {"paid", "unpaid"}:
        flash("Select whether new breaks are paid or unpaid.", "error")
        return _page_redirect("staff.payroll_page", business_slug)
    try:
        execute("""INSERT INTO staff_business_settings (business_id,break_policy)
            VALUES (%s,%s) ON CONFLICT (business_id) DO UPDATE SET break_policy=EXCLUDED.break_policy,updated_at=NOW()""",
            (_business_id(business_slug), policy))
        flash(f"New breaks will be recorded as {policy}.", "success")
    except _DB_ERRORS:
        _database_message()
    return _page_redirect("staff.payroll_page", business_slug)


@staff_blueprint.post("/<business_slug>/shifts/<int:shift_id>/approve")
@dashboard_login_required
def approve_shift(business_slug: str, shift_id: int):
    try:
        count = execute("""UPDATE staff_shifts SET approval_status='approved',approved_at=NOW(),
            manager_note=NULLIF(%s,'') WHERE id=%s AND business_id=%s AND clock_out_at IS NOT NULL AND approval_status='pending'""",
            (_clean_text(request.form.get("manager_note"), 500), shift_id, _business_id(business_slug)))
        flash("Shift approved." if count else "Only completed pending shifts can be approved.",
              "success" if count else "error")
    except _DB_ERRORS:
        _database_message()
    return _page_redirect("staff.approvals_page", business_slug)


@staff_blueprint.post("/<business_slug>/shifts/<int:shift_id>/reject")
@dashboard_login_required
def reject_shift(business_slug: str, shift_id: int):
    note = _clean_text(request.form.get("manager_note"), 500)
    if not note:
        flash("Enter a reason before rejecting the shift.", "error")
        return _page_redirect("staff.approvals_page", business_slug)
    try:
        count = execute("""UPDATE staff_shifts SET approval_status='rejected',approved_at=NOW(),
            manager_note=%s WHERE id=%s AND business_id=%s AND clock_out_at IS NOT NULL
            AND approval_status='pending'""", (note, shift_id, _business_id(business_slug)))
        flash("Shift rejected." if count else "That completed pending shift could not be found.", "success" if count else "error")
    except _DB_ERRORS:
        _database_message()
    return _page_redirect("staff.approvals_page", business_slug)


def _leave_input():
    leave_type = _clean_text(request.form.get("leave_type"), 20).lower() or "holiday"
    if leave_type not in _LEAVE_TYPES:
        raise ValueError("Select a valid type of leave.")
    start = _parse_date(request.form.get("start_date"), "start date")
    end = _parse_date(request.form.get("end_date"), "end date")
    if end < start:
        raise ValueError("The end date cannot be before the start date.")
    days = _working_days(start, end)
    if days <= 0:
        raise ValueError("This version counts Monday to Friday. Select at least one weekday; ask your manager about weekend leave.")
    if days > Decimal("9999.99"):
        raise ValueError("That leave period is too long.")
    return leave_type, start, end, days, _clean_text(request.form.get("employee_note"), 1000)


def _insert_leave(business_id: str, employee_id: int, values, status: str) -> str:
    # Lock one employee so simultaneous portal submissions cannot create overlapping leave.
    leave_type, start, end, days, note = values
    with transaction() as connection:
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("""SELECT id,full_name FROM staff_employees
                WHERE id=%s AND business_id=%s AND status='active' FOR UPDATE""", (employee_id, business_id))
            employee = cursor.fetchone()
            if not employee:
                raise ValueError("That active employee could not be found.")
            cursor.execute("""SELECT id FROM staff_leave_requests WHERE business_id=%s AND employee_id=%s
                AND approval_status IN ('pending','approved') AND start_date<=%s AND end_date>=%s
                LIMIT 1""", (business_id, employee_id, end, start))
            if cursor.fetchone():
                raise ValueError("These dates overlap an existing pending or approved leave record.")
            cursor.execute("""INSERT INTO staff_leave_requests
                (business_id,employee_id,leave_type,start_date,end_date,total_days,
                 approval_status,employee_note,approved_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,NULLIF(%s,''),
                        CASE WHEN %s='approved' THEN NOW() ELSE NULL END)""",
                (business_id, employee_id, leave_type, start, end, days, status, note, status))
            return employee["full_name"]


@staff_blueprint.post("/<business_slug>/leave")
@dashboard_login_required
def add_leave(business_slug: str):
    try:
        try:
            employee_id = int(request.form.get("employee_id", ""))
        except (TypeError, ValueError) as error:
            raise ValueError("Select an employee.") from error
        name = _insert_leave(_business_id(business_slug), employee_id, _leave_input(), "approved")
        flash(f"Leave added for {name}.", "success")
    except ValueError as error:
        flash(str(error), "error")
    except _DB_ERRORS:
        _database_message()
    return _page_redirect("staff.leave_page", business_slug)


@staff_blueprint.post("/<business_slug>/leave/<int:leave_id>/approve")
@dashboard_login_required
def approve_leave(business_slug: str, leave_id: int):
    try:
        count = execute("""UPDATE staff_leave_requests SET approval_status='approved',approved_at=NOW(),
            manager_note=NULLIF(%s,''),updated_at=NOW()
            WHERE id=%s AND business_id=%s AND approval_status='pending'""",
            (_clean_text(request.form.get("manager_note"), 1000), leave_id, _business_id(business_slug)))
        flash("Leave request approved." if count else "That pending leave request could not be found.",
              "success" if count else "error")
    except _DB_ERRORS:
        _database_message()
    return _page_redirect("staff.leave_page", business_slug)


@staff_blueprint.post("/<business_slug>/leave/<int:leave_id>/reject")
@dashboard_login_required
def reject_leave(business_slug: str, leave_id: int):
    note = _clean_text(request.form.get("manager_note"), 1000)
    if not note:
        flash("Enter a reason before rejecting the request.", "error")
        return _page_redirect("staff.leave_page", business_slug)
    try:
        count = execute("""UPDATE staff_leave_requests SET approval_status='rejected',approved_at=NOW(),
            manager_note=%s,updated_at=NOW() WHERE id=%s AND business_id=%s AND approval_status='pending'""",
            (note, leave_id, _business_id(business_slug)))
        flash("Leave request rejected." if count else "That pending leave request could not be found.",
              "success" if count else "error")
    except _DB_ERRORS:
        _database_message()
    return _page_redirect("staff.leave_page", business_slug)


@staff_blueprint.post("/<business_slug>/leave/<int:leave_id>/cancel")
@dashboard_login_required
def cancel_leave(business_slug: str, leave_id: int):
    try:
        count = execute("""UPDATE staff_leave_requests SET approval_status='cancelled',updated_at=NOW()
            WHERE id=%s AND business_id=%s AND approval_status IN ('pending','approved')
            AND end_date>=CURRENT_DATE""", (leave_id, _business_id(business_slug)))
        flash("Leave record cancelled." if count else "That leave record could not be cancelled.",
              "success" if count else "error")
    except _DB_ERRORS:
        _database_message()
    return _page_redirect("staff.leave_page", business_slug)


# Employee sessions never grant manager/dashboard access.
_EMPLOYEE_SESSION_KEY = "_staff_employee_auth"
_EMPLOYEE_SESSION_SECONDS = 8 * 60 * 60
_EMPLOYEE_LOGIN_WINDOW = 15 * 60
_employee_login_attempts: dict[tuple[str, ...], list[float]] = {}
_employee_login_lock = threading.Lock()


def _employee_login_allowed(business_id: str, phone: str) -> bool:
    """Existing per-worker limits; multiple workers need a shared limiter too."""
    now = time.monotonic()
    keys = ((("account", business_id, phone), 5), (("address", request.remote_addr or "unknown"), 30))
    with _employee_login_lock:
        for key in list(_employee_login_attempts):
            recent = [t for t in _employee_login_attempts[key] if now-t < _EMPLOYEE_LOGIN_WINDOW]
            if recent:
                _employee_login_attempts[key] = recent
            else:
                del _employee_login_attempts[key]
        if any(len(_employee_login_attempts.get(key, [])) >= limit for key, limit in keys):
            return False
        if len(_employee_login_attempts) + sum(key not in _employee_login_attempts for key, _ in keys) > 8192:
            return False
        for key, _ in keys:
            _employee_login_attempts.setdefault(key, []).append(now)
    return True


def _current_employee(business_slug: str) -> dict[str, Any] | None:
    auth = session.get(_EMPLOYEE_SESSION_KEY)
    if not isinstance(auth, dict):
        session.pop(_EMPLOYEE_SESSION_KEY, None)
        return None
    business_id = _business_id(business_slug)
    if auth.get("business_id") != business_id:
        return None
    employee_id, issued_at = auth.get("employee_id"), auth.get("issued_at")
    if (type(employee_id) is not int or employee_id <= 0 or type(issued_at) is not int
            or not 0 <= time.time()-issued_at < _EMPLOYEE_SESSION_SECONDS):
        session.pop(_EMPLOYEE_SESSION_KEY, None)
        return None
    employee = fetch_one("""SELECT id,business_id,full_name,phone,email,role,status
        FROM staff_employees WHERE id=%s AND business_id=%s AND status='active'""", (employee_id, business_id))
    if not employee:
        session.pop(_EMPLOYEE_SESSION_KEY, None)
    return employee


def employee_login_required(view_function):
    @wraps(view_function)
    def protected_view(business_slug: str, *args, **kwargs):
        try:
            employee = _current_employee(business_slug)
        except _DB_ERRORS:
            abort(503, description="Employee access is temporarily unavailable.")
        if employee is None:
            return redirect(url_for("staff.employee_login", business_slug=business_slug))
        g.staff_employee = employee
        return view_function(business_slug, *args, **kwargs)
    return protected_view


@staff_blueprint.after_request
def _prevent_employee_page_caching(response):
    if (request.endpoint or "").startswith("staff."):
        response.headers["Cache-Control"] = "no-store, private"
    return response


@staff_blueprint.route("/<business_slug>/employee/login", methods=["GET", "POST"])
def employee_login(business_slug: str):
    business_id = _business_id(business_slug)
    error_message, phone_value, status_code = "", "", 200
    try:
        if request.method == "GET":
            if _current_employee(business_slug) is not None:
                return _employee_redirect(business_slug)
        else:
            raw_phone = request.form.get("phone", "").strip()
            payroll_number = request.form.get("payroll_number", "").strip()
            phone_value = raw_phone[:40]
            phone = "".join(c for c in raw_phone if c.isdigit() or c == "+")
            valid = (0 < len(raw_phone) <= 100 and 0 < len(phone) <= 40
                     and any(c.isdigit() for c in phone) and 0 < len(payroll_number) <= 60)
            if not _employee_login_allowed(business_id, phone[:40]):
                error_message = "Too many login attempts. Please try again in 15 minutes."
                status_code = 429
            else:
                employee = None
                if valid:
                    employee = fetch_one("""SELECT id,payroll_number FROM staff_employees
                        WHERE business_id=%s AND phone=%s AND status='active'""", (business_id, phone))
                stored = str((employee or {}).get("payroll_number") or "")
                matches = hmac.compare_digest(payroll_number.encode("utf-8"), stored.encode("utf-8"))
                if employee and valid and stored and matches:
                    session[_EMPLOYEE_SESSION_KEY] = {
                        "employee_id": int(employee["id"]), "business_id": business_id,
                        "issued_at": int(time.time()),
                    }
                    return _employee_redirect(business_slug)
                error_message, status_code = "Phone number or payroll number is incorrect.", 401
    except _DB_ERRORS:
        error_message = "Employee login is temporarily unavailable. Please try again later."
        status_code = 503
    return render_template("staff_employee_login.html", business_slug=business_slug,
                           error_message=error_message, phone_value=phone_value,
                           csrf_token=_get_csrf_token), status_code


@staff_blueprint.post("/<business_slug>/employee/logout")
def employee_logout(business_slug: str):
    auth = session.get(_EMPLOYEE_SESSION_KEY)
    if isinstance(auth, dict) and auth.get("business_id") == _business_id(business_slug):
        session.pop(_EMPLOYEE_SESSION_KEY, None)
    return redirect(url_for("staff.employee_login", business_slug=business_slug))


@staff_blueprint.get("/<business_slug>/employee")
@staff_blueprint.get("/<business_slug>/employee/jobs", endpoint="employee_jobs", defaults={"page": "jobs"})
@staff_blueprint.get("/<business_slug>/employee/clocking", endpoint="employee_clocking", defaults={"page": "clocking"})
@staff_blueprint.get("/<business_slug>/employee/hours", endpoint="employee_hours", defaults={"page": "hours"})
@staff_blueprint.get("/<business_slug>/employee/leave", endpoint="employee_leave", defaults={"page": "leave"})
@staff_blueprint.get("/<business_slug>/employee/pay", endpoint="employee_pay", defaults={"page": "pay"})
@staff_blueprint.get("/<business_slug>/employee/profile", endpoint="employee_profile", defaults={"page": "profile"})
@employee_login_required
def employee_home(business_slug: str, page: str = "home"):
    """Employee-only pages; identities always come from the authenticated session."""
    employee = g.staff_employee
    parameters = (_business_id(business_slug), employee["id"])
    try:
        agency_settings = agency.settings(parameters[0])
        # An assignment is visible regardless of the business's clocking mode.
        assignments = agency.upcoming_assignments(*parameters) if page in {"home", "jobs", "clocking"} else []
        job_history = agency.assignment_history(*parameters) if page == "jobs" else []
        travel_origin = agency.origin_for_employee(*parameters) if page == "profile" and (
            agency_settings["organisation_mode"] == "agency" or agency_settings["travel_enabled"]) else None
        current_shift = fetch_one("""SELECT id,site_id,site_name,clock_in_at,approval_status
            FROM staff_shifts WHERE business_id=%s AND employee_id=%s AND clock_out_at IS NULL
            ORDER BY clock_in_at DESC LIMIT 1""", parameters)
        hours_summary = {}
        if page in {"home", "hours"}:
            hours_summary = fetch_one("""
                WITH period AS (SELECT DATE_TRUNC('week',NOW()) AS week_start,NOW() AS as_of)
                SELECT period.week_start::date AS week_start,
                       (period.week_start+INTERVAL '6 days')::date AS week_end,period.as_of,
                       COALESCE((SELECT ROUND(SUM(GREATEST(0,EXTRACT(EPOCH FROM
                         (LEAST(COALESCE(shift.clock_out_at,period.as_of),period.as_of)
                          - GREATEST(shift.clock_in_at,period.week_start))))/3600)::numeric,2)
                         FROM staff_shifts AS shift WHERE shift.business_id=%s AND shift.employee_id=%s
                           AND shift.clock_in_at<period.as_of
                           AND COALESCE(shift.clock_out_at,period.as_of)>period.week_start),0) AS hours_this_week
                FROM period
            """, parameters) or {}
        today_summary = _today_hours(*parameters) if page == "hours" else {}
        leave_summary, pending_leave, upcoming_leave, current_leave, leave_history = {}, [], [], [], []
        if page == "leave":
            leave_summary = fetch_one("""SELECT
                COUNT(*) FILTER (WHERE approval_status='pending') AS pending_count,
                COUNT(*) FILTER (WHERE approval_status='approved' AND start_date>CURRENT_DATE) AS upcoming_count,
                COUNT(*) FILTER (WHERE approval_status='approved'
                  AND CURRENT_DATE BETWEEN start_date AND end_date) AS current_count,
                COALESCE(SUM(total_days) FILTER (WHERE approval_status='pending'),0) AS pending_days,
                COALESCE(SUM(total_days) FILTER (WHERE approval_status='approved'
                  AND start_date>CURRENT_DATE),0) AS upcoming_days
                FROM staff_leave_requests WHERE business_id=%s AND employee_id=%s""", parameters) or {}
            leave_query = """SELECT id,leave_type,start_date,end_date,total_days,approval_status,
                employee_note,manager_note FROM staff_leave_requests WHERE business_id=%s AND employee_id=%s """
            pending_leave = fetch_all(leave_query + "AND approval_status='pending' ORDER BY start_date,id LIMIT 20", parameters)
            upcoming_leave = fetch_all(leave_query + """AND approval_status='approved' AND start_date>CURRENT_DATE
                ORDER BY start_date,id LIMIT 20""", parameters)
            current_leave = fetch_all(leave_query + """AND approval_status='approved'
                AND CURRENT_DATE BETWEEN start_date AND end_date ORDER BY start_date,id LIMIT 20""", parameters)
            leave_history = fetch_all(leave_query + "ORDER BY created_at DESC,id DESC LIMIT 30", parameters)
        payslips = []
        if page == "pay":
            payslips = fetch_all("""
                SELECT payslip.id,payslip.worked_minutes,payslip.paid_break_minutes,
                       payslip.unpaid_break_minutes,payslip.payable_minutes,payslip.hourly_rate,
                       payslip.gross_pay,payslip.deductions,payslip.net_pay,run.calculation_version,
                       run.period_start,run.period_end,run.status
                FROM staff_payslips AS payslip
                JOIN staff_payroll_runs AS run ON run.id=payslip.payroll_run_id
                WHERE payslip.business_id=%s AND payslip.employee_id=%s AND NOT run.needs_recalculation
                  AND run.status IN ('approved','sent','paid')
                ORDER BY run.period_end DESC,payslip.id DESC LIMIT 20
            """, parameters)
        sites = fetch_all("""SELECT id,name,address,photo_required,allowed_radius_metres FROM staff_sites
            WHERE business_id=%s AND active=TRUE ORDER BY name""", (parameters[0],)) if page == "clocking" and agency_settings["organisation_mode"] == "fixed" else []
        shift_history = []
        if page == "hours":
            shift_history = fetch_all("""SELECT s.id,s.site_name,s.clock_in_at,s.clock_out_at,s.approval_status,
                ROUND((GREATEST(0,EXTRACT(EPOCH FROM (COALESCE(s.clock_out_at,NOW())-s.clock_in_at)))/3600)::numeric,2) AS elapsed_hours,
                COALESCE((SELECT ROUND((SUM(GREATEST(0,EXTRACT(EPOCH FROM
                    (COALESCE(b.ended_at,s.clock_out_at,NOW())-b.started_at))))/60)::numeric,0)
                    FROM staff_breaks b WHERE b.shift_id=s.id AND b.employee_id=s.employee_id
                        AND b.business_id=s.business_id),0) AS break_minutes
                FROM staff_shifts s WHERE s.business_id=%s AND s.employee_id=%s
                ORDER BY s.clock_in_at DESC,s.id DESC LIMIT 100""", parameters)
        current_break = None
        if current_shift:
            current_break = fetch_one("""SELECT id,started_at,paid FROM staff_breaks
                WHERE business_id=%s AND employee_id=%s AND shift_id=%s AND ended_at IS NULL LIMIT 1""",
                parameters + (current_shift["id"],))
    except _DB_ERRORS:
        current_app.logger.exception("Employee summary failed")
        abort(503, description="Your employee summary is temporarily unavailable.")
    return render_template(
        "staff_employee_" + page + ".html", business_slug=business_slug, employee=employee,
        page=page, shift_history=shift_history, uk_display=agency.uk_display,
        current_shift=current_shift, is_clocked_in=current_shift is not None,
        hours_this_week=hours_summary.get("hours_this_week", Decimal("0")),
        week_start=hours_summary.get("week_start"), week_end=hours_summary.get("week_end"),
        as_of=hours_summary.get("as_of"), leave_summary=leave_summary, pending_leave=pending_leave,
        upcoming_leave=upcoming_leave, current_leave=current_leave, csrf_token=_get_csrf_token,
        sites=sites, current_break=current_break, leave_history=leave_history,
        today_summary=today_summary,
        payslips=payslips,
        agency_settings=agency_settings, assignments=assignments, travel_origin=travel_origin,
        current_jobs=[job for job in assignments if job["current_job"]],
        upcoming_jobs=[job for job in assignments if not job["current_job"]],
        job_history=job_history, uk_input=agency.uk_input,
    )


# Portal action contract for the staff_employee_* templates:
# All forms POST csrf_token. Clock forms also POST latitude, longitude, accuracy.
# Clock-in POSTs site_id; clock-out and break forms POST shift_id to prevent a
# delayed/replayed form from closing a newer shift. Leave POSTs leave_type,
# start_date, end_date and optional employee_note. Identity comes ONLY from session.


@staff_blueprint.post("/<business_slug>/presence/status")
@dashboard_api_login_required
def presence_status(business_slug):
    try:
        response = jsonify(shifts=presence.overview(_business_id(business_slug)))
        response.headers["Cache-Control"] = "no-store"
        return response
    except _DB_ERRORS:
        return jsonify(error="Presence status is temporarily unavailable."), 503


@staff_blueprint.post("/<business_slug>/employee/presence")
@employee_login_required
def employee_presence(business_slug):
    business_id, employee_id = _business_id(business_slug), g.staff_employee["id"]
    try:
        with transaction() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                _lock_employee(cursor, business_id, employee_id)
                result = presence.record(cursor, business_id, employee_id,
                    _positive_form_id("shift_id", "Shift"), request.form)
        return jsonify(result)
    except ValueError as error:
        return jsonify(error=str(error)), 400
    except _DB_ERRORS:
        return jsonify(error="Presence update unavailable. Clocking is unchanged."), 503


def _lock_employee(cursor, business_id: str, employee_id: int):
    cursor.execute("""SELECT id FROM staff_employees
        WHERE id=%s AND business_id=%s AND status='active' FOR UPDATE""", (employee_id, business_id))
    if not cursor.fetchone():
        raise ValueError("Your employee account is inactive. Please contact your manager.")


def _positive_form_id(field: str, label: str) -> int:
    try:
        value = int(request.form.get(field, ""))
        if value <= 0:
            raise ValueError()
        return value
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} is missing. Refresh the page and try again.") from error


def _distance_metres(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    a1, a2 = math.radians(lat1), math.radians(lat2)
    dlat, dlon = a2-a1, math.radians(lon2-lon1)
    hav = math.sin(dlat/2)**2 + math.cos(a1)*math.cos(a2)*math.sin(dlon/2)**2
    return 6371000 * 2 * math.asin(math.sqrt(min(1.0, max(0.0, hav))))


def _verified_location(site):
    # Browser GPS is evidence for manager review, not proof against device spoofing.
    if site["photo_required"]:
        raise ValueError("This site requires a photo. Portal photo upload is not ready; use your existing clocking process or contact your manager.")
    if site["latitude"] is None or site["longitude"] is None:
        raise ValueError("This site has no GPS location. Ask your manager to check its setup.")
    latitude = _parse_coordinate(request.form.get("latitude"), "latitude", Decimal(-90), Decimal(90))
    longitude = _parse_coordinate(request.form.get("longitude"), "longitude", Decimal(-180), Decimal(180))
    try:
        accuracy = float(request.form.get("accuracy", ""))
    except (TypeError, ValueError) as error:
        raise ValueError("Allow location access and try again.") from error
    radius = float(site["allowed_radius_metres"])
    if not math.isfinite(radius) or radius <= 0:
        raise ValueError("This site's GPS radius is invalid. Contact your manager.")
    if not math.isfinite(accuracy) or accuracy < 0 or accuracy > min(radius, 100):
        raise ValueError("Your GPS reading is not accurate enough. Move to an open area and try again.")
    distance = _distance_metres(float(latitude), float(longitude), float(site["latitude"]), float(site["longitude"]))
    if distance > radius:
        raise ValueError(f"You are about {round(distance)} metres from this site. Clocking requires being within {round(radius)} metres.")
    return latitude, longitude


@staff_blueprint.post("/<business_slug>/employee/clock-in")
@employee_login_required
def employee_clock_in(business_slug: str):
    business_id, employee_id = _business_id(business_slug), g.staff_employee["id"]
    try:
        with transaction() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                config = agency.locked_settings(cursor, business_id)
                _lock_employee(cursor, business_id, employee_id)
                assignment = None
                if config["organisation_mode"] == "agency":
                    assignment = agency.resolve_assignment(cursor, business_id, employee_id,
                        _positive_form_id("assignment_id", "Assignment"))
                    site_id = assignment["site_id"]
                else:
                    site_id = _positive_form_id("site_id", "Work site")
                cursor.execute("""SELECT id FROM staff_shifts WHERE business_id=%s AND employee_id=%s
                    AND clock_out_at IS NULL""", (business_id, employee_id))
                if cursor.fetchone():
                    raise ValueError("You are already clocked in. Refresh to see your current shift.")
                cursor.execute("""SELECT id,name,address,latitude,longitude,allowed_radius_metres,photo_required
                    FROM staff_sites WHERE id=%s AND business_id=%s AND active=TRUE FOR SHARE""", (site_id, business_id))
                site = cursor.fetchone()
                if not site:
                    raise ValueError("That active work site could not be found.")
                latitude, longitude = _verified_location(site)
                evidence = agency.gps_evidence(request.form, required=config["organisation_mode"] == "agency")
                cursor.execute("""INSERT INTO staff_shifts
                    (business_id,employee_id,site_id,site_name,clock_in_at,
                     clock_in_latitude,clock_in_longitude,approval_status)
                    VALUES (%s,%s,%s,%s,clock_timestamp(),%s,%s,'pending')
                    ON CONFLICT (business_id,employee_id) WHERE clock_out_at IS NULL DO NOTHING RETURNING id""",
                    (business_id, employee_id, site["id"], site["name"], latitude, longitude))
                if cursor.rowcount != 1:
                    raise ValueError("You are already clocked in. Refresh to see your shift.")
                agency.snapshot_shift(cursor, business_id, employee_id, cursor.fetchone()["id"],
                                      site, assignment, config, evidence)
        flash(f"Clocked in at {site['name']}.", "success")
    except ValueError as error:
        flash(str(error), "error")
    except _DB_ERRORS:
        _database_message()
    return _employee_redirect(business_slug)


def _locked_open_shift(cursor, business_id: str, employee_id: int, shift_id: int):
    _lock_employee(cursor, business_id, employee_id)
    cursor.execute("""SELECT * FROM staff_shifts
        WHERE id=%s AND business_id=%s AND employee_id=%s AND clock_out_at IS NULL FOR UPDATE""",
        (shift_id, business_id, employee_id))
    shift = cursor.fetchone()
    if not shift:
        raise ValueError("That shift is no longer open. Refresh to see your current status.")
    return shift


@staff_blueprint.post("/<business_slug>/employee/clock-out")
@employee_login_required
def employee_clock_out(business_slug: str):
    business_id, employee_id = _business_id(business_slug), g.staff_employee["id"]
    try:
        shift_id = _positive_form_id("shift_id", "Shift")
        with transaction() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                config = agency.locked_settings(cursor, business_id)
                shift = _locked_open_shift(cursor, business_id, employee_id, shift_id)
                # An inactive site may still be used to close its existing shift.
                cursor.execute("""SELECT id,latitude,longitude,allowed_radius_metres,photo_required
                    FROM staff_sites WHERE id=%s AND business_id=%s FOR SHARE""", (shift["site_id"], business_id))
                site = cursor.fetchone()
                if not site:
                    raise ValueError("This shift's site is unavailable. Ask your manager to help close the shift.")
                if shift.get("assignment_id") and shift.get("site_latitude_snapshot") is not None:
                    site = dict(site, latitude=shift["site_latitude_snapshot"],
                                longitude=shift["site_longitude_snapshot"],
                                allowed_radius_metres=shift["site_radius_snapshot"])
                latitude, longitude = _verified_location(site)
                accuracy, captured = agency.gps_evidence(request.form, required=bool(shift.get("assignment_id")))
                cursor.execute("SELECT clock_timestamp() AS finished_at")
                finished_at = cursor.fetchone()["finished_at"]
                cursor.execute("""UPDATE staff_breaks SET ended_at=%s,updated_at=%s
                    WHERE shift_id=%s AND business_id=%s AND employee_id=%s AND ended_at IS NULL""",
                    (finished_at, finished_at, shift_id, business_id, employee_id))
                cursor.execute("""UPDATE staff_shifts SET clock_out_at=%s,clock_out_latitude=%s,
                    clock_out_longitude=%s,updated_at=%s,clock_out_accuracy=%s,clock_out_captured_at=%s,
                    clock_out_verification='within_radius',approval_status='pending' WHERE id=%s AND business_id=%s
                    AND employee_id=%s AND clock_out_at IS NULL""",
                    (finished_at, latitude, longitude, finished_at, accuracy, captured, shift_id, business_id, employee_id))
        flash("Clocked out. Your completed shift is ready for manager review.", "success")
    except ValueError as error:
        flash(str(error), "error")
    except _DB_ERRORS:
        _database_message()
    return _employee_redirect(business_slug)


@staff_blueprint.post("/<business_slug>/employee/break/start")
@employee_login_required
def employee_break_start(business_slug: str):
    business_id, employee_id = _business_id(business_slug), g.staff_employee["id"]
    try:
        shift_id = _positive_form_id("shift_id", "Shift")
        with transaction() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                _locked_open_shift(cursor, business_id, employee_id, shift_id)
                cursor.execute("""INSERT INTO staff_business_settings (business_id)
                    VALUES (%s) ON CONFLICT (business_id) DO NOTHING""", (business_id,))
                cursor.execute("SELECT break_policy FROM staff_business_settings WHERE business_id=%s", (business_id,))
                break_policy = cursor.fetchone()["break_policy"]
                cursor.execute("""INSERT INTO staff_breaks
                    (business_id,employee_id,shift_id,started_at,paid)
                    VALUES (%s,%s,%s,clock_timestamp(),%s)
                    ON CONFLICT (shift_id) WHERE ended_at IS NULL DO NOTHING""",
                    (business_id, employee_id, shift_id, break_policy == "paid"))
                if cursor.rowcount != 1:
                    raise ValueError("You already have an open break.")
        flash("Break started.", "success")
    except ValueError as error:
        flash(str(error), "error")
    except _DB_ERRORS:
        _database_message()
    return _employee_redirect(business_slug)


@staff_blueprint.post("/<business_slug>/employee/break/end")
@employee_login_required
def employee_break_end(business_slug: str):
    business_id, employee_id = _business_id(business_slug), g.staff_employee["id"]
    try:
        shift_id = _positive_form_id("shift_id", "Shift")
        break_id = _positive_form_id("break_id", "Break")
        with transaction() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                _locked_open_shift(cursor, business_id, employee_id, shift_id)
                cursor.execute("""UPDATE staff_breaks SET ended_at=clock_timestamp(),updated_at=clock_timestamp()
                    WHERE id=%s AND shift_id=%s AND business_id=%s AND employee_id=%s AND ended_at IS NULL""",
                    (break_id, shift_id, business_id, employee_id))
                if cursor.rowcount != 1:
                    raise ValueError("That break is no longer open. Refresh your page.")
        flash("Break ended.", "success")
    except ValueError as error:
        flash(str(error), "error")
    except _DB_ERRORS:
        _database_message()
    return _employee_redirect(business_slug)


@staff_blueprint.post("/<business_slug>/employee/leave")
@employee_login_required
def employee_request_leave(business_slug: str):
    try:
        _insert_leave(_business_id(business_slug), g.staff_employee["id"], _leave_input(), "pending")
        flash("Your leave request has been sent to your manager for approval.", "success")
    except ValueError as error:
        flash(str(error), "error")
    except _DB_ERRORS:
        _database_message()
    return _employee_redirect(business_slug)


@staff_blueprint.post("/<business_slug>/employee/leave/<int:leave_id>/cancel")
@employee_login_required
def employee_cancel_leave(business_slug: str, leave_id: int):
    try:
        count = execute("""UPDATE staff_leave_requests SET approval_status='cancelled',updated_at=NOW()
            WHERE id=%s AND business_id=%s AND employee_id=%s AND approval_status='pending'""",
            (leave_id, _business_id(business_slug), g.staff_employee["id"]))
        flash("Pending leave request cancelled." if count else
              "Only your own pending requests can be cancelled here. Contact your manager about approved leave.",
              "success" if count else "error")
    except _DB_ERRORS:
        _database_message()
    return _employee_redirect(business_slug)


# Manager review and profile tools. Every database operation remains business-scoped.
def _page_arg(name):
    return min(1000000, max(1, request.args.get(name, 1, type=int) or 1))


def _approvals_page_link(**changes):
    allowed = {"q", "site", "from_date", "to_date", "page"}
    args = {k: v for k, v in request.args.items() if k in allowed}
    args.update(changes)
    return url_for("staff.approvals_page", business_slug=request.view_args["business_slug"], **args)


def _profile_page_link(**changes):
    allowed = {"employee", "profile_page"}
    args = {k: v for k, v in request.args.items() if k in allowed}
    args.update(changes)
    return url_for("staff.employees_page", business_slug=request.view_args["business_slug"], **args)


def _review_options():
    result = {"q": request.args.get("q", "").strip()[:150],
              "site": request.args.get("site", "").strip(),
              "from_date": request.args.get("from_date", "").strip(),
              "to_date": request.args.get("to_date", "").strip(), "page": _page_arg("page")}
    try:
        if result["site"]:
            if int(result["site"]) <= 0:
                raise ValueError()
        for key in ("from_date", "to_date"):
            if result[key]:
                _parse_date(result[key], key.replace("_", " "))
        if result["from_date"] and result["to_date"] and result["from_date"] > result["to_date"]:
            raise ValueError()
    except ValueError:
        abort(400, description="Check the site and date filters.")
    return result


def _review_where(business_id, review):
    parts = ["shift.business_id=%s", "shift.clock_out_at IS NOT NULL", "shift.approval_status='pending'"]
    params = [business_id]
    if review["q"]:
        parts.append("POSITION(LOWER(%s) IN LOWER(employee.full_name)) > 0")
        params.append(review["q"])
    if review["site"]:
        parts.append("shift.site_id=%s")
        params.append(int(review["site"]))
    for key, op in (("from_date", ">="), ("to_date", "<=")):
        if review[key]:
            parts.append("(shift.clock_in_at AT TIME ZONE 'Europe/London')::date " + op + " %s")
            params.append(_parse_date(review[key], key))
    return " AND ".join(parts), tuple(params)


_SHIFT_REVIEW_SQL = """
    SELECT shift.id,shift.employee_id,employee.full_name,shift.site_name,
           shift.clock_in_at,shift.clock_out_at,shift.approval_status,shift.manager_note,
           ROUND(EXTRACT(EPOCH FROM (COALESCE(shift.clock_out_at,NOW())-shift.clock_in_at))/3600,2) AS hours_worked,
           ROUND(LEAST(EXTRACT(EPOCH FROM (COALESCE(shift.clock_out_at,NOW())-shift.clock_in_at)),
                       COALESCE(b.unpaid_seconds,0))/3600,2) AS unpaid_hours,
           ROUND(GREATEST(0,EXTRACT(EPOCH FROM (COALESCE(shift.clock_out_at,NOW())-shift.clock_in_at))
                       -COALESCE(b.unpaid_seconds,0))/3600,2) AS net_hours
    FROM staff_shifts AS shift JOIN staff_employees AS employee
      ON employee.id=shift.employee_id AND employee.business_id=shift.business_id
    LEFT JOIN LATERAL (
      SELECT SUM(GREATEST(0,EXTRACT(EPOCH FROM
        (LEAST(COALESCE(br.ended_at,NOW()),COALESCE(shift.clock_out_at,NOW()))
         -GREATEST(br.started_at,shift.clock_in_at))))) AS unpaid_seconds
      FROM staff_breaks AS br WHERE br.business_id=shift.business_id
        AND br.employee_id=shift.employee_id AND br.shift_id=shift.id AND NOT br.paid
    ) AS b ON TRUE
"""


@staff_blueprint.post("/<business_slug>/shifts/<int:shift_id>/edit")
@dashboard_login_required
def edit_shift(business_slug: str, shift_id: int):
    business_id = _business_id(business_slug)
    try:
        clock_in_at = parse_shift_datetime(request.form.get("clock_in_at"), "clock-in time")
        clock_out_at = parse_shift_datetime(request.form.get("clock_out_at"), "clock-out time")
        adjustment_reason = _clean_text(request.form.get("adjustment_reason"), 1000)
        with transaction() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                agency.lock_business(cursor, business_id)
                cursor.execute("""
                    SELECT *
                    FROM staff_shifts WHERE id=%s AND business_id=%s FOR UPDATE
                """, (shift_id, business_id))
                shift = cursor.fetchone()
                if not shift:
                    raise ValueError("That shift could not be found.")
                if not shift["clock_out_at"]:
                    raise ValueError("Complete the shift before editing it.")
                cursor.execute("""
                    SELECT id,started_at,ended_at,paid FROM staff_breaks
                    WHERE business_id=%s AND shift_id=%s ORDER BY started_at,id FOR UPDATE
                """, (business_id, shift_id))
                existing_breaks = [dict(row) for row in cursor.fetchall()]
                edited_breaks = []
                for break_record in existing_breaks:
                    prefix = f"break_{break_record['id']}_"
                    edited_breaks.append({
                        "id": break_record["id"],
                        "started_at": parse_shift_datetime(request.form.get(prefix + "started_at"), "break start"),
                        "ended_at": parse_shift_datetime(request.form.get(prefix + "ended_at"), "break end"),
                    })
                validate_shift_edit(clock_in_at, clock_out_at, edited_breaks)
                values = dict(request.form, clock_in_at=clock_in_at, clock_out_at=clock_out_at,
                              adjustment_reason=adjustment_reason)
                message = agency.correct_shift(cursor, business_id, _manager_actor(), shift, values, edited_breaks)
        flash(message, "success")
    except (ValueError, PayrollError) as error:
        flash(str(error), "error")
    except _DB_ERRORS:
        _database_message()
    return redirect(url_for("staff.approvals_page", business_slug=business_slug))


@staff_blueprint.post("/<business_slug>/shifts/approve-selected")
@dashboard_login_required
def approve_selected_shifts(business_slug):
    try:
        raw_ids = request.form.getlist("shift_ids")
        if not 1 <= len(raw_ids) <= 20:
            raise ValueError("Select between 1 and 20 completed shifts on this page.")
        try:
            ids = sorted({int(value) for value in raw_ids})
            if any(value <= 0 for value in ids):
                raise ValueError()
        except ValueError as error:
            raise ValueError("The shift selection is invalid. Refresh and try again.") from error
        # One conditional statement prevents reapproval and never touches other businesses.
        count = execute("""UPDATE staff_shifts SET approval_status='approved',approved_at=NOW(),updated_at=NOW()
            WHERE business_id=%s AND id=ANY(%s) AND clock_out_at IS NOT NULL
              AND approval_status='pending'""", (_business_id(business_slug), ids))
        flash(f"{count} completed shift(s) approved. {len(ids)-count} unavailable or already reviewed.", "success")
    except ValueError as error:
        flash(str(error), "error")
    except _DB_ERRORS:
        _database_message()
    return _page_redirect("staff.approvals_page", business_slug)


@staff_blueprint.post("/<business_slug>/payroll/generate")
@dashboard_login_required
def generate_payroll(business_slug: str):
    try:
        period_start = period_dates(request.form.get("period_start"), "start date")
        period_end = period_dates(request.form.get("period_end"), "end date")
        payment_date = period_dates(request.form.get("payment_date"), "payment date")
        frequency = request.form.get("frequency", "")
        with transaction() as connection:
            with connection.cursor() as cursor:
                agency.lock_business(cursor, _business_id(business_slug))
            result = generate_payroll_run(connection, _business_id(business_slug), period_start, period_end,frequency)
            payroll_ledger.apply_calculations(connection, _business_id(business_slug), result["id"], payment_date, frequency,request.form.get('employer_name'))
        flash(
            f"Draft payroll created for {result['shift_count']} approved shift(s) and "
            f"{result['payslip_count']} employee(s). Gross pay: £{result['total_gross_pay']:.2f}.",
            "success",
        )
    except PayrollError as error:
        flash(str(error), "error")
    except _DB_ERRORS:
        _database_message()
    return _page_redirect("staff.payroll_page", business_slug)


@staff_blueprint.post("/<business_slug>/payroll/profiles/<int:employee_id>")
@dashboard_login_required
def payroll_profile(business_slug, employee_id):
    try:
        with transaction() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                payroll_ledger.save_profile(cursor, _business_id(business_slug), employee_id, request.form, "manager")
        flash("Payroll settings reviewed and saved. Affected drafts must be recalculated.", "success")
    except PayrollError as error:
        flash(str(error), "error")
    except _DB_ERRORS:
        _database_message()
    return _page_redirect("staff.payroll_page", business_slug)


@staff_blueprint.post("/<business_slug>/payroll/<int:run_id>/discard")
@dashboard_login_required
def discard_payroll(business_slug,run_id):
    try:
        with transaction() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                payroll_ledger.discard_draft(cursor,_business_id(business_slug),run_id,request.form.get('reason'),'manager')
        flash('Draft discarded and its shifts released. The audit record is retained.','success')
    except PayrollError as error:
        flash(str(error),'error')
    except _DB_ERRORS:
        _database_message()
    return _page_redirect('staff.payroll_page',business_slug)


@staff_blueprint.get("/<business_slug>/payroll/<int:run_id>")
@dashboard_login_required
def payroll_detail(business_slug, run_id):
    business_id = _business_id(business_slug)
    run = fetch_one("SELECT * FROM staff_payroll_runs WHERE id=%s AND business_id=%s", (run_id,business_id))
    if not run:
        abort(404)
    slips = fetch_all("""SELECT p.*,c.employee_name,c.result,n.status AS email_status,n.error_code
        FROM staff_payslips p LEFT JOIN staff_payroll_calculations c ON c.payslip_id=p.id AND c.business_id=p.business_id
        LEFT JOIN staff_payslip_notifications n ON n.payslip_id=p.id AND n.business_id=p.business_id
        WHERE p.payroll_run_id=%s AND p.business_id=%s ORDER BY p.employee_id""", (run_id,business_id))
    return render_template("staff_payroll_detail.html",run=run,slips=slips,business_slug=business_slug,csrf_token=_get_csrf_token)


def _payslip_document(business_slug, slip_id, employee_id=None):
    slip = fetch_one("""SELECT p.*,r.status,r.needs_recalculation,r.period_start,r.period_end,c.payment_date,
        c.tax_year,c.tax_period,c.frequency,c.profile,c.employee_name,c.employer_name,c.result
        FROM staff_payslips p JOIN staff_payroll_runs r ON r.id=p.payroll_run_id AND r.business_id=p.business_id
        JOIN staff_payroll_calculations c ON c.payslip_id=p.id AND c.business_id=p.business_id
        WHERE p.id=%s AND p.business_id=%s AND (%s IS NULL OR p.employee_id=%s)""",
        (slip_id, _business_id(business_slug), employee_id, employee_id))
    if not slip or slip["needs_recalculation"] or (employee_id is not None and slip["status"] == "draft"):
        abort(404)
    from trimtech.modules.staff.payslip_pdf import render as render_pdf
    response = make_response(render_pdf(slip))
    response.headers["Content-Type"] = 'application/pdf'
    response.headers["Content-Disposition"] = f'attachment; filename="payslip-{slip_id}.pdf"'
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@staff_blueprint.get("/<business_slug>/payroll/payslips/<int:slip_id>/download")
@dashboard_login_required
def manager_payslip_download(business_slug, slip_id):
    return _payslip_document(business_slug, slip_id)


@staff_blueprint.get("/<business_slug>/employee/payslips/<int:slip_id>/download")
@employee_login_required
def employee_payslip_download(business_slug, slip_id):
    return _payslip_document(business_slug, slip_id, int(g.staff_employee["id"]))


@staff_blueprint.post("/<business_slug>/payroll/payslips/<int:slip_id>/send")
@dashboard_login_required
def send_payslip(business_slug, slip_id):
    business_id = _business_id(business_slug)
    try:
        with transaction() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                payslip_delivery.queue(cursor, business_id, slip_id)
        status = payslip_delivery.dispatch(business_id, slip_id)
        flash({"sent":"Payslip notice accepted by email provider; inbox delivery is not confirmed.",
               "failed":"Payslip email failed. Check delivery status and configuration.",
               "disabled":"Payslip email is disabled.","pending":"Payslip notice is queued."}[status],
              "success" if status == "sent" else "error")
    except PayrollError as error:
        flash(str(error), "error")
    except _DB_ERRORS:
        _database_message()
    return _page_redirect("staff.payroll_page", business_slug)


@staff_blueprint.post("/<business_slug>/payroll/<int:run_id>/approve")
@dashboard_login_required
def approve_payroll(business_slug: str, run_id: int):
    try:
        with transaction() as connection:
            with connection.cursor() as cursor:
                agency.lock_business(cursor, _business_id(business_slug))
                cursor.execute("""UPDATE staff_payroll_runs SET status='approved',approved_at=NOW(),updated_at=NOW()
                    WHERE id=%s AND business_id=%s AND status='draft' AND NOT needs_recalculation""",
                    (run_id, _business_id(business_slug)))
                count = cursor.rowcount
        flash("Payroll run approved." if count else "That draft is unavailable or needs recalculation.",
              "success" if count else "error")
    except _DB_ERRORS:
        _database_message()
    return _page_redirect("staff.payroll_page", business_slug)


@staff_blueprint.post("/<business_slug>/employees/<int:employee_id>/edit")
@dashboard_login_required
def edit_employee(business_slug, employee_id):
    business_id = _business_id(business_slug)
    try:
        name = _clean_text(request.form.get("full_name"),150)
        phone = _clean_phone(request.form.get("phone"))
        email = _clean_text(request.form.get("email"),254).lower()
        role = _clean_text(request.form.get("role"),20)
        if not name or not any(c.isdigit() for c in phone):
            raise ValueError("Enter a full name and phone number.")
        if role not in {"staff","manager","owner"}:
            raise ValueError("Select a valid role.")
        if email and ("@" not in email or any(c.isspace() for c in email)):
            raise ValueError("Enter a valid email address.")
        rate = _parse_hourly_rate(request.form.get("hourly_rate"))
        with transaction() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("SELECT id FROM staff_employees WHERE id=%s AND business_id=%s FOR UPDATE",
                               (employee_id,business_id))
                if not cursor.fetchone():
                    abort(404)
                cursor.execute("SELECT id FROM staff_employees WHERE business_id=%s AND phone=%s AND id<>%s",
                               (business_id,phone,employee_id))
                if cursor.fetchone():
                    raise ValueError("Another employee already uses that phone number.")
                # A blank payroll field preserves the existing login credential.
                payroll = _clean_text(request.form.get("payroll_number"),50)
                cursor.execute("""UPDATE staff_employees SET full_name=%s,phone=%s,email=NULLIF(%s,''),
                    role=%s,hourly_rate=%s,payroll_number=COALESCE(NULLIF(%s,''),payroll_number),updated_at=NOW()
                    WHERE id=%s AND business_id=%s""", (name,phone,email,role,rate,payroll,employee_id,business_id))
        flash("Employee details updated. Rate changes do not create or recalculate payslips.", "success")
    except ValueError as error:
        flash(str(error), "error")
    except _DB_ERRORS:
        _database_message()
    return redirect(url_for("staff.employees_page", business_slug=business_slug,employee=employee_id,_anchor="profile"))


def _today_hours(business_id, employee_id):
    # Timestamp bounds use UK midnight, including 23/25-hour daylight-saving days.
    # Each break is clipped to its own shift and today's interval before subtraction.
    return fetch_one("""
        WITH period AS (
          SELECT (DATE_TRUNC('day',NOW() AT TIME ZONE 'Europe/London')
                  AT TIME ZONE 'Europe/London') AS day_start,NOW() AS as_of
        ), clipped AS (
          SELECT s.id,s.employee_id,s.business_id,
                 GREATEST(s.clock_in_at,p.day_start) AS begins,
                 LEAST(COALESCE(s.clock_out_at,p.as_of),p.as_of) AS ends
          FROM staff_shifts s CROSS JOIN period p
          WHERE s.business_id=%s AND s.employee_id=%s AND s.clock_in_at<p.as_of
            AND COALESCE(s.clock_out_at,p.as_of)>p.day_start
        ), amounts AS (
          SELECT GREATEST(0,EXTRACT(EPOCH FROM (c.ends-c.begins))) AS elapsed,
                 LEAST(GREATEST(0,EXTRACT(EPOCH FROM (c.ends-c.begins))),
                   COALESCE((SELECT SUM(GREATEST(0,EXTRACT(EPOCH FROM
                     (LEAST(COALESCE(b.ended_at,c.ends),c.ends)-GREATEST(b.started_at,c.begins)))))
                     FROM staff_breaks b WHERE b.business_id=c.business_id AND b.employee_id=c.employee_id
                       AND b.shift_id=c.id AND NOT b.paid),0)) AS unpaid
          FROM clipped c
        ) SELECT ROUND(COALESCE(SUM(elapsed),0)/3600,2) AS elapsed_hours,
                 ROUND(COALESCE(SUM(unpaid),0)/3600,2) AS unpaid_hours,
                 ROUND(COALESCE(SUM(elapsed-unpaid),0)/3600,2) AS net_hours
          FROM amounts
    """, (business_id,employee_id)) or {"elapsed_hours":0,"unpaid_hours":0,"net_hours":0}


def _manager_actor():
    return "manager:" + str(session.get("dashboard_username") or "dashboard")


from trimtech.modules.staff.agency_routes import register_routes
import sys

register_routes(sys.modules[__name__])
