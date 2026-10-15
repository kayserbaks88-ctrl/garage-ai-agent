"""Account form presentation checks without database or provider access."""
import unittest
from html.parser import HTMLParser
from pathlib import Path

from flask import Flask, render_template
from trimtech.modules.staff.routes import staff_blueprint


class FormMarkup(HTMLParser):
    def __init__(self, markup):
        super().__init__()
        self.inputs = {}
        self.help_sections = []
        self.feed(markup)

    def handle_starttag(self, tag, attributes):
        attributes = dict(attributes)
        if tag == 'input':
            self.inputs[attributes.get('name')] = attributes
        if tag == 'details' and 'data-email-code' in attributes:
            self.help_sections.append(attributes)


def preview_app():
    app = Flask(__name__, template_folder=str(Path(__file__).parent / 'templates'))
    app.secret_key = 'account-ui-local-tests-only'
    app.register_blueprint(staff_blueprint)
    return app


def render_account(app, mode, data=None):
    with app.test_request_context('/staff/account/' + mode, method='POST' if data else 'GET', data=data):
        return render_template('staff_account.html', mode=mode, error='', message='', csrf_token=lambda: 'test-csrf')


class AccountPresentationTests(unittest.TestCase):
    def setUp(self):
        self.app = preview_app()

    def test_all_account_modes_keep_security_fields_and_password_autocomplete(self):
        for mode in ('login', 'register', 'verify', 'reset', 'invite', 'recover', 'resend'):
            with self.subTest(mode=mode):
                markup = FormMarkup(render_account(self.app, mode))
                self.assertEqual(markup.inputs['csrf_token']['type'], 'hidden')
                self.assertEqual(markup.inputs['csrf_token']['value'], 'test-csrf')
                if mode in ('login', 'register', 'verify', 'reset', 'invite'):
                    self.assertEqual(markup.inputs['password']['type'], 'password')
                    self.assertEqual(markup.inputs['password']['autocomplete'],
                                     'current-password' if mode == 'login' else 'new-password')
                if mode in ('verify', 'reset', 'invite'):
                    self.assertEqual(len(markup.help_sections), 1)
                    self.assertNotIn('open', markup.help_sections[0])
                    self.assertIn('required', markup.inputs['token'])
                else:
                    self.assertNotIn('token', markup.inputs)

    def test_password_retry_keeps_email_code_without_rendering_it_as_text(self):
        token = 'A' * 43
        for mode in ('verify', 'reset', 'invite'):
            with self.subTest(mode=mode):
                html = render_account(self.app, mode, {'token': token, 'password': 'too short'})
                markup = FormMarkup(html)
                self.assertEqual(markup.inputs['token']['value'], token)
                self.assertNotIn('value', markup.inputs['password'])
                self.assertNotIn('>' + token + '<', html)

    def test_code_attribute_escaping_and_invalid_length_are_preserved(self):
        for token in ('A' * 44, '\"><script>alert(1)</script>'):
            html = render_account(self.app, 'reset', {'token': token})
            self.assertEqual(FormMarkup(html).inputs['token']['value'], token)
            self.assertNotIn('<script>alert(1)</script>', html)

    def test_employee_login_does_not_display_internal_business_identifier(self):
        with self.app.test_request_context('/preview'):
            html = render_template('staff_employee_login.html', business_slug='internal-business-123',
                                   staff_business_name='Example workplace',
                                   csrf_token=lambda: 'test-csrf', secure_portal=True,
                                   error_message='', phone_value='')
        self.assertNotIn('<strong>internal-business-123</strong>', html)
        self.assertIn('<strong>Example workplace</strong>', html)
        self.assertEqual(FormMarkup(html).inputs['payroll_number']['type'], 'password')
        self.assertIn('/staff/internal-business-123/', html)  # Routing remains tenant-scoped.


if __name__ == '__main__':
    unittest.main()
