"""Opt-in authenticated, short-lived tool context; no global caller/data cache."""
import base64
import hashlib
import hmac
import json
import os
import time

from flask import request


def enabled(name):
    return os.getenv(name, '').strip() == '1'


def authenticate():
    # Deploying compatibility code must not activate auth from a pre-existing key.
    if not (enabled('GARAGE_VOICE_WEBHOOK_AUTH_ENABLED') or enabled('GARAGE_VOICE_STRICT_MODE')):
        return None
    secret = os.getenv('VAPI_WEBHOOK_SECRET', '')
    if not secret:
        return 'not_configured'
    supplied = request.headers.get('Authorization', '')
    supplied = supplied[7:] if supplied.startswith('Bearer ') else ''
    return None if hmac.compare_digest(supplied.encode(), secret.encode()) else 'unauthorised'


def issue(kind, scope, value, ttl=600):
    secret = os.getenv('VAPI_WEBHOOK_SECRET', '')
    if not secret:
        return ''
    body = json.dumps(dict(kind=kind, scope=scope, value=value, expires=int(time.time())+ttl),
                      sort_keys=True, separators=(',', ':')).encode()
    encoded = base64.urlsafe_b64encode(body).decode().rstrip('=')
    signature = hmac.new(secret.encode(), encoded.encode(), hashlib.sha256).hexdigest()
    return encoded + '.' + signature


def verify(token, kind, scope):
    secret = os.getenv('VAPI_WEBHOOK_SECRET', '')
    if not secret or not isinstance(token, str) or len(token) > 12000:
        raise ValueError('Check the details again before confirming this action.')
    try:
        encoded, signature = token.rsplit('.', 1)
        expected = hmac.new(secret.encode(), encoded.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError()
        data = json.loads(base64.urlsafe_b64decode(encoded + '='*(-len(encoded)%4)))
        if data['kind'] != kind or data['scope'] != scope or data['expires'] <= time.time():
            raise ValueError()
        return data['value']
    except (ValueError, KeyError, TypeError, UnicodeError) as error:
        raise ValueError('Check the details again before confirming this action.') from error


def call_id(data):
    message = data.get('message') if isinstance(data.get('message'), dict) else {}
    call = message.get('call') or data.get('call') or {}
    if not isinstance(call, dict):
        return ''
    identifier = str(call.get('id') or '')
    return identifier if len(identifier) <= 200 else ''


def scope(business, phone, data):
    return [business.business_id, phone, call_id(data)]


def operation_id(data):
    """Stable Vapi tool-call IDs, never a mutable customer name as identity."""
    identifier = str(data.get('_tool_call_id') or data.get('operation_id') or '')
    call = call_id(data)
    if call and identifier and len(identifier) <= 200:
        return call + ':' + identifier
    return None
