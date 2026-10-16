"""A fixed, ordered collection of four-channel DAC boxes; no firmware changes."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import ipaddress
import threading
from .ad5780 import AD5780, integer
from ._line_socket import InstrumentError


@dataclass(frozen=True)
class ChannelLocation:
    channel: int
    unit: int
    local_channel: int
    address: str


@dataclass(frozen=True)
class UnitResult:
    unit: int
    address: str
    ok: bool
    value: object = None
    error: str = None


class UnitOperationError(InstrumentError):
    def __init__(self, unit, address, operation, cause):
        self.unit, self.address, self.operation, self.cause = unit, address, operation, cause
        super().__init__(f'Unit {unit} ({address}), {operation}: {cause}')


def normalize_addresses(addresses):
    if not isinstance(addresses, (list, tuple)) or not addresses:
        raise ValueError('addresses must be a nonempty ordered list of IPv4 addresses')
    result=[]
    for address in addresses:
        if not isinstance(address,str):raise ValueError('Each address must be a string')
        host,sep,port=address.strip().partition(':')
        try:
            host=str(ipaddress.IPv4Address(host))
            number=int(port) if sep else 23
            if not 1<=number<=65535:raise ValueError()
        except ValueError as exc:raise ValueError(f'Invalid DAC IPv4 address/port: {address!r}') from exc
        result.append(host if number==23 else f'{host}:{number}')
    if len(set(result))!=len(result):raise ValueError('Duplicate DAC addresses would alias the same four outputs')
    return tuple(result)


class DACArray:
    """Global channels 1..4N, in immutable IP-list order.

    Construction is disconnected by default. connect() returns an explicit
    per-unit result; an offline unit never renumbers or blocks the other units.
    Channel methods address one output. Recovery methods require a *unit* number
    and affect exactly that box's four outputs. There is no output-command retry.
    """
    def __init__(self, addresses, *, bench_ports=None, enabled=False, timeout=3,
                 dac_factory=AD5780):
        self.addresses=normalize_addresses(addresses)
        ports=[None]*len(self.addresses) if bench_ports is None else bench_ports
        if not isinstance(ports,(list,tuple)) or len(ports)!=len(self.addresses):
            raise ValueError('bench_ports must have one port or None per IP, in the same order')
        if any(p is not None and (not isinstance(p,str) or not p.strip()) for p in ports):
            raise ValueError('Each USB port must be a nonempty string or None')
        normalized=[p.strip().upper() for p in ports if p is not None]
        if len(set(normalized))!=len(normalized):raise ValueError('A USB port cannot belong to two DAC units')
        self.bench_ports=tuple(p.strip() if p is not None else None for p in ports)
        self.devices=tuple(dac_factory(address=a,enabled=False,timeout=timeout,bench_port=p)
                           for a,p in zip(self.addresses,self.bench_ports))
        self._locks=tuple(threading.RLock() for _ in self.devices)
        self._recovery_locks=tuple(threading.RLock() for _ in self.devices)
        self.connection_results=self.connect() if enabled else {}

    @property
    def channel_count(self):return 4*len(self.devices)
    @property
    def unit_count(self):return len(self.devices)

    def unit_index(self,unit):return integer(unit,1,self.unit_count,'unit')-1

    def locate(self,channel):
        channel=integer(channel,1,self.channel_count,'channel')
        index,local=divmod(channel-1,4)
        return ChannelLocation(channel,index+1,local+1,self.addresses[index])

    def _call(self,unit,method,*args,recovery=False,**kwargs):
        index=self.unit_index(unit)
        # USB recovery can interrupt a caller waiting for ramp completion.
        lock=(self._recovery_locks if recovery else self._locks)[index]
        with lock:
            try:return getattr(self.devices[index],method)(*args,**kwargs)
            except (InstrumentError,OSError) as exc:
                raise UnitOperationError(unit,self.addresses[index],method,exc) from exc

    def _channel(self,channel,method,*args,**kwargs):
        location=self.locate(channel)
        return self._call(location.unit,method,location.local_channel,*args,**kwargs)

    def _all(self,function):
        def run(unit):
            try:return UnitResult(unit,self.addresses[unit-1],True,function(unit))
            except Exception as exc:return UnitResult(unit,self.addresses[unit-1],False,error=str(exc))
        with ThreadPoolExecutor(max_workers=self.unit_count) as pool:
            return dict(zip(range(1,self.unit_count+1),pool.map(run,range(1,self.unit_count+1))))

    def connect(self, *, unit=None):
        if unit is None:return self._all(lambda u:self.connect(unit=u))
        index=self.unit_index(unit);self.devices[index].enabled=True
        self._call(unit,'connect')
        return True

    def disconnect(self, *, unit=None):
        if unit is None:return self._all(lambda u:self.disconnect(unit=u))
        return self._call(unit,'disconnect',recovery=True)

    def close(self):return self._all(lambda u:self._call(u,'close',recovery=True))
    def get_id(self, *, unit):return self._call(unit,'get_id')
    def initialize(self,channel):return self._channel(channel,'initialize')
    def initialize_unit(self, *, unit):return self._call(unit,'initialize')
    def set_voltage(self,channel,voltage):return self._channel(channel,'set_voltage',voltage)
    def get_voltage(self,channel):return self._channel(channel,'get_voltage')
    def set_code(self,channel,code):return self._channel(channel,'set_code',code)
    def get_code(self,channel):return self._channel(channel,'get_code')
    def get_calibration(self,channel,**kwargs):return self._channel(channel,'get_calibration',**kwargs)
    def get_voltage_limits(self,channel):return self._channel(channel,'get_voltage_limits')
    def voltage_to_code(self,channel,voltage):return self._channel(channel,'voltage_to_code',voltage)
    def code_to_voltage(self,channel,code):return self._channel(channel,'code_to_voltage',code)

    def ramp(self,channel,voltage,speed,**kwargs):
        location=self.locate(channel)
        result=self._call(location.unit,'ramp',location.local_channel,voltage,speed,**kwargs)
        return self._status(location.unit,result)

    def _status(self,unit,status):
        return dict(unit=unit,address=self.addresses[unit-1],state=status.state,
                    channel=4*(unit-1)+status.channel if status.channel else 0,
                    local_channel=status.channel,target_code=status.target_code)

    def get_status(self, *, unit):return self._status(unit,self._call(unit,'get_status'))
    def get_output_codes(self, *, unit, via_usb=False):
        values=self._call(unit,'get_output_codes',via_usb=via_usb,recovery=via_usb)
        return [dict(v,unit=unit,local_channel=v['channel'],channel=4*(unit-1)+v['channel']) for v in values]
    def abort_ramp(self, *, unit):return self._call(unit,'abort_ramp',recovery=True)
    def network_reset(self, *, unit, **kwargs):return self._call(unit,'network_reset',recovery=True,**kwargs)
    def safe_zero(self, *, unit, **kwargs):return self._call(unit,'safe_zero',recovery=True,**kwargs)
    def get_recovery_status(self, *, unit):return self._call(unit,'get_recovery_status',recovery=True)
    def safe_zero_all(self, **kwargs):
        """Explicit broadcast with per-unit results; failed units are never hidden."""
        return self._all(lambda u:self.safe_zero(unit=u,**kwargs))
    def __enter__(self):return self
    def __exit__(self,*exc):self.close()
