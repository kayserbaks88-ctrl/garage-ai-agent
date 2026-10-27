import contextlib
import io
import json
import time
import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta, time as daytime
from flask import Flask
from trimtech.core.business import BusinessConfig, ServiceDefinition
from trimtech.integrations.vapi import routes as v
from trimtech.integrations.google_calendar import service as cal
from trimtech.integrations import dvla
from trimtech.core import booking_engine as be
business = BusinessConfig('test-garage', 'garage', 'Test UK Garage', services=(
    ServiceDefinition('mot','MOT',60), ServiceDefinition('full_service','Full Service',120),
    ServiceDefinition('diagnostic','Diagnostic',45)), metadata={'calendar_id':'synthetic-calendar'})
now = datetime.now(business.timezone)
slot = datetime.combine((now+timedelta(days=7)).date(), daytime(10), tzinfo=business.timezone)
app = Flask(__name__)
app.testing = False
app.logger.disabled = True
app.register_blueprint(v.vapi_bp)
client = app.test_client()
observations = []
measurements = []
class VoiceProbe(unittest.TestCase):
    def setUp(self):
        self.scope = patch.object(v, '_resolve_business', return_value=business)
        self.scope.start(); self.addCleanup(self.scope.stop)

    def post(self, path, data):
        return client.post('/vapi/'+path,json=data)

    def values(self):
        return dict(phone='+447700900001',service_key='mot',requested_datetime=slot.isoformat(),
                    customer_name='Test Caller',registration='AB12CDE')

    def test_available_slot_is_grounded_in_tool_result(self):
        with patch.object(be,'check_requested_slot',return_value={'available':True,'slots':[slot]}) as check:
            response=self.post('check-availability',self.values())
        self.assertTrue(response.json['available'])
        self.assertEqual(check.call_args.kwargs['business'],business)

    def test_unavailable_slot_is_not_invented(self):
        with patch.object(be,'check_requested_slot',return_value={'available':False,'slots':[]}):
            data=self.post('check-availability',self.values()).json
        self.assertFalse(data['available']); self.assertEqual(data['alternatives'],[])

    def test_invalid_registration_does_not_book(self):
        with patch.object(dvla,'safely_lookup_vehicle',return_value={'success':False,'reason':'invalid_registration'}), patch.object(v,'create_booking') as create:
            result=self.post('lookup-vehicle',{'registration':'bad'}).json
        self.assertFalse(result['success']); create.assert_not_called()

    def test_booking_and_notification_order(self):
        order=[]
        with patch.object(dvla,'safely_lookup_vehicle',return_value={'success':True,'vehicle':{'registration':'AB12CDE'}}), patch.object(v,'create_booking',side_effect=lambda *a,**k: order.append('calendar') or {'id':'synthetic-event'}), patch.object(v,'send_booking_confirmation',side_effect=lambda **k: order.append('notification')):
            result=self.post('book-appointment',self.values()).json
        self.assertTrue(result['success']); self.assertEqual(order,['calendar','notification'])
        self.assertEqual(result['booking_id'],'synthetic-event')

    def test_slot_taken_cannot_report_booking_success(self):
        with patch.object(dvla,'safely_lookup_vehicle',return_value={'success':False}), patch.object(v,'create_booking',side_effect=ValueError('slot_taken')), patch.object(v,'send_booking_confirmation') as send:
            result=self.post('book-appointment',self.values()).json
        self.assertFalse(result['success']); send.assert_not_called()

    def test_notification_failure_preserves_successful_booking(self):
        with patch.object(dvla,'safely_lookup_vehicle',return_value={'success':False}), patch.object(v,'create_booking',return_value={'id':'synthetic-event'}), patch.object(v,'send_booking_confirmation',side_effect=RuntimeError('synthetic-failure')):
            result=self.post('book-appointment',self.values()).json
        self.assertTrue(result['success'])

    def test_other_callers_booking_cannot_be_cancelled(self):
        with patch.object(v,'list_bookings',return_value=[]), patch.object(v,'cancel_booking') as cancel:
            result=self.post('cancel-appointment',{'phone':'+447700900001','booking_id':'someone-else'}).json
        self.assertFalse(result['success']); cancel.assert_not_called()

    def test_reschedule_rejects_missing_or_unowned_booking(self):
        with patch.object(v,'list_bookings',return_value=[]), patch.object(v,'reschedule_booking') as move:
            result=self.post('reschedule-appointment',{'phone':'+447700900001','booking_id':'someone-else','new_requested_datetime':slot.isoformat()}).json
        self.assertFalse(result['success']); move.assert_not_called()

    def test_called_number_mapping_fails_closed_when_missing_or_ambiguous(self):
        self.scope.stop()
        with self.assertRaises(LookupError): v._resolve_business({})
        with patch.object(v,'_business_candidates',return_value=[business,business]), patch.object(v,'_configured_vapi_numbers',return_value={'+441234000000'}):
            with self.assertRaises(RuntimeError): v._resolve_business({'called_number':'+441234000000'})

    def test_calendar_filters_other_business_and_phone(self):
        api=MagicMock()
        api.events.return_value.list.return_value.execute.return_value={'items':[
            {'id':'ours','extendedProperties':{'private':{'business_id':'test-garage','phone':'07000'}}},
            {'id':'other-tenant','extendedProperties':{'private':{'business_id':'another','phone':'07000'}}},
            {'id':'other-caller','extendedProperties':{'private':{'business_id':'test-garage','phone':'07001'}}}]}
        with patch.object(cal,'calendar_service',return_value=api): rows=cal.list_bookings(business,'07000')
        self.assertEqual([r['id'] for r in rows],['ours'])

    def test_all_five_non_availability_tools_dispatch(self):
        names=['lookup_vehicle','create_booking','list_bookings','cancel_appointment','reschedule_appointment']
        result=self.post('tools',{'message':{'toolCallList':[{'id':str(i),'name':name,'arguments':{}} for i,name in enumerate(names)]}}).json
        self.assertEqual(len(result['results']),5)
        self.assertTrue(all(json.loads(r['result'])['success'] is False for r in result['results']))
        self.assertTrue(all('error' not in r for r in result['results']))

    def test_calendar_failure_is_structured(self):
        with patch.object(be,'check_requested_slot',return_value={'error':'calendar_unavailable'}):
            response=self.post('check-availability',self.values())
        self.assertEqual(response.status_code,200)
        self.assertFalse(response.json['success'])
        self.assertIn('temporarily unavailable', response.json['message'])

    def test_measure_calendar_request_amplification(self):
        for scenario,busy in [('free_day',False),('fully_busy_day',True)]:
            api=MagicMock()
            api.events.return_value.list.return_value.execute.return_value={'items':[{'id':'busy','start':{'dateTime':slot.replace(hour=9).isoformat()},'end':{'dateTime':slot.replace(hour=17).isoformat()}}] if busy else []}
            start=time.perf_counter()
            with patch.object(cal,'calendar_service',return_value=api) as build:
                slots=cal.get_available_slots(business,slot.date(),'mot')
            elapsed=(time.perf_counter()-start)*1000
            measurements.append({'scenario':scenario,'calendar_client_constructions':build.call_count,'calendar_list_calls':api.events.return_value.list.call_count,'slots_returned':len(slots),'mock_local_ms':round(elapsed,3),'not_network_latency':True})
        self.assertEqual(measurements[-2]['calendar_list_calls'],1)
        self.assertEqual(measurements[-1]['calendar_list_calls'],1)

    def test_legacy_requests_remain_compatible(self):
        with patch.object(dvla,'safely_lookup_vehicle',return_value={'success':False}), patch.object(v,'create_booking',return_value={'id':'synthetic-event'}) as create, patch.object(v,'send_booking_confirmation'):
            first=self.post('book-appointment',self.values())
            second=self.post('book-appointment',self.values())
        self.assertTrue(first.json['success'] and second.json['success'])
        self.assertEqual(create.call_count,2)
        observations.append({'finding':'endpoint accepts mutation without explicit confirmation field and invokes create twice for a replay','classification':'missing backend confirmation/replay guard; live prompt unknown; calendar duplicate not proven'})



