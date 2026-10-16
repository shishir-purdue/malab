"""malab; optional analysis/GUI packages load only when requested.

This lets the standalone network instrument drivers run with Python's standard
library while retaining legacy analysis exports for existing callers.
"""
from importlib import import_module as _import_module

_exports = {"SlabFile": "datamanagement", "h5File": "datamanagement",
            "AttrDict": "datamanagement", "Experiment": "experiment"}


def __getattr__(name):
    if name == "instruments":
        value = _import_module(".instruments", __name__)
    elif name in _exports:
        value = getattr(_import_module("." + _exports[name], __name__), name)
    elif name == "__all__":
        analysis = _import_module(".dataanalysis", __name__)
        return list(_exports) + [key for key in vars(analysis) if not key.startswith("_")]
    elif not name.startswith("_"):
        analysis = _import_module(".dataanalysis", __name__)
        try:
            value = getattr(analysis, name)
        except AttributeError:
            raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None
    else:
        raise AttributeError(name)
    globals()[name] = value
    return value
