"""Owner reporting over existing registration records and aggregate marketing counters."""
from datetime import date, datetime, time, timedelta, timezone
import json
import os
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from psycopg2.extras import RealDictCursor

from trimtech.modules.staff.database import transaction


def date_range(start_text, end_text):
    today = datetime.now(timezone.utc).date()
    try:
        start = date.fromisoformat(start_text) if start_text else today - timedelta(days=29)
        end = date.fromisoformat(end_text) if end_text else today
    except (ValueError, TypeError):
        raise ValueError('Use valid YYYY-MM-DD dates.') from None
    if start > end or end > today or (end-start).days > 365:
        raise ValueError('Choose an ordered date range of up to 366 days ending today or earlier.')
    return start, end


def account_metrics(start, end):
    """Report event dates from operational rows without modifying the signup transaction."""
    lower = datetime.combine(start, time.min, timezone.utc)
    upper = datetime.combine(end + timedelta(days=1), time.min, timezone.utc)
    with transaction() as connection:
        connection.set_session(readonly=True, isolation_level='REPEATABLE READ')
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("""WITH eligible AS (
                SELECT b.id,b.created_at,t.administrator_id,t.starts_at,a.verified_at
                FROM so_trials t JOIN sm_businesses b ON b.id=t.business_id
                JOIN sm_administrators a ON a.id=t.administrator_id
                WHERE NOT COALESCE((SELECT x.action='archive' FROM staff_audit x
                    WHERE x.business_id=b.id AND x.entity_type='subscription_management'
                    AND x.action IN ('archive','restore') ORDER BY x.id DESC LIMIT 1),FALSE)
                AND NOT COALESCE((SELECT x.action='mark_test' FROM staff_audit x
                    WHERE x.business_id=b.id AND x.entity_type='acquisition_classification'
                    ORDER BY x.id DESC LIMIT 1),FALSE)
                AND NOT (NOT b.active AND COALESCE((SELECT x.action='registration_review_deactivate'
                    FROM staff_audit x WHERE x.business_id=b.id AND x.entity_type='registration_review'
                    ORDER BY x.id DESC LIMIT 1),FALSE))
            ), events AS (
                SELECT created_at AS occurred_at,'registrations' AS metric,id AS identity FROM eligible
                UNION ALL
                SELECT DISTINCT verified_at,'verifications',administrator_id FROM eligible WHERE verified_at IS NOT NULL
                UNION ALL
                SELECT starts_at,'activations',id FROM eligible WHERE starts_at IS NOT NULL
            )
            SELECT (occurred_at AT TIME ZONE 'UTC')::date AS day,metric,COUNT(*) AS total
            FROM events WHERE occurred_at >= %s AND occurred_at < %s GROUP BY day,metric
            ORDER BY day,metric""", (lower, upper))
            rows = cursor.fetchall()
    days = {}
    current = start
    while current <= end:
        days[current.isoformat()] = dict(registrations=0, verifications=0, activations=0)
        current += timedelta(days=1)
    for row in rows:
        days[row['day'].isoformat()][row['metric']] = row['total']
    return days


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Avoid sending the service credential to another origin.
        return None


def marketing_metrics(start, end):
    unavailable = dict(available=False, started_at=None, days=[])
    url = os.getenv('STAFF_MARKETING_REPORT_URL', '').strip()
    token = os.getenv('MARKETING_ACQUISITION_REPORT_TOKEN', '')
    try:
        parsed = urlsplit(url)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment or len(token) < 32):
            return unavailable
        target = url + '?' + urlencode(dict(start=start.isoformat(), end=end.isoformat()))
        request = Request(target, headers={'Authorization': 'Bearer '+token})
        with build_opener(NoRedirect()).open(request, timeout=2) as response:
            payload = response.read(131073)
        if len(payload) > 131072:
            return unavailable
        result = json.loads(payload)
        if result.get('available') is not True:
            return unavailable
        started_at = datetime.fromisoformat(result['started_at'])
        if started_at.tzinfo is None or len(result['days']) != (end-start).days+1:
            return unavailable
        for offset, row in enumerate(result['days']):
            if row['day'] != (start+timedelta(days=offset)).isoformat():
                return unavailable
            if row['coverage'] not in ('unavailable', 'partial', 'recorded'):
                return unavailable
            for metric in ('landing_requests', 'trial_clicks'):
                value = row[metric]
                if row['coverage'] == 'unavailable':
                    if value is not None:
                        return unavailable
                elif type(value) is not int or value < 0:
                    return unavailable
        return result
    except Exception:
        # Remote diagnostics and credentials are deliberately absent from the report.
        return unavailable


def report(start, end):
    accounts = account_metrics(start, end)
    marketing = marketing_metrics(start, end)
    counters = {row['day']: row for row in marketing['days']}
    days = []
    for day, values in accounts.items():
        counter = counters.get(day, dict(landing_requests=None, trial_clicks=None, coverage='unavailable'))
        days.append(dict(day=day, **values, **{key: counter[key] for key in ('landing_requests','trial_clicks','coverage')}))
    totals = {metric: sum(row[metric] for row in days) for metric in ('registrations','verifications','activations')}
    for metric in ('landing_requests', 'trial_clicks'):
        totals[metric] = sum(row[metric] or 0 for row in days) if any(row[metric] is not None for row in days) else None
    complete = all(row['coverage'] == 'recorded' for row in days)
    return dict(days=days, totals=totals, marketing=marketing, complete=complete)


def register_routes(staff):
    from flask import abort, render_template, request
    from trimtech.modules.staff.platform_control import control_centre_required

    @staff.staff_blueprint.get('/platform/acquisition')
    @control_centre_required
    def platform_acquisition():
        try:
            start, end = date_range(request.args.get('start'), request.args.get('end'))
        except ValueError as error:
            return render_template('staff_acquisition.html', error=str(error)), 400
        try:
            data = report(start, end)
        except staff._DB_ERRORS:
            abort(503, description='Acquisition reporting is temporarily unavailable.')
        return render_template('staff_acquisition.html', start=start, end=end, **data)
