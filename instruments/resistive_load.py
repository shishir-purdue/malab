"""Python-only resistive-load settings and explicit mA APIs; never firmware data."""
import math
from numbers import Real
from .channel_settings import ChannelSettingsStore, endpoint_key


def finite(value, name):
    if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
        raise ValueError(f'{name} must be a finite number')
    return float(value)


def resistance(value):
    value = finite(value, 'Resistance in ohms')
    if value <= 0 or value / 1000 == 0 or not math.isfinite(10000 / value):
        raise ValueError('Resistance must be positive and support finite mA conversion')
    return value


def current_to_voltage(current_mA, ohms):
    value = finite(current_mA, 'Current in mA') * (resistance(ohms) / 1000)
    if not math.isfinite(value) or not -10 <= value <= 10:
        raise ValueError('Requested current requires a voltage outside -10 to +10 V')
    return value


def current_rate_to_voltage(speed_mA_s, ohms):
    speed = finite(speed_mA_s, 'Ramp speed in mA/s') * (resistance(ohms) / 1000)
    if not math.isfinite(speed) or speed <= 0:
        raise ValueError('Ramp speed must convert to a finite positive V/s rate')
    return speed


def voltage_to_current(voltage, ohms):
    if voltage is None:
        return None
    result = finite(voltage, 'Voltage') / resistance(ohms) * 1000
    if not math.isfinite(result):
        raise ValueError('Calculated current is outside the finite numeric range')
    return result


class ResistorStore(ChannelSettingsStore):
    """Persist positive load resistances in ohms, outside firmware."""
    filename = 'resistors.local.json'
    setting_name = 'resistor'

    def validate(self, value):
        return resistance(value)


class ResistiveLoadMixin:
    """Current is calculated as 1000*V/R in mA, not independently measured."""

    def add_resistor(self, channel, resistance_ohms):
        """Save/replace a positive resistance in ohms. Sends no instrument command."""
        address, local = self._channel_key(channel)
        return self._resistor_store.set(address, local, resistance(resistance_ohms))

    def remove_resistor(self, channel):
        """Return to voltage mode; leaves the physical output unchanged."""
        return self._resistor_store.set(*self._channel_key(channel), None)

    def get_resistance(self, channel):
        return self._resistor_store.get(*self._channel_key(channel))

    def _require_resistance(self, channel):
        ohms = self.get_resistance(channel)
        if ohms is None:
            raise ValueError('Add a resistor to this channel before using current in mA')
        return ohms

    def get_current(self, channel):
        ohms = self._require_resistance(channel)
        return voltage_to_current(self.get_voltage(channel), ohms)

    def get_current_limits(self, channel):
        ohms = self._require_resistance(channel)
        return tuple(voltage_to_current(v, ohms) for v in self.get_voltage_limits(channel))

    def set_current(self, channel, current_mA):
        """Set I*R through the existing voltage API; return register-derived mA."""
        ohms = self._require_resistance(channel)
        voltage = current_to_voltage(current_mA, ohms)
        return voltage_to_current(self.set_voltage(channel, voltage), ohms)

    def ramp_current(self, channel, current_mA, speed_mA_s, **kwargs):
        """Ramp to mA at mA/s; existing step size, completion and errors apply."""
        ohms = self._require_resistance(channel)
        voltage = current_to_voltage(current_mA, ohms)
        speed = current_rate_to_voltage(speed_mA_s, ohms)
        return self.ramp(channel, voltage, speed, **kwargs)
