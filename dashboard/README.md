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
Use `--config` to select another local bench JSON file, or `DAC_BENCH_CONFIG`.
CLI address overrides are also supported; keep real values out of tracked scripts.
Use the firmware containing `VALUES` telemetry; USB recovery also needs the
`uno_r4_minima_bench` build. Close other DAC clients and serial monitors: the
dashboard owns the DAC's single TCP connection and the USB diagnostic port.

## Reading the page

- Each unit’s four cards show volts derived from device codes. During a ramp the source
  says **last write**; idle values come from checked register reads. These are
  not independent analog measurements. A cold output can remain clamped while
  its register contains a nonzero value.
- The Keysight panel is the independent analog measurement of **the configured channel only** (currently DAC 5 on Unit 2).
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
the selected unit’s four channels at at most **0.02 V/s**. Progress remains visible through USB while
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

Edit the ignored `config/bench.local.json`, then run `./malab/tools/start_dashboard.ps1 -Restart`
while all units are idle. Each entry in `units` adds four channels, in order.
Its `address` and `usb_port` belong to that box; use `null` for USB when absent. Duplicate IPs/USB ports are rejected. Missing units stay visible
in their original positions, and each has its own health signal, command queue,
reset, stop and safe-zero controls. An unavailable unit does not disable another.
The top signal reports how many units have fresh responses. Configuration changes
require a restart; the browser reloads for the new server session without replaying
any output commands.

`meter.channel` is the **global** channel physically wired to the Keysight.
It is currently **5** (Unit 2, local channel 1). This is a label/association, not an electronic multiplexer;
move the meter leads before changing it. Only that channel receives an analog
accuracy comparison. A latched zero target can still have analog calibration
error; the meter comparison remains visible while latched.

The Python [DACArray API](../instruments/DAC_ARRAY.md) exposes the same global
numbering. No firmware changes are needed for additional units. Physical buttons
continue to control exactly their own box's four outputs.

## Recorded DAC 4 result (Unit 1)

The prior Unit 1 / DAC 4 visible test is
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

## Recorded two-unit bench

The ordered local configuration maps Unit 1 to DAC 1–4 and Unit 2 to DAC 5–8. The Keysight is on DAC 5. Unit 1 has USB
power only while the external supply is on Unit 2; its network can respond
while its DAC readbacks are unavailable. A green network signal reports
communication only. The operation label reports **Readback unavailable** when
the unit reports a DAC error. Do not interpret that condition as measured zero.

The visible [Unit 2 / DAC 5 notebook](../notebooks/unit2_dac5_acceptance.ipynb)
contains every test step, checks a small physical step before the full sweep,
and sends output/recovery actions only to Unit 2. Run on an isolated bench:

```powershell
./.venv-bench/Scripts/python.exe malab/tools/run_modular_checks.py --live --isolated --notebook unit2_dac5_acceptance.ipynb
```

Unit 2 has its own firmware identity and nominal calibration; Unit 1's measured
CH1 correction is not reused. Serial-selected DFU upload instructions are in
the firmware repository's software installation guide.


The 2026-10-16 DAC 5 run passed ramp timing/relative paths, network hold/reset/
abort and safe-zero slew/latch/rearm. Absolute set/get, ramp endpoint and safe-zero
accuracy **failed ±0.5 mV**: maximum request/display errors 2.459040/2.535334 mV,
final stored-zero reading +0.654471 mV. The diagnostic fit remains unapplied.
Only DAC 5 has analog evidence on Unit 2. See
[recorded evidence](../../tests/evidence/2026-10-16-unit2-dac5/).

See [local configuration](../../config/README.md) to add more units without source changes.

## Recorded three-unit bench

The ordered ignored configuration now contains three units, giving DAC 1–4,
5–8 and 9–12. Only Unit 3 has the external analog supply. The Keysight is wired
to **global DAC 10 (Unit 3, local channel 2)**. Units 1 and 2 remain reachable
on USB/network but report unavailable analog readbacks; this is expected with
their analog supplies off. The dashboard reads this configuration at launch.
Reload http://localhost:8765 after restarting an idle server with changed settings.

The [Unit 3 / DAC 10 notebook](../notebooks/unit3_dac10_acceptance.ipynb)
contains the preflight, eleven set/get points, six bidirectional ramps, network
reset/disconnect/abort and safe-zero checks directly in its cells. Recovery
commands target Unit 3 only; safe zero uses the current 0.02 V/s rate. The
network test checks that both other units remain reachable. Run only with the
meter on DAC 10 and all Unit 3 outputs isolated:

```powershell
./.venv-bench/Scripts/python.exe malab/tools/run_modular_checks.py --live --isolated --notebook unit3_dac10_acceptance.ipynb
```

