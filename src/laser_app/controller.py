"""LaserController: the object the GUI drives (plus ``Mode``, ``Status`` and ``validate_power``).

Tkinter is not thread-safe and serial I/O can block, so one background worker
thread owns the laser. GUI calls just enqueue a job and return immediately;
results come back as events on ``controller.events`` which the GUI drains with
``root.after``.

Safety rules enforced here:
* Turn off / disconnect / shutdown jump the queue and cancel every command
  still waiting in it (so a queued "turn on" can never run after "turn off").
* "Off" is always read back from the laser (``hardware.operations.turn_off``).
* The laser is turned off before every mode change, on disconnect, on shutdown
  and after any communication error. If "off" cannot be confirmed the GUI is
  told so loudly.
* Any error other than a refused command or bad user input is treated as a
  broken link: laser off (best effort) and disconnect.
"""

from __future__ import annotations

import enum
import itertools
import logging
import math
import queue
import sys
import threading
from dataclasses import dataclass, replace
from typing import Any, Callable, Optional

from .hardware import operations as ops
from .hardware.operations import Limits

log = logging.getLogger(__name__)

POLL_INTERVAL_S = 1.0
CAMERA_POWER_MW = 50.0     # power + calibration used in Camera mode (reference notebook)
OFF_UNCONFIRMED = ("Could not confirm the laser is off. "
                   "Switch it off at the laser controller (key switch) now.")

# Job priorities (lower runs first).
_SAFETY, _USER = 0, 1


class Mode(str, enum.Enum):
    """Operating mode. MANUAL: CW at a user-set power. CAMERA: pulsed, gated by the camera trigger."""

    MANUAL = "manual"
    CAMERA = "camera"


class InvalidInput(ValueError):
    """The request was rejected before anything was sent to the laser."""


@dataclass(frozen=True)
class Status:
    """Immutable snapshot of the controller state, published in every ``StatusEvent``.

    Attributes:
        connected: a laser is open and its limits have been read.
        busy: a connect or mode change is in progress (True -> False brackets
            every attempt, including rejected ones).
        port: the port being connected / connected to, else None.
        limits: power limits read at connect, else None.
        emitting: the laser reports ``L=1``. In Manual mode the beam is on. In
            Camera mode the laser is armed: the camera trigger gates the beam,
            so light is emitted only while the trigger is active.
        mode: the selected mode (kept across disconnects).
        setpoint_mw: last power setpoint read back from the laser, in mW.
        current_ma: last diode current read back from the laser, in mA.
    """

    connected: bool = False
    busy: bool = False
    port: Optional[str] = None
    limits: Optional[Limits] = None
    emitting: bool = False
    mode: Mode = Mode.MANUAL
    setpoint_mw: Optional[float] = None
    current_ma: Optional[float] = None


@dataclass(frozen=True)
class StatusEvent:
    """The controller status changed; ``status`` is the new snapshot."""

    status: Status


@dataclass(frozen=True)
class MessageEvent:
    """A one-line message for the user (the GUI shows the latest one above its readback bar)."""

    text: str
    level: str = "info"          # "info" | "warning" | "error"
    code: Optional[str] = None   # machine-readable reason, e.g. POWER_REJECTED


# MessageEvent.code values the GUI reacts to.
POWER_REJECTED = "power_rejected"   # a manual power outside the laser's limits (nothing sent)


Event = StatusEvent | MessageEvent
LaserFactory = Callable[[str], Any]
_LOG_LEVELS = {"info": logging.INFO, "warning": logging.WARNING, "error": logging.ERROR}


def is_number(mw: object) -> bool:
    """True for a finite int or float (bools excluded)."""
    return isinstance(mw, (int, float)) and not isinstance(mw, bool) and math.isfinite(mw)


def validate_power(mw: Optional[float], limits: Optional[Limits]) -> Optional[str]:
    """Range check against the laser's limits. Return an error or None. No I/O.

    Used for Camera mode's fixed power; Manual power has no app-side limits.
    """
    if not is_number(mw):
        return "Enter a number."
    if limits is None:
        return "Connect to the laser first."
    if mw < limits.min_mw or mw > limits.max_mw:
        return f"Power must be {limits.min_mw:g}–{limits.max_mw:g} mW."
    return None


