"""Narrow read-only client for PayChaser's private Control Centre summary API."""
import logging
import os
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests


logger = logging.getLogger(__name__)
API_PATH = '/api/platform/control-centre/v1/summary'
STATUS_KEYS = {
    'active',
    'trialing',
    'past_due',
    'canceled',
    'unpaid',
    'incomplete',
    'incomplete_expired',
    'checkout_pending',
    'other',
}
TIMEOUT = (2, 4)


def _configuration():
    endpoint = os.getenv('PAYCHASER_CONTROL_CENTRE_API_URL', '').strip()
    token = os.getenv('PAYCHASER_CONTROL_CENTRE_API_TOKEN', '')
    try:
        parsed = urlparse(endpoint)
        parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme != 'https'
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path.rstrip('/') != API_PATH
        or parsed.query
        or parsed.fragment
        or len(token) < 32
        or not token.isascii()
        or token != token.strip()
    ):
        return None
    return endpoint, token


def admin_url():
    """PayChaser's own platform-admin page, derived from the validated API URL.

    The link lands on PayChaser's separate sign-in; no credential or session is shared.
    """
    endpoint = os.getenv('PAYCHASER_CONTROL_CENTRE_API_URL', '').strip()
    try:
        parsed = urlparse(endpoint)
        parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme != 'https'
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path.rstrip('/') != API_PATH
        or parsed.query
        or parsed.fragment
    ):
        return None
    return 'https://%s/platform' % parsed.netloc

