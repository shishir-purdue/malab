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


class AD5780(LineSocketInstrument):
    default_port = 23

    def __init__(self, name="AD5780", address="192.168.1.200", enabled=True, timeout=3.0, recv_length=1024):
        # Retained from the lab's supplied voltsource.py constructor.
        # Newline framing, not a single recv size, determines complete replies.
        self.recv_length = integer(recv_length, 1, 65536, "recv_length")
        super().__init__(name, address, enabled, timeout)

    def _handshake(self):
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
        """Nominal register-derived voltage; use the DMM for an analog measurement."""
        return code_to_voltage(self.get_code(channel))

    def set_code(self, channel, code):
        channel, code = integer(channel, 1, 4, "channel"), integer(code, 0, MAX_CODE, "code")
        reply = self.query(f"SET {channel} {code}")
        if reply != f"SET command received with parameters: {channel} {code}":
            self._protocol_error(f"SET outcome uncertain; unexpected reply: {reply!r}")
        return code

    def set_voltage(self, channel, voltage):
        return code_to_voltage(self.set_code(channel, voltage_to_code(voltage)))

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
        target = voltage_to_code(voltage)
        step_size = integer(step_size, 1, MAX_CODE, "step_size")
        speed = positive_seconds(speed, "speed in V/s")
        timeout = positive_seconds(timeout)
        poll_interval = positive_seconds(poll_interval, "poll_interval")
        raw_delay = step_size * V_PER_BIT / speed * 1_000_000
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
