# Laser Control

A small desktop app for controlling the lab laser over a serial (COM) port. It has two modes:

- **Camera:** the laser is pulsed and its power follows the camera's analog signal, calibrated at 50 mW.
- **Manual:** continuous output at a power you set on a dial.

A round key turns the laser on and off. Built with Python, Tkinter and Pillow; it runs on Windows 11 x64 and can be developed on macOS.

> **Safety.** This software is not an interlock. If the USB cable is unplugged or the app crashes, the laser keeps its last state.
>
> The laser cannot report whether it is emitting, so the app only shows **Off** once the laser has answered an off command.
> - After connecting, the state is **Unknown** until you press the key once, which sends off.
> - If an off cannot be confirmed (cable pulled, laser silent), the app shows **May still be on** in red until a later off is confirmed.
> - While connected, Esc (with the window focused) and the key both send off whenever the laser is on or its state is unknown.

## Requirements

- **Python 3.12 or 3.13 with Tk 8.6.** The python.org installers include it. Some pyenv and Homebrew builds don't.
- **pyserial and Pillow**, installed automatically.
- **The laser's USB-serial driver** on the PC. Check the COM number in Device Manager → Ports (COM & LPT).

## Quick start

**Windows**, with Python 3.13 x64 from python.org:

```bat
py -3.13 -m venv .venv
.venv\Scripts\activate
pip install -c packaging\constraints.txt -e ".[dev]"
python -m laser_control --port COM3
```

**macOS**, with the python.org 3.13 installer:

```sh
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3.13 -m venv .venv
source .venv/bin/activate
pip install -c packaging/constraints.txt -e ".[dev]"
python -m laser_control --simulate
```

**Command-line options:**

| Option | What it does |
|---|---|
| `--simulate` | Use a simulated laser instead of real ports. `LASER_CONTROL_SIM=1` does the same. |
| `--port COM3` | Preselect a port. |
| `--timeout 2.0` | Serial read/write timeout in seconds, for this run only. |
| `--poll-ms 1000` | How often the set point and current are read, for this run only. |
| `--debug` | Log every serial line. |
| `--smoke-test` | Draw the window against the simulator and exit 0. Checks a build without a laser. |

**Simulated ports** (`--simulate`):

| Port | Behaves like |
|---|---|
| `SIM1` | A working laser |
| `SIM-INTERLOCK` | Refuses to turn on |
| `SIM-SILENT` | Never answers |
| `SIM-BUSY` | Port held by another app |
| `SIM-SMALL` | Max 40 mW, so Camera mode fails |

## Using it

1. **Connect.** Pick the port from the list and press **Connect**.
   - The list is re-scanned every time you open it, and ⟳ refreshes it.
   - If the port is wrong, press **Cancel**.
   - The selected mode (Camera or Manual) is applied as soon as the laser answers.
2. **Press the round key once.** The laser state starts as **Unknown**; this press sends off and confirms it.
3. **Manual mode:** set the power on the dial. You can:
   - drag the dial;
   - use − / + (hold Shift for 1 mW steps), the arrow keys or the mouse wheel;
   - click the reading and type a value.

   Then press **Apply** or Enter. Values above nominal turn red and are applied with a warning. A value you don't apply is never sent: switching modes uses the last applied power.
4. **Camera mode:** there is no power control, because the camera drives the laser (calibrated at 50 mW). Clicking Camera again repeats the calibration.
5. **Turn the laser on** with the round key. While it emits:
   - the key stays pressed in;
   - the laser card, the window border and the title bar turn amber.

   Switching mode keeps the laser on.
6. **Turn it off** with the key or with **Esc**. Disconnecting and closing the window also turn it off first. If the laser doesn't confirm, the app asks before closing.

**Settings and logs:**
- Settings (last port, last applied power) are kept in:
  - Windows: `%APPDATA%\LaserControl\config.json`
  - macOS: `~/Library/Application Support/LaserControl/config.json`
- Logs go to `logs/laser_control.log` in the same folder. Every laser command (connect, on, off, mode, power, disconnect) is logged with its result.

