"""Database-free guard: Control Centre migration verifiers must never receive a dict-row cursor.

Production reporting showed "Unavailable" because the sc_/sr_ verifiers compare tuple rows but
directory() handed them a RealDictCursor, so verification always failed once the tables existed.
"""
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from psycopg2.extras import RealDictCursor

from trimtech.modules.staff import platform_control


class FakeCursor:
    def __init__(self, dict_rows):
        self.dict_rows = dict_rows
        self.last = ''

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, *args):
        self.last = sql

    def fetchone(self):
        return {'present': True, 'review': True}

    def fetchall(self):
        return []


class FakeConnection:
    def set_session(self, **kwargs):
        pass

    def cursor(self, cursor_factory=None):
        return FakeCursor(cursor_factory is RealDictCursor)


@contextmanager
def fake_transaction():
    yield FakeConnection()


class DirectoryVerifyCursorTests(unittest.TestCase):
    def test_verifiers_receive_plain_cursors(self):
        seen = {}

        def recorder(name):
            def verify(cursor):
                seen[name] = cursor.dict_rows
            return verify

        names = ('migrations', 'accounts_migration', 'onboarding_migration', 'billing_migration',
                 'complimentary_migration', 'registration_review_migration')
        patches = [patch.object(platform_control, 'transaction', fake_transaction)]
        patches += [patch.object(getattr(platform_control, n), 'verify', recorder(n)) for n in names]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

        data = platform_control.directory()

        self.assertEqual(sorted(seen), sorted(names))
        self.assertFalse(any(seen.values()), seen)
        self.assertTrue(data['review_ready'])


if __name__ == '__main__':
    unittest.main()
