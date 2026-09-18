from __future__ import annotations

import hmac
import secrets
import threading
import time
from functools import wraps
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from flask import (
    Blueprint,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from psycopg2 import Error as PostgreSQLError

from dashboard_auth import dashboard_login_required
from trimtech.modules.staff.database import (
    StaffDatabaseError,
    execute,
    fetch_all,
    fetch_one,
    init_staff_database,
)


staff_blueprint = Blueprint(
    "staff",
    __name__,
    url_prefix="/staff",
)

# Short alias for compatibility with other module naming styles.
staff_bp = staff_blueprint


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

    expected_token = session.get("_staff_csrf_token", "")
    received_token = request.form.get("csrf_token", "")

    if (
        not expected_token
        or not received_token
        or not hmac.compare_digest(expected_token, received_token)
    ):
        abort(400)

    return None


def _business_id(business_slug: str) -> str:
    return str(business_slug or "").strip().lower()


def _clean_text(value: Any, maximum_length: int = 255) -> str:
    return str(value or "").strip()[:maximum_length]


def _clean_phone(value: Any) -> str:
    phone = _clean_text(value, 30)
    return "".join(
        character
        for character in phone
        if character.isdigit() or character == "+"
    )


def _parse_hourly_rate(value: Any) -> Decimal:
    cleaned = str(value or "").strip().replace(",", "")

    try:
        hourly_rate = Decimal(cleaned).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError) as error:
        raise ValueError("Enter a valid hourly rate.") from error

    if hourly_rate < 0:
        raise ValueError("Hourly rate cannot be negative.")

    return hourly_rate


def _parse_coordinate(
    value: Any,
    label: str,
    minimum: Decimal,
    maximum: Decimal,
) -> Decimal:
    cleaned = str(value or "").strip()

    try:
        coordinate = Decimal(cleaned)
    except (InvalidOperation, ValueError) as error:
        raise ValueError(f"Enter a valid {label}.") from error

    if coordinate < minimum or coordinate > maximum:
        raise ValueError(
            f"{label.capitalize()} must be between {minimum} and {maximum}."
        )

    return coordinate.quantize(Decimal("0.0000001"))


def _parse_radius(value: Any) -> int:
    cleaned = str(value or "").strip()

    try:
        radius = int(cleaned)
    except (TypeError, ValueError) as error:
        raise ValueError("Enter a valid GPS radius.") from error

    if radius < 10 or radius > 10000:
        raise ValueError("GPS radius must be between 10 and 10,000 metres.")

    return radius


def _parse_date(value: Any, label: str) -> date:
    cleaned = str(value or "").strip()

    try:
        return date.fromisoformat(cleaned)
    except ValueError as error:
        raise ValueError(f"Enter a valid {label}.") from error


def _working_days(start_date: date, end_date: date) -> Decimal:
    current_date = start_date
    total_days = 0

    while current_date <= end_date:
        if current_date.weekday() < 5:
            total_days += 1
        current_date += timedelta(days=1)

    return Decimal(total_days)