class LaserController:
    """Owns the laser on a background worker thread; the GUI drives it through non-blocking calls.

    ``factory(port)`` opens a laser (default: the serial port via
    ``hardware.operations.open_laser``; tests and ``--simulate`` pass
    ``hardware.simulator.simulated_laser``).
    While connected and idle, the status is refreshed every ``poll_interval_s``.
    Results arrive as ``StatusEvent`` / ``MessageEvent`` objects on ``events``.
    """

    def __init__(self, factory: LaserFactory = ops.open_laser, poll_interval_s: float = POLL_INTERVAL_S):
        self._factory = factory
        self._poll_interval_s = poll_interval_s
        self._jobs: queue.PriorityQueue = queue.PriorityQueue()
        self._seq = itertools.count()
        self._generation = 0           # bumped by safety jobs; older user jobs are skipped
        self._gen_lock = threading.Lock()
        # Worker-thread-only state:
        self._laser: Any = None
        self._manual_power_mw: Optional[float] = None
        # Shared state (read by the GUI thread):
        self._status = Status()
        self._status_lock = threading.Lock()
        self.events: "queue.Queue[Event]" = queue.Queue()
        self._thread = threading.Thread(target=self._run, name="laser-worker", daemon=True)
        self._stopped = threading.Event()

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> None:
        """Start the worker thread. Call once before submitting commands."""
        self._thread.start()

    def shutdown(self, timeout: float = 60.0) -> None:
        """Turn the laser off, close the port and stop the worker. Blocks up to ``timeout``.

        The default is generous because a connect that is still running cannot be
        interrupted: probing a port whose device does not answer can take about
        15 s (one read timeout per line the handshake looks at).
        """
        if not self._thread.is_alive():
            return
        self._submit(_SAFETY, self._do_shutdown, cancel_pending=True)
        self._thread.join(timeout)
        if self._thread.is_alive():
            log.critical("Laser worker did not stop within %.0f s; laser state unknown.", timeout)
            if sys.stderr is not None:
                print("WARNING: " + OFF_UNCONFIRMED, file=sys.stderr)

    @property
    def status(self) -> Status:
        """The current ``Status`` snapshot (thread-safe)."""
        with self._status_lock:
            return self._status

    # ------------------------------------------------------------------ GUI API (non-blocking)
    def connect(self, port: str, mode: Mode, manual_power_mw: Optional[float] = None) -> None:
        """Open ``port`` and configure ``mode``.

        ``manual_power_mw`` is the CW power restored whenever Manual mode is
        entered (afterwards it tracks the last value applied in Manual mode).
        """
        self._submit(_USER, lambda: self._do_connect(port, mode, manual_power_mw))

    def disconnect(self) -> None:
        """Turn the laser off (verified), close the port and cancel queued commands."""
        self._submit(_SAFETY, self._do_disconnect, cancel_pending=True)

    def turn_on(self) -> None:
        """Switch emission on (in Camera mode: arm the laser for the trigger)."""
        self._submit(_USER, self._do_turn_on)

    def turn_off(self) -> None:
        """Switch emission off (verified) ahead of, and cancelling, any queued command."""
        self._submit(_SAFETY, self._do_turn_off, cancel_pending=True)

    def set_mode(self, mode: Mode) -> None:
        """Change mode; the laser is turned off first.

        Manual: CW + internal control, restoring the last manual power. Camera:
        the reference setup at ``CAMERA_POWER_MW``; rejected (nothing sent) if
        that power is outside the laser's limits.
        """
        self._submit(_USER, lambda: self._do_set_mode(mode))

    def apply_power(self, mw: float) -> None:
        """Manual mode: set the CW output power in mW (only the laser's own limits apply)."""
        self._submit(_USER, lambda: self._do_apply_power(mw))

    # ------------------------------------------------------------------ queue plumbing
    def _submit(self, priority: int, fn: Callable[[], None], cancel_pending: bool = False) -> None:
        with self._gen_lock:
            if cancel_pending:
                self._generation += 1
            gen = self._generation
        self._jobs.put((priority, next(self._seq), gen, fn))

    def _run(self) -> None:
        while not self._stopped.is_set():
            try:
                priority, _, gen, fn = self._jobs.get(timeout=self._poll_interval_s)
            except queue.Empty:
                if self._laser is not None:
                    self._guarded(self._refresh)
                continue
            with self._gen_lock:
                stale = priority != _SAFETY and gen < self._generation
            if stale:
                log.info("Skipped a queued command because the laser was turned off.")
                self._publish()        # let the GUI drop any "pending" state for it
                continue
            self._guarded(fn)

    def _guarded(self, fn: Callable[[], None]) -> None:
        try:
            fn()
        except InvalidInput as exc:          # nothing was sent; link is fine
            self._message(str(exc), "error")
        except ops.PowerRejected as exc:     # outside the laser's limits; nothing was sent
            self._message(str(exc), "error", code=POWER_REJECTED)
        except ops.LaserRefused as exc:      # laser answered "no"; link is fine
            self._message(str(exc), "error")
            self._guarded(self._refresh)
        except Exception as exc:             # anything else: assume the link is broken
            log.exception("Laser communication failed")
            self._drop_connection(f"Communication error: {exc}")

    # ------------------------------------------------------------------ jobs (worker thread)
    def _do_connect(self, port: str, mode: Mode, manual_power_mw: Optional[float]) -> None:
        if self._laser is not None:
            self._release_laser()
        self._manual_power_mw = manual_power_mw
        self._status_reset(busy=True, port=port)
        self._message(f"Connecting to {port}…")
        try:
            laser = self._factory(port)
        except Exception as exc:
            log.exception("Connect failed")
            self._status_reset()
            self._message(f"Could not connect to {port}: {exc}", "error")
            return
        self._laser = laser
        ops.turn_off(laser)                       # always start with the beam off
        self._set(connected=True, limits=ops.read_limits(laser))
        self._message(f"Connected to {port}.")
        if mode is Mode.CAMERA and validate_power(CAMERA_POWER_MW, self.status.limits):
            mode = Mode.MANUAL      # camera power outside this laser's range: start safe
            self._message(f"Camera mode needs {CAMERA_POWER_MW:g} mW, outside this laser's "
                          "range; starting in Manual mode.", "warning")
        self._do_set_mode(mode)

    def _do_disconnect(self) -> None:
        if self._laser is None:
            return
        port = self.status.port
        off = self._release_laser()
        self._status_reset()
        if off:
            self._message(f"Laser off. Disconnected from {port}.")

    def _do_shutdown(self) -> None:
        if self._laser is not None:
            self._release_laser()
        self._stopped.set()

    def _do_turn_on(self) -> None:
        laser = self._require()
        try:
            ops.turn_on(laser)
        except ops.LaserRefused:
            # Refused, so it should be off; make sure (verified) before reporting.
            # A CommError here means "off" is unconfirmed: it drops the link loudly.
            ops.turn_off(laser)
            raise
        except Exception:
            # The ON command may or may not have reached the laser: switch off first.
            try:
                ops.turn_off(laser)
            except Exception:
                pass
            raise
        self._refresh()
        if not self.status.emitting:
            self._message("The laser did not report emission after ON.", "warning")
        elif self.status.mode is Mode.CAMERA:
            self._message("Laser on (camera mode).")
        else:
            self._message("Laser on.")

    def _do_turn_off(self) -> None:
        if self._laser is None:
            return
        ops.turn_off(self._laser)               # verified; raises CommError if not confirmed
        self._refresh()
        self._message("Laser off.")

    def _do_set_mode(self, mode: Mode) -> None:
        laser = self._require()
        # busy=True -> busy=False brackets every attempt, including a rejected one,
        # so the GUI can always tell when a mode request has finished.
        self._set(busy=True)
        if mode is Mode.CAMERA:                 # validate before touching the laser
            err = validate_power(CAMERA_POWER_MW, self.status.limits)
            if err:
                self._set(busy=False)
                raise InvalidInput(f"Camera mode is not available on this laser: {err}")
        advisories: list[str] = []
        was_on = self.status.emitting
        ops.turn_off(laser)                     # always, never trust a cached flag
        if was_on:
            self._message("Laser turned off to change mode.", "warning")
        if mode is Mode.CAMERA:
            # 50 mW is above nominal on many lasers; that is intended here, so the
            # advisory is only logged, not shown.
            for text in ops.configure_camera(laser, CAMERA_POWER_MW):
                log.info("Camera setup: %s", text)
            self._set(mode=Mode.CAMERA)
            self._message("Camera mode.")
        else:
            ops.configure_manual(laser)
            # Camera mode leaves the setpoint at the camera power (often 50 mW,
            # above nominal); restore the last manual power so "Turn on" in
            # Manual never emits at an unexpected level.
            mw = self._manual_power_mw
            if is_number(mw):
                try:
                    advisories = ops.set_power(laser, mw)
                    self._message(f"Manual mode, power {mw:g} mW.")
                except ops.PowerRejected as exc:
                    # Never leave the camera power in place: fall back to the
                    # laser's minimum power and say so.
                    floor = self.status.limits.min_mw if self.status.limits else 0.0
                    advisories = ops.set_power(laser, floor)
                    self._message(f"Manual mode. {exc} Power set to {floor:g} mW instead.",
                                  "warning")
            else:
                self._message("Manual mode.")
            self._set(mode=Mode.MANUAL)
        for text in advisories:
            self._message(text, "warning")
        self._set(busy=False)
        self._refresh()
        # On any exception above, _guarded drops the connection (laser off +
        # disconnect), so a half-configured laser is never left in use.

    def _do_apply_power(self, mw: float) -> None:
        laser = self._require()
        if self.status.mode is not Mode.MANUAL:
            raise InvalidInput("Power can only be changed in Manual mode.")
        if not is_number(mw):              # the app sets no power limits of its own
            raise InvalidInput("Enter a number.")
        for text in ops.set_power(laser, mw):
            self._message(text, "warning")
        self._manual_power_mw = mw
        self._refresh()
        self._message(f"Power set to {mw:g} mW.")

    # ------------------------------------------------------------------ helpers
    def _require(self) -> Any:
        if self._laser is None:
            raise InvalidInput("Not connected.")
        return self._laser

    def _refresh(self) -> None:
        laser = self._laser
        if laser is None:
            return
        self._set(
            emitting=ops.read_emitting(laser),
            setpoint_mw=ops.read_setpoint(laser),
            current_ma=ops.read_current(laser),
        )

    def _release_laser(self) -> bool:
        """Turn off (verified) and close. Reports loudly if "off" was not confirmed."""
        laser, self._laser = self._laser, None
        off = ops.close(laser)
        if not off:
            log.critical(OFF_UNCONFIRMED)
            self._message(OFF_UNCONFIRMED, "error")
        return off

    def _drop_connection(self, reason: str) -> None:
        if self._laser is not None:
            self._release_laser()
        self._status_reset()
        self._message(reason + " Disconnected; check the cable and reconnect.", "error")

    def _update(self, make: Callable[[Status], Status]) -> None:
        """Replace the status with ``make(old)`` and publish it."""
        with self._status_lock:
            self._status = status = make(self._status)
        self.events.put(StatusEvent(status))

    def _status_reset(self, **changes: Any) -> None:
        """Back to a disconnected status, keeping the selected mode."""
        self._update(lambda old: Status(mode=old.mode, **changes))

    def _set(self, **changes: Any) -> None:
        """Change some status fields and publish."""
        self._update(lambda old: replace(old, **changes))

    def _publish(self) -> None:
        self.events.put(StatusEvent(self.status))

    def _message(self, text: str, level: str = "info", code: Optional[str] = None) -> None:
        log.log(_LOG_LEVELS.get(level, logging.INFO), text)
        self.events.put(MessageEvent(text, level, code))
