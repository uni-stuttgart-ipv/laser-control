# Architecture

How Laser Control is put together. For running and building the app see the
[README](../README.md) and [building.md](building.md).

## Overview

```
 Tk main thread                          worker thread ("laser-worker")
┌───────────────────────┐   jobs     ┌───────────────────────────────────────┐
│ ui.app.App            │──────────▶ │ controller.LaserController            │
│  one tk.Canvas        │ (priority  │  owns the laser, polls it every 1 s   │
│  widgets + images     │   queue)   │  hardware.operations ─▶ laser.Laser   │──▶ serial port
│  drains events/50 ms  │ ◀──────────│  StatusEvent / MessageEvent           │
└───────────────────────┘   events   └───────────────────────────────────────┘
```

The code is in `src/laser_app/`, in three layers. Each layer only imports from
the layers below it.

| Layer | Modules | Job |
|---|---|---|
| UI | `ui/` | Draws the window and turns clicks into controller calls |
| Core | `controller.py`, `config.py` | Worker thread, job queue, safety rules, status; settings file |
| Hardware | `hardware/` | Serial driver, laser procedures, simulator, port list |

`__main__.py` wires them together: it parses the command line, sets up
logging, creates the controller (real or simulated laser) and starts the UI.

## Threading

- Tkinter is not thread-safe, and serial I/O can block. Only the worker thread
  ever talks to the laser.
- The UI calls non-blocking `LaserController` methods (`connect`, `turn_on`,
  `set_mode`, `apply_power`, …). Each one puts a job on a priority queue and
  returns at once.
- The worker reports back through `controller.events`: a `StatusEvent` carries
  a new immutable `Status` snapshot, a `MessageEvent` a line for the user. The
  UI drains the queue every 50 ms with `root.after` and calls `App.render()`.
- Safety jobs (turn off, disconnect, shutdown) run before user jobs and cancel
  every user job still waiting, so a queued "turn on" can never run after
  "turn off".

## Safety rules (controller)

- The laser is turned off when connecting, before every mode change, on
  disconnect, on shutdown and after any communication error.
- "Off" is always read back (`?L`). If it cannot be confirmed, the user is
  told to switch the laser off at the controller.
- Any error other than a refused command or bad input is treated as a broken
  link: laser off (as far as possible), then disconnect.
- Switching back to Manual restores the last manual power, never the 50 mW
  camera power; if it is outside the laser's limits, the laser's minimum is used.

## Laser driver and procedures (hardware/)

`hardware/laser.py` is the app's own serial driver for the laser's ASCII
protocol (19200 baud, lines end with CR LF):

| Exchange | Meaning |
|---|---|
| `?KEY` → `KEY=value` | Query, e.g. `?L` (emission), `?SP` (setpoint), `?C` (current), `?MINLP` / `?NOMP` / `?MAXLP` (power limits) |
| `KEY=value` → `KEY=value` | Command; the reply echoes the value actually applied |
| `L=1` → `L=0` + reason line | Emission refused, e.g. `Interlock open` |
| `CAL=value` → (nothing) | Pulsed-mode calibration has no reply |
| `?>` / `>=0` | Command prompt state; switched off while connected, restored on close |

`Laser` has one method per command. Every read is strict: no reply within
1 s, or a reply that cannot be parsed, raises `CommError`, so a silent laser
is never mistaken for a valid value. Opening a port runs a handshake (skip
any power-up banner, switch the prompt off, read the power limits) and
refuses a device that does not answer like the laser.

`hardware/operations.py` builds the procedures the controller uses on top of
it:

- **Verified off:** `L=0`, then `?L` must read 0; retried three times, then
  `CommError` ("could not confirm the laser is off").
- **Power check:** negative or above the laser's maximum raises
  `PowerRejected` before anything is sent; above nominal or below the minimum
  is sent with an advisory message. The app sets no limits of its own.
- **Manual set-up:** `CW=1` (continuous), `EXT=0` (internal control), then `P=<mW>`.
- **Camera set-up:** `EXT=1` (external control), `CW=0` (pulsed), `ANA=1`
  (current modulation), `P=50`, `CAL=50`. The laser accepts current
  modulation only in pulsed mode, so `ANA=1` comes after `CW=0`; if the laser
  does not confirm it, the set-up fails and the controller disconnects safely.

`hardware/simulator.py` models the laser's side of the same protocol
(`SimulatedDevice`) behind an in-memory serial port (`SimulatedPort`). The
simulator therefore runs the real driver, procedures and controller, both for
`--simulate` and in the tests; the tests also serve it on a pseudo-terminal to
cover real serial I/O.

## User interface (ui/)

Tk widgets cannot be translucent, so the window is **one `tk.Canvas`**:

- a pre-rendered opaque base image (gradient, warm glow and translucent tiles),
  one variant per mode because the Power tile only exists in Manual;
- canvas text items;
- pre-rendered RGBA images for every state of every control, cached and
  swapped when the state changes;
- one real widget, the power `tk.Entry`, placed over a flat area of the Power
  tile whose colour it matches.

| Module | Contents |
|---|---|
| `theme.py` | Every colour and overlay (design tokens). Change the look here. |
| `render.py` | Pillow drawing: background, tiles, pill and icon buttons, laser button, glyphs. No Tk. |
| `layout.py` | Window size and every position; the tile rectangles. |
| `text.py` | Font selection; power formatting/parsing; ellipsizing. |
| `widgets.py` | The canvas controls. `Control` is the base class: hit area, hover/pressed/disabled state, `command`, image swapping. |
| `app.py` | `App`: builds the widgets, routes mouse events, and `render()`s the latest `Status`. |

Shapes are drawn at 3× size and scaled down with LANCZOS, so curves stay
smooth on every platform. Control images have a transparent margin (`theme.M`)
so shadows and glows are not clipped.

`App.render()` is the only place that turns a `Status` into widget states.
It is cheap to call often, because each widget only touches the canvas when its
own state actually changed.

## Packaging

Briefcase builds include `src/laser_app`, the `dependencies` from
`pyproject.toml` and, on Windows and macOS, the
Tkinter copy made by `tools/collect_tk.py`. At startup `__main__._prepare_tkinter()` imports that
`tkinter_runtime` package, which points Python and Tcl/Tk at the bundled
files. See [building.md](building.md).
