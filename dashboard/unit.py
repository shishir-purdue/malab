"""One independently polled four-channel unit; no global channel indexing."""
import copy
import math
import queue
import threading
import time
from collections import deque

from malab.instruments.voltsource import AD5780
from malab.instruments._line_socket import CommandError


class UnitController:
    def __init__(self, address='192.168.1.200', usb='COM5', dac_factory=AD5780, dac=None):
        self.lock=threading.RLock()
        self.stop=threading.Event()
        self.commands=queue.Queue(maxsize=1)
        self.dac=dac if dac is not None else dac_factory(address=address,enabled=False,timeout=1,bench_port=usb)
        self.want_connection=True
        self.profiles={}
        self.retry_at=0
        self.usb_at=0
        self.last_recovery=None
        self.events=deque(maxlen=50)
        self.jobs={}
        self.threads=[]
        self.state=dict(network=dict(state='connecting',address=address,last_ok=None,latency_ms=None,error=None),
            recovery=dict(state='unknown' if self.dac.bench_port else 'unsupported',at=None,error=None),
            channels=[dict(channel=i,voltage=None,code=None,source='unknown',at=None,calibrated=False,limits=None) for i in range(1,5)],
            ramp=dict(state='IDLE',channel=0,target_code=0),pending=None,device_error=None,server_started=time.time())

    def start(self):
        for function in (self.dac_loop,):
            t=threading.Thread(target=function,daemon=True);self.threads.append(t);t.start()

    def event(self,message,level='info'):
        with self.lock:self.events.appendleft(dict(at=time.time(),message=message,level=level))

    def snapshot(self):
        with self.lock:
            result=copy.deepcopy(self.state)
            result['now']=time.time();result['events']=list(self.events)
            result['jobs']=dict(list(self.jobs.items())[-64:])
        return result

    def submit(self,data):
        if not isinstance(data,dict):raise ValueError('Command must be an object')
        action=data.get('action');request_id=data.get('request_id')
        if action not in {'connect','disconnect','initialize','set','ramp','abort','network','safe_zero'}:
            raise ValueError('Unknown action')
        if not isinstance(request_id,str) or not 1<=len(request_id)<=80:raise ValueError('A request ID is required')
        if action in {'set','ramp'}:
            if type(data.get('channel')) is not int or not 1<=data['channel']<=4:raise ValueError('Choose channel 1–4')
            if type(data.get('voltage')) not in (int,float) or not math.isfinite(data['voltage']) or not -10<=data['voltage']<=10:
                raise ValueError('Voltage must be finite and within −10 to +10 V')
        if action=='ramp':
            if type(data.get('speed')) not in (int,float) or not math.isfinite(data['speed']) or data['speed']<=0:
                raise ValueError('Ramp speed must be a positive number in V/s')
            if type(data.get('step_size',10)) is not int or not 1<=data.get('step_size',10)<=262143:
                raise ValueError('Step size must be an integer from 1 to 262143')
        with self.lock:
            if request_id in self.jobs:return self.jobs[request_id]
            if len(self.jobs)>=10000:raise ValueError('Session command log is full; restart the local dashboard')
            if self.state['pending']:raise ValueError('Another action is pending; wait for its result')
            if action in {'set','ramp','initialize'}:
                network=self.state['network']
                if network['state']!='good' or network['last_ok'] is None or time.time()-network['last_ok']>2.5:
                    raise ValueError('This unit has no fresh network response; output action was not queued')
                if self.state['recovery']['state'] in ('ACTIVE','LATCHED','FAILED'):
                    raise ValueError('This unit is in safe-zero recovery; use NETWORK to rearm')
            if action in {'set','ramp','initialize'} and self.state['ramp']['state']=='RUNNING':
                raise ValueError('A ramp is running. Stop it before changing an output.')
            job=dict(id=request_id,action=action,state='pending',at=time.time())
            self.jobs[request_id]=job;self.state['pending']=request_id
            # Keep IDs for this server lifetime: a retry cannot replay an output command.
            self.commands.put_nowait(dict(data))
            return dict(job)

    def complete(self,data,error=None):
        with self.lock:
            self.jobs[data['request_id']].update(state='failed' if error else 'complete',error=error,finished=time.time())
            self.state['pending']=None
        label=data['action'].replace('_',' ').upper()
        self.event(f'{label}: {error}' if error else f'{label} accepted', 'error' if error else 'info')

    def refresh_profiles(self):
        self.profiles={ch:self.dac.get_calibration(ch) for ch in range(1,5)}
        with self.lock:
            for ch in self.state['channels']:
                profile=self.profiles[ch['channel']]
                ch['calibrated']=profile.measured
                ch['limits']=[max(-10,profile.voltage(0)),min(10,profile.voltage(262143))]
                ch['calibration']=dict(offset_nanovolts=profile.offset_nanovolts,
                    step_picovolts=profile.step_picovolts,zero_code=profile.zero_code,
                    volts_per_code=profile.volts_per_code)

    def apply_codes(self,codes):
        with self.lock:
            for item in codes:
                row=self.state['channels'][item['channel']-1];profile=self.profiles.get(item['channel'])
                row.update(code=item['code'],source=item['source'],at=time.time(),
                    voltage=profile.voltage(item['code']) if profile and item['code'] is not None else None)

    def action(self,data):
        action=data['action']
        if action=='connect':
            self.want_connection=True;self.retry_at=0
            with self.lock:self.state['network'].update(state='connecting',error=None)
        elif action=='disconnect':
            self.want_connection=False;self.dac.disconnect()
            with self.lock:
                self.state['network'].update(state='disconnected',error=None)
                self.state['ramp']['state']='UNKNOWN'
        elif action=='initialize':self.dac.initialize()
        elif action=='set':
            # Connecting is read-only. An explicit output command prepares only
            # its channel; INIT preserves an already active output and releases
            # a cold channel from its startup clamp at calibrated zero.
            self.dac.voltage_to_code(data['channel'],data['voltage'])
            self.dac.initialize(data['channel'])
            self.dac.set_voltage(data['channel'],data['voltage'])
        elif action=='ramp':
            self.dac.voltage_to_code(data['channel'],data['voltage'])
            profile=self.dac.get_calibration(data['channel'])
            delay=data.get('step_size',10)*profile.volts_per_code/data['speed']*1e6
            if not math.isfinite(delay) or delay>2147483647:
                raise ValueError('Requested speed is too slow for the device delay range')
            self.dac.initialize(data['channel'])
            r=self.dac.ramp(data['channel'],data['voltage'],data['speed'],step_size=data.get('step_size',10),wait=False)
            with self.lock:self.state['ramp']=dict(state='RUNNING',channel=r.channel,target_code=r.target_code)
        elif action=='abort':
            self.dac.abort_ramp();self.want_connection=True;self.retry_at=time.monotonic()+0.2
            with self.lock:
                self.state['network'].update(state='connecting',error=None)
                self.state['ramp']['state']='STOPPING'
        elif action=='network':
            self.dac.network_reset();self.want_connection=True;self.retry_at=time.monotonic()+0.3
            self.last_recovery='READY'
            with self.lock:self.state['network'].update(state='connecting',error=None)
        elif action=='safe_zero':
            self.dac.safe_zero();self.want_connection=False
            self.last_recovery='ACTIVE'
            with self.lock:
                self.state['network'].update(state='suspended',error=None)
                self.state['recovery'].update(state='ACTIVE',at=time.time(),error=None)
                self.state['ramp']['state']='ABORTED'

    def poll_usb(self):
        if not self.dac.bench_port or time.monotonic()<self.usb_at:return
        self.usb_at=time.monotonic()+0.5
        try:
            recovery=self.dac.get_recovery_status()
            old=self.last_recovery;self.last_recovery=recovery
            with self.lock:self.state['recovery'].update(state=recovery,at=time.time(),error=None)
            if recovery in ('ACTIVE','LATCHED','FAILED'):
                self.want_connection=False
                if self.dac.connected:self.dac.abort_ramp()
                with self.lock:self.state['network'].update(state='suspended',error=None)
                self.apply_codes(self.dac.get_output_codes(via_usb=True))
            elif old in ('ACTIVE','LATCHED','FAILED','OFFLINE') and recovery=='READY':
                self.want_connection=True;self.retry_at=0
            if recovery!=old:self.event('Recovery: '+recovery)
        except Exception as exc:
            self.usb_at=time.monotonic()+5
            with self.lock:self.state['recovery'].update(state='unavailable',error=str(exc))

    def poll_dac(self):
        if not self.want_connection:return
        if not self.dac.connected:
            if time.monotonic()<self.retry_at:return
            self.retry_at=time.monotonic()+2
            with self.lock:self.state['network']['state']='connecting'
            self.dac.enabled=True;self.dac.connect()
            self.refresh_profiles();self.event('DAC connection established; outputs unchanged')
        started=time.monotonic()
        status=self.dac.get_status()
        with self.lock:self.state['ramp']=dict(state=status.state,channel=status.channel,target_code=status.target_code)
        if status.state!='RUNNING':
            errors=[]
            for channel in range(1,5):
                try:self.dac.get_code(channel)
                except CommandError as exc:errors.append(f'DAC {channel}: {exc}')
            with self.lock:self.state['device_error']='; '.join(errors) or None
        self.apply_codes(self.dac.get_output_codes())
        with self.lock:self.state['network'].update(state='good',last_ok=time.time(),latency_ms=round((time.monotonic()-started)*1000,1),error=None)

    def dac_loop(self):
        while not self.stop.is_set():
            try:data=self.commands.get(timeout=0.2)
            except queue.Empty:data=None
            if data:
                try:self.action(data)
                except Exception as exc:self.complete(data,str(exc))
                else:self.complete(data)
            self.poll_usb()
            try:self.poll_dac()
            except Exception as exc:
                self.dac.disconnect();self.retry_at=time.monotonic()+2
                with self.lock:
                    changed=self.state['network']['error']!=str(exc)
                    self.state['network'].update(state='failed',error=str(exc))
                if changed:self.event('DAC communication: '+str(exc),'error')
        self.dac.close()

    def close(self):
        self.stop.set()
        for thread in self.threads:thread.join(timeout=7)