@staff_blueprint.get("/<business_slug>")
@dashboard_login_required
def dashboard(business_slug: str):
    """
    Show the live Staff Manager dashboard for one business.

    The first successful visit also creates any missing Staff Manager
    tables and indexes.
    """
    business_id = _business_id(business_slug)

    try:
        init_staff_database()

        summary = fetch_one(
            """
            SELECT
                (
                    SELECT COUNT(*)
                    FROM staff_employees
                    WHERE business_id = %s
                      AND status = 'active'
                ) AS active_employees,
                (
                    SELECT COUNT(*)
                    FROM staff_shifts
                    WHERE business_id = %s
                      AND clock_out_at IS NULL
                ) AS staff_clocked_in,
                (
                    SELECT COUNT(*)
                    FROM staff_shifts
                    WHERE business_id = %s
                      AND approval_status = 'pending'
                ) AS shifts_waiting_approval,
                (
                    SELECT COALESCE(
                        ROUND(
                            SUM(
                                EXTRACT(
                                    EPOCH FROM (
                                        COALESCE(clock_out_at, NOW()) -
                                        clock_in_at
                                    )
                                ) / 3600
                            )::numeric,
                            1
                        ),
                        0
                    )
                    FROM staff_shifts
                    WHERE business_id = %s
                      AND clock_in_at >= DATE_TRUNC('week', NOW())
                ) AS hours_this_week,
                (
                    SELECT COUNT(*)
                    FROM staff_leave_requests
                    WHERE business_id = %s
                      AND leave_type = 'holiday'
                      AND approval_status = 'approved'
                      AND CURRENT_DATE BETWEEN start_date AND end_date
                ) AS on_holiday_today
            """,
            (
                business_id,
                business_id,
                business_id,
                business_id,
                business_id,
            ),
        ) or {}

        employees = fetch_all(
            """
            SELECT
                id,
                full_name,
                phone,
                email,
                role,
                hourly_rate,
                status,
                payroll_number,
                created_at
            FROM staff_employees
            WHERE business_id = %s
            ORDER BY
                CASE WHEN status = 'active' THEN 0 ELSE 1 END,
                full_name ASC
            """,
            (business_id,),
        )

        sites = fetch_all(
            """
            SELECT
                id,
                name,
                address,
                latitude,
                longitude,
                allowed_radius_metres,
                photo_required,
                active,
                created_at
            FROM staff_sites
            WHERE business_id = %s
            ORDER BY
                CASE WHEN active THEN 0 ELSE 1 END,
                name ASC
            """,
            (business_id,),
        )

        live_shifts = fetch_all(
            """
            SELECT
                shift.id,
                shift.employee_id,
                employee.full_name,
                employee.role,
                shift.site_name,
                shift.clock_in_at,
                shift.clock_out_at,
                shift.approval_status,
                shift.manager_note,
                CASE
                    WHEN shift.clock_out_at IS NULL THEN
                        ROUND(
                            (
                                EXTRACT(
                                    EPOCH FROM (
                                        NOW() - shift.clock_in_at
                                    )
                                ) / 3600
                            )::numeric,
                            2
                        )
                    ELSE
                        ROUND(
                            (
                                EXTRACT(
                                    EPOCH FROM (
                                        shift.clock_out_at -
                                        shift.clock_in_at
                                    )
                                ) / 3600
                            )::numeric,
                            2
                        )
                END AS hours_worked
            FROM staff_shifts AS shift
            JOIN staff_employees AS employee
              ON employee.id = shift.employee_id
            WHERE shift.business_id = %s
              AND (
                    shift.clock_out_at IS NULL
                    OR shift.clock_in_at::date = CURRENT_DATE
                  )
            ORDER BY
                CASE WHEN shift.clock_out_at IS NULL THEN 0 ELSE 1 END,
                shift.clock_in_at DESC
            """,
            (business_id,),
        )

        pending_shifts = fetch_all(
            """
            SELECT
                shift.id,
                employee.full_name,
                shift.site_name,
                shift.clock_in_at,
                shift.clock_out_at,
                shift.approval_status,
                ROUND(
                    (
                        EXTRACT(
                            EPOCH FROM (
                                COALESCE(shift.clock_out_at, NOW()) -
                                shift.clock_in_at
                            )
                        ) / 3600
                    )::numeric,
                    2
                ) AS hours_worked
            FROM staff_shifts AS shift
            JOIN staff_employees AS employee
              ON employee.id = shift.employee_id
            WHERE shift.business_id = %s
              AND shift.approval_status = 'pending'
            ORDER BY shift.clock_in_at ASC
            LIMIT 20
            """,
            (business_id,),
        )

        current_leave = fetch_all(
            """
            SELECT
                leave_request.id,
                leave_request.employee_id,
                employee.full_name,
                employee.role,
                leave_request.leave_type,
                leave_request.start_date,
                leave_request.end_date,
                leave_request.total_days,
                leave_request.employee_note,
                leave_request.manager_note
            FROM staff_leave_requests AS leave_request
            JOIN staff_employees AS employee
              ON employee.id = leave_request.employee_id
            WHERE leave_request.business_id = %s
              AND leave_request.approval_status = 'approved'
              AND CURRENT_DATE BETWEEN
                    leave_request.start_date
                    AND leave_request.end_date
            ORDER BY employee.full_name ASC
            """,
            (business_id,),
        )

        upcoming_leave = fetch_all(
            """
            SELECT
                leave_request.id,
                leave_request.employee_id,
                employee.full_name,
                employee.role,
                leave_request.leave_type,
                leave_request.start_date,
                leave_request.end_date,
                leave_request.total_days,
                leave_request.employee_note,
                leave_request.manager_note
            FROM staff_leave_requests AS leave_request
            JOIN staff_employees AS employee
              ON employee.id = leave_request.employee_id
            WHERE leave_request.business_id = %s
              AND leave_request.approval_status = 'approved'
              AND leave_request.start_date > CURRENT_DATE
            ORDER BY
                leave_request.start_date ASC,
                employee.full_name ASC
            LIMIT 20
            """,
            (business_id,),
        )

        pending_leave = fetch_all(
            """
            SELECT
                leave_request.id,
                leave_request.employee_id,
                employee.full_name,
                employee.role,
                leave_request.leave_type,
                leave_request.start_date,
                leave_request.end_date,
                leave_request.total_days,
                leave_request.employee_note
            FROM staff_leave_requests AS leave_request
            JOIN staff_employees AS employee
              ON employee.id = leave_request.employee_id
            WHERE leave_request.business_id = %s
              AND leave_request.approval_status = 'pending'
            ORDER BY
                leave_request.start_date ASC,
                employee.full_name ASC
            LIMIT 20
            """,
            (business_id,),
        )

    except StaffDatabaseError as error:
        flash(str(error), "error")
        summary = {
            "active_employees": 0,
            "staff_clocked_in": 0,
            "shifts_waiting_approval": 0,
            "hours_this_week": 0,
            "on_holiday_today": 0,
        }
        employees = []
        sites = []
        live_shifts = []
        pending_shifts = []
        current_leave = []
        upcoming_leave = []
        pending_leave = []

    return render_template(
        "staff_dashboard.html",
        business_slug=business_slug,
        summary=summary,
        employees=employees,
        sites=sites,
        live_shifts=live_shifts,
        pending_shifts=pending_shifts,
        current_leave=current_leave,
        upcoming_leave=upcoming_leave,
        pending_leave=pending_leave,
        csrf_token=_get_csrf_token,
    )