def _nonnegative_integer(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _optional_timestamp(payload, key):
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError('Invalid PayChaser record freshness timestamp.')
    timestamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if timestamp.tzinfo is None:
        raise ValueError('PayChaser record freshness timestamp has no timezone.')
    return timestamp.astimezone(timezone.utc)


def _validate_payload(payload):
    if not isinstance(payload, dict) or payload.get('schema_version') != 1:
        raise ValueError('Unsupported PayChaser summary schema.')

    for key in (
        'registered_businesses',
        'businesses_without_subscription',
        'active_trials',
        'scheduled_cancellations',
    ):
        if not _nonnegative_integer(payload.get(key)):
            raise ValueError('Invalid PayChaser summary count.')

    statuses = payload.get('subscription_status_counts')
    if not isinstance(statuses, dict) or set(statuses) != STATUS_KEYS:
        raise ValueError('Invalid PayChaser subscription status counts.')
    if not all(_nonnegative_integer(value) for value in statuses.values()):
        raise ValueError('Invalid PayChaser subscription status count.')

    as_of = payload.get('as_of')
    if not isinstance(as_of, str):
        raise ValueError('Invalid PayChaser summary timestamp.')
    parsed_as_of = datetime.fromisoformat(as_of.replace('Z', '+00:00'))
    if parsed_as_of.tzinfo is None:
        raise ValueError('PayChaser summary timestamp has no timezone.')
    if payload.get('data_freshness') != 'live_database_query':
        raise ValueError('PayChaser summary freshness is unknown.')

    return {
        'registered_businesses': payload['registered_businesses'],
        'businesses_without_subscription': payload['businesses_without_subscription'],
        'active_trials': payload['active_trials'],
        'scheduled_cancellations': payload['scheduled_cancellations'],
        'subscription_status_counts': statuses,
        'as_of': parsed_as_of.astimezone(timezone.utc),
        'business_records_updated_at': _optional_timestamp(
            payload,
            'business_records_updated_at',
        ),
        'subscription_records_updated_at': _optional_timestamp(
            payload,
            'subscription_records_updated_at',
        ),
    }


def fetch_summary():
    config = _configuration()
    if config is None:
        return {
            'available': False,
            'status': 'not_configured',
            'message': 'PayChaser service integration is not configured.',
        }

    endpoint, token = config
    try:
        response = requests.get(
            endpoint,
            headers={'Authorization': f'Bearer {token}', 'Accept': 'application/json'},
            timeout=TIMEOUT,
            allow_redirects=False,
        )
    except requests.Timeout:
        logger.warning('PayChaser Control Centre API request timed out')
        return {
            'available': False,
            'status': 'timeout',
            'message': 'PayChaser summary request timed out.',
        }
    except requests.RequestException:
        logger.warning('PayChaser Control Centre API request failed')
        return {
            'available': False,
            'status': 'unavailable',
            'message': 'PayChaser summary is temporarily unavailable.',
        }

    if response.status_code == 401:
        logger.error('PayChaser Control Centre API rejected service authentication')
        return {
            'available': False,
            'status': 'authentication_error',
            'message': 'PayChaser service authentication failed.',
        }
    if response.status_code >= 500:
        logger.warning(
            'PayChaser Control Centre API returned HTTP %s',
            response.status_code,
        )
        return {
            'available': False,
            'status': 'unavailable',
            'message': 'PayChaser summary is temporarily unavailable.',
        }
    if not response.ok:
        logger.error(
            'PayChaser Control Centre API returned unexpected HTTP %s',
            response.status_code,
        )
        return {
            'available': False,
            'status': 'api_error',
            'message': 'PayChaser returned an unexpected response.',
        }

    try:
        data = _validate_payload(response.json())
    except (ValueError, requests.exceptions.JSONDecodeError):
        logger.error('PayChaser Control Centre API returned an invalid summary')
        return {
            'available': False,
            'status': 'invalid_response',
            'message': 'PayChaser returned an invalid summary.',
        }

    return {
        'available': True,
        'status': 'connected',
        'message': '',
        'data': data,
    }


# ---------------------------------------------------------------------------
# Business administration (list, detail, profile edit) over the same private
# service token. Only whitelisted, type-checked fields are ever returned to a
# page; the token stays server-side.
# ---------------------------------------------------------------------------
PROFILE_FIELDS = (
    'name', 'email', 'phone', 'address_line_1', 'address_line_2',
    'town_or_city', 'postcode', 'country_code', 'company_number',
)
FIELD_LABELS = {
    'name': 'Business name', 'email': 'Business email', 'phone': 'Phone',
    'address_line_1': 'Address line 1', 'address_line_2': 'Address line 2',
    'town_or_city': 'Town or city', 'postcode': 'Postcode',
    'country_code': 'Country code', 'company_number': 'Company number',
}
BUSINESSES_PATH = '/api/platform/control-centre/v1/businesses'


class PayChaserAdminError(Exception):
    """A safe, displayable failure; never contains credentials or response bodies."""

    def __init__(self, message, status='error', fields=None):
        super().__init__(message)
        self.status = status
        self.fields = fields or {}


def _businesses_endpoint(business_id=None):
    config = _configuration()
    if config is None:
        raise PayChaserAdminError('PayChaser service integration is not configured.', 'not_configured')
    summary_url, token = config
    parsed = urlparse(summary_url)
    url = 'https://%s%s' % (parsed.netloc, BUSINESSES_PATH)
    if business_id is not None:
        url += '/%d' % int(business_id)
    return url, token


def _request(method, business_id=None, body=None):
    url, token = _businesses_endpoint(business_id)
    try:
        response = requests.request(
            method, url,
            headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/json'},
            json=body, timeout=TIMEOUT, allow_redirects=False,
        )
    except requests.Timeout:
        raise PayChaserAdminError('PayChaser did not respond in time.', 'timeout')
    except requests.RequestException:
        raise PayChaserAdminError('PayChaser is temporarily unavailable.', 'unavailable')
    if response.status_code == 401:
        logger.error('PayChaser business API rejected service authentication')
        raise PayChaserAdminError('PayChaser service authentication failed.', 'authentication_error')
    if response.status_code == 404:
        raise PayChaserAdminError('PayChaser business not found.', 'not_found')
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if response.status_code == 422:
        fields = payload.get('fields') if isinstance(payload, dict) else None
        fields = {
            str(key): str(value)[:200] for key, value in fields.items()
        } if isinstance(fields, dict) else {}
        raise PayChaserAdminError('PayChaser rejected the details.', 'validation', fields)
    if response.status_code >= 500:
        raise PayChaserAdminError('PayChaser is temporarily unavailable.', 'unavailable')
    if not response.ok or not isinstance(payload, dict) or payload.get('schema_version') != 1:
        raise PayChaserAdminError('PayChaser returned an unexpected response.', 'api_error')
    return payload


def _text(value, limit=500):
    if not isinstance(value, str):
        raise PayChaserAdminError('PayChaser returned an invalid business record.', 'invalid_response')
    return value[:limit]


def _clean_business(item):
    if (not isinstance(item, dict) or not isinstance(item.get('id'), int)
            or isinstance(item.get('id'), bool)):
        raise PayChaserAdminError('PayChaser returned an invalid business record.', 'invalid_response')
    business = {'id': item['id'], 'slug': _text(item.get('slug'), 120)}
    for field in PROFILE_FIELDS:
        business[field] = _text(item.get(field))
    for key in ('created_at', 'updated_at', 'trial_started_at'):
        value = item.get(key)
        business[key] = value[:40] if isinstance(value, str) else None
    subscription = item.get('subscription')
    if isinstance(subscription, dict):
        status = subscription.get('status')
        period_end = subscription.get('current_period_end')
        business['subscription_status'] = status[:30] if isinstance(status, str) else None
        business['current_period_end'] = period_end[:40] if isinstance(period_end, str) else None
        business['cancel_at_period_end'] = subscription.get('cancel_at_period_end') is True
    else:
        business.update(subscription_status=None, current_period_end=None, cancel_at_period_end=False)
    members = item.get('member_count')
    business['member_count'] = members if isinstance(members, int) and not isinstance(members, bool) else None
    return business


def list_businesses():
    payload = _request('GET')
    items = payload.get('businesses')
    if not isinstance(items, list):
        raise PayChaserAdminError('PayChaser returned an invalid business list.', 'invalid_response')
    return [_clean_business(item) for item in items]


def get_business(business_id):
    payload = _request('GET', business_id)
    return _clean_business(payload.get('business'))


def update_business(business_id, actor, reason, values):
    changes = {field: str(values.get(field, '')) for field in PROFILE_FIELDS}
    payload = _request('PATCH', business_id, {
        'actor': str(actor)[:100], 'reason': str(reason or '').strip(), 'changes': changes,
    })
    return _clean_business(payload.get('business'))
