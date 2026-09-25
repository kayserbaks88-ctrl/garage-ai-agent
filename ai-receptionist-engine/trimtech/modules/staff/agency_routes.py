"""Additional routes registered on the existing authenticated, CSRF-protected blueprint."""
from datetime import datetime, timedelta

from flask import abort, flash, g, redirect, render_template, request, url_for
from psycopg2.extras import RealDictCursor

from dashboard_auth import dashboard_login_required
from trimtech.modules.staff import agency
from trimtech.modules.staff.database import fetch_all, fetch_one, transaction
from trimtech.modules.staff.payroll import UK_TIMEZONE, recalculate_payroll_run


def register_routes(staff):
    bp = staff.staff_blueprint

    @bp.get("/<business_slug>/agency")
    @dashboard_login_required
    def agency_dashboard(business_slug):
        business_id = staff._business_id(business_slug)
        today = datetime.now(UK_TIMEZONE).date()
        try:
            week = staff._parse_date(request.args["week"], "week") if request.args.get("week") else today
            if not 1901 <= week.year <= 9998:
                raise ValueError("Choose a week between 1901 and 9998.")
        except ValueError as error:
            abort(400, description=str(error))
        week -= timedelta(days=week.weekday())
        starts = datetime.combine(week, datetime.min.time(), UK_TIMEZONE)
        ends = datetime.combine(week + timedelta(days=7), datetime.min.time(), UK_TIMEZONE)
        employees = fetch_all("SELECT id,full_name,status FROM staff_employees WHERE business_id=%s ORDER BY full_name", (business_id,))
        sites = fetch_all("SELECT * FROM staff_sites WHERE business_id=%s ORDER BY name", (business_id,))
        assignments = fetch_all("""SELECT a.*,e.full_name,s.name,s.address FROM staff_assignments a
            JOIN staff_employees e ON e.id=a.employee_id AND e.business_id=a.business_id
            JOIN staff_sites s ON s.id=a.site_id AND s.business_id=a.business_id
            WHERE a.business_id=%s AND a.starts_at<%s AND a.ends_at>%s ORDER BY a.starts_at,e.full_name""",
            (business_id, ends, starts))
        edit = None
        if request.args.get("assignment", type=int):
            edit = fetch_one("SELECT * FROM staff_assignments WHERE business_id=%s AND id=%s",
                             (business_id, request.args.get("assignment", type=int)))
            if not edit:
                abort(404)
        origin, origin_employee = None, None
        if request.args.get("origin_employee", type=int):
            origin_employee = next((e for e in employees if e["id"] == request.args.get("origin_employee", type=int)), None)
            if not origin_employee:
                abort(404)
            origin = agency.origin_for_employee(business_id, origin_employee["id"])
        adjustments = fetch_all("SELECT * FROM staff_payroll_adjustments WHERE business_id=%s AND status='pending' ORDER BY id", (business_id,))
        audit = fetch_all("""SELECT actor,action,entity_type,entity_id,reason,created_at FROM staff_audit
            WHERE business_id=%s ORDER BY id DESC LIMIT 50""", (business_id,))
        return render_template("staff_agency.html", business_slug=business_slug, config=agency.settings(business_id),
            employees=employees, sites=sites, assignments=assignments, edit=edit, week=week,
            previous_week=week-timedelta(days=7), next_week=week+timedelta(days=7),
            origin=origin, origin_employee=origin_employee, adjustments=adjustments, audit=audit,
            csrf_token=staff._get_csrf_token, uk_input=agency.uk_input)

    def manager_action(business_slug, operation):
        try:
            with transaction() as connection:
                with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                    operation(cursor, staff._business_id(business_slug), staff._manager_actor())
            flash("Change saved.", "success")
        except ValueError as error:
            flash(str(error), "error")
        except staff._DB_ERRORS:
            staff._database_message()
        return redirect(url_for("staff.agency_dashboard", business_slug=business_slug))

    @bp.post("/<business_slug>/settings/organisation")
    @dashboard_login_required
    def organisation_settings(business_slug):
        return manager_action(business_slug, lambda c, b, a: agency.change_mode(c, b, a,
            request.form.get("organisation_mode"), request.form.get("travel_enabled") == "on",
            staff._clean_text(request.form.get("reason"), 1000)))

    @bp.post("/<business_slug>/assignments")
    @bp.post("/<business_slug>/assignments/<int:assignment_id>/edit")
    @dashboard_login_required
    def save_assignment(business_slug, assignment_id=None):
        return manager_action(business_slug, lambda c, b, a:
            agency.save_assignment(c, b, a, request.form, assignment_id))

    @bp.post("/<business_slug>/assignments/<int:assignment_id>/cancel")
    @dashboard_login_required
    def cancel_assignment(business_slug, assignment_id):
        return manager_action(business_slug, lambda c, b, a:
            agency.save_assignment(c, b, a, request.form, assignment_id, cancel=True))

    @bp.post("/<business_slug>/employee/travel-origin")
    @staff.employee_login_required
    def employee_travel_origin(business_slug):
        try:
            with transaction() as connection:
                with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                    agency.save_origin(cursor, staff._business_id(business_slug), g.staff_employee["id"], request.form)
            flash("Travel preference saved. Existing shift estimates are unchanged.", "success")
        except ValueError as error:
            flash(str(error), "error")
        except staff._DB_ERRORS:
            staff._database_message()
        return staff._employee_redirect(business_slug)

    @bp.post("/<business_slug>/payroll/<int:run_id>/recalculate")
    @dashboard_login_required
    def recalculate_payroll(business_slug, run_id):
        try:
            with transaction() as connection:
                recalculate_payroll_run(connection, staff._business_id(business_slug), run_id, staff._manager_actor())
            flash("Draft recalculated from reviewed shifts; travel estimates remain excluded.", "success")
        except ValueError as error:
            flash(str(error), "error")
        except staff._DB_ERRORS:
            staff._database_message()
        return staff._manager_redirect(business_slug)

    @bp.post("/<business_slug>/payroll-adjustments/<int:adjustment_id>/resolve")
    @dashboard_login_required
    def resolve_payroll_adjustment(business_slug, adjustment_id):
        def resolve(cursor, business_id, actor):
            agency.lock_business(cursor, business_id)
            resolution = staff._clean_text(request.form.get("resolution"), 1000)
            if not resolution:
                raise ValueError("Record the payroll adjustment reference or reason no adjustment was needed.")
            cursor.execute("""UPDATE staff_payroll_adjustments SET status='resolved',resolution=%s,
                resolved_by=%s,resolved_at=NOW() WHERE id=%s AND business_id=%s AND status='pending'
                RETURNING shift_id""", (resolution, actor, adjustment_id, business_id))
            row = cursor.fetchone()
            if not row:
                raise ValueError("That pending adjustment could not be found.")
            agency.audit(cursor, business_id, actor, "payroll_adjustment_resolved", "shift", row["shift_id"],
                         None, {"adjustment_id": adjustment_id}, resolution)
        return manager_action(business_slug, resolve)