@staff_blueprint.post("/<business_slug>/employees")
@dashboard_login_required
def add_employee(business_slug: str):
    """Add a staff member to the current business."""
    business_id = _business_id(business_slug)

    full_name = _clean_text(request.form.get("full_name"), 150)
    phone = _clean_phone(request.form.get("phone"))
    email = _clean_text(request.form.get("email"), 255).lower()
    role = _clean_text(request.form.get("role"), 20).lower() or "staff"
    payroll_number = _clean_text(
        request.form.get("payroll_number"),
        50,
    )

    if not full_name:
        flash("Enter the employee’s full name.", "error")
        return redirect(url_for("staff.dashboard", business_slug=business_slug))

    if not phone:
        flash("Enter the employee’s phone number.", "error")
        return redirect(url_for("staff.dashboard", business_slug=business_slug))

    if role not in {"owner", "manager", "staff"}:
        flash("Select a valid staff role.", "error")
        return redirect(url_for("staff.dashboard", business_slug=business_slug))

    try:
        hourly_rate = _parse_hourly_rate(
            request.form.get("hourly_rate")
        )

        existing_employee = fetch_one(
            """
            SELECT id
            FROM staff_employees
            WHERE business_id = %s
              AND phone = %s
            """,
            (business_id, phone),
        )

        if existing_employee:
            flash(
                "A staff member with that phone number already exists.",
                "error",
            )
            return redirect(
                url_for("staff.dashboard", business_slug=business_slug)
            )

        execute(
            """
            INSERT INTO staff_employees (
                business_id,
                full_name,
                phone,
                email,
                role,
                hourly_rate,
                status,
                payroll_number
            )
            VALUES (
                %s,
                %s,
                %s,
                NULLIF(%s, ''),
                %s,
                %s,
                'active',
                NULLIF(%s, '')
            )
            """,
            (
                business_id,
                full_name,
                phone,
                email,
                role,
                hourly_rate,
                payroll_number,
            ),
        )

    except ValueError as error:
        flash(str(error), "error")
    except StaffDatabaseError as error:
        flash(str(error), "error")
    else:
        flash(f"{full_name} has been added to Staff Manager.", "success")

    return redirect(url_for("staff.dashboard", business_slug=business_slug))


@staff_blueprint.post(
    "/<business_slug>/employees/<int:employee_id>/status"
)
@dashboard_login_required
def change_employee_status(
    business_slug: str,
    employee_id: int,
):
    """Activate or deactivate an employee."""
    business_id = _business_id(business_slug)
    new_status = _clean_text(request.form.get("status"), 20).lower()

    if new_status not in {"active", "inactive"}:
        flash("Select a valid employee status.", "error")
        return redirect(url_for("staff.dashboard", business_slug=business_slug))

    try:
        updated_rows = execute(
            """
            UPDATE staff_employees
            SET
                status = %s,
                updated_at = NOW()
            WHERE id = %s
              AND business_id = %s
            """,
            (
                new_status,
                employee_id,
                business_id,
            ),
        )

        if updated_rows == 0:
            flash("That employee could not be found.", "error")
        else:
            flash("Employee status updated.", "success")

    except StaffDatabaseError as error:
        flash(str(error), "error")

    return redirect(url_for("staff.dashboard", business_slug=business_slug))