class SafetyTests(unittest.TestCase):
    def test_webhook_secret_rejects_missing_or_bad_auth_before_lookup(self):
        with patch.dict('os.environ', VAPI_WEBHOOK_SECRET='synthetic-secret',GARAGE_VOICE_WEBHOOK_AUTH_ENABLED='1'), patch.object(v,'_resolve_business') as resolve:
            self.assertEqual(client.post('/vapi/check-availability',json={}).status_code,401)
            self.assertEqual(client.post('/vapi/check-availability',json={},headers={'Authorization':'Bearer wrong'}).status_code,401)
            resolve.assert_not_called()

    def test_strict_mode_without_secret_fails_closed(self):
        with patch.dict('os.environ', VAPI_WEBHOOK_SECRET='', GARAGE_VOICE_STRICT_MODE='1'):
            self.assertEqual(client.post('/vapi/tools',json={}).status_code,503)

    def test_signed_state_expires_and_rejects_tampering_or_other_tenants(self):
        from trimtech.integrations.vapi import safety
        with patch.dict('os.environ', VAPI_WEBHOOK_SECRET='synthetic-secret'):
            token=safety.issue('availability',['alpha','phone','call'],['mot','slot'])
            self.assertEqual(safety.verify(token,'availability',['alpha','phone','call']),['mot','slot'])
            for kind,scope in [('vehicle',['alpha','phone','call']),('availability',['beta','phone','call']),('availability',['alpha','other','call'])]:
                with self.assertRaises(ValueError): safety.verify(token,kind,scope)
            with self.assertRaises(ValueError): safety.verify(token+'x','availability',['alpha','phone','call'])
            with patch('trimtech.integrations.vapi.safety.time.time',return_value=time.time()+601):
                with self.assertRaises(ValueError): safety.verify(token,'availability',['alpha','phone','call'])

    def test_strict_confirmation_binds_service_slot_and_booking(self):
        from trimtech.integrations.vapi import safety
        data=dict(service_key='mot',confirmed=True,operation_id='op',call={'id':'call'})
        with patch.dict('os.environ', VAPI_WEBHOOK_SECRET='synthetic-secret',GARAGE_VOICE_STRICT_MODE='1'):
            data['availability_token']=safety.issue('availability',safety.scope(business,'phone',data),['mot',slot.isoformat()])
            v._guard_mutation(data,business,'phone',slot=slot)
            for change in ({'confirmed':False},{'service_key':'full_service'},{'operation_id':''}):
                with self.assertRaises(ValueError): v._guard_mutation(dict(data,**change),business,'phone',slot=slot)
            with self.assertRaises(ValueError): v._guard_mutation(data,business,'phone',slot=slot+timedelta(hours=1))

    def test_trusted_call_phone_overrides_model_supplied_phone(self):
        self.assertEqual(v._caller_phone({'phone':'07700900999','caller_number':'07700900998','call':{'customer':{'number':'07700900001'}}}),'+447700900001')

    def test_function_envelope_all_six_tools_and_string_arguments(self):
        with patch.object(v,'_resolve_business',return_value=business), patch.object(be,'check_requested_slot',return_value={'available':False,'slots':[]}):
            names=['lookup_vehicle','check_availability','create_booking','list_bookings','cancel_appointment','reschedule_appointment']
            data={'called_number':'test','call':{'id':'call','customer':{'number':'07700900001'}},'message':{'toolCallList':[{'id':str(i),'function':{'name':name,'arguments':json.dumps({'service_key':'mot','requested_datetime':slot.isoformat()})}} for i,name in enumerate(names)]}}
            with patch.object(v,'list_bookings',return_value=[]): response=client.post('/vapi/tools',json=data)
        self.assertEqual(response.status_code,200)
        self.assertEqual(len(response.json['results']),6)
        self.assertTrue(all('result' in item for item in response.json['results']))

    def test_notification_worker_always_requires_scheduler_auth(self):
        self.assertEqual(client.post('/vapi/notifications/run',json={}).status_code,503)
        with patch.dict('os.environ',INTERNAL_API_TOKEN='synthetic-internal'):
            self.assertEqual(client.post('/vapi/notifications/run',json={}).status_code,401)

    def test_signed_vehicle_result_skips_second_dvla_call(self):
        from trimtech.integrations.vapi import safety
        data=dict(phone='+447700900001',service_key='mot',requested_datetime=slot.isoformat(),customer_name='Test',registration='AB12CDE',call={'id':'call'})
        with patch.dict('os.environ',VAPI_WEBHOOK_SECRET='synthetic-secret'):
            data['vehicle_token']=safety.issue('vehicle',safety.scope(business,data['phone'],data),{'registration':'AB12CDE','vehicle':{'registration':'AB12CDE'}})
            with patch.object(v,'_resolve_business',return_value=business),patch.object(dvla,'safely_lookup_vehicle') as lookup,patch.object(v,'create_booking',return_value={'id':'event'}),patch.object(v,'send_booking_confirmation'):
                response=client.post('/vapi/book-appointment',json=data,headers={'Authorization':'Bearer synthetic-secret'})
                self.assertTrue(response.json['success']);lookup.assert_not_called()

    def test_deferred_mode_does_not_send_on_booking_response_path(self):
        data=dict(phone='+447700900001',service_key='mot',requested_datetime=slot.isoformat(),customer_name='Test',registration='AB12CDE')
        with patch.dict('os.environ',GARAGE_VOICE_DEFER_CONFIRMATIONS='1',GARAGE_VOICE_NOTIFICATION_WORKER_READY='1',INTERNAL_API_TOKEN='synthetic'),patch.object(v,'_resolve_business',return_value=business),patch.object(dvla,'safely_lookup_vehicle',return_value={'success':False}),patch.object(v,'create_booking',return_value={'id':'event'}) as create,patch.object(v,'send_booking_confirmation') as send:
            response=client.post('/vapi/book-appointment',json=data)
        self.assertTrue(response.json['success']);self.assertTrue(create.call_args.kwargs['defer_confirmation']);send.assert_not_called()


