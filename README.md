# malab

## DAC Box and Keysight bench drivers

The AD5780 API retains the channel-first calls and the historical import
`from malab.instruments.voltsource import AD5780`. The Keysight 34461A driver uses
SCPI over LAN. Unrelated instrument drivers are unchanged. This clone is a
separate Git repository inside `DAC Box/malab`; the installed Anaconda copy is
not overwritten. Commit it separately from the firmware repo.

### Run the tests

Open [live_acceptance.ipynb](notebooks/live_acceptance.ipynb). Each test contains
its actual commands, measurements and assertions directly in the notebook.
Run setup, set `RUN_LIVE` and `ALL_OUTPUTS_ISOLATED` for your bench, then run any
case. Errors remain visible. The committed notebook disables hardware actions.
D01 is a historical raw calibration survey and deliberately fails accuracy on
this box; V01 is the calibrated acceptance test. D02 diagnoses original timing.

| Cases | Checks |
|---|---|
| V01 | SET/GET versus meter at independent voltages, ±0.5 mV, achievable limits |
| R01 | Rates 0.001/0.01/0.1 V/s, both signs, steps 1/10/100, timing/path/endpoints |
| N01, S01 | NETWORK preserves outputs, SAFE ZERO rate/zero/latch/priority/rearm |
| F01, P01 | Invalid inputs, clamp warnings, framing, deadlines, explicit errors/no replay |
| C01, C02 | Socket churn, ownership, fragments, busy operations and cancellation |
| I01 | Repeated/all-channel INIT preserves active outputs; channel isolation |
| L01 | 120-second idle expiry and >120-second operation without heartbeats |
| Q01 | 6,000-command soak with no serial monitor |
| E01, E02 | Bench fault injection: corrupt readback and real W5500 configuration loss |

Run the same visible cells without Jupyter, from the parent folder:

```powershell
.venv-bench/Scripts/python.exe malab/tools/run_acceptance.py --cases V01 R01 N01 S01 --live --isolated
.venv-bench/Scripts/python.exe malab/tools/run_offline_tests.py
```

Add `--jupyter` to execute in a real Jupyter kernel using the selected Python
environment. The runner saves an executed notebook, revision/source manifest and CSV data in
`notebooks/results/<UTC run>/`. The [offline notebook](notebooks/driver_offline_tests.ipynb)
contains 25 groups covering framing, validation, calibration, timing/status, SCPI,
USB and fault controls. These are supporting tests without hardware.

On this computer select `DAC Box/.venv-bench/Scripts/python.exe` as the notebook
Python environment. On the bench computer install `requirements-bench.txt` in a
Python 3.11 environment and make this checkout importable from its parent folder.
Restart the kernel if the installed lab copy is already imported; setup checks
which checkout is loaded. The historical `voltsource` module still imports legacy
NumPy/VISA/telnet dependencies and can print the existing optional-VISA warning.
The standalone `malab.instruments.AD5780` alias avoids those imports, but final
acceptance deliberately uses the requested `voltsource` entry point.

### API and calibration

```python
from malab.instruments.voltsource import AD5780
from malab.instruments import Keysight34461A

with AD5780(address="192.168.1.200") as dac:
    print(dac.get_id())
    print(dac.get_calibration(1))
    print(dac.get_voltage_limits(1))
    print(dac.get_voltage(1))  # Calibrated register-derived volts, not a meter reading.

with Keysight34461A(address="192.168.1.71") as meter:
    meter.configure_dc_voltage(voltage_range=10, nplc=1)
    print(meter.read_voltage())
```

| Call | Behavior |
|---|---|
| `initialize(channel=None)` / `init(...)` | Verify active outputs unchanged; initialize an already-clamped cold channel at calibrated zero. |
| `set_voltage(channel, voltage)` | Validate, send once, verify acknowledgment; return quantized calibrated volts. |
| `get_voltage(channel)` | Numeric calibrated volts. Remove the old extra code-to-volts conversion. |
| `get_code(channel)` / `set_code(channel, code)` | Explicit raw-code operations. |
| `get_calibration(channel)` | Device measured/nominal offset, volts per code and zero code. |
| `get_voltage_limits(channel)` | Calibrated range within the API's ±10 V nominal limits. |
| `ramp(channel, voltage, speed)` | V/s; wait for COMPLETE by default; return `RampStatus`. |
| `ramp(..., wait=False)` | Return ACCEPTED; poll `get_status()`. |
| `abort_ramp()` / `close()` | Disconnect; firmware aborts remote ramp and holds output. No automatic zero. |

