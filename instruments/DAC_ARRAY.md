# Several four-channel boxes as one DAC

`DACArray` is exported from `malab.instruments.voltsource` and
`malab.instruments`. The ordered IP list fixes the global channel numbering:

| List entry | Global channels | Channels sent to its firmware |
| --- | --- | --- |
| First IP | 1–4 | 1–4 |
| Second IP | 5–8 | 1–4 |
| Third IP | 9–12 | 1–4 |

An offline unit retains its numbers. There is no failover to another box and no
automatic output replay. Append new IPs to preserve the existing mapping.
Changing the order intentionally changes the mapping when a new array is created.
Duplicate IPs (including equivalent default ports) and duplicate USB ports are
rejected before any connections are opened.

```python
from malab.instruments.voltsource import DACArray

# Supply your real ordered list. These are documentation addresses, not this bench.
dac = DACArray(["192.0.2.10", "192.0.2.20"], bench_ports=["COM5", None])
results = dac.connect()  # One explicit UnitResult per unit, including failures.
if not results[2].ok:
    raise RuntimeError(results[2].error)

dac.initialize(5)       # Second box, physical channel 1; preserves active outputs.
dac.set_voltage(5, 1.0)
print(dac.get_voltage(5))
dac.ramp(8, 0.0, 0.01)  # Second box, physical channel 4; speed in V/s.
print(dac.locate(8))    # Global channel, unit, local channel and IP.
```

Construction is disconnected by default and never initializes/sets outputs.
`enabled=True` attempts parallel connections and stores their results in
`connection_results`; output methods still raise explicit errors for unavailable
units. Typed channel methods preserve the existing single-box semantics.
`get_status(unit=2)` and `ramp(...)` return a dictionary with both global and local
channel numbers. Error messages identify the unit, address and operation.

Recovery always names a **unit**, because its firmware and physical buttons each
control four channels:

```python
dac.abort_ramp(unit=2)       # TCP disconnect; hold that box's intermediate value.
dac.network_reset(unit=1)   # Independent USB, outputs preserved.
dac.safe_zero(unit=1)       # Only global channels 1–4, then latched.
dac.get_recovery_status(unit=1)
results = dac.safe_zero_all()  # Explicit broadcast; inspect EVERY per-unit result.
```

GUI recovery requires the corresponding USB bench port and bench firmware. A
unit without USB retains its physical buttons; the GUI recovery controls are
disabled. There is no Ethernet SET-to-zero fallback pretending to be an
independent safety control. Associate each USB port with the correct physical
box in the configuration; the current protocol cannot authenticate that wiring.
USB recovery can interrupt a Python caller waiting for a ramp. Independent unit
workers/connections let another box keep responding during an outage.

`disconnect(unit=...)` closes just that unit's Ethernet; omitting `unit` disconnects
all network sessions with per-unit results. `close()` releases network and USB
resources on all units. No multi-unit command is atomic: a successful action on
one box is not rolled back if another fails. Physical safe zero continues on its
own box after the request even when Python/network access disappears.

The [offline notebook](../notebooks/multidac_offline_tests.ipynb) contains all
fake-unit test code and assertions directly. A second physical box has not yet
been supplied or tested.
