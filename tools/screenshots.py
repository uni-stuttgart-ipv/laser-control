"""Regenerate the README screenshot (``docs/screenshots/overview.png``).

Runs the real window against the simulated laser, walks through four states
(not connected, Manual with the laser on, Camera, a refused power value) and
saves them side by side::

    python tools/screenshots.py            # writes docs/screenshots/overview.png
    python tools/screenshots.py --out shots   # also keeps each state as its own PNG

Needs a desktop session (on Linux: an X display, e.g. ``xvfb-run``; on macOS
the terminal needs the Screen Recording permission). Your saved settings are
not touched.
"""

from __future__ import annotations

import argparse
import sys
import time
import tkinter as tk
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from PIL import Image, ImageGrab  # noqa: E402

from laser_app.config import Settings  # noqa: E402
from laser_app.controller import LaserController, Mode  # noqa: E402
from laser_app.hardware.ports import PortInfo  # noqa: E402
from laser_app.hardware.simulator import simulated_laser  # noqa: E402
from laser_app.ui import app as app_module  # noqa: E402

PORTS = [PortInfo("COM3", "USB Serial Device (COM3)")] + \
    [PortInfo(f"COM{i}", detected=False) for i in range(1, 21) if i != 3]
STATES = ["disconnected", "manual-on", "camera-on", "power-refused"]


def _pump(root: tk.Tk, secs: float, until=None) -> None:
    end = time.monotonic() + secs
    while time.monotonic() < end:
        root.update()
        if until is not None and until():
            return
        time.sleep(0.01)
    if until is not None and not until():
        raise RuntimeError("the app did not reach the expected state")


def capture_states() -> dict[str, Image.Image]:
    """Drive the simulated app through ``STATES`` and grab the window in each."""
    app_module.save_settings = lambda settings: None        # leave real settings alone
    ctl = LaserController(factory=simulated_laser, poll_interval_s=0.2)
    ctl.start()
    root = tk.Tk()
    root.geometry("+0+0")
    app = app_module.build_app(root, ctl, Settings(last_port="COM3"), lambda: list(PORTS))
    idle = lambda: app.status.connected and not app.status.busy   # noqa: E731

    def grab() -> Image.Image:
        _pump(root, 0.8)
        x, y = root.winfo_rootx(), root.winfo_rooty()
        return ImageGrab.grab(bbox=(x, y, x + root.winfo_width(), y + root.winfo_height()))

    shots = {}
    try:
        shots["disconnected"] = grab()
        app.toggle_connect()
        _pump(root, 5, idle)
        app.power.var.set("12")
        app.apply_manual()
        _pump(root, 3, lambda: app.status.setpoint_mw == 12.0)
        app.toggle_laser()
        _pump(root, 3, lambda: app.status.emitting)
        shots["manual-on"] = grab()
        app.on_mode(Mode.CAMERA)
        _pump(root, 5, lambda: app.status.mode is Mode.CAMERA and idle())
        app.toggle_laser()
        _pump(root, 3, lambda: app.status.emitting)
        shots["camera-on"] = grab()
        app.toggle_laser()
        _pump(root, 3, lambda: not app.status.emitting)
        app.on_mode(Mode.MANUAL)
        _pump(root, 5, lambda: app.status.mode is Mode.MANUAL and idle())
        app.power.var.set("70")
        app.power.entry.focus_force()
        app.apply_manual()
        _pump(root, 3, lambda: app._power_error is not None)
        shots["power-refused"] = grab()
    finally:
        root.destroy()
        ctl.shutdown()
    return shots


def side_by_side(images: list[Image.Image], gap: int = 10, width: int = 1400) -> Image.Image:
    """The images in a row on white, ``gap`` px apart, scaled to ``width``."""
    w = sum(i.width for i in images) + gap * (len(images) - 1)
    h = max(i.height for i in images)
    sheet = Image.new("RGB", (w, h), "white")
    x = 0
    for img in images:
        sheet.paste(img, (x, 0))
        x += img.width + gap
    return sheet.resize((width, round(h * width / w)), Image.LANCZOS)


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, help="also save each state as <out>/<state>.png")
    args = parser.parse_args(argv)
    shots = capture_states()
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        for name, img in shots.items():
            img.save(args.out / f"{name}.png")
    target = ROOT / "docs" / "screenshots" / "overview.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    side_by_side([shots[s] for s in STATES]).save(target)
    print("saved", target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