No constructor initializes or sets a DAC. Firmware stores the measured CH1 profile
for the box labeled A8:61:0A:AE:F2:01. Conversion is
`-9.992845256 + code * 0.000076283553` volts; calibrated zero is code **130996**.
The attainable lower endpoint is approximately **−9.99285 V**, so calibrated
−10 V requests raise `ValueError`. A +10 V request is achievable and corrected.
CH2–4 retain nominal, unmeasured profiles. This calibration is specific to this
box and bench conditions; remeasure after reference/hardware changes.

`use_calibration=False` explicitly selects nominal diagnostic conversion:
`code * 20/262144 - 10`. Do not use that override for calibrated acceptance.
The ±15 V supplies are not the DAC conversion range. `get_voltage` derives volts
from the DAC register; independent accuracy comes from the multimeter.

Ramps default to ten-code steps. Delay is microseconds:
`ceil(step_size * channel_volts_per_code / speed * 1e6)`. Firmware schedules
against elapsed time, including service work; severe traffic/stalls can still
slow it. Tests retain a 5% timing tolerance plus measurement/observation allowance.
An overall `ramp(timeout=...)` expiration raises while leaving the ramp connection
intact; explicitly abort if desired. Transport timeouts close the uncertain
connection. Commands that change outputs are never automatically replayed.

Invalid arguments raise `ValueError`, device rejection raises `CommandError`,
malformed replies raise `ProtocolError`, and connection/deadline errors raise
`InstrumentConnectionError` / `InstrumentTimeout` (from `_line_socket`). No
communication failure returns `None`. `recv_length` remains accepted; complete
newline framing determines reply length. The old full-range `sweep()` is omitted;
use explicit ramp bounds and rates.

### Recovery actions and fault tests

The `uno_r4_minima_bench` firmware enables USB emulation. Production ignores USB
commands. Close other serial monitors before opening COM5:

```python
with AD5780(enabled=False, bench_port="COM5") as dac:
    print(dac.get_recovery_status())
    # dac.safe_zero(wait=True)  # All four channels, <=0.01 V/s, then latched.
    # dac.network_reset()      # Rearm/reset Ethernet; outputs preserved.
```

With Ethernet enabled, `network_reset(wait=True)` also waits for a fresh TCP
connection. `safe_ramp` aliases `safe_zero`. Status distinguishes successful
`LATCHED` from readback-validation `FAILED`; both require explicit NETWORK rearm.
SAFE ZERO uses device-stored calibrated zero and works without the PC/network
once requested. Only CH1 analog behavior is measured; CH2–4 results are register
checks. USB emulation does not test switch contacts or debounce.

`bench_inject_fault('readback')` substitutes invalid received SPI frames without
changing real DAC registers. `'clear'` removes that override; `'network'` clears
the real W5500 IP register to test automatic recovery. These diagnostic calls
require opt-in bench firmware and independent USB. The notebook clears faults
and rearms explicitly. They do not establish recovery from damaged hardware or
an SPI-unresponsive Ethernet chip.

Evidence and local commits are in the outer repository's
[fix ledger](../tests/LIVE_FIX_LEDGER.md) and
[checklist coverage](../tests/LIVE_COVERAGE.md). No changes are pushed.

References: [Keysight LAN connections](https://www.keysight.com/zz/en/lib/resources/user-manuals/direct-instrument-connection-using-lan-572739.html)
and [Truevolt Operating and Service Guide](https://www.keysight.com/us/en/assets/9018-03876/service-manuals/9018-03876.pdf).

### Local dashboard

Open **http://localhost:8765** after running `./malab/tools/start_dashboard.ps1`
from the outer DAC Box folder. See [dashboard instructions](dashboard/README.md)
and the [visible dashboard acceptance notebook](notebooks/dashboard_acceptance.ipynb).
All four channels have controls and live device values; only CH1 is independently
measured by the Keysight. The passive Network good indicator requires a fresh
application reply. Connecting is read-only; Set/Ramp prepare their selected
channel so a cold output is released from its startup clamp.

`dac.get_output_codes()` reports four tracked code/source records without SPI
reads, including during a ramp. Sources distinguish checked readback, last
completed write, and unknown. `via_usb=True` uses the independent bench port
for safe-zero progress while Ethernet is off. Neither transport measures voltage.
`dac.disconnect()` and `abort_ramp()` close Ethernet only, preserving USB recovery.
`dac.close()` closes both transports when the instrument session is finished.

### Multiple DAC units

Use [DACArray](instruments/DAC_ARRAY.md) with an ordered list of IP addresses.
Each box contributes four global channels; network/recovery controls stay scoped
to its unit. Configure the GUI in `dashboard/units.json`. The Keysight is now
assigned to DAC 4. See the [current visible hardware tests](notebooks/modular_dac_acceptance.ipynb)
and [offline multi-unit tests](notebooks/multidac_offline_tests.ipynb).
DAC 4 passes functional checks but fails ±0.5 mV absolute accuracy as-is; its
nominal zero measures about +2.87 mV. No calibration or firmware was changed.
