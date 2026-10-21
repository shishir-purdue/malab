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
from malab.instruments.resistive_load import (endpoint_key,
    current_to_voltage, current_rate_to_voltage, voltage_to_current)


class Dashboard:
    def __init__(self, addresses, *, bench_ports=None, meter_address=None,
                 meter_channel=1, dac_factory=AD5780, meter_factory=Keysight34461A,
                 resistor_store=None,label_store=None):
        if meter_address is None:
            from malab.bench_config import load_bench_config
            meter_address=load_bench_config()['meter']['address']
        self.array=DACArray(addresses,bench_ports=bench_ports,timeout=1,dac_factory=dac_factory,
                            resistor_store=resistor_store,label_store=label_store)
        self.array.locate(meter_channel)
        self.meter_channel=meter_channel
        self.units=[UnitController(address=a,usb=p,dac=d,resistor_store=self.array._resistor_store) for a,p,d in
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
        if action in ('set','ramp','set_current','ramp_current','resistor','label'):
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
            if action=='label':
                if 'label' not in data:raise ValueError('Supply label text, or an empty string to clear it')
                try:label=self.array.set_label(data['channel'],data['label'])
                except OSError as exc:raise ValueError('Could not save the local label; output unchanged') from exc
                result=dict(id=request_id,action=action,state='complete',at=time.time(),
                            finished=time.time(),error=None,label=label,channel=data['channel'])
                with controller.lock:controller.jobs[request_id]=result
                controller.event(f'DAC {location.local_channel}: label '+(f'saved: {label}' if label else 'cleared'))
            elif action=='resistor':
                if 'resistance_ohms' not in data:
                    raise ValueError('Supply resistance_ohms, or null to remove the resistor')
                with controller.lock:
                    if (controller.state['pending'] or controller.state['ramp']['state']=='RUNNING'
                            or controller.state['recovery']['state']=='ACTIVE'):
                        raise ValueError('Wait until this unit is idle before changing resistance')
                    ohms=data['resistance_ohms']
                    try:
                        if ohms is None:self.array.remove_resistor(data['channel'])
                        else:self.array.add_resistor(data['channel'],ohms)
                    except OSError as exc:
                        raise ValueError('Could not save local resistor settings; output unchanged') from exc
                    result=dict(id=request_id,action=action,state='complete',at=time.time(),
                                finished=time.time(),error=None)
                    controller.jobs[request_id]=result
                    controller.event(f"DAC {location.local_channel}: resistor " +
                        ('removed; voltage mode' if ohms is None else f'{ohms:g} ohms saved; calculated mA mode'))
            else:
                if action in ('set','ramp','set_current','ramp_current'):
                    ohms=self.array.get_resistance(data['channel'])
                    local['expected_resistance_ohms']=ohms
                    if action in ('set_current','ramp_current'):
                        if ohms is None or type(data.get('resistance_ohms')) not in (int,float) or data['resistance_ohms']!=ohms:
                            raise ValueError('Resistance changed or is missing; refresh and review the current target')
                        local['action']='set' if action=='set_current' else 'ramp'
                        local['display_action']=action
                        local['voltage']=current_to_voltage(data.get('current_mA'),ohms)
                        if action=='ramp_current':
                            local['speed']=current_rate_to_voltage(data.get('speed_mA_s'),ohms)
                    elif ohms is not None:
                        raise ValueError('This channel is in current mode; refresh and use current in mA')
                result=controller.submit(local)
                if action in ('set_current','ramp_current'):
                    with controller.lock:controller.jobs[request_id]['action']=action
                    result['action']=action
            self.routes[request_id]=(unit,signature)
            return dict(result,unit=unit)

    def snapshot(self,include_history=True):
        now=time.time();units=[];channels=[];jobs={};events=[]
        settings=self.array._resistor_store.snapshot()
        labels=self.array._label_store.snapshot()
        for index,controller in enumerate(self.units):
            unit=index+1;s=controller.snapshot()
            rows=[dict(c,channel=index*4+c['channel'],local_channel=c['channel'],unit=unit) for c in s['channels']]
            for row in rows:
                ohms=settings.get(endpoint_key(self.array.addresses[index]),{}).get(str(row['local_channel']))
                row.update(label=labels.get(endpoint_key(self.array.addresses[index]),{}).get(str(row['local_channel']),''),
                    resistance_ohms=ohms,
                    current_mA=voltage_to_current(row['voltage'],ohms) if ohms is not None else None,
                    current_limits_mA=[voltage_to_current(v,ohms) for v in row['limits']] if ohms is not None and row['limits'] else None)
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
        ohms=channels[self.meter_channel-1]['resistance_ohms']
        meter.update(resistance_ohms=ohms,
                     current_mA=voltage_to_current(meter['voltage'],ohms) if ohms is not None else None)
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
            meter_fresh=m['state']=='good' and m['at'] and now-m['at']<2.5
            with self.lock:self.history.append(dict(at=now,channels=values,
                currents=[c['current_mA'] if v is not None else None for c,v in zip(s['channels'],values)],
                resistances=[c['resistance_ohms'] for c in s['channels']],
                meter=m['voltage'] if meter_fresh else None,
                meter_current=m['current_mA'] if meter_fresh else None))
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