class CalendarTests(unittest.TestCase):
    def test_pagination_and_all_day_busy_are_honoured(self):
        api=MagicMock()
        api.events.return_value.list.return_value.execute.side_effect=[{'items':[],'nextPageToken':'page2'},{'items':[{'start':{'date':slot.date().isoformat()},'end':{'date':(slot.date()+timedelta(days=1)).isoformat()}}]}]
        with patch.object(cal,'calendar_service',return_value=api) as build:
            result=cal.get_available_slots(business,slot.date(),'mot')
        self.assertEqual(result,[]);self.assertEqual(build.call_count,1)
        self.assertEqual(api.events.return_value.list.call_count,2)

    def test_overlap_boundaries_transparency_and_malformed_busy_event(self):
        event={'start':{'dateTime':slot.isoformat()},'end':{'dateTime':(slot+timedelta(hours=1)).isoformat()}}
        self.assertFalse(cal._slot_free(business,[event],slot,slot+timedelta(minutes=30)))
        self.assertTrue(cal._slot_free(business,[event],slot+timedelta(hours=1),slot+timedelta(hours=2)))
        self.assertTrue(cal._slot_free(business,[dict(event,transparency='transparent')],slot,slot+timedelta(hours=1)))
        self.assertFalse(cal._slot_free(business,[{}],slot,slot+timedelta(hours=1)))

    def test_paginated_caller_booking_search_normalizes_uk_phone(self):
        api=MagicMock()
        api.events.return_value.list.return_value.execute.side_effect=[{'items':[],'nextPageToken':'p2'},{'items':[{'id':'mine','extendedProperties':{'private':{'business_id':business.business_id,'phone':'07700 900001'}}}]}]
        with patch.object(cal,'calendar_service',return_value=api): rows=cal.list_bookings(business,'+447700900001')
        self.assertEqual([r['id'] for r in rows],['mine'])

    def test_create_uses_one_client_and_persists_notification_marker_atomically(self):
        api=MagicMock()
        api.events.return_value.list.return_value.execute.return_value={'items':[]}
        api.events.return_value.insert.return_value.execute.return_value={'id':'event'}
        with patch.object(cal,'calendar_service',return_value=api) as build:
            cal.create_booking(business,phone='phone',service_key='mot',start_dt=slot,customer_name='Test',vehicle={'registration':'AB12CDE'},defer_confirmation=True)
        self.assertEqual(build.call_count,1)
        self.assertEqual(api.events.return_value.insert.call_args.kwargs['body']['extendedProperties']['private']['voice_notification_state'],'pending')

    def test_write_timeout_reconciles_same_id_without_second_insert(self):
        from types import SimpleNamespace
        class Missing(Exception): resp=SimpleNamespace(status=404)
        api=MagicMock(); saved={}
        def get():
            if not saved: raise Missing()
            return dict(saved)
        api.events.return_value.get.return_value.execute.side_effect=get
        api.events.return_value.list.return_value.execute.return_value={'items':[]}
        def insert(**kwargs):
            saved.update(kwargs['body']);saved['id']=saved['id']
            request=MagicMock();request.execute.side_effect=TimeoutError('synthetic');return request
        api.events.return_value.insert.side_effect=insert
        values=dict(phone='phone',service_key='mot',start_dt=slot,customer_name='Test',vehicle={'registration':'AB12CDE'},operation_id='call:op')
        with patch.object(cal,'calendar_service',return_value=api):
            result=cal.create_booking(business,**values)
            repeat=cal.create_booking(business,**values)
            with self.assertRaises(ValueError):cal.create_booking(business,**dict(values,customer_name='Changed'))
        self.assertTrue(result['replayed'] and repeat['replayed'])
        self.assertEqual(api.events.return_value.insert.call_count,1)


