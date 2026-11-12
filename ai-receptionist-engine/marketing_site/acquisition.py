"""Daily request counters. Stores UTC dates and totals without visitor identifiers."""
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
import hmac
import logging
import os
from pathlib import Path
import sqlite3

from flask import abort, jsonify, redirect, request

logger = logging.getLogger(__name__)
REGISTRATION_URL = 'https://garage-voice.onrender.com/staff/account/register'


def database_path():
    value = os.getenv('MARKETING_ACQUISITION_DB') or os.getenv('MARKETING_DEMO_STATE_DB', '')
    path = Path(value)
    if not value or not path.is_absolute() or not path.parent.is_dir():
        raise ValueError('Persistent acquisition storage is unavailable.')
    return path


def initialize(connection, now):
    connection.execute('CREATE TABLE IF NOT EXISTS acquisition_collection (id INTEGER PRIMARY KEY CHECK(id=1), started_at TEXT NOT NULL)')
    connection.execute('CREATE TABLE IF NOT EXISTS acquisition_daily (day TEXT PRIMARY KEY, landing_requests INTEGER NOT NULL DEFAULT 0, trial_clicks INTEGER NOT NULL DEFAULT 0)')
    connection.execute('INSERT OR IGNORE INTO acquisition_collection(id,started_at) VALUES (1,?)', (now.isoformat(),))


def record(metric):
    """Bound lock waits and fail open so storage failures cannot reject a page or redirect."""
    try:
        if metric not in ('landing_requests', 'trial_clicks'):
            raise ValueError('Unknown acquisition metric.')
        now = datetime.now(timezone.utc)
        with closing(sqlite3.connect(database_path(), timeout=0.05)) as connection:
            with connection:
                initialize(connection, now)
                # The column is selected exclusively from the fixed allowlist above.
                connection.execute(
                    f'INSERT INTO acquisition_daily(day,{metric}) VALUES (?,1) '
                    f'ON CONFLICT(day) DO UPDATE SET {metric}={metric}+1',
                    (now.date().isoformat(),),
                )
    except Exception:
        # No URL, query, IP, cookie, referrer, user agent or visitor identifier is logged.
        logger.warning('Staff acquisition counter write unavailable')


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


def summary(start, end):
    path = database_path()
    # Reporting must never create an empty historical database.
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=0.2)) as connection:
        row = connection.execute('SELECT started_at FROM acquisition_collection WHERE id=1').fetchone()
        if not row:
            raise ValueError('Collection has not started.')
        started_at = datetime.fromisoformat(row[0])
        counts = {
            day: (requests, clicks)
            for day, requests, clicks in connection.execute(
                'SELECT day,landing_requests,trial_clicks FROM acquisition_daily WHERE day BETWEEN ? AND ?',
                (start.isoformat(), end.isoformat()),
            )
        }
    days = []
    current = start
    while current <= end:
        available = current >= started_at.date()
        requests, clicks = counts.get(current.isoformat(), (0, 0))
        days.append(dict(
            day=current.isoformat(),
            landing_requests=requests if available else None,
            trial_clicks=clicks if available else None,
            coverage='unavailable' if not available else 'partial' if current in (started_at.date(), datetime.now(timezone.utc).date()) else 'recorded',
        ))
        current += timedelta(days=1)
    return dict(available=True, started_at=started_at.isoformat(), days=days)


def register_routes(app):
    @app.after_request
    def count_landing(response):
        if request.method == 'GET' and request.path == '/staff-manager' and response.status_code == 200:
            record('landing_requests')
            response.headers['Cache-Control'] = 'no-store'
        return response

    @app.get('/staff-manager/start-trial')
    def staff_start_trial():
        if request.method == 'GET':
            record('trial_clicks')
        response = redirect(REGISTRATION_URL, code=302)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Referrer-Policy'] = 'no-referrer'
        return response

    @app.get('/internal/staff-acquisition')
    def staff_acquisition_summary():
        expected = os.getenv('MARKETING_ACQUISITION_REPORT_TOKEN', '')
        supplied = request.headers.get('Authorization', '')
        if len(expected) < 32 or not hmac.compare_digest(supplied.encode(), ('Bearer '+expected).encode()):
            abort(403)
        try:
            start, end = date_range(request.args.get('start'), request.args.get('end'))
        except ValueError as error:
            return jsonify(error=str(error)), 400
        try:
            response = jsonify(summary(start, end))
        except (OSError, ValueError, sqlite3.Error):
            response = jsonify(available=False, started_at=None, days=[])
        response.headers['Cache-Control'] = 'no-store'
        return response
