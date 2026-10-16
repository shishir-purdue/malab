# malab

## DAC Box and Keysight bench drivers

The AD5780 interface follows the lab's supplied `voltsource.py` (2026-10-16),
with corrected ramp units and explicit errors. Unrelated instrument drivers
remain unchanged. The package initializers load instruments on demand so these
two network drivers do not require legacy VISA, GUI, or analysis packages.

This clone is a separate Git repository inside `DAC Box/malab`; the outer DAC
firmware repository ignores it. Changes must be reviewed/committed in each repo.
The installed Anaconda copy is not overwritten.

### Start here

- [Core hardware notebook](notebooks/ad5780_core_bench.ipynb): commands,
  measurements, timing/path assertions, CSV traces and plots directly in cells.
- [Offline driver notebook](notebooks/driver_offline_tests.ipynb): 18 groups
  covering framing, errors, validation, ramp timing/status, meter SCPI and USB.
- `python tools/run_offline_tests.py` runs those same notebook tests without
  Jupyter or hardware. The executed result is in `notebooks/results/`.

Use Python 3.9+; the new LAN drivers need only its standard library. Jupyter and
Matplotlib are needed for the hardware notebook, and `pyserial` for optional USB
button emulation. From the parent of this clone:

On this computer, `DAC Box/.venv-bench/Scripts/python.exe` is prepared with
pyserial 3.5 and access to the existing Anaconda notebook/plotting packages.
Select that Python environment for the live notebook. On another bench computer,
create a virtual environment and install `requirements-bench.txt` from this clone.

Example (read-only DAC access):

```python
from malab.instruments import AD5780, Keysight34461A

with AD5780(address="192.168.1.200") as dac:
    print(dac.get_id())
    print(dac.get_code(1))       # Raw integer, 0..262143.
    print(dac.get_voltage(1))    # Nominal volts derived from register readback.

with Keysight34461A(address="192.168.1.71") as meter:
    meter.configure_dc_voltage(voltage_range=10, nplc=1)
    print(meter.read_voltage())  # Actual analog reading, volts.
```

The notebooks locate this checkout and stop if another `malab` is already
imported. Restart the kernel when switching from the installed lab copy.
`from malab.instruments.voltsource import AD5780` is also available, but that
legacy module still loads its old NumPy/VISA/telnet dependencies; prefer the
direct import above. Other legacy instruments still need their own dependencies.

### AD5780 API and migration

The channel-first calls `initialize(channel=None)`, `set_voltage(channel,
voltage)`, `get_voltage(channel)`, `ramp(channel, voltage, speed)`, and `get_id()`
retain their argument order. `recv_length` remains accepted by the constructor;
newline framing now handles full replies regardless of TCP packet boundaries.

Intentional return/error changes:

| Call | New behavior |
| --- | --- |
| `set_voltage(1, v)` | Validate, send once, verify acknowledgment; return quantized nominal volts. |
| `get_voltage(1)` | Return numeric volts, **not the old raw-code string**. Remove any old extra code-to-volts conversion. |
| `get_code(1)` | Return raw integer code when that is needed. |
| `ramp(1, v, speed)` | Speed in V/s; block until STATUS confirms COMPLETE; return `RampStatus`. |
| `ramp(..., wait=False)` | Return ACCEPTED immediately; use `get_status()` to track completion. |
| `abort_ramp()` | Close TCP; firmware aborts when it detects disconnect and holds the current output. |
| `close()` | Release connection; never automatically zero or restore outputs. |

No constructor initializes or sets a DAC. Call `initialize(1)` explicitly when
appropriate. Nominal conversion is `code * 20/262144 - 10`, so zero is code 131072
and the positive endpoint is +9.999923706 V. A requested +10 V maps to that last
representable code. The +/-15 V supply is not the conversion range.

Ramps use ten-code steps by default. The firmware delay is microseconds:
`ceil(step_size * (20/262144) / speed * 1e6)`. For 0.001/0.01 V/s this is
762940/76294 us. Firmware service overhead can slow a ramp; the hardware notebook
measures this. `timeout` on `ramp` is an overall wait limit (default 3600 s),
separate from each network exchange's timeout. An overall wait expiration leaves
the ramp connection intact; choose whether to abort. Transport failure closes it.

Invalid inputs raise `ValueError`; device rejections raise `CommandError`;
framing/readback failures raise `ProtocolError`; transport failures raise
`InstrumentTimeout` or `InstrumentConnectionError`. These are defined in
`malab.instruments._line_socket`. No timeout returns `None`. Output-changing
commands are never retried automatically because their outcome could be unknown.
The old full-range `sweep()` shortcut is not retained; specify bounds/rates with
explicit ramp calls. Acknowledged writes do not substitute for a meter reading.

### Button emulation

The outer firmware project has an opt-in `uno_r4_minima_bench` build. The normal
build ignores USB commands. Close any serial monitor before using:

```python
from malab.instruments import DACBenchControls
with DACBenchControls("COM5") as controls:
    print(controls.status())
    # controls.network_reset()  # Disconnect/reset Ethernet; preserve DACs.
    # controls.safe_zero()      # All four DACs to zero at <=0.01 V/s; latch.
```

USB commands request the same actions as physical buttons. `OK` acknowledges a
request, not its completion. SAFE ZERO is complete only after the latch, final
DAC codes and meter readings are checked. A failed DAC readback can also leave
the controller latched. A new NETWORK action after completion explicitly rearms.
Emulation does not verify button wiring, debounce or electrically dead hardware.

### Validation status (2026-10-16)

18 offline groups passed. Both normal and bench firmware compile; the outer
firmware's 82 regression tests passed. Before the user paused live work, the
Keysight at 192.168.1.71 identified as serial MY60041761. DC setup and three reads
succeeded (approximately 0.009, 0.016 and 0.072 mV); the SCPI error queue was clear.
This proves communication, not DAC accuracy. No new firmware upload or DAC-output
test was performed. Live tests remain disabled pending bench readiness.

References: [Keysight direct LAN connections](https://www.keysight.com/zz/en/lib/resources/user-manuals/direct-instrument-connection-using-lan-572739.html)
(SCPI socket port 5025) and the
[Truevolt Operating and Service Guide](https://www.keysight.com/us/en/assets/9018-03876/service-manuals/9018-03876.pdf)
(DC voltage, NPLC, READ and system-error commands).