class NotificationTests(unittest.TestCase):
    def event(self,state='pending'):
        return {'id':'event','etag':'original','start':{'dateTime':slot.isoformat()},'extendedProperties':{'private':{'business_id':business.business_id,'voice_notification_state':state,'phone':'+447700900001','customer_name':'Test','service':'mot','reg':'AB12CDE'}}}

    def test_claim_precedes_send_and_uses_etag_for_each_update(self):
        from trimtech.integrations.vapi import notifications as n
        api=MagicMock();event=self.event();api.events.return_value.list.return_value.execute.return_value={'items':[event]}
        order=[];headers=[]
        def execute():
            headers.append(api.events.return_value.patch.return_value.headers['If-Match'])
            order.append('patch');return {'etag':'claimed'}
        api.events.return_value.patch.return_value.headers={}
        api.events.return_value.patch.return_value.execute.side_effect=execute
        with patch.object(n,'calendar_service',return_value=api),patch.object(n,'send_booking_confirmation',side_effect=lambda **k:order.append('send') or {'sid':'synthetic'}):
            result=n.process_pending(business)
        self.assertEqual(order,['patch','send','patch']);self.assertEqual(headers,['original','claimed']);self.assertEqual(result['sent'],1)

    def test_failed_etag_claim_never_sends(self):
        from trimtech.integrations.vapi import notifications as n
        api=MagicMock();api.events.return_value.list.return_value.execute.return_value={'items':[self.event()]}
        api.events.return_value.patch.return_value.execute.side_effect=RuntimeError('etag-conflict')
        with patch.object(n,'calendar_service',return_value=api),patch.object(n,'send_booking_confirmation') as send:
            result=n.process_pending(business)
        send.assert_not_called();self.assertEqual(result['skipped'],1)

    def test_uncertain_provider_send_is_not_replayed(self):
        from trimtech.integrations.vapi import notifications as n
        api=MagicMock();api.events.return_value.list.return_value.execute.return_value={'items':[self.event()]}
        api.events.return_value.patch.return_value.execute.return_value={'etag':'claimed'}
        with patch.object(n,'calendar_service',return_value=api),patch.object(n,'send_booking_confirmation',side_effect=TimeoutError('synthetic')) as send:
            result=n.process_pending(business)
            api.events.return_value.list.return_value.execute.return_value={'items':[self.event('processing'),self.event('uncertain')]}
            n.process_pending(business)
        self.assertEqual(result['uncertain'],1);self.assertEqual(send.call_count,1)
        self.assertEqual(api.events.return_value.patch.call_args.kwargs['body']['extendedProperties']['private']['voice_notification_state'],'uncertain')

    def test_deferred_booking_requires_worker_readiness_before_any_write(self):
        with patch.dict('os.environ',GARAGE_VOICE_DEFER_CONFIRMATIONS='1',GARAGE_VOICE_NOTIFICATION_WORKER_READY='0'),patch.object(v,'_resolve_business',return_value=business),patch.object(v,'create_booking') as create:
            response=client.post('/vapi/book-appointment',json=VoiceProbe().values())
        self.assertEqual(response.status_code,503);create.assert_not_called()


