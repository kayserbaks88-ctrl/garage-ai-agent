"""Connection-count and isolation regressions; no external services."""
import unittest
from unittest.mock import MagicMock, patch

import psycopg2
from flask import Blueprint, Flask, jsonify
from trimtech.modules.staff import database


class StaffReadPerformanceTests(unittest.TestCase):
    def app(self, blueprint='staff', fail=False):
        app = Flask(__name__)
        app.testing = True
        bp = Blueprint(blueprint, __name__, url_prefix='/read')
        bp.teardown_request(database.close_request_connection)
        @bp.route('/<tenant>', methods=['GET', 'POST'])
        def read(tenant):
            first = database.fetch_one('SELECT value FROM synthetic WHERE tenant=%s', (tenant,))
            second = database.fetch_one('SELECT value FROM synthetic WHERE tenant=%s', (tenant,))
            return jsonify(first=first['value'], second=second['value'])
        app.register_blueprint(bp)
        return app

    def connection(self, value=1):
        connection = MagicMock()
        connection.closed = 0
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.side_effect = [{'value': value}, {'value': value + 1}]
        return connection, cursor

    def test_get_reuses_connection_but_executes_each_query_and_closes_at_response(self):
        connection, cursor = self.connection()
        with patch.object(database, 'get_connection', return_value=connection) as connect:
            response = self.app().test_client().get('/read/alpha')
        self.assertEqual(response.json, {'first': 1, 'second': 2})
        self.assertEqual(connect.call_count, 1)
        self.assertEqual(cursor.execute.call_count, 2)
        self.assertTrue(connection.autocommit)
        connection.close.assert_called_once()
        connection.commit.assert_not_called()

    def test_new_request_and_other_tenant_never_share_connection_or_rows(self):
        first, first_cursor = self.connection(1)
        second, second_cursor = self.connection(10)
        client = self.app().test_client()
        with patch.object(database, 'get_connection', side_effect=[first, second]) as connect:
            self.assertEqual(client.get('/read/alpha').json['first'], 1)
            self.assertEqual(client.get('/read/beta').json['first'], 10)
        self.assertEqual(connect.call_count, 2)
        self.assertEqual(first_cursor.execute.call_args.args[1], ('alpha',))
        self.assertEqual(second_cursor.execute.call_args.args[1], ('beta',))
        first.close.assert_called_once()
        second.close.assert_called_once()

    def test_post_and_other_products_keep_independent_transactions(self):
        for method, blueprint in [('post', 'staff'), ('get', 'other_product')]:
            first, _ = self.connection(1)
            second, _ = self.connection(10)
            with self.subTest(method=method, blueprint=blueprint), patch.object(database, 'get_connection', side_effect=[first, second]) as connect:
                response = getattr(self.app(blueprint).test_client(), method)('/read/alpha')
                self.assertEqual(response.json, {'first': 1, 'second': 10})
                self.assertEqual(connect.call_count, 2)
                first.commit.assert_called_once()
                second.commit.assert_called_once()
                first.close.assert_called_once()
                second.close.assert_called_once()

    def test_database_failure_does_not_leave_connection_for_next_request(self):
        broken, cursor = self.connection()
        cursor.execute.side_effect = psycopg2.OperationalError('synthetic disconnect')
        fresh, _ = self.connection(10)
        client = self.app().test_client()
        with patch.object(database, 'get_connection', side_effect=[broken, fresh]):
            with self.assertRaises(psycopg2.OperationalError):
                client.get('/read/alpha')
            self.assertEqual(client.get('/read/alpha').json['first'], 10)
        broken.close.assert_called_once()
        fresh.close.assert_called_once()
