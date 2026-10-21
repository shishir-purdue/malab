"""Atomic Python-only settings keyed by physical unit and local channel."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import tempfile
import threading
import time


def endpoint_key(address):
    host, sep, port = address.partition(':')
    return host if not sep or int(port) == 23 else f'{host}:{int(port)}'


class ChannelSettingsStore:
    """Atomic local storage keyed by physical address and local channel.

    Reads see other Python clients' changes. An OS file lock serializes writers
    across processes; a replacement file prevents partially written settings.
    A missing file means no settings. Invalid settings fail visibly.
    """
    _thread_lock = threading.RLock()
    filename = 'channels.local.json'
    setting_name = 'channel'

    def validate(self, value):
        raise NotImplementedError

    def __init__(self, path=None):
        if path is None:
            from malab.bench_config import config_path
            path = config_path().parent / self.filename
        self.path = Path(path)

    def snapshot(self):
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding='utf-8'))
            if type(data['version']) is not int or data['version'] != 1 or not isinstance(data['units'], dict):
                raise ValueError('Unsupported format')
            for address, channels in data['units'].items():
                if not isinstance(address, str) or not isinstance(channels, dict):
                    raise ValueError('Invalid unit settings')
                for channel, value in channels.items():
                    if channel not in ('1', '2', '3', '4'):
                        raise ValueError('Invalid local channel')
                    if self.validate(value) != value or value is None:
                        raise ValueError('Invalid stored value')
            return data['units']
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f'Invalid local {self.setting_name} settings; repair the local file') from exc

    def get(self, address, channel):
        return self.snapshot().get(endpoint_key(address), {}).get(str(channel))

    @contextmanager
    def _write_lock(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._thread_lock, self.path.with_suffix('.lock.local.json').open('a+b') as lock:
            lock.seek(0, os.SEEK_END)
            if lock.tell() == 0:
                lock.write(b'0'); lock.flush()
            deadline = time.monotonic() + 2
            while True:
                try:
                    lock.seek(0)
                    if os.name == 'nt':
                        import msvcrt
                        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise ValueError(f'{self.setting_name.title()} settings are busy; try again')
                    time.sleep(.02)
            try:
                yield
            finally:
                lock.seek(0)
                if os.name == 'nt':
                    msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def set(self, address, channel, value):
        if type(channel) is not int or not 1 <= channel <= 4:
            raise ValueError('Choose local channel 1–4')
        if value is not None:
            value = self.validate(value)
        with self._write_lock():
            units = self.snapshot()
            key = endpoint_key(address)
            channels = units.setdefault(key, {})
            if value is None:
                channels.pop(str(channel), None)
                if not channels:
                    units.pop(key, None)
            else:
                channels[str(channel)] = value
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=self.path.parent,
                                                 prefix=self.path.stem+'-', suffix='.local.json', delete=False) as file:
                    temporary = Path(file.name)
                    json.dump(dict(version=1, units=units), file, indent=2, allow_nan=False)
                    file.write('\n'); file.flush(); os.fsync(file.fileno())
                os.replace(temporary, self.path)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
        return value