@staff_blueprint.post("/<business_slug>/sites")
@dashboard_login_required
def add_site(business_slug: str):
    """Add a GPS-verified work site to the current business."""
    business_id = _business_id(business_slug)
    name = _clean_text(request.form.get("name"), 150)
    address = _clean_text(request.form.get("address"), 1000)
    photo_required = request.form.get("photo_required") == "on"

    if not name:
        flash("Enter the site name.", "error")
        return redirect(url_for("staff.dashboard", business_slug=business_slug))

    try:
        latitude = _parse_coordinate(
            request.form.get("latitude"),
            "latitude",
            Decimal("-90"),
            Decimal("90"),
        )
        longitude = _parse_coordinate(
            request.form.get("longitude"),
            "longitude",
            Decimal("-180"),
            Decimal("180"),
        )
        radius = _parse_radius(request.form.get("allowed_radius_metres"))

        existing_site = fetch_one(
            """
            SELECT id
            FROM staff_sites
            WHERE business_id = %s
              AND LOWER(name) = LOWER(%s)
            """,
            (business_id, name),
        )

        if existing_site:
            flash("A site with that name already exists.", "error")
            return redirect(
                url_for("staff.dashboard", business_slug=business_slug)
            )

        execute(
            """
            INSERT INTO staff_sites (
                business_id,
                name,
                address,
                latitude,
                longitude,
                allowed_radius_metres,
                photo_required,
                active
            )
            VALUES (
                %s,
                %s,
                NULLIF(%s, ''),
                %s,
                %s,
                %s,
                %s,
                TRUE
            )
            """,
            (
                business_id,
                name,
                address,
                latitude,
                longitude,
                radius,
                photo_required,
            ),
        )

    except ValueError as error:
        flash(str(error), "error")
    except StaffDatabaseError as error:
        flash(str(error), "error")
    else:
        flash(f"{name} has been added as a work site.", "success")

    return redirect(url_for("staff.dashboard", business_slug=business_slug))


@staff_blueprint.post("/<business_slug>/sites/<int:site_id>/status")
@dashboard_login_required
def change_site_status(business_slug: str, site_id: int):
    """Activate or deactivate a work site without deleting its history."""
    business_id = _business_id(business_slug)
    new_status = _clean_text(request.form.get("status"), 20).lower()

    if new_status not in {"active", "inactive"}:
        flash("Select a valid site status.", "error")
        return redirect(url_for("staff.dashboard", business_slug=business_slug))

    active = new_status == "active"

    try:
        updated_rows = execute(
            """
            UPDATE staff_sites
            SET
                active = %s,
                updated_at = NOW()
            WHERE id = %s
              AND business_id = %s
            """,
            (active, site_id, business_id),
        )

        if updated_rows == 0:
            flash("That work site could not be found.", "error")
        else:
            flash("Work site status updated.", "success")

    except StaffDatabaseError as error:
        flash(str(error), "error")

    return redirect(url_for("staff.dashboard", business_slug=business_slug))


@staff_blueprint.post(
    "/<business_slug>/shifts/<int:shift_id>/approve"
)
@dashboard_login_required
def approve_shift(
    business_slug: str,
    shift_id: int,
):
    """Approve one completed staff shift."""
    business_id = _business_id(business_slug)

    try:
        updated_rows = execute(
            """
            UPDATE staff_shifts
            SET
                approval_status = 'approved',
                approved_at = NOW(),
                manager_note = NULLIF(%s, '')
            WHERE id = %s
              AND business_id = %s
              AND clock_out_at IS NOT NULL
            """,
            (
                _clean_text(request.form.get("manager_note"), 500),
                shift_id,
                business_id,
            ),
        )

        if updated_rows == 0:
            flash(
                "Only completed shifts can be approved.",
                "error",
            )
        else:
            flash("Shift approved.", "success")

    except StaffDatabaseError as error:
        flash(str(error), "error")

    return redirect(url_for("staff.dashboard", business_slug=business_slug))


