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

- All four cards show volts derived from device codes. During a ramp the source
  says **last write**; idle values come from checked register reads. These are
  not independent analog measurements. A cold output can remain clamped while
  its register contains a nonzero value.
- The Keysight panel is the independent analog measurement of **CH1 only**.
  It compares against fresh idle CH1 data with the unchanged **±0.5 mV** limit.
  The comparison is suspended during ramps because samples are asynchronous.
- **Network good** is a passive signal based on a recent valid device response.
  It changes on connecting, disconnection, failure, or stale data. It does not
  claim that DAC analog output or calibration is correct.
- Stale numbers are dimmed and labeled. Unknown codes show a dash. CH2–4 use
  nominal calibration; their analog accuracy has not been measured.

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
all channels at at most **0.01 V/s**. Progress remains visible through USB while
Ethernet is paused. It remains latched at zero until a fresh NETWORK action.
These two GUI controls require COM5/bench firmware; physical buttons continue
to work independently of this server. Closing the browser leaves the server
running. Stopping the server closes its TCP connection and can stop a remote
ramp; device safe-zero continues independently.

Commands are serialized. Duplicate request IDs are not replayed. A timeout
reports an unknown outcome and never retries an output command. After restarting
the server, reload the page to obtain the new session token.

## Visible tests

`notebooks/dashboard_acceptance.ipynb` contains the complete test actions and
assertions for SET/GET accuracy, six ramps, network reset/hold, stop, and safe
zero from both signs. It uses the same HTTP actions/state as the page. Keep
Chrome open to observe it. Set both live-test flags only with all outputs
isolated. The notebook exercises CH1 from −9 to +10 V and small CH2–4 values.
It writes detailed readings and plots under `notebooks/results/dashboard_*`.
HTTP assertions validate the data path, not the browser rendering; the final
cell describes the separate visual check. Physical switch contacts and
unplugged-chip behavior are not certified by USB action emulation.

Offline controller checks:

```powershell
./.venv-bench/Scripts/python.exe -m unittest discover -s malab/dashboard/tests -v
```
