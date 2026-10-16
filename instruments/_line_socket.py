"""Bounded, newline-framed transport for the DAC and Truevolt drivers only.

Transport failures close the connection: the outcome of the last command may be
unknown, so output-changing commands are never retried automatically.
"""
import math
from numbers import Real
import socket
import threading
import time


class InstrumentError(RuntimeError):
    pass


class InstrumentTimeout(TimeoutError, InstrumentError):
    pass


class InstrumentConnectionError(ConnectionError, InstrumentError):
    pass


class ProtocolError(InstrumentError):
    pass


class CommandError(InstrumentError):
    pass


def positive_seconds(value, name="timeout"):
    if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be finite and positive")
    return float(value)


class LineSocketInstrument:
    default_port = 5025
    max_reply = 8192
    query_sleep = 0.0  # Compatibility; framing replaces arbitrary sleeps.

    def __init__(self, name, address, enabled=True, timeout=3.0):
        self.name, self.address = name, address
        self.timeout = positive_seconds(timeout)
        self.enabled = bool(enabled)
        host, sep, port = address.partition(":")
        if not host or (sep and not port.isdecimal()):
            raise ValueError("address must be a hostname/IPv4 address, optionally followed by :port")
        self.ip, self.port = host, int(port) if sep else self.default_port
        if not 1 <= self.port <= 65535:
            raise ValueError("port must be 1..65535")
        self.socket = None
        self._rx = bytearray()
        self._lock = threading.RLock()
        if self.enabled:
            self.connect()

    @property
    def connected(self):
        return self.socket is not None

    def connect(self):
        with self._lock:
            if self.socket is not None:
                return self
            if not self.enabled:
                raise InstrumentConnectionError("Instrument disabled; explicitly enable before connecting")
            try:
                self.socket = socket.create_connection((self.ip, self.port), self.timeout)
                self.socket.settimeout(self.timeout)
                self._rx.clear()
                self._handshake()
            except (socket.timeout, TimeoutError) as exc:
                self.close()
                raise InstrumentTimeout("Instrument connection/handshake timed out") from exc
            except OSError as exc:
                self.close()
                raise InstrumentConnectionError(f"Cannot connect to {self.address}: {exc}") from exc
            except Exception:
                self.close()
                raise
        return self

    def _handshake(self):
        pass

    def close(self):
        with self._lock:
            sock, self.socket = self.socket, None
            self._rx.clear()
            if sock is not None:
                sock.close()

    def reconnect(self):
        self.close()
        return self.connect()

    def set_enable(self, enabled=True):
        self.close()
        self.enabled = bool(enabled)
        if self.enabled:
            self.connect()

    def set_timeout(self, timeout):
        self.timeout = positive_seconds(timeout)

    def get_timeout(self):
        return self.timeout

    def get_name(self):
        return self.name

    def _require_connection(self):
        if not self.enabled or self.socket is None:
            raise InstrumentConnectionError("No live connection; connect explicitly (commands are never replayed)")

    @staticmethod
    def _encode(command):
        if not isinstance(command, str) or not command.strip() or any(c in command for c in "\r\n\x00"):
            raise ValueError("command must be one nonempty line without CR/LF/NUL")
        data = command.encode("ascii")
        if len(data) > 4096:
            raise ValueError("command too long")
        return data + b"\n"

    def _remaining(self, deadline):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise socket.timeout("response deadline expired")
        self.socket.settimeout(remaining)

    def _send(self, data, deadline):
        self._remaining(deadline)
        self.socket.sendall(data)

    def _readline(self, deadline):
        while True:
            newline = self._rx.find(b"\n")
            if newline >= 0:
                if newline > self.max_reply:
                    raise ProtocolError("Reply exceeds maximum line length")
                raw = bytes(self._rx[:newline]).rstrip(b"\r")
                del self._rx[:newline + 1]
                try:
                    return raw.decode("ascii")
                except UnicodeDecodeError as exc:
                    raise ProtocolError("Non-ASCII instrument reply") from exc
            if len(self._rx) > self.max_reply:
                raise ProtocolError("Unterminated/oversized instrument reply")
            self._remaining(deadline)
            data = self.socket.recv(4096)
            if not data:
                raise InstrumentConnectionError("Instrument closed connection before a complete reply")
            self._rx.extend(data)

    def _exchange(self, command=None, *, read=True, timeout=None):
        data = self._encode(command) if command is not None else None
        seconds = self.timeout if timeout is None else positive_seconds(timeout)
        with self._lock:
            self._require_connection()
            deadline = time.monotonic() + seconds
            try:
                if data is not None:
                    self._send(data, deadline)
                return self._readline(deadline) if read else None
            except (socket.timeout, TimeoutError) as exc:
                self.close()
                raise InstrumentTimeout("Instrument reply timed out; connection closed, command outcome may be unknown") from exc
            except (OSError, ProtocolError, InstrumentConnectionError) as exc:
                self.close()
                if isinstance(exc, (ProtocolError, InstrumentConnectionError)):
                    raise
                raise InstrumentConnectionError(f"Instrument transport failed: {exc}") from exc

    def query(self, command, timeout=None):
        return self._exchange(command, timeout=timeout)

    def write(self, command):
        return self._exchange(command, read=False)

    def read(self, timeout=None):
        return self._exchange(timeout=timeout)

    def __enter__(self):
        if not self.connected:
            self.connect()
        return self

    def __exit__(self, *exc):
        self.close()
