# Laser Control

A small desktop app for the lab laser, connected over a serial (COM) port. It uses the [`coherent-cube`](https://pypi.org/project/coherent-cube/) library to control a Coherent Cube laser.

It has two modes:

- **Camera:** the laser is pulsed, and its power follows the camera's analog signal, calibrated at 50 mW.
- **Manual:** continuous output at a power you set on a dial, up to 50 mW.

One round key turns the laser on and off. Built with Python and Tkinter for Windows 11; developed on macOS.

> **Safety.** This app is not an interlock. If the USB cable is unplugged or the app crashes, the laser keeps its last state.
> Turn the laser off with the round key, **Disconnect**, or by closing the window. There is no keyboard shortcut for it.
> **Choosing Camera or pressing Reset turns the laser on** (also when connecting in camera mode): 1 s continuous at 50 mW, then pulse mode.

## Run it

**Windows**, with Python 3.13 x64 from python.org:

```bat
py -3.13 -m venv .venv
.venv\Scripts\activate
pip install -e .
python -m laser_control
```

**macOS** (no laser, for working on the code). Use a Python that includes Tk 8.6, such as the python.org installer:

```sh
python3.13 -m venv .venv
source .venv/bin/activate
pip install -e .
python -m laser_control
```

## Using it

1. Pick the laser's port (COM3 on the lab PC) and press **Connect**. If the laser doesn't answer, connecting can take up to a minute before it shows an error: the library tries 10 times, waiting 5 seconds each time.
   - On connect, the app turns the laser off.
   - It then applies the selected mode.
2. **Manual mode:** set the power. Each change is sent to the laser automatically:
   - **drag the dial:** sent 0.5 s after you let go;
   - **− and +:** sent 0.5 s after the last click (Shift + click steps by 1 mW);
   - **arrow keys or the mouse wheel:** sent the same way, 0.5 s after the last change;
   - **click the reading and type a value:** sent on Enter.

   "Applied ✓" shows when the laser has the value. The range is the laser's minimum up to 50 mW.
3. **Camera mode:** there is no power control. The camera drives the laser.
   - Choosing Camera, from off or from Manual, first runs the laser **continuous at 50 mW for 1 s**, then switches to pulse mode and calibrates at 50 mW. The laser stays on.
   - **Reset** (the round ↻ key, left of the on/off key on the laser card, camera mode only) runs this again: 1 s continuous at 50 mW, calibrate, pulse mode. The laser is on afterwards. It is greyed out before connecting and until a reset has finished.
   - Why: `calibrate(50)` takes the laser's output at that moment to be 50 mW. Calibrated in the dark, camera mode stays almost dark (measured: 0.06 mW, against about 21 mW).
4. **Turn the laser on** with the round key. While it emits, the key, the window border and the title bar turn amber. You can switch mode while it's on; it stays on.
5. **Turn it off** with the key.

If the laser refuses to turn on (for example, the interlock is open), the app shows the laser's reason and stays connected. If the connection is lost, the app shows the error and closes the port.

## Log tab and log file

The **Log** tab, next to **Laser** at the top, shows what has happened, newest at the bottom:

- **By default:** one plain line per event ("Laser on", "Power set to 12.5 mW"). Warnings are amber, errors red.
- **☐ Technical:** every line: each command the app sent (`writing L=1`), each reply from the laser (`recieved b'L=1\r\n'`), and full errors. The time is to the millisecond.
- **Copy** copies the lines shown, for example to send to someone. The tab keeps the last 500 lines of each view.

The header stays on both tabs, so you can always see whether the laser is emitting. On the Log tab, ↑/↓ and the mouse wheel scroll the log; they never change the power there.

Everything is also saved, with times to the millisecond, in:

- **Windows:** `C:\Users\<you>\LaserControl\laser_control.log`
- **macOS:** `~/LaserControl/laser_control.log`

The log also records each action (`connect`, `turn_on`, …) and the full error when one fails. A reply that never arrived shows as `recieved b''` (the spelling is the library's). After 1 MB the file starts again, and the last 3 files are kept as `.log.1` to `.log.3`. Send the log along when reporting a problem.

## How it is built

```
src/laser_control/
    __main__.py     starts the app; closing the window turns the laser off
    controller.py   the only module the window talks to; runs laser commands on one background thread
    manual.py       manual mode (continuous, power from the window)
    camera.py       camera mode: 1 s continuous at 50 mW, then pulsed, external control, calibrated
    ports.py        lists the serial ports for the dropdown
    log.py          saves every laser command and reply to the log file
    ui/
        window.py   MainWindow: builds the window, user actions, collects results every 100 ms
        state.py    State: what the screen shows, and what each controller result changes
        buttons.py  makes the drawn buttons clickable (hover, press, click)
        power.py    the 7 ways to change the power, and the 0.5 s auto-send
        log_view.py the Log tab's lines, the Technical view, scrolling and Copy
        paint.py    shared drawing helpers and layout sizes
        sections/   one file per part of the window (tab_bar, header, port_row, mode_bar,
                    power_card, laser_card, message, readouts, log_card)
        art.py      draws the soft shapes, icons and dial with Pillow
        theme.py    colours and fonts
        chrome.py   amber Windows 11 title bar while emitting
    assets/         window and app icons
packaging/          PyInstaller spec, Inno Setup script, Windows build script
```

- **The controller and the window.** The window calls the controller's methods (`connect`, `turn_on`, `set_power`, …), and each one only puts a job on a queue.
- **One background thread.** A single thread runs the jobs one at a time, so the window never freezes and laser commands never overlap.
- **Results.** The window collects what happened every 100 ms with `get_results()`.
- **Power limits.** `MAX_POWER_MW` and `CAMERA_POWER_MW` are set at the top of `controller.py`.

**Note on `analog_control_mode`.** `camera.py` sets `laser.analog_control_mode = cc.AnalogControlMode.Current`. In the library, `analog_control_mode` is a method, not a property, so this assignment sends nothing to the laser; the laser keeps its stored analog mode (current mode, `ANA=1`, on the lab laser).

**Version.** Set it in one place: `__version__` in `src/laser_control/__init__.py`.

## Tests

No laser needed: the tests use a fake laser that records every command instead of sending it.

```sh
pip install -e ".[dev]"
pytest -q
```

| File | Checks |
|---|---|
| `tests/test_modes.py` | `manual.py` and `camera.py` send the expected commands in order; camera mode runs 1 s at 50 mW before calibrating |
| `tests/test_ports.py` | port names come back in order (COM3 before COM10) |
| `tests/test_controller.py` | connect, on/off, interlock refusal, power limits, switching mode while on, lost connection, disconnect, closing |
| `tests/test_log.py` | the log file, the plain-words line for every result, the feed to the Log tab |
| `tests/test_log_tab.py` | the two views, 500 lines each, scrolling and New lines, Copy, arrows, tab height, wrapping |
| `tests/test_state.py` | what each laser result does to the screen, and when Reset shows and is locked (no window needed) |
| `tests/test_window.py` | auto-send after 0.5 s, dial drag, typed values, limits, mode switch while on, camera Reset, Esc does not turn the laser off |

The build script and GitHub Actions run the tests first, and stop if any fail.

## Building the Windows installer

PyInstaller can't build a Windows app from macOS, so build on Windows. There are two ways:

- **On a Windows PC:** run `packaging\build_windows.bat` from the project folder. It:
  - installs the pinned versions from `packaging/constraints.txt`;
  - builds `dist\LaserControl\LaserControl.exe`;
  - builds `packaging\Output\LaserControl-Setup-<version>.exe` if Inno Setup 6 is installed.
- **On GitHub Actions:** push a tag such as `v0.1.0`, or run the `build-windows` workflow from the Actions tab. The exe folder and the installer are uploaded as artifacts.

The installer is per-user and needs no admin rights. The exe is unsigned, so the first time it starts, Windows shows "Windows protected your PC": choose **More info → Run anyway**.

The laser's USB-serial driver must be installed. Find its COM number in Device Manager → Ports (COM & LPT).

## Licence

MIT; see `LICENSE`.