## Tests

No hardware is needed: the tests run the real driver against a simulated serial port.

```sh
pytest -q                                   # everything, about 10 s
pytest tests/test_sequences.py -q           # the exact commands each laser sequence sends
pytest tests/test_controller.py -k interlock
pytest tests/test_ui.py -q                  # real-window click and drag tests (needs a display)
```

`tests/test_sequences.py` asserts the exact bytes each sequence sends. If the laser logic ever drifts from the reference script, a test fails.

## Building the Windows app

PyInstaller cannot cross-compile, so the `.exe` must be built on Windows. Either:

- **On a Windows PC:** run `packaging\build_windows.bat` from the repo root. It:
  1. creates a venv with the pinned versions in `packaging/constraints.txt`;
  2. runs the tests;
  3. builds `dist\LaserControl\LaserControl.exe` (one folder) and checks it with `--smoke-test`;
  4. if Inno Setup 6 is installed, builds `packaging\Output\LaserControl-Setup-<version>.exe`. The installer is per-user, needs no admin rights, and replaces old runtime files cleanly on upgrade.
- **With GitHub Actions:** push a tag like `v0.1.0`, or run the **build-windows** workflow from the Actions tab. It tests on Windows and macOS, builds and smoke-tests the exe and the installer, and uploads both as artifacts.

The **tests** workflow runs the test suite on every push and pull request.

**Unsigned exe:**
- On first launch, Windows SmartScreen shows "Windows protected your PC". Choose **More info → Run anyway**.
- If you downloaded a zip, right-click it → Properties → **Unblock** before extracting.
- If *Smart App Control* is on (Windows Security → App & browser control), it can block unsigned apps outright. That needs code signing, or switching Smart App Control off.

**Version.** The version lives in one place: `__version__` in `src/laser_control/__init__.py`. The package, the build script, CI and the installer all read it from there.

## How it works

```
src/laser_control/
  driver.py      serial driver supplied with the project, unchanged apart from the class name
  sequences.py   the laser command sequences: the only code that changes the laser's state
  worker.py      the one thread that owns the serial port; jobs run in priority order (Off first)
  controller.py  state machine, polling, and the API the window calls (all on the Tk thread)
  model.py       immutable state snapshot and message types shared with the window
  errors.py      turns driver exceptions and warnings into plain messages
  sim.py         simulated laser that replaces the serial port, not the driver
  app.py         entry point: command line, logging, safe shutdown
  ui/            the window, drawn on one Tk canvas with Pillow-rendered shapes and icons
  assets/        window icons
tests/           pytest suite (simulator-based, plus real-window tests)
packaging/       PyInstaller spec, Inno Setup script, Windows build script, pinned versions
resources/       app icon artwork (.ico, .icns, PNGs 16–1024) used for the exe and installer
.github/         CI: tests on every push; Windows build on tags
```

**Rules the code relies on:**
- **One serial thread.** Every command gets exactly one reply line, so only the worker thread ever talks to the port. The window never blocks waiting for the laser.
- **Off must be confirmed.** The driver reports success for a command even when nothing answers. So after `off()` the app reads the laser's status, and only an answer counts as Off.
- **Off goes first.** Off jumps ahead of everything else in the queue and cancels any queued turn-on. Queued mode and power changes still run, with the laser off.
- **Mouse input survives redraws.** The window redraws from the current state on every change, and clicks and drags are tracked on the canvas itself, so a status update arriving mid-click can't swallow it.

**Open decision.** The reference script's line `laser.analog_control_mode = …` assigns to a method, so nothing is sent to the laser. The app keeps that behaviour (`ANALOG_MODE_POLICY = AS_WRITTEN` in `sequences.py`). Changing that one line to `CALL_AFTER_PULSED` sends the real analog-current command after the switch to pulsed mode.

## License

MIT; see `LICENSE`. The serial driver in `src/laser_control/driver.py` is also MIT-licensed; its notice is in `LICENSES/driver-MIT.txt`.
