"""Backend contracts for all 18 conversation fixtures, not speech/LLM simulation.

Utterance interpretation is supplied as synthetic tool arguments. These tests do
not establish that the unpublished Vapi prompt understands speech or suppresses
radio/echo; that remains a test-assistant listening/evaluation gate.
"""
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from datetime import timedelta

from test_garage_voice_reliability import business, slot, client, v, be, dvla
from trimtech.integrations.vapi import safety

from garage_voice_scenarios import SCENARIOS as CASES


class ConversationContracts(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict('os.environ', VAPI_WEBHOOK_SECRET='synthetic-secret',
                              GARAGE_VOICE_STRICT_MODE='1')
        self.env.start(); self.addCleanup(self.env.stop)
        self.data = dict(phone='+447700900001', call={'id':'synthetic-call',
            'customer':{'number':'+447700900001'}}, operation_id='synthetic-operation',
            service_key='mot', requested_datetime=slot.isoformat(),
            customer_name='Test Caller', registration='AB12CDE', confirmed=True)
        self.booking = dict(id='existing', start=slot.isoformat(), service='mot', reg='AB12CDE')
        for obj,name,kwargs in (
                (v,'_resolve_business',{'return_value':business}),
                (be,'check_requested_slot',{'return_value':{'available':True,'slots':[slot]}}),
                (dvla,'safely_lookup_vehicle',{'return_value':{'success':False}}),
                (v,'create_booking',{'return_value':{'id':'new'}}),
                (v,'list_bookings',{'return_value':[self.booking]}),
                (v,'cancel_booking',{'return_value':True}),
                (v,'reschedule_booking',{'return_value':{'id':'existing','start':slot.isoformat()}}),
                (v,'send_booking_confirmation',{'return_value':{'sid':'synthetic'}})):
            patcher=patch.object(obj,name,**kwargs)
            setattr(self,name,patcher.start()); self.addCleanup(patcher.stop)

    def post(self,path,data):
        return client.post('/vapi/'+path,json=data,
            headers={'Authorization':'Bearer synthetic-secret'}).get_json()

    def availability(self,data):
        return self.post('check-availability',data)['availability_token']

    def token(self,data=None):
        return safety.issue('booking', safety.scope(business,self.data['phone'],data or self.data),
                            v._booking_state(self.booking))

    def run_case(self,case):
        key=case['id']; data=dict(self.data)
        self.assertTrue(case['caller_turns'] and case['forbidden'])
        if key=='mot-natural':
            data['availability_token']=self.availability(data)
            self.assertTrue(self.post('book-appointment',data)['success'])
            self.assertEqual(self.create_booking.call_args.kwargs['start_dt'],slot)
        elif key=='service-correction':
            data['availability_token']=self.availability(data)
            data['service_key']='full_service'
            self.assertFalse(self.post('book-appointment',data)['success'])
            self.create_booking.assert_not_called()
            data['availability_token']=self.availability(data)
            self.assertTrue(self.post('book-appointment',data)['success'])
            self.assertEqual(self.create_booking.call_args.kwargs['service_key'],'full_service')
        elif key=='mot-and-service':
            data['service_key']='unconfigured_combination'
            self.assertFalse(self.post('book-appointment',data)['success'])
            self.create_booking.assert_not_called()
        elif key=='diagnostic':
            data.update(service_key='diagnostic',notes='Judders when cold; engine light on')
            data['availability_token']=self.availability(data)
            self.assertTrue(self.post('book-appointment',data)['success'])
            self.assertEqual(self.create_booking.call_args.kwargs['notes'],data['notes'])
        elif key in ('radio','backchannel','echo'):
            data.update(availability_token=self.availability(data),confirmed=False)
            self.assertFalse(self.post('book-appointment',data)['success'])
            self.create_booking.assert_not_called()
        elif key in ('compressor','pause-registration'):
            data.update(registration='',confirmed=False)
            self.assertFalse(self.post('book-appointment',data)['success'])
            self.create_booking.assert_not_called()
        elif key=='genuine-barge-in':
            data['availability_token']=self.availability(data)
            data['requested_datetime']=(slot+timedelta(days=1)).isoformat()
            self.assertFalse(self.post('book-appointment',data)['success'])
            self.create_booking.assert_not_called()
        elif key=='list-choice':
            self.list_bookings.return_value=[self.booking,dict(self.booking,id='van',reg='CD34EFG')]
            result=self.post('list-bookings',data)
            self.assertEqual(len(result['bookings']),2)
            self.assertTrue(all(x['booking_token'] for x in result['bookings']))
            self.cancel_booking.assert_not_called()
        elif key in ('cancel-no','cancel-yes'):
            data.update(booking_id='existing',booking_token=self.token(),confirmed=key=='cancel-yes')
            self.assertEqual(self.post('cancel-appointment',data)['success'],key=='cancel-yes')
            self.assertEqual(self.cancel_booking.call_count,1 if key=='cancel-yes' else 0)
        elif key=='reschedule':
            data.update(booking_id='existing',booking_token=self.token(),
                        new_requested_datetime=slot.isoformat(),availability_token=self.availability(data))
            self.assertTrue(self.post('reschedule-appointment',data)['success'])
            self.reschedule_booking.assert_called_once()
            self.cancel_booking.assert_not_called(); self.create_booking.assert_not_called()
        elif key in ('slot-race','tool-timeout'):
            data['availability_token']=self.availability(data)
            self.create_booking.side_effect=ValueError('slot_taken') if key=='slot-race' else TimeoutError('synthetic')
            result=self.post('book-appointment',data)
            self.assertFalse(result['success']);self.send_booking_confirmation.assert_not_called()
            if key=='tool-timeout':self.assertIn('before retrying',result['message'])
        elif key=='uk-date':
            for value in ('03/04','2027-03-28T01:30:00','2027-10-31T01:30:00'):
                with self.assertRaises(ValueError):v._parse_datetime(business,value)
            self.assertEqual(v._parse_datetime(business,'2027-10-31T01:30:00+01:00').hour,1)
        elif key=='human-fallback':
            result=self.post('tools',dict(data,message={'toolCallList':[{'id':'transfer','name':'unconfigured_transfer','arguments':{}}]}))
            self.assertIn('error',result['results'][0])
            self.create_booking.assert_not_called()
        else:
            self.fail('Scenario has no executable contract: '+key)


for scenario in CASES:
    def run(self,case=scenario): self.run_case(case)
    setattr(ConversationContracts,'test_'+scenario['id'].replace('-','_'),run)
