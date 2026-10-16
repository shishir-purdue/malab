import unittest
from types import SimpleNamespace
from malab.dashboard.controller import Dashboard
from malab.instruments.ad5780 import ChannelCalibration
from malab.instruments._line_socket import CommandError


class FakeDac:
    def __init__(self,**kwargs):
        self.connected=False;self.bench_port=kwargs['bench_port'];self.calls=[];self.bad=False
        self.state='IDLE';self.codes=[131072]*4
    def connect(self):self.connected=True;self.calls.append('connect')
    def close(self):self.connected=False;self.calls.append('close')
    def disconnect(self):self.connected=False;self.calls.append('disconnect')
    def get_calibration(self,ch):return ChannelCalibration(-10000000000,76293945,131072,False)
    def get_status(self):return SimpleNamespace(state=self.state,channel=1,target_code=131072)
    def get_code(self,ch):
        if self.bad and ch==1:raise CommandError('invalid readback')
        return self.codes[ch-1]
    def get_output_codes(self,**kwargs):
        return [dict(channel=i+1,code=None if self.bad and i==0 else c,source='unknown' if self.bad and i==0 else 'readback') for i,c in enumerate(self.codes)]
    def set_voltage(self,ch,v):self.calls.append(('set',ch,v))
    def voltage_to_code(self,ch,v):return self.get_calibration(ch).code(v)
    def initialize(self,ch=None):self.calls.append(('initialize',ch))
    def ramp(self,ch,v,speed,**kwargs):
        self.calls.append(('ramp',ch,v,speed));return SimpleNamespace(channel=ch,target_code=131072)


class ControllerTests(unittest.TestCase):
    def make(self):return Dashboard(dac_factory=FakeDac,usb=None)
    def test_monitor_connects_without_output_commands(self):
        d=self.make();d.poll_dac()
        self.assertEqual(d.dac.calls,['connect']);self.assertEqual(d.snapshot()['network']['state'],'good')
        self.assertEqual([r['voltage'] for r in d.snapshot()['channels']],[0]*4)
    def test_validation_and_idempotency(self):
        d=self.make()
        with self.assertRaises(ValueError):d.submit(dict(action='set',request_id='bad',channel=0,voltage=0))
        with self.assertRaises(ValueError):d.submit(dict(action='ramp',request_id='bad',channel=1,voltage=0,speed=0))
        request=dict(action='set',request_id='once',channel=1,voltage=.05)
        d.submit(request);d.submit(request)
        self.assertEqual(d.commands.qsize(),1)
        d.action(d.commands.get());d.complete(request);d.submit(request)
        self.assertEqual(d.dac.calls,[('initialize',1),('set',1,.05)]);self.assertTrue(d.commands.empty())
    def test_explicit_ramp_prepares_only_its_channel(self):
        d=self.make();d.action(dict(action='ramp',channel=3,voltage=.01,speed=.001))
        self.assertEqual(d.dac.calls,[('initialize',3),('ramp',3,.01,.001)])
    def test_failed_prepare_never_sends_output_command(self):
        d=self.make()
        def fail(ch):raise CommandError('Cannot initialize')
        d.dac.initialize=fail
        with self.assertRaises(CommandError):d.action(dict(action='set',channel=1,voltage=1))
        self.assertEqual(d.dac.calls,[])
    def test_invalid_ramp_cannot_initialize_a_cold_output(self):
        d=self.make()
        with self.assertRaises(ValueError):d.action(dict(action='ramp',channel=1,voltage=0,speed=1e-300))
        self.assertEqual(d.dac.calls,[])
    def test_busy_commands_cannot_be_queued_for_later(self):
        d=self.make();d.state['ramp']['state']='RUNNING'
        with self.assertRaises(ValueError):d.submit(dict(action='set',request_id='x',channel=1,voltage=0))
        d.submit(dict(action='abort',request_id='stop'))
        self.assertEqual(d.commands.qsize(),1)
    def test_disconnect_stays_disconnected_and_values_age(self):
        d=self.make();d.poll_dac();before=d.snapshot()['channels'][0]['at']
        d.action(dict(action='disconnect'));d.poll_dac()
        self.assertFalse(d.want_connection);self.assertEqual(d.dac.calls,['connect','disconnect'])
        self.assertEqual(d.snapshot()['channels'][0]['at'],before)
        self.assertEqual(d.snapshot()['network']['state'],'disconnected')
    def test_bad_dac_data_does_not_falsely_report_network_down(self):
        d=self.make();d.dac.bad=True;d.poll_dac();s=d.snapshot()
        self.assertEqual(s['network']['state'],'good');self.assertIn('invalid readback',s['device_error'])
        self.assertIsNone(s['channels'][0]['voltage'])


if __name__=='__main__':unittest.main()