This run uses Unit 3's nominal calibration. Absolute voltage errors remain
subject to the same ±0.5 mV criterion. Measurements and any failures are in the
[Unit 3 evidence](../../tests/evidence/2026-10-16-unit3-dac10/); no correction is
applied by the notebook. Only DAC 10 is connected to the meter. USB recovery
emulation verifies firmware actions rather than the physical button contacts.

## Per-channel resistor and current controls

Open **Add resistor** on any channel, enter its total effective load resistance
in **ohms**, and select **Save resistor**. That channel shows calculated **mA**
as its primary reading, with voltage underneath. Its target and **Set current**
use mA; its ramp speed uses **mA/s**. Edit or remove the resistor in the same
panel. Saving/removing a resistance sends no output command. A mode change
converts any existing target/rate to preserve its voltage meaning.

The conversion is `current_mA = 1000 * voltage / resistance_ohms`. It assumes
the entered resistance is across the DAC output. This is a calculated current,
not current feedback or a direct ammeter reading. The Keysight stays in voltage
mode; its panel also calculates mA when its channel has a resistor. Its voltage
accuracy comparison remains in mV. The history selector offers voltage for all
channels or current for channels with resistors. Stored history retains the
resistance used at each sample, with gaps at setting changes.

Settings live only in ignored `config/resistors.local.json`, keyed by physical
unit address and local channel. They survive restart and global channel
reordering. The firmware and physical buttons are unchanged. SAFE ZERO remains
0.02 V/s, equivalent to `20 / resistance_ohms` mA/s for a resistive load. Existing
voltage calibration errors also affect the calculated current.

Both `AD5780` and `DACArray` provide these Python methods on an existing client:

```python
dacs.add_resistor(2, 1000)         # ohms; save only, output unchanged
dacs.get_resistance(2)            # ohms or None
dacs.get_current(2)               # calculated mA from register-derived voltage
dacs.get_current_limits(2)        # voltage limits converted to mA
dacs.set_current(2, 1.5)          # mA -> 1.5 V for this 1000-ohm load
dacs.ramp_current(2, 0, 0.1)      # target mA, speed mA/s; existing ramp options apply
dacs.remove_resistor(2)           # save only, output unchanged
```

For `AD5780`, the channel is local 1–4. For `DACArray`, it is global 1–4N in
the active address-list order. Explicit `set_voltage/get_voltage/ramp` retain
their original units in the Python API. Current commands validate resistance,
finite targets/rates and device voltage limits. The dashboard also rejects
outdated mode/resistance requests, changing resistance during an active operation,
and current actions without a fresh network response. No output command is retried.
Use the dashboard or a separate connected Python controller as the unit's owner,
not both simultaneously.

All regression cases are directly visible in
[resistor_current_tests.ipynb](../notebooks/resistor_current_tests.ipynb). They
use temporary settings and simulated instruments; no live outputs are changed:

```powershell
./.venv-bench/Scripts/python.exe malab/tools/run_modular_checks.py --offline-notebook resistor_current_tests.ipynb
```

The active local bench now contains two units in the user's selected order,
giving DAC 1–4 and DAC 5–8. The meter is on DAC 2 (the former global DAC 10).
Historical acceptance notebooks retain their original unit/channel numbering;
their mapping preconditions must match before they can be run live again.

## Channel names

Select **Rename** beside a channel's DAC number, enter a name, and select
**Save name**. **Cancel** discards the draft; **Reset** restores the default
`DAC N` name. Names appear on the card, meter panel, ramp status and history
legend. The numeric channel, unit and local channel remain visible for routing.

Both `AD5780` (local channels 1–4) and `DACArray` (global channels 1–4N) support:

```python
dacs.set_label(2, "Bias coil")
name = dacs.get_label(2)           # "Bias coil", or "" if unset
dacs.set_label(2, "")              # clear the custom name
```

Labels are trimmed, single-line text of at most 80 characters. They are saved
in ignored `config/labels.local.json`, keyed by physical address/local channel,
and follow that output when the unit list is reordered. Saving a label works
without an instrument connection and never sends an output/recovery command.
Labels do not change channel numbers, resistor values or firmware. They render
as plain text, including punctuation and HTML-like text.

The [label notebook](../notebooks/channel_label_tests.ipynb) contains four visible
offline cases for API persistence/reordering, validation/reset, dashboard routing
without hardware I/O, and JavaScript Rename/Save/Cancel/Reset behavior:

```powershell
./.venv-bench/Scripts/python.exe malab/tools/run_modular_checks.py --offline-notebook channel_label_tests.ipynb
```
