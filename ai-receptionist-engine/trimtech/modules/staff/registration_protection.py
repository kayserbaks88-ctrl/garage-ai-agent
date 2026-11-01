"""Anti-automation checks for public Staff Manager business registration."""
import hmac
import logging
import os
import secrets

import requests

VERIFY_URL = 'https://challenges.cloudflare.com/turnstile/v0/siteverify'
NONCE_KEY = '_staff_register_nonce'
HONEYPOT_FIELD = 'company_website'
TOKEN_FIELD = 'cf-turnstile-response'
logger = logging.getLogger(__name__)


class Rejected(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def site_key():
    """Public widget key, only when both Turnstile keys are configured."""
    key = os.getenv('TURNSTILE_SITE_KEY', '').strip()
    return key if key and os.getenv('TURNSTILE_SECRET_KEY', '').strip() else ''


def turnstile_enabled():
    return bool(site_key())


def issue_nonce(session):
    nonce = secrets.token_urlsafe(24)
    session[NONCE_KEY] = nonce
    return nonce


def consume_nonce(session, submitted):
    """One-time form token: blocks replayed and directly posted submissions."""
    expected = session.pop(NONCE_KEY, None)
    if not expected or not isinstance(submitted, str) or not hmac.compare_digest(expected, submitted):
        raise Rejected(400, 'This form has expired or was already submitted. Please reload the page and try again.')


def honeypot_tripped(form):
    return bool(str(form.get(HONEYPOT_FIELD, '')).strip())


def verify_turnstile(token, remote_ip):
    """Fail closed once configured: a missing, invalid or unverifiable token is rejected."""
    if not turnstile_enabled():
        logger.warning('Turnstile is not configured; registration is not protected by a challenge.')
        return
    token = str(token or '').strip()
    if not token or len(token) > 2048:
        raise Rejected(400, 'Please complete the security check and try again.')
    payload = {'secret': os.getenv('TURNSTILE_SECRET_KEY', '').strip(), 'response': token}
    if remote_ip:
        payload['remoteip'] = remote_ip
    try:
        reply = requests.post(VERIFY_URL, data=payload, timeout=5)
        reply.raise_for_status()
        success = reply.json().get('success') is True
    except (requests.RequestException, ValueError):
        logger.warning('Turnstile verification unavailable; registration rejected.')
        raise Rejected(503, 'Registration is temporarily unavailable. Please try again.')
    if not success:
        raise Rejected(400, 'The security check failed. Please try again.')
