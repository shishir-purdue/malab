"""Optional USB bench actions; needs the DAC's uno_r4_minima_bench firmware.

These invoke the same action requests as the buttons, not their electrical
contacts/debounce. pyserial is required only when constructing this class.
"""
import threading
import time
from ._line_socket import (InstrumentTimeout, InstrumentConnectionError, ProtocolError,
                          CommandError, positive_seconds)


class DACBenchControls:
    def __init__(self, port, timeout=5.0):
        import serial
        self.timeout = positive_seconds(timeout)
        self._lock = threading.RLock()
        # Native USB on the Minima uses 1200-baud touch for bootloader entry.
        # 115200 is the normal diagnostic baud; no reset command is sent.
        self.port = serial.Serial(port, 115200, timeout=0.1, write_timeout=self.timeout)
        self._rx = bytearray()
        try:
            self.status()  # Fail clearly on firmware without bench commands.
        except Exception:
            self.close()
            raise

    def _query(self, command):
        try:
            return self._exchange(command)
        except (OSError, TimeoutError) as exc:
            self.close()
            if isinstance(exc, InstrumentTimeout):
                raise
            raise InstrumentConnectionError("USB transport failed; action outcome may be unknown") from exc

    def _exchange(self, command):
        with self._lock:
            if not self.port.is_open:
                raise InstrumentConnectionError("USB connection is closed; reopen explicitly")
            deadline = time.monotonic() + self.timeout
            data = ("BENCH " + command + "\n").encode("ascii")
            if self.port.write(data) != len(data):
                self.close()
                raise InstrumentConnectionError("Incomplete USB command; action outcome unknown")
            while time.monotonic() < deadline:
                newline = self._rx.find(b"\n")
                if newline >= 0:
                    line = bytes(self._rx[:newline]).rstrip(b"\r").decode("ascii", errors="replace")
                    del self._rx[:newline+1]
                    if line.startswith("BENCH ERR"):
                        raise CommandError(line)
                    if line.startswith("BENCH "):
                        return line
                else:
                    self._rx.extend(self.port.read(max(1, min(self.port.in_waiting, 4096))))
                    if len(self._rx) > 8192:
                        self.close()
                        raise ProtocolError("Unterminated USB diagnostic line")
            self.close()  # Do not leave a late action reply for the next query.
            raise InstrumentTimeout("No BENCH reply; connection closed. Action outcome unknown; check bench firmware/USB monitor.")

    def status(self):
        reply = self._query("STATUS")
        if reply not in {"BENCH STATUS READY", "BENCH STATUS OFFLINE", "BENCH STATUS ACTIVE", "BENCH STATUS LATCHED", "BENCH STATUS FAILED"}:
            self.close()
            raise ProtocolError(reply)
        return reply.rsplit(" ", 1)[1]

    def network_reset(self):
        reply = self._query("NETWORK")
        if reply != "BENCH OK NETWORK":
            self.close()
            raise ProtocolError(reply)
        return reply  # Acceptance; wait for a fresh TCP connection separately.

    def safe_zero(self):
        reply = self._query("SAFEZERO")
        if reply != "BENCH OK SAFEZERO":
            self.close()
            raise ProtocolError(reply)
        return reply

    def close(self):
        self.port.close()

    def inject_fault(self, kind):
        if kind not in {"readback", "network", "clear"}:
            raise ValueError("kind must be readback, network, or clear")
        reply = self._query("FAULT " + kind.upper())
        if reply != "BENCH OK FAULT " + kind.upper():
            self.close()
            raise ProtocolError(reply)
        return reply

    def output_codes(self):
        reply = self._query("VALUES")
        if not reply.startswith("BENCH VALUES "):
            self.close()
            raise ProtocolError(reply)
        return reply[6:]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