@staff_blueprint.post(
    "/<business_slug>/shifts/<int:shift_id>/reject"
)
@dashboard_login_required
def reject_shift(
    business_slug: str,
    shift_id: int,
):
    """Reject a shift and record the manager’s reason."""
    business_id = _business_id(business_slug)
    manager_note = _clean_text(
        request.form.get("manager_note"),
        500,
    )

    if not manager_note:
        flash("Enter a reason before rejecting the shift.", "error")
        return redirect(url_for("staff.dashboard", business_slug=business_slug))

    try:
        updated_rows = execute(
            """
            UPDATE staff_shifts
            SET
                approval_status = 'rejected',
                approved_at = NOW(),
                manager_note = %s
            WHERE id = %s
              AND business_id = %s
            """,
            (
                manager_note,
                shift_id,
                business_id,
            ),
        )

        if updated_rows == 0:
            flash("That shift could not be found.", "error")
        else:
            flash("Shift rejected.", "success")

    except StaffDatabaseError as error:
        flash(str(error), "error")

    return redirect(url_for("staff.dashboard", business_slug=business_slug))


@staff_blueprint.post("/<business_slug>/leave")
@dashboard_login_required
def add_leave(business_slug: str):
    """Add an approved holiday or other leave record for an employee."""
    business_id = _business_id(business_slug)
    leave_type = _clean_text(
        request.form.get("leave_type"),
        20,
    ).lower() or "holiday"
    employee_note = _clean_text(
        request.form.get("employee_note"),
        1000,
    )

    allowed_leave_types = {
        "holiday",
        "sickness",
        "unpaid",
        "compassionate",
        "parental",
        "other",
    }

    if leave_type not in allowed_leave_types:
        flash("Select a valid type of leave.", "error")
        return redirect(url_for("staff.dashboard", business_slug=business_slug))

    try:
        employee_id = int(request.form.get("employee_id", ""))
    except (TypeError, ValueError):
        flash("Select an employee.", "error")
        return redirect(url_for("staff.dashboard", business_slug=business_slug))

    try:
        start_date = _parse_date(
            request.form.get("start_date"),
            "start date",
        )
        end_date = _parse_date(
            request.form.get("end_date"),
            "end date",
        )

        if end_date < start_date:
            raise ValueError("The end date cannot be before the start date.")

        employee = fetch_one(
            """
            SELECT id, full_name
            FROM staff_employees
            WHERE id = %s
              AND business_id = %s
              AND status = 'active'
            """,
            (employee_id, business_id),
        )

        if not employee:
            flash("That active employee could not be found.", "error")
            return redirect(
                url_for("staff.dashboard", business_slug=business_slug)
            )

        duplicate = fetch_one(
            """
            SELECT id
            FROM staff_leave_requests
            WHERE business_id = %s
              AND employee_id = %s
              AND leave_type = %s
              AND start_date = %s
              AND end_date = %s
              AND approval_status IN ('pending', 'approved')
            """,
            (
                business_id,
                employee_id,
                leave_type,
                start_date,
                end_date,
            ),
        )

        if duplicate:
            flash("That leave record already exists.", "error")
            return redirect(
                url_for("staff.dashboard", business_slug=business_slug)
            )

        execute(
            """
            INSERT INTO staff_leave_requests (
                business_id,
                employee_id,
                leave_type,
                start_date,
                end_date,
                total_days,
                approval_status,
                employee_note,
                approved_at
            )
            VALUES (
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                'approved',
                NULLIF(%s, ''),
                NOW()
            )
            """,
            (
                business_id,
                employee_id,
                leave_type,
                start_date,
                end_date,
                _working_days(start_date, end_date),
                employee_note,
            ),
        )

    except ValueError as error:
        flash(str(error), "error")
    except StaffDatabaseError as error:
        flash(str(error), "error")
    else:
        flash(
            f"Leave added for {employee['full_name']}.",
            "success",
        )

    return redirect(url_for("staff.dashboard", business_slug=business_slug))


@staff_blueprint.post(
    "/<business_slug>/leave/<int:leave_id>/approve"
)
@dashboard_login_required
def approve_leave(business_slug: str, leave_id: int):
    """Approve a pending holiday or leave request."""
    business_id = _business_id(business_slug)

    try:
        updated_rows = execute(
            """
            UPDATE staff_leave_requests
            SET
                approval_status = 'approved',
                approved_at = NOW(),
                manager_note = NULLIF(%s, ''),
                updated_at = NOW()
            WHERE id = %s
              AND business_id = %s
              AND approval_status = 'pending'
            """,
            (
                _clean_text(request.form.get("manager_note"), 1000),
                leave_id,
                business_id,
            ),
        )

        if updated_rows == 0:
            flash("That pending leave request could not be found.", "error")
        else:
            flash("Leave request approved.", "success")

    except StaffDatabaseError as error:
        flash(str(error), "error")

    return redirect(url_for("staff.dashboard", business_slug=business_slug))


