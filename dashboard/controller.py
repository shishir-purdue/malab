"""Independent unit workers, a fixed global channel map, and one meter sampler."""
import copy
import json
import os
import threading
import time
from collections import deque
from malab.instruments.voltsource import DACArray, AD5780
from malab.instruments import Keysight34461A
from .unit import UnitController


class Dashboard:
    def __init__(self, addresses, *, bench_ports=None, meter_address=None,
                 meter_channel=1, dac_factory=AD5780, meter_factory=Keysight34461A):
        if meter_address is None:
            from malab.bench_config import load_bench_config
            meter_address=load_bench_config()['meter']['address']
        self.array=DACArray(addresses,bench_ports=bench_ports,timeout=1,dac_factory=dac_factory)
        self.array.locate(meter_channel)
        self.meter_channel=meter_channel
        self.units=[UnitController(address=a,usb=p,dac=d) for a,p,d in
                    zip(self.array.addresses,self.array.bench_ports,self.array.devices)]
        self.lock=threading.RLock();self.stop=threading.Event();self.threads=[]
        self.routes={};self.history=deque(maxlen=240)
        self.server_started=time.time()
        self.meter_address=meter_address;self.meter_factory=meter_factory
        self.meter=dict(state='connecting',address=meter_address,channel=meter_channel,
                        voltage=None,at=None,error=None)

    def start(self):
        for unit in self.units:unit.start()
        for function in (self.meter_loop,self.history_loop):
            t=threading.Thread(target=function,daemon=True);self.threads.append(t);t.start()

    def submit(self,data):
        if not isinstance(data,dict):raise ValueError('Command must be an object')
        action=data.get('action');local=dict(data)
        if action in ('set','ramp'):
            location=self.array.locate(data.get('channel'))
            unit=location.unit
            if 'unit' in data and self.array.unit_index(data['unit'])!=unit-1:
                raise ValueError('Unit and global channel do not match')
            local['channel']=location.local_channel
        else:
            unit=self.array.unit_index(data.get('unit'))+1
        controller=self.units[unit-1]
        if action in ('network','safe_zero') and not controller.dac.bench_port:
            raise ValueError(f'Unit {unit} has no USB recovery port; use its physical button')
        request_id=data.get('request_id')
        if not isinstance(request_id,str) or not 1<=len(request_id)<=80:
            raise ValueError('A request ID is required')
        signature=json.dumps(data,sort_keys=True,allow_nan=False)
        with self.lock:
            if request_id in self.routes:
                old_unit,old_signature=self.routes[request_id]
                if (unit,signature)!=(old_unit,old_signature):
                    raise ValueError('Request ID already belongs to a different action or unit')
                return dict(controller.jobs[request_id],unit=unit)
            if len(self.routes)>=10000:raise ValueError('Session command log is full; restart the dashboard')
            result=controller.submit(local)
            self.routes[request_id]=(unit,signature)
            return dict(result,unit=unit)

    def snapshot(self,include_history=True):
        now=time.time();units=[];channels=[];jobs={};events=[]
        for index,controller in enumerate(self.units):
            unit=index+1;s=controller.snapshot()
            rows=[dict(c,channel=index*4+c['channel'],local_channel=c['channel'],unit=unit) for c in s['channels']]
            channels.extend(rows)
            ramp=dict(s['ramp'],local_channel=s['ramp']['channel'],
                      channel=index*4+s['ramp']['channel'] if s['ramp']['channel'] else 0)
            units.append(dict(unit=unit,address=self.array.addresses[index],first_channel=index*4+1,
                last_channel=index*4+4,usb_port=self.array.bench_ports[index],network=s['network'],
                recovery=s['recovery'],ramp=ramp,pending=s['pending'],device_error=s['device_error']))
            jobs.update({key:dict(job,unit=unit) for key,job in s['jobs'].items()})
            events.extend(dict(e,unit=unit) for e in s['events'])
        with self.lock:
            meter=copy.deepcopy(self.meter)
            history=list(self.history) if include_history else []
        return dict(now=now,server_started=self.server_started,server_pid=os.getpid(),units=units,channels=channels,
                    meter=meter,history=history,events=sorted(events,key=lambda e:e['at'],reverse=True)[:80],
                    jobs=jobs,channel_count=self.array.channel_count)

    def history_loop(self):
        while not self.stop.is_set():
            s=self.snapshot(False);now=s['now'];values=[]
            for c in s['channels']:
                u=s['units'][c['unit']-1]
                reachable=(u['network']['state']=='good' and u['network']['last_ok'] is not None and now-u['network']['last_ok']<2.5)
                reachable=reachable or u['recovery']['state'] in ('ACTIVE','LATCHED')
                values.append(c['voltage'] if reachable and c['at'] and now-c['at']<2.5 else None)
            m=s['meter']
            with self.lock:self.history.append(dict(at=now,channels=values,
                meter=m['voltage'] if m['state']=='good' and m['at'] and now-m['at']<2.5 else None))
            self.stop.wait(.25)

    def meter_loop(self):
        meter=None
        while not self.stop.is_set():
            try:
                if meter is None:
                    meter=self.meter_factory(address=self.meter_address,timeout=2)
                    meter.configure_dc_voltage(10,nplc=1)
                voltage=meter.read_voltage()
                with self.lock:self.meter.update(state='good',voltage=voltage,at=time.time(),error=None)
                self.stop.wait(.1)
            except Exception as exc:
                if meter:meter.close()
                meter=None
                with self.lock:self.meter.update(state='failed',error=str(exc))
                self.stop.wait(2)
        if meter:meter.close()

    def close(self):
        self.stop.set()
        for unit in self.units:unit.stop.set()
        for unit in self.units:unit.close()
        for thread in self.threads:thread.join(timeout=7)
