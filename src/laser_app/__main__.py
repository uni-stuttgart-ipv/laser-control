"""Entry point: ``python -m laser_app [--simulate] [--log-level DEBUG]``."""

from __future__ import annotations

import argparse
import importlib
import logging
import sys
from logging.handlers import RotatingFileHandler

from . import __version__
from .config import load_settings, log_dir
from .controller import LaserController
from .hardware.ports import PortInfo, list_serial_ports
from .hardware.simulator import SIM_PORT, simulated_laser


def setup_logging(level: str) -> None:
    """Log to stderr (when there is one) and to a rotating file in ``log_dir()``."""
    root = logging.getLogger()
    root.setLevel(level)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(threadName)s %(name)s: %(message)s")
    if sys.stderr is not None:          # packaged GUI apps may have no console
        console = logging.StreamHandler()
        console.setFormatter(fmt)
        root.addHandler(console)
    try:
        d = log_dir()
        d.mkdir(parents=True, exist_ok=True)
        fh = RotatingFileHandler(d / "laser_control.log", maxBytes=1_000_000, backupCount=5, encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)
    except OSError:
        root.warning("File logging disabled (log folder not writable).")


def main(argv: list[str] | None = None) -> int:
    """Parse arguments, start the controller, run the GUI and shut down. Returns the exit code."""
    parser = argparse.ArgumentParser(prog="laser_app", description="Laser Control: desktop app for the lab laser")
    parser.add_argument("--simulate", action="store_true", help="use a simulated laser (no hardware)")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    # parse_known_args: a packaged app may be started with extra OS arguments.
    args, unknown = parser.parse_known_args(argv)

    setup_logging(args.log_level)
    if unknown:
        logging.getLogger(__name__).warning("Ignoring unknown arguments: %s", " ".join(unknown))
    logging.getLogger(__name__).info("Laser Control %s starting (simulate=%s)", __version__, args.simulate)

    if args.simulate:
        controller = LaserController(factory=simulated_laser)

        def ports() -> list[PortInfo]:
            return [PortInfo(SIM_PORT, "Simulated laser")]
    else:
        controller = LaserController()
        ports = list_serial_ports

    try:
        _prepare_tkinter()
        from .ui import run_app   # imported late so --help works without a display
    except ImportError as exc:
        logging.getLogger(__name__).critical("GUI libraries are not available: %s", exc)
        _fatal_dialog("Laser Control cannot start: a required component (Tkinter or "
                      f"Pillow) is missing from this build.\n\n{exc}\n\n"
                      "See docs/building.md in the source repository.")
        return 1

    controller.start()
    try:
        run_app(controller, load_settings(), ports)
    finally:
        controller.shutdown()
    return 0


def _prepare_tkinter() -> None:
    """In a Briefcase build, make the bundled Tkinter importable (see tools/collect_tk.py).

    Briefcase's Python for Windows and macOS ships without Tkinter; the build
    adds it back as the ``tkinter_runtime`` package. Running from source this
    package is absent (or harmless) and the normal Tkinter is used.
    """
    try:
        importlib.import_module("tkinter_runtime")   # side effect: paths + TCL/TK_LIBRARY
    except ModuleNotFoundError as exc:
        if exc.name != "tkinter_runtime":
            raise


def _fatal_dialog(text: str) -> None:
    """Show an error without Tk (it is what failed). Best effort, never raises."""
    try:
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, text, "Laser Control", 0x10)
        elif sys.platform == "darwin":
            import subprocess
            msg = text.replace("\\", "\\\\").replace('"', '\\"')
            subprocess.run(["osascript", "-e",
                            f'display alert "Laser Control" message "{msg}" as critical'],
                           timeout=60, check=False)
        elif sys.stderr is not None:
            print(text, file=sys.stderr)
    except Exception:
        pass


if __name__ == "__main__":
    sys.exit(main())