@staff_blueprint.post(
    "/<business_slug>/leave/<int:leave_id>/reject"
)
@dashboard_login_required
def reject_leave(business_slug: str, leave_id: int):
    """Reject a pending holiday or leave request."""
    business_id = _business_id(business_slug)
    manager_note = _clean_text(
        request.form.get("manager_note"),
        1000,
    )

    if not manager_note:
        flash("Enter a reason before rejecting the request.", "error")
        return redirect(url_for("staff.dashboard", business_slug=business_slug))

    try:
        updated_rows = execute(
            """
            UPDATE staff_leave_requests
            SET
                approval_status = 'rejected',
                approved_at = NOW(),
                manager_note = %s,
                updated_at = NOW()
            WHERE id = %s
              AND business_id = %s
              AND approval_status = 'pending'
            """,
            (manager_note, leave_id, business_id),
        )

        if updated_rows == 0:
            flash("That pending leave request could not be found.", "error")
        else:
            flash("Leave request rejected.", "success")

    except StaffDatabaseError as error:
        flash(str(error), "error")

    return redirect(url_for("staff.dashboard", business_slug=business_slug))


@staff_blueprint.post(
    "/<business_slug>/leave/<int:leave_id>/cancel"
)
@dashboard_login_required
def cancel_leave(business_slug: str, leave_id: int):
    """Cancel an approved or pending future leave record."""
    business_id = _business_id(business_slug)

    try:
        updated_rows = execute(
            """
            UPDATE staff_leave_requests
            SET
                approval_status = 'cancelled',
                updated_at = NOW()
            WHERE id = %s
              AND business_id = %s
              AND approval_status IN ('pending', 'approved')
              AND end_date >= CURRENT_DATE
            """,
            (leave_id, business_id),
        )

        if updated_rows == 0:
            flash("That leave record could not be cancelled.", "error")
        else:
            flash("Leave record cancelled.", "success")

    except StaffDatabaseError as error:
        flash(str(error), "error")

    return redirect(url_for("staff.dashboard", business_slug=business_slug))

# Employee portal. These sessions never grant manager/dashboard access.
_EMPLOYEE_SESSION_KEY = "_staff_employee_auth"
_EMPLOYEE_SESSION_SECONDS = 8 * 60 * 60
_EMPLOYEE_LOGIN_WINDOW = 15 * 60
_employee_login_attempts: dict[tuple[str, ...], list[float]] = {}
_employee_login_lock = threading.Lock()


def _employee_login_allowed(business_id: str, phone: str) -> bool:
    """Bound login attempts per account and address in this worker process.

    Multi-worker deployments should also enforce a shared limit at the proxy
    or application layer. No database or schema changes are needed here.
    """
    now = time.monotonic()
    keys = (
        (("account", business_id, phone), 5),
        (("address", request.remote_addr or "unknown"), 30),
    )
    with _employee_login_lock:
        for key in list(_employee_login_attempts):
            recent = [
                attempt for attempt in _employee_login_attempts[key]
                if now - attempt < _EMPLOYEE_LOGIN_WINDOW
            ]
            if recent:
                _employee_login_attempts[key] = recent
            else:
                del _employee_login_attempts[key]
        if any(
            len(_employee_login_attempts.get(key, [])) >= limit
            for key, limit in keys
        ):
            return False
        # Bound memory and fail closed if the limiter is at capacity.
        missing = sum(key not in _employee_login_attempts for key, _ in keys)
        if len(_employee_login_attempts) + missing > 8192:
            return False
        for key, _ in keys:
            _employee_login_attempts.setdefault(key, []).append(now)
    return True


def _current_employee(business_slug: str) -> dict[str, Any] | None:
    """Recheck business membership and active status on protected requests."""
    auth = session.get(_EMPLOYEE_SESSION_KEY)
    if not isinstance(auth, dict):
        session.pop(_EMPLOYEE_SESSION_KEY, None)
        return None
    business_id = _business_id(business_slug)
    if auth.get("business_id") != business_id:
        return None
    employee_id = auth.get("employee_id")
    issued_at = auth.get("issued_at")
    if (
        type(employee_id) is not int
        or employee_id <= 0
        or type(issued_at) is not int
        or not 0 <= time.time() - issued_at < _EMPLOYEE_SESSION_SECONDS
    ):
        session.pop(_EMPLOYEE_SESSION_KEY, None)
        return None
    employee = fetch_one(
        """
        SELECT id, business_id, full_name, phone, email, role, status
        FROM staff_employees
        WHERE id = %s AND business_id = %s AND status = 'active'
        """,
        (employee_id, business_id),
    )
    if not employee:
        session.pop(_EMPLOYEE_SESSION_KEY, None)
    return employee


