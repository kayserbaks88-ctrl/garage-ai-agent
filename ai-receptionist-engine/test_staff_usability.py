"""Database-free validation for shared manager forms."""
import unittest
from pathlib import Path
from decimal import Decimal
from flask import Flask
from trimtech.modules.staff.routes import _site_values


class StaffUsabilityTests(unittest.TestCase):
    def test_site_validation_accepts_zero_coordinates_and_rejects_invalid_values(self):
        values = dict(name=" Site ", address=" London SW1A 1AA ", client_reference=" Job ",
                      latitude="0", longitude="0", allowed_radius_metres="250")
        parsed = _site_values(values)
        self.assertEqual(parsed, ("Site", "London SW1A 1AA", Decimal(0), Decimal(0), 250, "Job"))
        for changes in ({"name": " "}, {"latitude": "NaN"}, {"longitude": "Infinity"},
                        {"latitude": "91"}, {"longitude": "-181"}, {"allowed_radius_metres": "10001"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                _site_values({**values, **changes})

    def test_shared_site_form_escapes_addresses_and_keeps_gps_fields(self):
        app = Flask(__name__, template_folder=str(Path(__file__).parent / "templates"))
        with app.app_context():
            macro = app.jinja_env.get_template("staff_site_fields.html").module.site_fields
            html = str(macro("test", [{"address": '<script>alert(1)</script>', "name": "Test"}], assignment=True))
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn('name="address"', html)
        self.assertIn('data-use-location', html)
        for field in ("latitude", "longitude", "allowed_radius_metres", "client_reference"):
            self.assertIn(f'name="{field}"', html)

    def test_all_templates_compile(self):
        app = Flask(__name__, template_folder=str(Path(__file__).parent / "templates"))
        for template in app.jinja_env.list_templates():
            with self.subTest(template=template):
                app.jinja_env.get_template(template)