class FinalGuardTests(unittest.TestCase):
    def test_complete_busy_day_availability_uses_one_client_and_list(self):
        api=MagicMock()
        busy={'start':{'dateTime':slot.replace(hour=9).isoformat()},'end':{'dateTime':slot.replace(hour=17).isoformat()}}
        api.events.return_value.list.return_value.execute.return_value={'items':[busy]}
        with patch.object(cal,'calendar_service',return_value=api) as build:
            result=be.check_requested_slot({'service_key':'mot','requested_datetime':slot},business=business)
        self.assertFalse(result['available']);self.assertEqual(result['slots'],[])
        self.assertEqual(build.call_count,1);self.assertEqual(api.events.return_value.list.call_count,1)

    def test_search_snapshot_does_not_replace_fresh_write_check(self):
        api=MagicMock()
        busy={'start':{'dateTime':slot.isoformat()},'end':{'dateTime':(slot+timedelta(hours=1)).isoformat()}}
        api.events.return_value.list.return_value.execute.side_effect=[{'items':[]},{'items':[busy]}]
        with patch.object(cal,'calendar_service',return_value=api):
            self.assertTrue(cal.check_day_availability(business,slot,'mot')['available'])
            with self.assertRaises(ValueError):
                cal.create_booking(business,phone='phone',service_key='mot',start_dt=slot,customer_name='Test',vehicle={})
        api.events.return_value.insert.assert_not_called()

    def test_out_of_hours_is_not_offered_or_written(self):
        api=MagicMock();api.events.return_value.list.return_value.execute.return_value={'items':[]}
        late=slot.replace(hour=22)
        with patch.object(cal,'calendar_service',return_value=api):
            self.assertFalse(cal.check_day_availability(business,late,'mot')['available'])
            with self.assertRaises(ValueError):cal.create_booking(business,phone='phone',service_key='mot',start_dt=late,customer_name='Test',vehicle={})
        api.events.return_value.insert.assert_not_called()

    def test_argument_scope_cannot_override_authenticated_tool_envelope(self):
        other=BusinessConfig('other','garage','Other',services=business.services)
        data={'called_number':'+441111111111','call':{'id':'call','customer':{'number':'07700900001'}},'message':{'toolCallList':[{'id':'op','function':{'name':'create_booking','arguments':dict(VoiceProbe().values(),called_number='+442222222222',phone='07700900999',caller_number='07700900998',call={'id':'fake'})}}]}}
        with patch.object(v,'_business_candidates',return_value=[business,other]),patch.object(v,'_configured_vapi_numbers',side_effect=lambda b:{'+441111111111' if b==business else '+442222222222'}),patch.object(v,'create_booking',return_value={'id':'event'}) as create,patch.object(dvla,'safely_lookup_vehicle',return_value={'success':False}),patch.object(v,'send_booking_confirmation'):
            response=client.post('/vapi/tools',json=data)
        self.assertTrue(json.loads(response.json['results'][0]['result'])['success'])
        self.assertEqual(create.call_args.args[0],business)
        self.assertEqual(create.call_args.kwargs['phone'],'+447700900001')
        self.assertEqual(create.call_args.kwargs['operation_id'],'call:op')

    def test_malformed_function_arguments_never_execute_a_mutation(self):
        with patch.object(v,'_resolve_business',return_value=business),patch.object(v,'create_booking') as create:
            for function in ('bad',{'name':'create_booking','arguments':'not json'},{'name':'create_booking','arguments':[]}):
                response=client.post('/vapi/tools',json={'message':{'toolCallList':[{'id':'op','function':function}]}})
                self.assertEqual(response.status_code,200)
        create.assert_not_called()