def employee_login_required(view_function):
    @wraps(view_function)
    def protected_view(business_slug: str, *args, **kwargs):
        try:
            employee = _current_employee(business_slug)
        except (StaffDatabaseError, PostgreSQLError):
            abort(503, description="Employee access is temporarily unavailable.")
        if employee is None:
            return redirect(url_for(
                "staff.employee_login", business_slug=business_slug,
            ))
        g.staff_employee = employee
        return view_function(business_slug, *args, **kwargs)
    return protected_view


@staff_blueprint.after_request
def _prevent_employee_page_caching(response):
    if request.endpoint in {
        "staff.employee_login", "staff.employee_home", "staff.employee_logout",
    }:
        response.headers["Cache-Control"] = "no-store, private"
    return response


@staff_blueprint.route(
    "/<business_slug>/employee/login", methods=["GET", "POST"],
)
def employee_login(business_slug: str):
    """Authenticate using the existing phone and nonempty payroll number.

    Template: staff_employee_login.html; form fields: phone, payroll_number,
    csrf_token. Use csrf_token() just as in the manager templates.
    """
    business_id = _business_id(business_slug)
    error_message = ""
    phone_value = ""
    status_code = 200
    try:
        if request.method == "GET":
            if _current_employee(business_slug) is not None:
                return redirect(url_for(
                    "staff.employee_home", business_slug=business_slug,
                ))
        else:
            # The existing blueprint before_request validates CSRF first.
            raw_phone = request.form.get("phone", "").strip()
            payroll_number = request.form.get("payroll_number", "").strip()
            phone_value = raw_phone[:40]
            # Match the manager's normalization, without truncating credentials.
            phone = "".join(c for c in raw_phone if c.isdigit() or c == "+")
            valid_input = (
                0 < len(raw_phone) <= 100
                and 0 < len(phone) <= 40
                and any(c.isdigit() for c in phone)
                and 0 < len(payroll_number) <= 60
            )
            if not _employee_login_allowed(business_id, phone[:40]):
                error_message = "Too many login attempts. Please try again in 15 minutes."
                status_code = 429
            else:
                employee = None
                if valid_input:
                    employee = fetch_one(
                        """
                        SELECT id, payroll_number
                        FROM staff_employees
                        WHERE business_id = %s AND phone = %s
                          AND status = 'active'
                        """,
                        (business_id, phone),
                    )
                stored_payroll = str((employee or {}).get("payroll_number") or "")
                matches = hmac.compare_digest(
                    payroll_number.encode("utf-8"),
                    stored_payroll.encode("utf-8"),
                )
                if employee and valid_input and stored_payroll and matches:
                    # Keep unrelated manager session keys intact; never store
                    # phone/payroll credentials in the signed session cookie.
                    session[_EMPLOYEE_SESSION_KEY] = {
                        "employee_id": int(employee["id"]),
                        "business_id": business_id,
                        "issued_at": int(time.time()),
                    }
                    return redirect(url_for(
                        "staff.employee_home", business_slug=business_slug,
                    ))
                error_message = "Phone number or payroll number is incorrect."
                status_code = 401
    except (StaffDatabaseError, PostgreSQLError):
        error_message = "Employee login is temporarily unavailable. Please try again later."
        status_code = 503

    return render_template(
        "staff_employee_login.html",
        business_slug=business_slug,
        error_message=error_message,
        phone_value=phone_value,
        csrf_token=_get_csrf_token,
    ), status_code


@staff_blueprint.post("/<business_slug>/employee/logout")
def employee_logout(business_slug: str):
    """CSRF-protected logout for this business, preserving manager access."""
    auth = session.get(_EMPLOYEE_SESSION_KEY)
    if isinstance(auth, dict) and auth.get("business_id") == _business_id(business_slug):
        session.pop(_EMPLOYEE_SESSION_KEY, None)
    return redirect(url_for("staff.employee_login", business_slug=business_slug))


