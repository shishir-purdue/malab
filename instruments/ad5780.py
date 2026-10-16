"""Four-channel DAC Box client; requires RAMP ACCEPTED / STATUS firmware.

Construction consumes the welcome banner but never initializes or sets a DAC.
Nominal voltage conversion assumes +/-10 V DAC references, not supply-rail voltage.
"""
from dataclasses import dataclass
import math
from numbers import Real
import operator
import time

from ._line_socket import (LineSocketInstrument, CommandError, ProtocolError,
                          InstrumentTimeout, positive_seconds)

V_PER_BIT = 20.0 / (1 << 18)
MAX_CODE = (1 << 18) - 1


def integer(value, minimum, maximum, name):
    if isinstance(value, bool):
        raise ValueError(f"{name} must be an integer, not bool")
    try:
        value = operator.index(value)
    except TypeError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be {minimum}..{maximum}")
    return value


def voltage_to_code(voltage):
    if isinstance(voltage, bool) or not isinstance(voltage, Real) or not math.isfinite(voltage) or not -10 <= voltage <= 10:
        raise ValueError("voltage must be finite and between -10 and +10 V")
    return min(MAX_CODE, int(math.floor((voltage + 10) / V_PER_BIT + 0.5)))


def code_to_voltage(code):
    return integer(code, 0, MAX_CODE, "code") * V_PER_BIT - 10


@dataclass(frozen=True)
class RampStatus:
    state: str
    channel: int
    target_code: int


@dataclass(frozen=True)
class ChannelCalibration:
    offset_nanovolts: int
    step_picovolts: int
    zero_code: int
    measured: bool

    @property
    def volts_per_code(self):
        if (self.offset_nanovolts, self.step_picovolts, self.zero_code, self.measured) == (-10000000000, 76293945, 131072, False):
            return V_PER_BIT
        return self.step_picovolts * 1e-12

    def voltage(self, code):
        return self.offset_nanovolts * 1e-9 + integer(code, 0, MAX_CODE, "code") * self.volts_per_code

    def code(self, voltage):
        voltage_to_code(voltage)  # Common finite/nominal +/-10 V validation.
        raw = (voltage-self.offset_nanovolts*1e-9)/self.volts_per_code
        # A nominal +10 V convention can be one LSB above full scale. Larger
        # excursions (e.g. calibrated -10 V on this box) must never clamp silently.
        if raw < -1.000001 or raw > MAX_CODE+1.000001:
            raise ValueError(f"Requested voltage is outside this channel's achievable range "
                             f"[{self.voltage(0):.9f}, {self.voltage(MAX_CODE):.9f}] V")
        return min(MAX_CODE, max(0, int(math.floor(raw+0.5))))