class WriteResultTests(unittest.TestCase):
    def test_booking_without_provider_id_is_not_success(self):
        with patch.object(v,'_resolve_business',return_value=business),patch.object(dvla,'safely_lookup_vehicle',return_value={'success':False}),patch.object(v,'create_booking',return_value={}),patch.object(v,'send_booking_confirmation') as send:
            response=client.post('/vapi/book-appointment',json=VoiceProbe().values())
        self.assertFalse(response.json['success']);send.assert_not_called()

    def test_unconfirmed_cancellation_is_not_success(self):
        with patch.object(v,'_resolve_business',return_value=business),patch.object(v,'list_bookings',return_value=[{'id':'event','start':slot.isoformat()}]),patch.object(v,'cancel_booking',return_value=False):
            response=client.post('/vapi/cancel-appointment',json={'phone':'07700900001','booking_id':'event'})
        self.assertFalse(response.json['success'])

    def test_move_without_provider_id_is_not_success(self):
        with patch.object(v,'_resolve_business',return_value=business),patch.object(v,'list_bookings',return_value=[{'id':'event','start':slot.isoformat(),'service':'mot'}]),patch.object(v,'reschedule_booking',return_value={}):
            response=client.post('/vapi/reschedule-appointment',json={'phone':'07700900001','booking_id':'event','new_requested_datetime':slot.isoformat()})
        self.assertFalse(response.json['success'])


