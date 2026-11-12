"""First-party request counts with synthetic SQLite data and no network calls."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from marketing_site import acquisition, app as marketing


class AcquisitionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'daily.sqlite'
        self.token = 'synthetic-report-token-with-32-characters'
        environment = patch.dict(os.environ, MARKETING_ACQUISITION_DB=str(self.path),
                                 MARKETING_ACQUISITION_REPORT_TOKEN=self.token)
        environment.start()
        self.addCleanup(environment.stop)
        self.client = marketing.app.test_client()

    def summary(self, **dates):
        return self.client.get('/internal/staff-acquisition', query_string=dates,
                               headers={'Authorization': 'Bearer '+self.token})

    def test_page_redirect_and_method_definitions(self):
        page = self.client.get('/staff-manager')
        self.assertEqual(page.status_code, 200)
        self.assertIn(b'href="/staff-manager/start-trial"', page.data)
        self.assertEqual(page.headers['Cache-Control'], 'no-store')
        self.client.head('/staff-manager')
        self.client.head('/staff-manager/start-trial')
        self.assertEqual(self.client.post('/staff-manager/start-trial').status_code, 405)
        response = self.client.get('/staff-manager/start-trial?next=https://untrusted.example&gclid=discard')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, acquisition.REGISTRATION_URL)
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        today = datetime.now(timezone.utc).date().isoformat()
        data = self.summary(start=today, end=today).get_json()
        self.assertEqual(data['days'][0]['landing_requests'], 1)
        self.assertEqual(data['days'][0]['trial_clicks'], 1)
        self.assertEqual(data['days'][0]['coverage'], 'partial')
        with closing(sqlite3.connect(self.path)) as connection:
            columns = connection.execute('PRAGMA table_info(acquisition_daily)').fetchall()
            self.assertEqual([column[1] for column in columns], ['day','landing_requests','trial_clicks'])

    def test_storage_failure_does_not_block_page_or_trial_redirect(self):
        for error in (sqlite3.OperationalError('locked'), OSError('unwritable')):
            with patch.object(acquisition.sqlite3, 'connect', side_effect=error):
                self.assertEqual(self.client.get('/staff-manager').status_code, 200)
                self.assertEqual(self.client.get('/staff-manager/start-trial').location, acquisition.REGISTRATION_URL)
        with patch.dict(os.environ, MARKETING_ACQUISITION_DB='relative.sqlite'):
            self.assertEqual(self.client.get('/staff-manager').status_code, 200)
            self.assertEqual(self.client.get('/staff-manager/start-trial').status_code, 302)

    def test_internal_report_auth_and_unavailable_history(self):
        self.assertEqual(self.client.get('/internal/staff-acquisition').status_code, 403)
        self.assertEqual(self.client.get('/internal/staff-acquisition',headers={'Authorization':'Bearer wrong'}).status_code,403)
        self.assertFalse(self.summary().get_json()['available'])
        self.assertFalse(self.path.exists())
        self.client.get('/staff-manager')
        today = datetime.now(timezone.utc).date()
        data = self.summary(start=(today-timedelta(days=1)).isoformat(),end=today.isoformat()).get_json()
        self.assertIsNone(data['days'][0]['landing_requests'])
        self.assertIsNone(data['days'][0]['trial_clicks'])
        self.assertEqual(data['days'][0]['coverage'], 'unavailable')
        self.assertEqual(self.summary(start='invalid').status_code, 400)
        self.assertEqual(self.summary(start=today.isoformat(),end='2000-01-01').status_code,400)

    def test_atomic_counts_persist_across_connections(self):
        acquisition.record('landing_requests')
        with ThreadPoolExecutor(max_workers=3) as pool:
            list(pool.map(lambda _: acquisition.record('trial_clicks'), range(15)))
        with closing(sqlite3.connect(self.path)) as connection:
            self.assertEqual(connection.execute('SELECT landing_requests,trial_clicks FROM acquisition_daily').fetchone(), (1,15))

    def test_historical_dates_are_read_without_backfill(self):
        acquisition.record('landing_requests')
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute("UPDATE acquisition_collection SET started_at='2026-01-02T12:00:00+00:00'")
            connection.execute("INSERT INTO acquisition_daily VALUES ('2026-01-02',3,2),('2026-01-03',4,1)")
            connection.commit()
        data=self.summary(start='2026-01-01',end='2026-01-03').get_json()
        self.assertEqual([row['coverage'] for row in data['days']], ['unavailable','partial','recorded'])
        self.assertEqual(data['days'][2]['landing_requests'],4)


if __name__ == '__main__':
    unittest.main()