@staff_blueprint.get("/<business_slug>/employee")
@employee_login_required
def employee_home(business_slug: str):
    """Read-only first-stage portal; clock/leave actions are added later.

    Hours are elapsed clocked hours (including open/rejected shifts, before
    break deductions), not approved payroll hours. Week boundaries and leave
    dates use the database timezone, as the existing manager dashboard does.
    """
    employee = g.staff_employee
    parameters = (_business_id(business_slug), employee["id"])
    try:
        current_shift = fetch_one(
            """
            SELECT id, site_name, clock_in_at, approval_status
            FROM staff_shifts
            WHERE business_id = %s AND employee_id = %s
              AND clock_out_at IS NULL
            ORDER BY clock_in_at DESC
            LIMIT 1
            """,
            parameters,
        )
        hours_summary = fetch_one(
            """
            WITH period AS (
                SELECT DATE_TRUNC('week', NOW()) AS week_start,
                       NOW() AS as_of
            )
            SELECT period.week_start::date AS week_start,
                   (period.week_start + INTERVAL '6 days')::date AS week_end,
                   period.as_of,
                   COALESCE((
                       SELECT ROUND(SUM(GREATEST(0, EXTRACT(EPOCH FROM (
                           LEAST(COALESCE(shift.clock_out_at, period.as_of), period.as_of)
                           - GREATEST(shift.clock_in_at, period.week_start)
                       ))) / 3600)::numeric, 2)
                       FROM staff_shifts AS shift
                       WHERE shift.business_id = %s AND shift.employee_id = %s
                         AND shift.clock_in_at < period.as_of
                         AND COALESCE(shift.clock_out_at, period.as_of) > period.week_start
                   ), 0) AS hours_this_week
            FROM period
            """,
            parameters,
        ) or {}
        leave_summary = fetch_one(
            """
            SELECT COUNT(*) FILTER (
                       WHERE approval_status = 'pending'
                   ) AS pending_count,
                   COUNT(*) FILTER (
                       WHERE approval_status = 'approved' AND start_date > CURRENT_DATE
                   ) AS upcoming_count,
                   COUNT(*) FILTER (
                       WHERE approval_status = 'approved'
                         AND CURRENT_DATE BETWEEN start_date AND end_date
                   ) AS current_count,
                   COALESCE(SUM(total_days) FILTER (
                       WHERE approval_status = 'pending'
                   ), 0) AS pending_days,
                   COALESCE(SUM(total_days) FILTER (
                       WHERE approval_status = 'approved' AND start_date > CURRENT_DATE
                   ), 0) AS upcoming_days
            FROM staff_leave_requests
            WHERE business_id = %s AND employee_id = %s
            """,
            parameters,
        ) or {}
        # Counts above cover all records; lists are bounded for the home page.
        pending_leave = fetch_all(
            """
            SELECT id, leave_type, start_date, end_date, total_days, approval_status
            FROM staff_leave_requests
            WHERE business_id = %s AND employee_id = %s AND approval_status = 'pending'
            ORDER BY start_date ASC, id ASC
            LIMIT 20
            """,
            parameters,
        )
        upcoming_leave = fetch_all(
            """
            SELECT id, leave_type, start_date, end_date, total_days, approval_status
            FROM staff_leave_requests
            WHERE business_id = %s AND employee_id = %s
              AND approval_status = 'approved' AND start_date > CURRENT_DATE
            ORDER BY start_date ASC, id ASC
            LIMIT 20
            """,
            parameters,
        )
        current_leave = fetch_all(
            """
            SELECT id, leave_type, start_date, end_date, total_days, approval_status
            FROM staff_leave_requests
            WHERE business_id = %s AND employee_id = %s
              AND approval_status = 'approved'
              AND CURRENT_DATE BETWEEN start_date AND end_date
            ORDER BY start_date ASC, id ASC
            LIMIT 20
            """,
            parameters,
        )
    except (StaffDatabaseError, PostgreSQLError):
        abort(503, description="Your employee summary is temporarily unavailable.")

    return render_template(
        "staff_employee_home.html",
        business_slug=business_slug,
        employee=employee,
        current_shift=current_shift,
        is_clocked_in=current_shift is not None,
        hours_this_week=hours_summary.get("hours_this_week", Decimal("0")),
        week_start=hours_summary.get("week_start"),
        week_end=hours_summary.get("week_end"),
        as_of=hours_summary.get("as_of"),
        leave_summary=leave_summary,
        pending_leave=pending_leave,
        upcoming_leave=upcoming_leave,
        current_leave=current_leave,
        csrf_token=_get_csrf_token,
    )