class ConcurrentChangeTests(unittest.TestCase):
    def test_cancellation_uses_etag_from_owned_listing(self):
        api=MagicMock();api.events.return_value.delete.return_value.headers={}
        with patch.object(cal,'calendar_service',return_value=api):
            self.assertTrue(cal.cancel_booking(business,'event',expected_etag='known-version'))
        self.assertEqual(api.events.return_value.delete.return_value.headers['If-Match'],'known-version')

    def test_reschedule_detects_changed_start_before_update(self):
        api=MagicMock();api.events.return_value.get.return_value.execute.return_value={'start':{'dateTime':(slot+timedelta(hours=1)).isoformat()}}
        with patch.object(cal,'calendar_service',return_value=api):
            with self.assertRaises(ValueError):cal.reschedule_booking(business,event_id='event',new_start=slot,expected_start=slot.isoformat())
        api.events.return_value.update.assert_not_called()

    def test_reschedule_uses_etag_and_shared_client(self):
        api=MagicMock()
        api.events.return_value.get.return_value.execute.return_value={'id':'event','etag':'version','start':{'dateTime':slot.isoformat()},'extendedProperties':{'private':{'business_id':business.business_id,'service':'mot'}}}
        api.events.return_value.list.return_value.execute.return_value={'items':[]}
        api.events.return_value.update.return_value.headers={}
        api.events.return_value.update.return_value.execute.return_value={'id':'event'}
        with patch.object(cal,'calendar_service',return_value=api) as build:
            result=cal.reschedule_booking(business,event_id='event',new_start=slot,expected_start=slot.isoformat())
        self.assertEqual(result['id'],'event');self.assertEqual(build.call_count,1)
        self.assertEqual(api.events.return_value.update.return_value.headers['If-Match'],'version')


class CompatibilityActivationTests(unittest.TestCase):
    def test_preexisting_webhook_secret_does_not_activate_optional_auth(self):
        from trimtech.integrations.vapi import safety
        with patch.dict('os.environ',VAPI_WEBHOOK_SECRET='synthetic-secret',GARAGE_VOICE_WEBHOOK_AUTH_ENABLED='0',GARAGE_VOICE_STRICT_MODE='0'),app.test_request_context('/vapi/check-availability'):
            self.assertIsNone(safety.authenticate())

    def test_explicit_auth_without_configured_secret_fails_closed(self):
        with patch.dict('os.environ',VAPI_WEBHOOK_SECRET='',GARAGE_VOICE_WEBHOOK_AUTH_ENABLED='1',GARAGE_VOICE_STRICT_MODE='0'):
            self.assertEqual(client.post('/vapi/tools',json={}).status_code,503)
