"""Marketing-only, fail-closed demo protection. No shared application database."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import hmac
import ipaddress
import json
import os
from pathlib import Path
import re
import sqlite3
import time
import unicodedata
from urllib.parse import urlencode
from urllib.request import Request, urlopen

SITEVERIFY = 'https://challenges.cloudflare.com/turnstile/v0/siteverify'


class DemoRejected(Exception):
    def __init__(self, message, status=400):
        self.message, self.status = message, status


def configuration():
    """Explicit operator enablement and testing acknowledgement; missing values close the form."""
    if os.getenv('MARKETING_DEMO_ENABLED', 'false').strip().lower() != 'true':
        return None
    if os.getenv('MARKETING_DEMO_PROTECTION_TESTED', 'false').strip().lower() != 'true':
        return None
    site = os.getenv('MARKETING_TURNSTILE_SITE_KEY', '').strip()
    secret = os.getenv('MARKETING_TURNSTILE_SECRET_KEY', '').strip()
    state_secret = os.getenv('MARKETING_DEMO_STATE_SECRET', '')
    hosts = {h.strip().lower() for h in os.getenv('MARKETING_TURNSTILE_HOSTNAMES', '').split(',') if h.strip()}
    path = Path(os.getenv('MARKETING_DEMO_STATE_DB', ''))
    if (not site or len(secret) < 20 or len(state_secret) < 32 or not hosts
            or any(not re.fullmatch(r'[a-z0-9]+(?:[.-][a-z0-9]+)*', h) for h in hosts)
            or any(re.match(r'^[123]x0', key) for key in (site, secret))
            or not path.is_absolute() or not path.parent.is_dir()):
        return None
    try:
        proxies = [ipaddress.ip_network(c.strip()) for c in os.getenv('MARKETING_DEMO_TRUSTED_PROXY_CIDRS', '').split(',') if c.strip()]
        if any(p.prefixlen == 0 for p in proxies):
            return None
    except ValueError:
        return None
    return dict(site=site, secret=secret, state_secret=state_secret, hosts=hosts, path=str(path), proxies=proxies)


def client_address(request, config):
    """Ignore forwarded headers unless the socket peer is an explicitly trusted proxy."""
    try:
        peer = ipaddress.ip_address(request.remote_addr or '')
        chain = request.headers.get('X-Forwarded-For', '')
        if len(chain) > 2048:
            raise ValueError()
        if chain and any(peer in net for net in config['proxies']):
            for value in reversed(chain.split(',')):
                if not any(peer in net for net in config['proxies']):
                    break
                peer = ipaddress.ip_address(value.strip())
        return str(peer)
    except ValueError:
        raise DemoRejected('Unable to validate this request.', 400) from None


@contextmanager
def state(config):
    connection = sqlite3.connect(config['path'], timeout=2, isolation_level=None)
    try:
        connection.execute('CREATE TABLE IF NOT EXISTS demo_limits(key TEXT PRIMARY KEY, attempts INTEGER NOT NULL, expires INTEGER NOT NULL)')
        connection.execute('CREATE TABLE IF NOT EXISTS demo_claims(key TEXT PRIMARY KEY, expires INTEGER NOT NULL)')
        connection.execute('BEGIN IMMEDIATE')
        now = int(time.time())
        connection.execute('DELETE FROM demo_limits WHERE expires<=?', (now,))
        connection.execute('DELETE FROM demo_claims WHERE expires<=?', (now,))
        yield connection, now
        connection.execute('COMMIT')
    except Exception:
        if connection.in_transaction:
            connection.execute('ROLLBACK')
        raise
    finally:
        connection.close()


def digest(config, value):
    return hmac.new(config['state_secret'].encode(), value.encode(), hashlib.sha256).hexdigest()


def increment(connection, config, name, now, seconds, maximum):
    bucket = now // seconds
    key = digest(config, f'{name}:{bucket}')
    connection.execute('INSERT INTO demo_limits VALUES (?,1,?) ON CONFLICT(key) DO UPDATE SET attempts=attempts+1', (key, (bucket+1)*seconds))
    return connection.execute('SELECT attempts FROM demo_limits WHERE key=?', (key,)).fetchone()[0] <= maximum


def validate(form):
    limits = dict(name=120, business_name=160, phone=40, email=254, contact_method=10, garage_size=20, message=1000,
                  website=200, **{'cf-turnstile-response': 2048})
    if any(key not in limits or len(form.getlist(key)) != 1 for key in form):
        raise DemoRejected('Please submit the demo form once with valid details.')
    values = {}
    for key, limit in limits.items():
        raw = form.get(key, '')
        if len(raw) > limit:
            raise DemoRejected('One or more fields is too long.')
        values[key] = unicodedata.normalize('NFKC', raw).strip()
        if len(values[key]) > limit:
            raise DemoRejected('One or more fields is too long.')
        if any(unicodedata.category(c).startswith('C') and not (key == 'message' and c in '\n\r\t') for c in values[key]):
            raise DemoRejected('Please use plain text in the form.')
    if values['website']:
        raise DemoRejected('Unable to accept this enquiry.')
    for field in ('name', 'business_name'):
        value = values[field]
        # Unicode names and ordinary business punctuation are supported; domains,
        # schemes, markup, encoded links and disguised dot-separated URLs are not.
        if (len(value) < 2 or not any(c.isalpha() for c in value)
                or any(not (c.isalnum() or c in " &'’.-(),") for c in value)
                or re.search(r'(?i)(www\b|https?\b|[a-z0-9]\s*\.\s*[a-z]{2,}\b|\b\d{1,3}(?:\.\d{1,3}){3}\b)', value)):
            raise DemoRejected('Enter a valid name and business name without links.')
    email = values['email'].lower()
    if not re.fullmatch(r"[a-z0-9!#$%&'*+/=?^_`{|}~.-]+@[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.[a-z]{2,63}", email) or '..' in email:
        raise DemoRejected('Enter a valid email address.')
    local, domain = email.rsplit('@', 1)
    if len(local) > 64 or local.startswith('.') or local.endswith('.') or any(
            not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label) for label in domain.split('.')):
        raise DemoRejected('Enter a valid email address.')
    if not re.fullmatch(r'\+?[0-9 ()-]{7,40}', values['phone']):
        raise DemoRejected('Enter a valid phone number.')
    phone = re.sub(r'[^0-9+]', '', values['phone'])
    if phone.startswith('0044'):
        phone = '0' + phone[4:]
    elif phone.startswith('+44'):
        phone = '0' + phone[3:]
    if not 7 <= len(phone.lstrip('+')) <= 15:
        raise DemoRejected('Enter a valid phone number.')
    if values['contact_method'] not in {'phone', 'email', 'whatsapp'} or values['garage_size'] not in {'', 'solo', '2-5', '6-10', '11-plus', 'multi-site'}:
        raise DemoRejected('Choose a valid contact method and business size.')
    if not values['cf-turnstile-response']:
        raise DemoRejected('Complete the security check before submitting.')
    values.update(email=email, phone=phone)
    return {key: values[key] for key in ('name', 'business_name', 'phone', 'email', 'contact_method', 'garage_size', 'message')}, values['cf-turnstile-response']


def verify_turnstile(config, token, address):
    body = urlencode(dict(secret=config['secret'], response=token, remoteip=address)).encode()
    outbound = Request(SITEVERIFY, data=body, headers={'Content-Type': 'application/x-www-form-urlencoded'}, method='POST')
    try:
        with urlopen(outbound, timeout=5) as response:
            data = json.loads(response.read(16385))
        timestamp = datetime.fromisoformat(data['challenge_ts'].replace('Z', '+00:00'))
        age = (datetime.now(timezone.utc) - timestamp).total_seconds()
        return (data.get('success') is True and data.get('hostname') in config['hosts']
                and data.get('action') == 'marketing_demo' and -30 <= age <= 300)
    except Exception:
        # Timeouts, malformed responses and provider errors never open the gate.
        return False


def protect_submission(request):
    config = configuration()
    if not config:
        raise DemoRejected('Demo requests are temporarily unavailable. Please try again later.', 503)
    if request.content_length is None or request.content_length > 16384:
        raise DemoRejected('This submission is too large.', 413)
    if request.mimetype != 'application/x-www-form-urlencoded':
        raise DemoRejected('Please use the demo form.', 415)
    address = client_address(request, config)
    try:
        with state(config) as (connection, now):
            ip_allowed = increment(connection, config, 'ip:'+address, now, 900, 5)
            global_allowed = increment(connection, config, 'attempts', now, 900, 100)
        if not ip_allowed or not global_allowed:
            raise DemoRejected('Too many requests. Please try again later.', 429)
        lead, token = validate(request.form)
        if not verify_turnstile(config, token, address):
            raise DemoRejected('The security check failed or expired. Please reload the form.')
        keys = [digest(config, 'email:'+lead['email']), digest(config, 'phone:'+lead['phone']), digest(config, 'token:'+token)]
        with state(config) as (connection, now):
            if any(connection.execute('SELECT 1 FROM demo_claims WHERE key=?', (key,)).fetchone() for key in keys):
                raise DemoRejected('This enquiry has already been submitted. Please wait for our reply.', 409)
            if not increment(connection, config, 'accepted', now, 86400, 10):
                raise DemoRejected('Demo requests are temporarily at capacity. Please try again later.', 429)
            for key in keys:
                connection.execute('INSERT INTO demo_claims VALUES (?,?)', (key, now+86400))
        # Reserve before any delivery: failures and concurrent retries cannot send again.
        return lead
    except sqlite3.Error:
        raise DemoRejected('Demo requests are temporarily unavailable. Please try again later.', 503) from None
