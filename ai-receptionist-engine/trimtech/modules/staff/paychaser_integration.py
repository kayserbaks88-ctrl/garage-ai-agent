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
