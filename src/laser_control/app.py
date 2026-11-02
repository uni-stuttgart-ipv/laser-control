"""Application entry point: command line, logging, wiring and safe shutdown.

Usage::

    laser-control [--simulate] [--port COM3] [--timeout 2.0] [--poll-ms 1000] [--debug]

``LASER_CONTROL_SIM=1`` in the environment is the same as ``--simulate``.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import tkinter as tk
from importlib import resources
from logging.handlers import RotatingFileHandler
from tkinter import messagebox

from laser_control import __version__
from laser_control.config import AppConfig, config_dir, load_config, save_config
from laser_control.controller import LaserController
from laser_control.model import ConnState, Mode, Snapshot
from laser_control.ports import pick_default
from laser_control.ui import MainWindow
from laser_control.ui.chrome import enable_dpi_awareness

logger = logging.getLogger("laser_control")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="laser-control", description="Control the laser over a serial port.")
    parser.add_argument("--simulate", action="store_true",
                        help="use a simulated laser instead of real serial ports")
    parser.add_argument("--port", help="serial port to preselect, e.g. COM3")
    parser.add_argument("--timeout", type=float, help="serial read/write timeout in seconds (default 2)")
    parser.add_argument("--poll-ms", type=int, help="status poll interval in milliseconds (default 1000)")
    parser.add_argument("--debug", action="store_true", help="log every serial line")
    parser.add_argument("--smoke-test", action="store_true",
                        help="build the window against the simulator, then exit 0 (used by CI on the packaged exe)")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser.parse_args(argv)


def setup_logging(debug: bool) -> None:
    """Log to a rotating file in the settings folder (the windowed exe has no console)."""
    log_dir = config_dir() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(log_dir / "laser_control.log", maxBytes=1_000_000, backupCount=3,
                                  encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(threadName)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if debug else logging.INFO)
    root.addHandler(handler)
    if sys.stderr is not None:
        console = logging.StreamHandler()
        console.setLevel(logging.WARNING)
        root.addHandler(console)
    # The driver logs every serial line at INFO; keep that only when debugging.
    logging.getLogger("laser_control.driver").setLevel(logging.INFO if debug else logging.WARNING)


def _quiet_unraisable(hook_args) -> None:
    """The driver's ``__del__`` raises AttributeError if its constructor failed; that is harmless."""
    if isinstance(hook_args.exc_value, AttributeError) and "__del__" in repr(hook_args.object):
        logger.debug("ignored: %r", hook_args.exc_value)
        return
    sys.__unraisablehook__(hook_args)


ICON_SIZES = (256, 64, 32, 16)
"""PNG sizes shipped in ``assets/``; the OS picks the best one for title bar, taskbar or dock."""


def _set_icon(root: tk.Tk) -> None:
    """Set the window icon from ``assets/`` (the artwork originals live in ``resources/``)."""
    try:
        assets = resources.files("laser_control") / "assets"
        if sys.platform == "win32":
            # A multi-size .ico gives Windows crisp 16/24/32/48 px versions for the title bar and taskbar.
            with resources.as_file(assets / "laser_control.ico") as ico:
                root.iconbitmap(default=str(ico))
        else:
            photos = []
            for size in ICON_SIZES:
                with resources.as_file(assets / f"laser_control-{size}.png") as png:
                    photos.append(tk.PhotoImage(master=root, file=str(png)))
            root.iconphoto(True, *photos)
            root._icon_photos = photos  # keep a reference so Tk never loses the images
    except Exception as exc:
        logger.debug("no window icon: %r", exc)


def smoke_test() -> int:
    """Check that a build can import everything and draw the window, without hardware.

    Returns:
        0 on success, 1 on any error (details in the log).
    """
    try:
        from laser_control import sim
        sim.install()
        root = tk.Tk()
        root.withdraw()
        controller = LaserController(root, port="SIM1", timeout_s=0.2)
        window = MainWindow(root, controller)
        root.update()
        assert window.height > 0
        root.destroy()
        logger.info("smoke test passed")
        return 0
    except Exception:
        logger.exception("smoke test failed")
        return 1


