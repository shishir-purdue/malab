"""Keysight 34461A LAN SCPI driver, using port 5025 without VISA.

Reference: Keysight Truevolt Operating and Service Guide, SCPI programming.
https://www.keysight.com/us/en/assets/9018-03876/service-manuals/9018-03876.pdf
"""
import math
from ._line_socket import LineSocketInstrument, ProtocolError, CommandError


class Keysight34461A(LineSocketInstrument):
    def __init__(self, name="Keysight34461A", address=None, enabled=True, timeout=5.0):
        if address is None:
            from malab.bench_config import load_bench_config
            address=load_bench_config()['meter']['address']
        self._dc_configured = False
        super().__init__(name, address, enabled, timeout)

    def _handshake(self):
        self._dc_configured = False
        self.get_id()  # Identify only; no reset or measurement configuration.

    def get_id(self):
        reply = self.query("*IDN?")
        fields = reply.split(",")
        if len(fields) < 4 or fields[1].strip() != "34461A":
            raise ProtocolError(f"Expected a Keysight 34461A, received {reply!r}")
        return reply

    def get_configuration(self):
        return self.query("CONF?")

    def check_errors(self, limit=16):
        errors = []
        for _ in range(limit):
            reply = self.query("SYST:ERR?")
            try:
                number = int(reply.split(",", 1)[0])
            except ValueError as exc:
                raise ProtocolError(f"Invalid SCPI error response: {reply!r}") from exc
            if number == 0:
                if errors:
                    raise CommandError("Keysight SCPI errors: " + "; ".join(errors))
                return
            errors.append(reply)
        raise CommandError("Keysight error queue did not clear: " + "; ".join(errors))

    def configure_dc_voltage(self, voltage_range=10.0, nplc=1.0):
        if isinstance(voltage_range, bool) or voltage_range not in (0.1, 1, 10, 100, 1000):
            raise ValueError("voltage_range must be 0.1, 1, 10, 100, or 1000 V")
        if isinstance(nplc, bool) or nplc not in (0.02, 0.2, 1, 10, 100):
            raise ValueError("34461A NPLC must be 0.02, 0.2, 1, 10, or 100")
        self._dc_configured = False
        with self._lock:
            self.check_errors()  # Expose preexisting errors rather than clearing silently.
            for command in (f"CONF:VOLT:DC {voltage_range:g}", f"VOLT:DC:NPLC {nplc:g}",
                            "TRIG:SOUR IMM", "TRIG:COUN 1", "SAMP:COUN 1"):
                self.write(command)
            if self.query("*OPC?") != "1":
                raise ProtocolError("Keysight did not confirm configuration completion")
            self.check_errors()
            self._dc_configured = True

    def read_voltage(self):
        """Acquire one DC reading; explicitly configure first to bound trigger behavior."""
        if not self._dc_configured:
            raise CommandError("Call configure_dc_voltage() before reading voltage")
        reply = self.query("READ?")
        try:
            value = float(reply)
        except ValueError as exc:
            raise ProtocolError(f"Invalid voltage reading: {reply!r}") from exc
        if not math.isfinite(value) or abs(value) >= 9e37:
            raise ProtocolError(f"Keysight overload or invalid measurement: {reply!r}")
        return value

    get_voltage = read_voltage
    get_value = read_voltage
    set_DCvoltage = configure_dc_voltage
