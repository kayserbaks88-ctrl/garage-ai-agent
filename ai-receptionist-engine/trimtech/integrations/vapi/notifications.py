"""Calendar-backed confirmation outbox; no in-memory threads or database schema.

Pending work is saved atomically with the booking. A worker claims an event using
its ETag before sending. Interrupted/uncertain sends require reconciliation rather
than automatic replay: Twilio and Calendar do not offer a shared transaction.
"""
from trimtech.integrations.google_calendar.service import (
    _list_events, _required_calendar_id, calendar_service, service_definition, timezone,
)
from trimtech.modules.reminders.sender import send_booking_confirmation
from datetime import datetime


def process_pending(business, limit=20):
    api = calendar_service(business)
    events = _list_events(business, api=api,
                         privateExtendedProperty=['voice_notification_state=pending',
                                                  'business_id='+business.business_id])
    counts = dict(sent=0, uncertain=0, skipped=0)
    for event in events[:max(1, min(int(limit), 100))]:
        private = (event.get('extendedProperties') or {}).get('private') or {}
        if (event.get('status') == 'cancelled' or private.get('business_id') != business.business_id
                or private.get('voice_notification_state') != 'pending' or not event.get('etag')):
            counts['skipped'] += 1
            continue

        def update(state, etag):
            body = dict(private, voice_notification_state=state)
            request = api.events().patch(calendarId=_required_calendar_id(business),
                eventId=event['id'], body={'extendedProperties': {'private': body}})
            request.headers['If-Match'] = etag
            return request.execute()

        # Validate all local fields before claiming or contacting the provider.
        try:
            start = datetime.fromisoformat(event['start']['dateTime']).astimezone(timezone(business))
            label = service_definition(business, private['service']).name
            phone, name, registration = private['phone'], private['customer_name'], private['reg']
            if not phone:
                raise ValueError('missing_phone')
            claimed = update('processing', event['etag'])
            if not claimed.get('etag'):
                raise ValueError('claim_unconfirmed')
        except Exception:
            counts['skipped'] += 1
            continue
        try:
            result = send_booking_confirmation(phone=phone, customer_name=name,
                service_label=label, registration=registration,
                date_text=f"{start.strftime('%A')} {start.day} {start.strftime('%B')}",
                time_text=start.strftime('%I:%M %p').lstrip('0').replace(':00 ', ' ').lower())
            if not result or not result.get('sid'):
                raise RuntimeError('provider_acceptance_unconfirmed')
            update('sent', claimed['etag'])
            counts['sent'] += 1
        except Exception:
            # Do not replay: a timeout or failed status update can follow a send.
            # 'processing' also remains durable if this final update fails/crashes.
            try:
                update('uncertain', claimed['etag'])
            except Exception:
                pass
            counts['uncertain'] += 1
    return counts