def main(argv: list[str] | None = None) -> None:
    """Start the app and block until the window is closed."""
    args = parse_args(argv)
    if args.smoke_test:
        setup_logging(args.debug)
        sys.exit(smoke_test())
    simulate = args.simulate or os.environ.get("LASER_CONTROL_SIM") == "1"
    setup_logging(args.debug)
    sys.unraisablehook = _quiet_unraisable
    logger.info("Laser Control %s starting (simulate=%s)", __version__, simulate)

    cfg = load_config()
    # Command-line overrides apply to this run only; they are never saved.
    timeout_s = args.timeout if args.timeout is not None else cfg.timeout_s
    poll_ms = args.poll_ms if args.poll_ms is not None else cfg.poll_interval_ms
    if simulate:
        from laser_control import sim
        sim.install(realtime=True)

    enable_dpi_awareness()
    root = tk.Tk()
    root.report_callback_exception = _log_tk_exception
    _set_icon(root)

    from laser_control.ports import list_ports
    port = args.port or pick_default(list_ports(simulate=simulate), "SIM1" if simulate else cfg.last_port)
    controller = LaserController(root, port=port, manual_power_mw=cfg.last_power_mw, timeout_s=timeout_s,
                                 poll_interval_ms=poll_ms, simulate=simulate)
    window = MainWindow(root, controller, title_suffix=" (simulation)" if simulate else "")
    controller.subscribe(lambda snap: _remember(cfg, controller, snap, simulate))
    root.report_callback_exception = lambda *exc: (_log_tk_exception(*exc), window.show_internal_error())

    def done() -> None:
        try:
            if not simulate:
                save_config(cfg)
        except Exception:
            logger.exception("could not save settings")
        finally:
            root.destroy()

    def unsafe(still_running: bool) -> None:
        if still_running:
            text = ("The laser has not confirmed it is off yet.\n\n"
                    "Close anyway? Choose No to keep waiting.")
        else:
            text = ("The laser did not confirm the off command and may still be emitting. "
                    "Check the laser.\n\nClose anyway? Choose No to stay in the app.")
        if messagebox.askyesno("Laser may still be on", text, icon="warning", parent=root):
            done()
        elif still_running:
            controller.shutdown(on_done=done, on_unsafe=unsafe)  # keep waiting, with a new deadline
        else:
            controller.cancel_shutdown()

    root.protocol("WM_DELETE_WINDOW", lambda: controller.shutdown(on_done=done, on_unsafe=unsafe))
    # Windows logoff/shutdown: Tk reports the session ending as WM_SAVE_YOURSELF. There is no
    # time for dialogs, so send off and close straight away.
    root.protocol("WM_SAVE_YOURSELF", lambda: (_emergency_off(controller), root.destroy()))
    try:
        root.mainloop()
    finally:
        _emergency_off(controller)
        logger.info("Laser Control stopped")


def _remember(cfg: AppConfig, controller: LaserController, snap: Snapshot, simulate: bool) -> None:
    """Keep the settings in step with what actually worked."""
    if simulate or snap.conn is not ConnState.CONNECTED:
        return
    cfg.last_port = snap.port
    if snap.mode is Mode.MANUAL and snap.applying is None:
        cfg.last_power_mw = controller.manual_power_mw  # last *applied* manual power


def _log_tk_exception(exc_type, exc, tb) -> None:
    """Tk swallows callback errors in a windowed exe (no stderr); send them to the log."""
    logger.error("unhandled error in a Tk callback", exc_info=(exc_type, exc, tb))


def _emergency_off(controller: LaserController) -> None:
    """Last resort when the main loop ends without a clean shutdown (crash, Ctrl+C, logoff).

    Queues a shutdown job and waits briefly for the worker to send off and close.
    """
    worker = controller._worker
    if not worker.is_alive() or controller.snapshot.conn not in (ConnState.CONNECTED, ConnState.DISCONNECTING,
                                                                  ConnState.SHUTTING_DOWN):
        return
    from laser_control.worker import Job, JobKind, Priority
    logger.warning("main loop ended without a clean shutdown; sending off")
    worker.generation += 1
    worker.submit(Job(JobKind.SHUTDOWN, priority=Priority.SHUTDOWN, generation=worker.generation))
    worker.stop_when_idle()
    worker.join(timeout=5)


if __name__ == "__main__":
    main()
