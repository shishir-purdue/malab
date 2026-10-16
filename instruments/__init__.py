"""Instrument exports loaded on demand; unrelated drivers keep their own dependencies."""
from importlib import import_module as _import_module

_exports = {
    "AD5780": "ad5780", "Keysight34461A": "keysight34461a",
    "DACBenchControls": "dac_bench",
    "DACArray": "dac_array",
    "InstrumentManager": "instrumentmanager", "InstrumentManagerWindow": "InstrumentManagerWindow",
    "Instrument": "instrumenttypes", "VisaInstrument": "instrumenttypes",
    "TelnetInstrument": "instrumenttypes", "SocketInstrument": "instrumenttypes",
    "SerialInstrument": "instrumenttypes", "WebInstrument": "instrumenttypes",
    "E4440": "spectrumanalyzer", "N5242A": "PNAX", "N5183B": "rfgenerators",
    "E8257D": "rfgenerators", "BNC845": "rfgenerators", "Keithley199": "multimeter",
    "HP34401A": "multimeter", "BKPowerSupply": "bkpowersupply",
    "BKPowerSupplynew": "bkpowersupply", "BKPowerSupply2": "bkpowersupply",
    "SRS900": "voltsource", "YokogawaGS200": "voltsource",
    "BiasDriver": "function_generator", "FilamentDriver": "function_generator",
    "BNCAWG": "function_generator",
}

__all__ = list(_exports)


def __getattr__(name):
    if name not in _exports:
        raise AttributeError(name)
    value = getattr(_import_module("." + _exports[name], __name__), name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(_exports))
