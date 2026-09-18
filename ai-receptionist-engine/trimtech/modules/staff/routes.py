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
    request, session, url_for,
)
from psycopg2 import Error as PostgreSQLError
from psycopg2.extras import RealDictCursor

from dashboard_auth import dashboard_login_required
from trimtech.modules.staff.database import (
    StaffDatabaseError, execute, fetch_all, fetch_one,
    init_staff_database, transaction,
)


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


def _manager_redirect(business_slug: str):
    return redirect(url_for("staff.dashboard", business_slug=business_slug))


def _employee_redirect(business_slug: str):
    return redirect(url_for("staff.employee_home", business_slug=business_slug))


def _database_message():
    # Keep database details out of browser messages.
    current_app.logger.exception("Staff Manager database operation failed")
    flash("Staff Manager could not save that change. Please try again.", "error")


@staff_blueprint.get("/<business_slug>")
@dashboard_login_required
def dashboard(business_slug: str):
    business_id = _business_id(business_slug)
    summary = dict(active_employees=0, staff_clocked_in=0, shifts_waiting_approval=0,
                   hours_this_week=0, on_holiday_today=0)
    employees, sites, live_shifts, pending_shifts = [], [], [], []
    current_leave, upcoming_leave, pending_leave = [], [], []
    try:
        init_staff_database()
        summary = fetch_one("""
            SELECT
              (SELECT COUNT(*) FROM staff_employees
               WHERE business_id=%s AND status='active') AS active_employees,
              (SELECT COUNT(*) FROM staff_shifts
               WHERE business_id=%s AND clock_out_at IS NULL) AS staff_clocked_in,
              (SELECT COUNT(*) FROM staff_shifts
               WHERE business_id=%s AND approval_status='pending') AS shifts_waiting_approval,
              (SELECT COALESCE(ROUND(SUM(EXTRACT(EPOCH FROM
                 (COALESCE(clock_out_at,NOW())-clock_in_at))/3600)::numeric,1),0)
               FROM staff_shifts WHERE business_id=%s
               AND clock_in_at >= DATE_TRUNC('week',NOW())) AS hours_this_week,
              (SELECT COUNT(*) FROM staff_leave_requests WHERE business_id=%s
               AND leave_type='holiday' AND approval_status='approved'
               AND CURRENT_DATE BETWEEN start_date AND end_date) AS on_holiday_today
        """, (business_id,) * 5) or summary
        employees = fetch_all("""
            SELECT id, full_name, phone, email, role, hourly_rate, status, payroll_number, created_at
            FROM staff_employees WHERE business_id=%s
            ORDER BY CASE WHEN status='active' THEN 0 ELSE 1 END, full_name
        """, (business_id,))
        sites = fetch_all("""
            SELECT id, name, address, latitude, longitude, allowed_radius_metres,
                   photo_required, active, created_at
            FROM staff_sites WHERE business_id=%s
            ORDER BY CASE WHEN active THEN 0 ELSE 1 END, name
        """, (business_id,))
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
        pending_shifts = fetch_all(shift_query + """
            AND shift.approval_status='pending' ORDER BY shift.clock_in_at LIMIT 20
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
        current_app.logger.exception("Staff dashboard could not load")
        flash("Staff Manager data is temporarily unavailable. Please refresh to try again.", "error")
    return render_template(
        "staff_dashboard.html", business_slug=business_slug, summary=summary,
        employees=employees, sites=sites, live_shifts=live_shifts,
        pending_shifts=pending_shifts, current_leave=current_leave,
        upcoming_leave=upcoming_leave, pending_leave=pending_leave, csrf_token=_get_csrf_token,
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
    return _manager_redirect(business_slug)


@staff_blueprint.post("/<business_slug>/employees/<int:employee_id>/status")
@dashboard_login_required
def change_employee_status(business_slug: str, employee_id: int):
    status = _clean_text(request.form.get("status"), 20).lower()
    if status not in {"active", "inactive"}:
        flash("Select a valid employee status.", "error")
        return _manager_redirect(business_slug)
    try:
        count = execute("""UPDATE staff_employees SET status=%s,updated_at=NOW()
            WHERE id=%s AND business_id=%s""", (status, employee_id, _business_id(business_slug)))
        flash("Employee status updated." if count else "That employee could not be found.",
              "success" if count else "error")
    except _DB_ERRORS:
        _database_message()
    return _manager_redirect(business_slug)


@staff_blueprint.post("/<business_slug>/sites")
@dashboard_login_required
def add_site(business_slug: str):
    business_id = _business_id(business_slug)
    name = _clean_text(request.form.get("name"), 150)
    try:
        if not name:
            raise ValueError("Enter the site name.")
        latitude = _parse_coordinate(request.form.get("latitude"), "latitude", Decimal(-90), Decimal(90))
        longitude = _parse_coordinate(request.form.get("longitude"), "longitude", Decimal(-180), Decimal(180))
        radius = _parse_radius(request.form.get("allowed_radius_metres"))
        if fetch_one("SELECT id FROM staff_sites WHERE business_id=%s AND LOWER(name)=LOWER(%s)",
                     (business_id, name)):
            raise ValueError("A site with that name already exists.")
        execute("""INSERT INTO staff_sites
            (business_id,name,address,latitude,longitude,allowed_radius_metres,photo_required,active)
            VALUES (%s,%s,NULLIF(%s,''),%s,%s,%s,%s,TRUE)""",
            (business_id, name, _clean_text(request.form.get("address"), 1000), latitude,
             longitude, radius, request.form.get("photo_required") == "on"))
        flash(f"{name} has been added as a work site.", "success")
    except ValueError as error:
        flash(str(error), "error")
    except _DB_ERRORS:
        _database_message()
    return _manager_redirect(business_slug)


@staff_blueprint.post("/<business_slug>/sites/<int:site_id>/status")
@dashboard_login_required
def change_site_status(business_slug: str, site_id: int):
    status = _clean_text(request.form.get("status"), 20).lower()
    if status not in {"active", "inactive"}:
        flash("Select a valid site status.", "error")
        return _manager_redirect(business_slug)
    try:
        count = execute("""UPDATE staff_sites SET active=%s,updated_at=NOW()
            WHERE id=%s AND business_id=%s""", (status == "active", site_id, _business_id(business_slug)))
        flash("Work site status updated." if count else "That work site could not be found.",
              "success" if count else "error")
    except _DB_ERRORS:
        _database_message()
    return _manager_redirect(business_slug)


@staff_blueprint.post("/<business_slug>/shifts/<int:shift_id>/approve")
@dashboard_login_required
def approve_shift(business_slug: str, shift_id: int):
    try:
        count = execute("""UPDATE staff_shifts SET approval_status='approved',approved_at=NOW(),
            manager_note=NULLIF(%s,'') WHERE id=%s AND business_id=%s AND clock_out_at IS NOT NULL""",
            (_clean_text(request.form.get("manager_note"), 500), shift_id, _business_id(business_slug)))
        flash("Shift approved." if count else "Only completed shifts can be approved.",
              "success" if count else "error")
    except _DB_ERRORS:
        _database_message()
    return _manager_redirect(business_slug)


@staff_blueprint.post("/<business_slug>/shifts/<int:shift_id>/reject")
@dashboard_login_required
def reject_shift(business_slug: str, shift_id: int):
    note = _clean_text(request.form.get("manager_note"), 500)
    if not note:
        flash("Enter a reason before rejecting the shift.", "error")
        return _manager_redirect(business_slug)
    try:
        count = execute("""UPDATE staff_shifts SET approval_status='rejected',approved_at=NOW(),
            manager_note=%s WHERE id=%s AND business_id=%s""", (note, shift_id, _business_id(business_slug)))
        flash("Shift rejected." if count else "That shift could not be found.", "success" if count else "error")
    except _DB_ERRORS:
        _database_message()
    return _manager_redirect(business_slug)


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
    return _manager_redirect(business_slug)


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
    return _manager_redirect(business_slug)


@staff_blueprint.post("/<business_slug>/leave/<int:leave_id>/reject")
@dashboard_login_required
def reject_leave(business_slug: str, leave_id: int):
    note = _clean_text(request.form.get("manager_note"), 1000)
    if not note:
        flash("Enter a reason before rejecting the request.", "error")
        return _manager_redirect(business_slug)
    try:
        count = execute("""UPDATE staff_leave_requests SET approval_status='rejected',approved_at=NOW(),
            manager_note=%s,updated_at=NOW() WHERE id=%s AND business_id=%s AND approval_status='pending'""",
            (note, leave_id, _business_id(business_slug)))
        flash("Leave request rejected." if count else "That pending leave request could not be found.",
              "success" if count else "error")
    except _DB_ERRORS:
        _database_message()
    return _manager_redirect(business_slug)


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
    return _manager_redirect(business_slug)


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
    if (request.endpoint or "").startswith("staff.employee_"):
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
@employee_login_required
def employee_home(business_slug: str):
    """Keep existing template variables and add sites, break status and leave history.

    Elapsed hours retain the original meaning (all approval states, before breaks).
    Database timezone is retained for consistency with the existing manager view.
    """
    employee = g.staff_employee
    parameters = (_business_id(business_slug), employee["id"])
    try:
        current_shift = fetch_one("""SELECT id,site_id,site_name,clock_in_at,approval_status
            FROM staff_shifts WHERE business_id=%s AND employee_id=%s AND clock_out_at IS NULL
            ORDER BY clock_in_at DESC LIMIT 1""", parameters)
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
        sites = fetch_all("""SELECT id,name,address,photo_required,allowed_radius_metres FROM staff_sites
            WHERE business_id=%s AND active=TRUE ORDER BY name""", (parameters[0],))
        current_break = None
        if current_shift:
            current_break = fetch_one("""SELECT id,started_at,paid FROM staff_breaks
                WHERE business_id=%s AND employee_id=%s AND shift_id=%s AND ended_at IS NULL LIMIT 1""",
                parameters + (current_shift["id"],))
    except _DB_ERRORS:
        current_app.logger.exception("Employee summary failed")
        abort(503, description="Your employee summary is temporarily unavailable.")
    return render_template(
        "staff_employee_home.html", business_slug=business_slug, employee=employee,
        current_shift=current_shift, is_clocked_in=current_shift is not None,
        hours_this_week=hours_summary.get("hours_this_week", Decimal("0")),
        week_start=hours_summary.get("week_start"), week_end=hours_summary.get("week_end"),
        as_of=hours_summary.get("as_of"), leave_summary=leave_summary, pending_leave=pending_leave,
        upcoming_leave=upcoming_leave, current_leave=current_leave, csrf_token=_get_csrf_token,
        sites=sites, current_break=current_break, leave_history=leave_history,
    )


# Portal action contract for staff_employee_home.html:
# All forms POST csrf_token. Clock forms also POST latitude, longitude, accuracy.
# Clock-in POSTs site_id; clock-out and break forms POST shift_id to prevent a
# delayed/replayed form from closing a newer shift. Leave POSTs leave_type,
# start_date, end_date and optional employee_note. Identity comes ONLY from session.


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
        site_id = _positive_form_id("site_id", "Work site")
        with transaction() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                _lock_employee(cursor, business_id, employee_id)
                cursor.execute("""SELECT id FROM staff_shifts WHERE business_id=%s AND employee_id=%s
                    AND clock_out_at IS NULL""", (business_id, employee_id))
                if cursor.fetchone():
                    raise ValueError("You are already clocked in. Refresh to see your current shift.")
                cursor.execute("""SELECT id,name,latitude,longitude,allowed_radius_metres,photo_required
                    FROM staff_sites WHERE id=%s AND business_id=%s AND active=TRUE FOR SHARE""", (site_id, business_id))
                site = cursor.fetchone()
                if not site:
                    raise ValueError("That active work site could not be found.")
                latitude, longitude = _verified_location(site)
                cursor.execute("""INSERT INTO staff_shifts
                    (business_id,employee_id,site_id,site_name,clock_in_at,
                     clock_in_latitude,clock_in_longitude,approval_status)
                    VALUES (%s,%s,%s,%s,clock_timestamp(),%s,%s,'pending')
                    ON CONFLICT (business_id,employee_id) WHERE clock_out_at IS NULL DO NOTHING""",
                    (business_id, employee_id, site["id"], site["name"], latitude, longitude))
                if cursor.rowcount != 1:
                    raise ValueError("You are already clocked in. Refresh to see your shift.")
        flash(f"Clocked in at {site['name']}.", "success")
    except ValueError as error:
        flash(str(error), "error")
    except _DB_ERRORS:
        _database_message()
    return _employee_redirect(business_slug)


def _locked_open_shift(cursor, business_id: str, employee_id: int, shift_id: int):
    _lock_employee(cursor, business_id, employee_id)
    cursor.execute("""SELECT id,site_id,site_name,clock_in_at FROM staff_shifts
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
                shift = _locked_open_shift(cursor, business_id, employee_id, shift_id)
                # An inactive site may still be used to close its existing shift.
                cursor.execute("""SELECT id,latitude,longitude,allowed_radius_metres,photo_required
                    FROM staff_sites WHERE id=%s AND business_id=%s FOR SHARE""", (shift["site_id"], business_id))
                site = cursor.fetchone()
                if not site:
                    raise ValueError("This shift's site is unavailable. Ask your manager to help close the shift.")
                latitude, longitude = _verified_location(site)
                cursor.execute("SELECT clock_timestamp() AS finished_at")
                finished_at = cursor.fetchone()["finished_at"]
                cursor.execute("""UPDATE staff_breaks SET ended_at=%s,updated_at=%s
                    WHERE shift_id=%s AND business_id=%s AND employee_id=%s AND ended_at IS NULL""",
                    (finished_at, finished_at, shift_id, business_id, employee_id))
                cursor.execute("""UPDATE staff_shifts SET clock_out_at=%s,clock_out_latitude=%s,
                    clock_out_longitude=%s,updated_at=%s WHERE id=%s AND business_id=%s
                    AND employee_id=%s AND clock_out_at IS NULL""",
                    (finished_at, latitude, longitude, finished_at, shift_id, business_id, employee_id))
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
                cursor.execute("""INSERT INTO staff_breaks
                    (business_id,employee_id,shift_id,started_at,paid)
                    VALUES (%s,%s,%s,clock_timestamp(),FALSE)
                    ON CONFLICT (shift_id) WHERE ended_at IS NULL DO NOTHING""",
                    (business_id, employee_id, shift_id))
                if cursor.rowcount != 1:
                    raise ValueError("You already have an open break.")
        flash("Unpaid break started.", "success")
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