class AD5780(LineSocketInstrument):
    default_port = 23

    def __init__(self, name="AD5780", address="192.168.1.200", enabled=True, timeout=3.0, recv_length=1024,
                 *, use_calibration=True):
        # Retained from the lab's supplied voltsource.py constructor.
        # Newline framing, not a single recv size, determines complete replies.
        self.recv_length = integer(recv_length, 1, 65536, "recv_length")
        if not isinstance(use_calibration, bool):
            raise ValueError("use_calibration must be bool")
        self.use_calibration = use_calibration
        self._calibration = {}
        super().__init__(name, address, enabled, timeout)

    def _handshake(self):
        self._calibration.clear()
        first = self.read()
        if first.startswith("ERR!"):
            raise CommandError(first)
        second = self.read()
        if first != "Welcome to the Telnet server!" or second != "Type HELP for instructions.":
            raise ProtocolError(f"Unexpected DAC welcome: {first!r}, {second!r}")

    def query(self, command, timeout=None):
        if len(self._encode(command)) > 128:
            raise ValueError("DAC command exceeds its 127-byte input limit")
        if command.split()[0] == "HELP":
            raise ValueError("HELP is multiline; use the documented typed API instead")
        reply = super().query(command, timeout)
        if reply.startswith("ERR!"):
            raise CommandError(reply)
        if reply.startswith("#Help:"):
            self._protocol_error("Unexpected multiline HELP response; connection closed to prevent reply misalignment")
        return reply

    def _protocol_error(self, message):
        self.close()
        raise ProtocolError(message)

    def get_id(self):
        reply = self.query("ID")
        if reply != "AD5780":
            self._protocol_error(f"Unexpected device ID: {reply!r}")
        return reply

    def initialize(self, channel=None):
        command = "INIT" if channel is None else f"INIT {integer(channel, 1, 4, 'channel')}"
        reply = self.query(command)
        if not reply.startswith("Initialized ") or not reply.endswith("; active outputs preserved."):
            self._protocol_error(f"Unexpected INIT reply: {reply!r}")
        return reply

    init = initialize

    def get_code(self, channel):
        channel = integer(channel, 1, 4, "channel")
        reply = self.query(f"READ {channel}")
        if not reply.isdecimal() or not 0 <= int(reply) <= MAX_CODE:
            self._protocol_error(f"Invalid DAC readback: {reply!r}")
        return int(reply)

    def get_voltage(self, channel):
        """Calibrated register-derived volts; use a meter for an independent reading."""
        code = self.get_code(channel)
        return self.code_to_voltage(channel, code)

    def get_calibration(self, channel, *, refresh=False):
        channel = integer(channel, 1, 4, "channel")
        if not self.use_calibration:
            return ChannelCalibration(-10000000000, 76293945, 131072, False)
        if refresh or channel not in self._calibration:
            reply = self.query(f"CAL {channel}")
            try:
                label, ch, offset, step, zero, measured = reply.split()
                ch, offset, step, zero, measured = map(int, (ch,offset,step,zero,measured))
                if (label != "CAL" or ch != channel or measured not in (0,1)
                        or not -12_000_000_000 <= offset <= -8_000_000_000
                        or not 60_000_000 <= step <= 100_000_000
                        or not 0 <= zero <= MAX_CODE):
                    raise ValueError("invalid calibration fields")
                cal = ChannelCalibration(offset, step, zero, bool(measured))
                if abs(cal.voltage(zero)) > cal.volts_per_code:
                    raise ValueError("zero code inconsistent with calibration")
            except (ValueError, TypeError):
                self._protocol_error(f"Invalid device calibration: {reply!r}")
            self._calibration[channel] = cal
        return self._calibration[channel]

    def get_voltage_limits(self, channel):
        cal = self.get_calibration(channel)
        return max(-10.0, cal.voltage(0)), min(10.0, cal.voltage(MAX_CODE))

    def voltage_to_code(self, channel, voltage):
        voltage_to_code(voltage)  # Reject invalid requests before any CAL query.
        return self.get_calibration(channel).code(voltage)

    def code_to_voltage(self, channel, code):
        integer(code, 0, MAX_CODE, "code")
        return self.get_calibration(channel).voltage(code)

    def set_code(self, channel, code):
        channel, code = integer(channel, 1, 4, "channel"), integer(code, 0, MAX_CODE, "code")
        reply = self.query(f"SET {channel} {code}")
        if reply != f"SET command received with parameters: {channel} {code}":
            self._protocol_error(f"SET outcome uncertain; unexpected reply: {reply!r}")
        return code

    def set_voltage(self, channel, voltage):
        code = self.set_code(channel, self.voltage_to_code(channel, voltage))
        return self.code_to_voltage(channel, code)

    def get_status(self, timeout=None):
        reply = self.query("STATUS", timeout)
        parts = reply.split()
        if len(parts) != 4 or parts[0] != "RAMP" or parts[1] not in {"IDLE", "RUNNING", "COMPLETE", "ABORTED", "FAILED"}:
            self._protocol_error(f"Malformed ramp status: {reply!r}")
        try:
            channel, target = int(parts[2]), int(parts[3])
            integer(channel, 0 if parts[1] == "IDLE" else 1, 4, "channel")
            integer(target, 0, MAX_CODE, "target")
        except ValueError:
            self._protocol_error(f"Malformed ramp status fields: {reply!r}")
        return RampStatus(parts[1], channel, target)

    def ramp(self, channel, voltage, speed, *, step_size=10, wait=True, timeout=3600, poll_interval=0.1):
        """Ramp at nominal V/s. Device timing/transport overhead can make it slower.

        Overall completion timeout leaves the connection/ramp intact; a transport
        timeout closes the connection. Neither case retries the output command.
        """
        channel = integer(channel, 1, 4, "channel")
        voltage_to_code(voltage)
        step_size = integer(step_size, 1, MAX_CODE, "step_size")
        speed = positive_seconds(speed, "speed in V/s")
        timeout = positive_seconds(timeout)
        poll_interval = positive_seconds(poll_interval, "poll_interval")
        # Reject impossibly slow rates before any calibration/network query.
        if step_size * V_PER_BIT / speed * 1_000_000 > 2147483647:
            raise ValueError("Requested speed is too slow for the device delay range")
        cal = self.get_calibration(channel)
        target = cal.code(voltage)
        raw_delay = step_size * cal.volts_per_code / speed * 1_000_000
        if not math.isfinite(raw_delay) or raw_delay > 2147483647:
            raise ValueError("Requested speed is too slow for the device delay range")
        delay = max(1, math.ceil(raw_delay))
        deadline = time.monotonic() + timeout
        reply = self.query(f"RAMP {channel} {target} {step_size} {delay}", min(self.timeout, timeout))
        if reply != f"RAMP ACCEPTED {channel} {target} {step_size} {delay}":
            self._protocol_error(f"Ramp acceptance unknown: {reply!r}")
        if not wait:
            return RampStatus("ACCEPTED", channel, target)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise InstrumentTimeout("Ramp completion deadline expired; ramp may still run. Close connection deliberately to abort.")
            status = self.get_status(min(self.timeout, remaining))
            if (status.channel, status.target_code) != (channel, target):
                raise CommandError(f"Ramp ownership changed: {status}")
            if status.state == "COMPLETE":
                return status
            if status.state != "RUNNING":
                raise CommandError(f"Ramp did not complete: {status.state}")
            time.sleep(min(poll_interval, max(0, deadline-time.monotonic())))

    def abort_ramp(self):
        """Close this client's socket; firmware aborts when it detects disconnect."""
        self.close()
