# Local DAC dashboard

Open **http://localhost:8765** in Chrome on the computer running the server.
The dashboard is bound to loopback; it is not a hosted website or a LAN service.

From the DAC Box folder, start it with:

```powershell
./malab/tools/start_dashboard.ps1
```

The launcher uses the existing `.venv-bench` Python environment and opens Chrome.
Use `-NoBrowser` to start only the server. Or run in a terminal (Ctrl+C stops it):

```powershell
./.venv-bench/Scripts/python.exe -m malab.dashboard
```

Python 3.11 and pyserial are required by this checkout's bench drivers. The web
server itself uses only Python's standard library. On another installation,
create the bench environment following the main README before running it.
Optional arguments: `--port 8765 --dac 192.168.1.200 --meter 192.168.1.71 --usb COM5`.
Use the firmware containing `VALUES` telemetry; USB recovery also needs the
`uno_r4_minima_bench` build. Close other DAC clients and serial monitors: the
dashboard owns the DAC's single TCP connection and the USB diagnostic port.

## Reading the page

- Each unit’s four cards show volts derived from device codes. During a ramp the source
  says **last write**; idle values come from checked register reads. These are
  not independent analog measurements. A cold output can remain clamped while
  its register contains a nonzero value.
- The Keysight panel is the independent analog measurement of **the configured channel only** (currently DAC 4).
  It compares against fresh idle data for that channel with the unchanged **±0.5 mV** limit.
  The comparison is suspended during ramps because samples are asynchronous.
- **Network good** is a passive signal based on a recent valid device response.
  It changes on connecting, disconnection, failure, or stale data. It does not
  claim that DAC analog output or calibration is correct.
- Stale numbers are dimmed and labeled. Unknown codes show a dash. Calibration badges come from each device. A nominal profile does not imply measured accuracy.

## Controls

Connecting reads existing state; it never initializes or changes outputs.
**Set voltage** and **Ramp** explicitly prepare the selected channel first.
Initialization preserves an active output and releases a cold/clamped output
at its calibrated zero before applying the requested operation. A failed
initialization prevents the output command. Ramp speed is in **V/s**, using
ten-code steps and device calibration.

**Stop ramp** closes the controlling connection, holds the intermediate value,
then reconnects. **Disconnect** holds the output and stays disconnected.
**Reset network** invokes the NETWORK action through USB and reconnects;
DAC codes are preserved. **Safe zero** invokes the independent USB action on
the selected unit’s four channels at at most **0.01 V/s**. Progress remains visible through USB while
Ethernet is paused. It remains latched at its stored zero target until a fresh NETWORK action.
These two GUI controls require the selected unit’s USB port/bench firmware; physical buttons continue
to work independently of this server. Closing the browser leaves the server
running. Stopping the server closes its TCP connection and can stop a remote
ramp; device safe-zero continues independently.

Commands are serialized. Duplicate request IDs are not replayed. A timeout
reports an unknown outcome and never retries an output command. After restarting
the server, reload the page to obtain the new session token.

## Visible tests

The current hardware and offline notebooks are described below. Every test's
commands and assertions appear directly in notebook cells. The original
`dashboard_acceptance.ipynb` is retained as historical CH1 evidence for the
previous one-unit HTTP interface.

Single-unit/controller regressions:

```powershell
./.venv-bench/Scripts/python.exe -m unittest discover -s malab/dashboard/tests -v
```

## Ordered units and meter assignment

Edit `dashboard/units.json`, then run `./malab/tools/start_dashboard.ps1 -Restart`
while all units are idle. Each entry in `addresses` adds four channels, in order.
Keep the `bench_ports` list aligned with the IP list; use `null` for a unit with
no USB control. Duplicate IPs/USB ports are rejected. Missing units stay visible
in their original positions, and each has its own health signal, command queue,
reset, stop and safe-zero controls. An unavailable unit does not disable another.
The top signal reports how many units have fresh responses. Configuration changes
require a restart; the browser reloads for the new server session without replaying
any output commands.

`meter_channel` is the **global** channel physically wired to the Keysight.
It is currently **4**. This is a label/association, not an electronic multiplexer;
move the meter leads before changing it. Only that channel receives an analog
accuracy comparison. A latched zero target can still have analog calibration
error; the meter comparison remains visible while latched.

The Python [DACArray API](../instruments/DAC_ARRAY.md) exposes the same global
numbering. No firmware changes are needed for additional units. Physical buttons
continue to control exactly their own box's four outputs.

## Current DAC 4 result

The current visible test is
[`modular_dac_acceptance.ipynb`](../notebooks/modular_dac_acceptance.ipynb).
Run it with both live flags enabled on an isolated bench, or use:

```powershell
./.venv-bench/Scripts/python.exe malab/tools/run_modular_checks.py --live --isolated
```

DAC 4 was tested with its existing nominal calibration and unchanged firmware.
Timing/path, network hold/reset, abort, all four stored safe-zero codes, latch and
rearm pass. Absolute SET/GET, ramp endpoints and safe-zero analog zero **fail**
the unchanged ±0.5 mV criterion: nominal zero reads approximately +2.87 mV.
The diagnostic fit is recorded but not applied. DAC 4 needs calibration before
claiming the same analog accuracy as DAC 1. In particular, Python-only correction
would not fix its independent physical safe-zero endpoint.

Offline multi-unit routing/failure tests (no hardware needed):

```powershell
./.venv-bench/Scripts/python.exe malab/tools/run_modular_checks.py
```

All cases and assertions are directly visible in
`notebooks/multidac_offline_tests.ipynb`. The earlier dashboard acceptance notebook
records the original one-unit HTTP interface and CH1 result; use the modular
notebook for the current interface. The runner continues after assertion failures
so the final cleanup and remaining independent cases run, records each FAIL,
and exits with a nonzero status if any assertion failed.
