from __future__ import annotations

import hmac
import secrets
from decimal import Decimal, InvalidOperation
from typing import Any

from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

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
                ) AS hours_this_week
            """,
            (
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

    except StaffDatabaseError as error:
        flash(str(error), "error")
        summary = {
            "active_employees": 0,
            "staff_clocked_in": 0,
            "shifts_waiting_approval": 0,
            "hours_this_week": 0,
        }
        employees = []
        live_shifts = []
        pending_shifts = []

    return render_template(
        "staff_dashboard.html",
        business_slug=business_slug,
        summary=summary,
        employees=employees,
        live_shifts=live_shifts,
        pending_shifts=pending_shifts,
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