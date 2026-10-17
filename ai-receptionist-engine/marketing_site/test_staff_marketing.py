"""Marketing release checks; no live requests, database access or deliveries."""
import hashlib
from html.parser import HTMLParser
from pathlib import Path
import re
import unittest
from unittest.mock import patch

from marketing_site import app as marketing

BASE = Path(__file__).resolve().parent
TRIAL = 'https://garage-voice.onrender.com/staff/account/register'
PRESERVED = {
    'garage-ai': 'd1c12d4ebe8e5a3fe8cdb2052434ba57c2e85b62beb974d770cd56550c133326',
    'paychaser': '8e301ce84bce81331027bee4f3b693e59b64dd975ae3f25f573d08b3dc5925e0',
    'paychaser-features': '9d893ce824e8058d9b2fd39903aeed9aae53faa6d0758c4ad6b46cb0f646a036',
    'demos': '10b269c5010de8419fd3840aeb39318cf2481c4d710961bbf2b4128e4871e29c',
}


class Tags(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.tags = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


class StaffMarketingTests(unittest.TestCase):
    def setUp(self):
        self.client = marketing.app.test_client()
        with self.client.get('/') as response:
            self.html = response.get_data(as_text=True)
        self.tags = Tags(self.html).tags

    def test_trial_links_use_exact_registration_url(self):
        trial = re.findall(r'<a\b[^>]*href="([^"]+)"[^>]*>Start your 14-day free trial</a>', self.html)
        self.assertEqual(len(trial), 4)
        self.assertEqual(set(trial), {TRIAL})

    def test_existing_product_and_demo_sections_are_preserved(self):
        for name, expected in PRESERVED.items():
            with self.subTest(section=name):
                section = re.search(rf'<section id="{name}"[\s\S]*?</section>', self.html)
                self.assertIsNotNone(section)
                self.assertEqual(hashlib.sha256(section.group().encode()).hexdigest(), expected)

    def test_every_local_image_and_responsive_variant_is_served(self):
        images = set()
        for tag, attrs in self.tags:
            if tag == 'img':
                images.add(attrs['src'])
            if tag == 'source' and 'srcset' in attrs:
                images.update(item.strip().split()[0] for item in attrs['srcset'].split(','))
        self.assertEqual(len(images), 16)
        for image in images:
            with self.subTest(image=image):
                self.assertTrue(image.startswith('/static/'))
                response = self.client.get(image)
                self.addCleanup(response.close)
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.mimetype.startswith('image/'))
                if image.endswith('.webp'):
                    self.assertEqual(response.mimetype, 'image/webp')
                    self.assertEqual(response.data[:4], b'RIFF')
                    self.assertEqual(response.data[8:12], b'WEBP')
                else:
                    self.assertIn(response.data[:3], (b'\xff\xd8\xff', b'\x89PN'))

    def test_stock_photos_have_accessible_responsive_markup(self):
        photos = [attrs for tag, attrs in self.tags if tag == 'img' and '/staff-manager/' in attrs.get('src','')]
        self.assertEqual(len(photos), 3)
        for image in photos:
            self.assertTrue(image.get('alt', '').strip())
            self.assertEqual((image['width'],image['height']), ('960','600'))
            self.assertEqual(image['loading'], 'lazy')
            self.assertEqual(image['decoding'], 'async')
        sources = [attrs for tag, attrs in self.tags if tag == 'source' and '/staff-manager/' in attrs.get('srcset','')]
        self.assertEqual(len(sources), 3)
        for source in sources:
            self.assertEqual(source['type'], 'image/webp')
            self.assertEqual(len(source['srcset'].split(',')), 4)
            self.assertTrue(source['sizes'])
        self.assertIn('Illustrative workplace stock photography.', self.html)
        self.assertTrue((BASE / 'STOCK_PHOTO_CREDITS.md').is_file())

    def test_navigation_targets_resolve(self):
        ids = [attrs['id'] for _, attrs in self.tags if 'id' in attrs]
        self.assertEqual(len(ids), len(set(ids)))
        for tag, attrs in self.tags:
            if tag == 'a' and attrs.get('href', '').startswith('#'):
                self.assertIn(attrs['href'][1:], ids)

    def test_public_pages_do_not_contact_delivery_providers(self):
        with patch.object(marketing, 'urlopen', side_effect=AssertionError('Unexpected network call')):
            for route in ('/', '/staff-manager', '/demo', '/health'):
                with self.subTest(route=route):
                    with self.client.get(route) as response:
                        self.assertEqual(response.status_code, 200)

    def test_marketing_route_inventory_contains_only_expected_pages(self):
        self.assertEqual({rule.rule for rule in marketing.app.url_map.iter_rules()},
                         {'/', '/staff-manager', '/demo', '/health', '/static/<path:filename>'})

    def test_staff_manager_opens_directly_with_its_own_metadata(self):
        with self.client.get('/staff-manager') as response:
            self.assertEqual(response.status_code, 200)
            self.assertNotIn('Location', response.headers)
            html = response.get_data(as_text=True)
        self.assertIn('<title>Staff Manager | GPS Clock-in, Rotas &amp; Payroll | TrimTech AI</title>', html)
        self.assertIn('id="staff-manager"', html)
        self.assertIn('<h1 id="staff-title">', html)
        self.assertNotIn('id="garage-ai"', html)
        self.assertNotIn('id="paychaser"', html)
        self.assertNotIn('{%', html)
        self.assertNotIn('{{', html)

    def test_staff_manager_reuses_the_exact_homepage_product_section(self):
        with self.client.get('/staff-manager') as response:
            html = response.get_data(as_text=True)
        pattern = r'<section id="staff-manager"[\s\S]*?</section>'
        # Only heading semantics differ: primary page heading vs homepage section.
        dedicated = re.search(pattern, html).group().replace('<h1 ', '<h2 ').replace('</h1>', '</h2>')
        self.assertEqual(dedicated, re.search(pattern, self.html).group())

    def test_all_dedicated_page_trial_buttons_use_the_registration_url(self):
        with self.client.get('/staff-manager') as response:
            html = response.get_data(as_text=True)
        trial = re.findall(r'<a\b[^>]*href="([^"]+)"[^>]*>Start your 14-day free trial</a>', html)
        self.assertEqual(len(trial), 3)
        self.assertEqual(set(trial), {TRIAL})

    def test_both_pages_link_to_staff_manager_and_homepage_navigation(self):
        for route in ('/', '/staff-manager'):
            with self.subTest(route=route), self.client.get(route) as response:
                tags = Tags(response.get_data(as_text=True)).tags
                links = {attrs.get('href') for tag, attrs in tags if tag == 'a'}
                self.assertIn('/staff-manager', links)
                self.assertIn('/#garage-ai', links)
                self.assertIn('/#paychaser', links)
                for link in links:
                    if link and link.startswith('/#'):
                        self.assertIn(f'id="{link[2:]}"', self.html)


if __name__ == '__main__':
    unittest.main()
