"""Application state machine and the public API the UI calls.

Everything in this module runs on the Tk (main) thread. Commands never block:
each one queues a :class:`~laser_control.worker.Job` and returns. A pump
scheduled with ``after()`` drains finished jobs, updates the
:class:`~laser_control.model.Snapshot` and calls the UI's callbacks.

State overview::

    DISCONNECTED --connect()--> CONNECTING --ok--> CONNECTED --disconnect()--> DISCONNECTING --> DISCONNECTED
         ^   ^--cancel_connect()--+                     |
         |                        |                     | fatal error: the worker tried a confirmed
         +--- select_port() --- ERROR <------fail-------+ off, then closed the port

Emission safety rules:

* ``Emission.OFF`` is only set when an off was *confirmed* (the laser answered
  right after it), or when the laser itself refused to turn on.
* Right after connecting, emission is ``UNKNOWN``: the laser may have been
  left on. The UI asks for one press of the key (which sends off) before it
  allows turning on.
* If an off cannot be confirmed (link lost, laser silent), emission becomes
  ``UNKNOWN`` and ``emission_warning`` is set. It stays set after disconnecting
  until a later off is confirmed.

Behaviour decided with the lab:

* The selected mode's sequence is applied right after connecting, and again on
  every mode change, including while the laser is emitting (it stays on).
* Manual power is only sent by Apply; mode changes reuse the last applied power.
* Disconnect and window close send a confirmed off before closing the port.
* Off jumps the queue and cancels any queued turn-on; queued mode or power
  changes still run, with the laser off.
"""

from __future__ import annotations

import logging
import math
import queue
import time
from dataclasses import dataclass, replace
from typing import Callable, Protocol

from laser_control import ports, sequences
from laser_control.errors import Phase, classify, on_refused_cause, power_warning
from laser_control.model import ConnState, Emission, Mode, PortInfo, Snapshot, UserMessage
from laser_control.worker import Job, JobKind, JobResult, LaserWorker, Priority

logger = logging.getLogger(__name__)

StateCallback = Callable[[Snapshot], None]
MessageCallback = Callable[[UserMessage], None]
UnsafeCallback = Callable[[bool], None]
"""Called with ``still_running``: True if the shutdown job has not finished yet."""

_USER_JOBS = (JobKind.ON, JobKind.OFF, JobKind.MODE, JobKind.SET_POWER, JobKind.DISCONNECT)

CAMERA_POWER_MW = sequences.CAMERA_POWER_MW
"""Re-exported so the UI does not need to import :mod:`sequences`."""

REFUSED_TITLE = "Laser did not turn on"
"""Title of the message sent when the laser refuses ``on()``; the UI clears it once emission starts."""


class Scheduler(Protocol):
    """The part of ``tk.Tk`` the controller needs; tests pass a fake."""

    def after(self, ms: int, func: Callable[[], None]) -> str: ...

    def after_cancel(self, id: str) -> None: ...


@dataclass(frozen=True)
class Controls:
    """Which controls are usable for a given snapshot. See :func:`controls_for`."""

    port_select: bool
    connect: bool
    connect_label: str
    mode_select: bool
    power_edit: bool
    laser_on: bool
    laser_off: bool


_CONNECT_LABEL = {
    ConnState.DISCONNECTED: "Connect",
    ConnState.ERROR: "Retry",
    ConnState.CONNECTING: "Cancel",
    ConnState.CONNECTED: "Disconnect",
    ConnState.DISCONNECTING: "Disconnecting",
    ConnState.SHUTTING_DOWN: "Closing",
}


def controls_for(s: Snapshot) -> Controls:
    """Derive which controls are enabled. Pure function, used by the UI and tests.

    * Off is allowed whenever connected, even while other commands run, and
      even if the app believes the laser is already off (resending is harmless).
    * On is allowed only from a confirmed ``OFF``, with no command running and
      a known mode.
    * Mode and power changes wait for a running mode sequence, but may queue
      behind other commands.
    """
    idle = s.connected and not s.busy and s.applying is None
    return Controls(
        port_select=s.conn in (ConnState.DISCONNECTED, ConnState.ERROR),
        connect=s.conn in (ConnState.DISCONNECTED, ConnState.ERROR, ConnState.CONNECTING, ConnState.CONNECTED),
        connect_label=_CONNECT_LABEL[s.conn],
        mode_select=s.conn in (ConnState.DISCONNECTED, ConnState.ERROR) or (s.connected and s.applying is None),
        power_edit=s.connected and s.mode is Mode.MANUAL and s.applying is None,
        laser_on=idle and s.emission is Emission.OFF and s.mode is not Mode.UNKNOWN,
        laser_off=s.connected,
    )


class LaserController:
    """Owns the worker thread and the app state.

    Args:
        scheduler: Usually the ``tk.Tk`` root.
        port: Initially selected port.
        manual_power_mw: Last applied manual-mode power; applied on connect.
        timeout_s: Serial read/write timeout passed to the driver.
        poll_interval_ms: How often to read set point and current while connected.
        pump_ms: How often to drain finished jobs.
        simulate: List simulated ports instead of real ones.
        worker_factory: Builds the worker from the results queue (tests);
            a :class:`LaserWorker` is started by default.
    """

    def __init__(self, scheduler: Scheduler, *, port: str = ports.DEFAULT_PORT, manual_power_mw: float = 5.0,
                 timeout_s: float = 2.0, poll_interval_ms: int = 1000, pump_ms: int = 50,
                 simulate: bool = False,
                 worker_factory: Callable[[queue.SimpleQueue[JobResult]], LaserWorker] | None = None):
        self._scheduler = scheduler
        self._timeout_s = timeout_s
        self._poll_ms = max(250, poll_interval_ms)
        self._pump_ms = pump_ms
        self._simulate = simulate
        self._manual_power = manual_power_mw
        self._snap = Snapshot(port=port)
        self._state_cbs: list[StateCallback] = []
        self._message_cbs: list[MessageCallback] = []
        self._pending: dict[int, Job] = {}
        self._poll_in_flight = False
        self._generation = 0
        self._on_epoch = 0
        self._on_shutdown: Callable[[], None] | None = None
        self._on_unsafe: UnsafeCallback | None = None
        self._shutdown_pending = False
        self._shutdown_deadline: float | None = None

        self._results: queue.SimpleQueue[JobResult] = queue.SimpleQueue()
        self._worker = (worker_factory or LaserWorker)(self._results)
        if not self._worker.is_alive():
            self._worker.start()
        self._scheduler.after(self._pump_ms, self._pump)
        self._scheduler.after(self._poll_ms, self._poll_tick)

    # ---- subscription ----

    def subscribe(self, on_state: StateCallback, on_message: MessageCallback | None = None) -> None:
        """Register UI callbacks. They always run on the Tk thread."""
        self._state_cbs.append(on_state)
        if on_message:
            self._message_cbs.append(on_message)
        on_state(self._snap)

    @property
    def snapshot(self) -> Snapshot:
        """The current state."""
        return self._snap

    @property
    def manual_power_mw(self) -> float:
        """The manual-mode power last applied (or to be applied on connect)."""
        return self._manual_power

    # ---- ports ----

    def list_ports(self) -> list[PortInfo]:
        """List serial ports. Fast, and never touches the open connection."""
        return ports.list_ports(simulate=self._simulate)

    def select_port(self, port: str) -> None:
        """Choose the port for the next connect. Ignored unless disconnected."""
        if self._snap.conn in (ConnState.DISCONNECTED, ConnState.ERROR):
            self._set(port=port, conn=ConnState.DISCONNECTED, last_error=None)

    # ---- commands (all non-blocking) ----

    def connect(self) -> None:
        """Open the selected port, then apply the selected mode."""
        if self._snap.conn not in (ConnState.DISCONNECTED, ConnState.ERROR):
            return
        port, timeout = self._snap.port, self._timeout_s
        self._set(conn=ConnState.CONNECTING, last_error=None, on_refused=False)
        self._submit(Job(JobKind.CONNECT, fn=lambda: sequences.open_laser(port, timeout),
                         generation=self._generation, tag=port))

    def cancel_connect(self) -> None:
        """Abandon a running connect attempt.

        The driver's probe cannot be interrupted; if it succeeds later the
        worker closes the port straight away.
        """
        if self._snap.conn is ConnState.CONNECTING:
            self._bump_generation()
            self._set(conn=ConnState.DISCONNECTED)

    def disconnect(self) -> None:
        """Turn the laser off (confirmed) and close the port."""
        if self._snap.conn is not ConnState.CONNECTED:
            return
        self._bump_generation()
        self._set(conn=ConnState.DISCONNECTING)
        self._submit(Job(JobKind.DISCONNECT, priority=Priority.OFF, generation=self._generation))

    def laser_on(self) -> None:
        """Turn emission on (if :func:`controls_for` allows it)."""
        if controls_for(self._snap).laser_on:
            self._submit(Job(JobKind.ON, fn=sequences.laser_on, generation=self._generation,
                             on_epoch=self._on_epoch))

    def laser_off(self) -> None:
        """Turn emission off. Jumps the queue and cancels any queued turn-on."""
        if not self._snap.connected:
            return
        self._on_epoch += 1
        self._worker.on_epoch = self._on_epoch
        self._submit(Job(JobKind.OFF, priority=Priority.OFF, generation=self._generation))

    def select_mode(self, mode: Mode) -> None:
        """Select a mode and, when connected, run its sequence.

        Selecting the mode that is already selected re-runs its sequence
        (for example to repeat the camera calibration). Manual mode uses the last *applied* power (:attr:`manual_power_mw`),
        never an unapplied value from the dial.
        """
        if mode is Mode.UNKNOWN or not controls_for(self._snap).mode_select:
            return
        self._set(mode=mode, on_refused=False)
        if self._snap.connected:
            self._submit_mode(mode)

    def set_power(self, power_mw: float) -> bool:
        """Send a new manual-mode power (the Apply button).

        Returns:
            False if the value was rejected before sending (not a finite
            number, or power editing is not allowed right now).
        """
        if not controls_for(self._snap).power_edit:
            return False
        if not isinstance(power_mw, (int, float)) or not math.isfinite(power_mw):
            self._message(UserMessage("warning", "Power not applied", "Enter a power in mW, as a number."))
            return False
        power = round(power_mw, 2)
        self._submit(Job(JobKind.SET_POWER, fn=lambda laser: sequences.set_power(laser, power),
                         generation=self._generation, tag=power))
        return True

    def refresh_status(self) -> None:
        """Read set point and current now instead of waiting for the next poll."""
        if self._snap.connected and not self._poll_in_flight:
            self._poll_in_flight = True
            self._submit(Job(JobKind.POLL, fn=sequences.read_status, priority=Priority.POLL,
                             generation=self._generation))

    def shutdown(self, on_done: Callable[[], None], on_unsafe: UnsafeCallback | None = None,
                 timeout_s: float | None = None) -> None:
        """Turn the laser off (confirmed), close the port, then call ``on_done``.

        ``on_unsafe(still_running)`` is called instead when closing may leave
        the laser on:

        * ``still_running=True``: the worker has not finished within the
          deadline (it may be blocked on a slow laser). Calling ``shutdown()``
          again keeps waiting with a new deadline; ``on_done`` still runs
          when the job finishes safely.
        * ``still_running=False``: the port is closed but the off was not
          confirmed, or the laser was already in that state. Call
          :meth:`cancel_shutdown` to return to the disconnected state.

        Args:
            on_done: Called once it is safe to exit.
            on_unsafe: See above; defaults to calling ``on_done``.
            timeout_s: Deadline; defaults to ``max(3 * timeout + 1, 5)`` seconds.
        """
        self._on_shutdown = on_done
        self._on_unsafe = on_unsafe or (lambda still_running: on_done())
        limit = timeout_s if timeout_s is not None else max(3 * self._timeout_s + 1, 5)
        if self._snap.conn is ConnState.SHUTTING_DOWN:
            if self._shutdown_pending:
                self._shutdown_deadline = time.monotonic() + limit
            return
        was = self._snap.conn
        self._set(conn=ConnState.SHUTTING_DOWN)
        self._bump_generation()  # also drops a connect still in progress
        if was in (ConnState.CONNECTED, ConnState.DISCONNECTING):
            self._shutdown_pending = True
            self._shutdown_deadline = time.monotonic() + limit
            self._submit(Job(JobKind.SHUTDOWN, priority=Priority.SHUTDOWN, generation=self._generation))
        else:  # no port is open
            self._scheduler.after(0, lambda: self._finish_shutdown(None))

    def cancel_shutdown(self) -> None:
        """Return from a finished-but-unsafe shutdown to the disconnected state."""
        if self._snap.conn is ConnState.SHUTTING_DOWN and not self._shutdown_pending:
            self._on_shutdown = self._on_unsafe = None
            self._set(conn=ConnState.DISCONNECTED, busy=False, applying=None, setpoint_mw=None,
                      current_ma=None, limits=None)

    # ---- internals ----

    def _submit_mode(self, mode: Mode) -> None:
        power = self._clamped_manual_power()
        self._set(applying=mode)
        self._submit(Job(JobKind.MODE, fn=lambda laser: sequences.apply_mode(laser, mode, power),
                         generation=self._generation, tag=(mode, power)))

    def _clamped_manual_power(self) -> float:
        limits = self._snap.limits
        power = self._manual_power
        if limits:
            power = min(max(power, limits.min_mw), limits.max_mw)
        return round(power, 2)

    def _submit(self, job: Job) -> None:
        if job.kind in _USER_JOBS:
            self._pending[job.job_id] = job
            self._set(busy=True)
        self._worker.submit(job)

    def _bump_generation(self) -> None:
        self._generation += 1
        self._worker.generation = self._generation

    def _set(self, **changes) -> None:
        new = replace(self._snap, **changes)
        if new != self._snap:
            self._snap = new
            for cb in list(self._state_cbs):
                try:
                    cb(new)
                except Exception:  # a UI bug must never stop state handling
                    logger.exception("state callback failed")

    def _message(self, msg: UserMessage) -> None:
        log = logger.warning if msg.level != "info" else logger.info
        log("%s: %s %s", msg.title, msg.text, msg.detail or "")
        for cb in list(self._message_cbs):
            try:
                cb(msg)
            except Exception:
                logger.exception("message callback failed")

    def _after_close(self, confirmed: bool | None) -> tuple[Emission, bool]:
        """Emission and warning after the port was closed with a best-effort off."""
        s = self._snap
        if confirmed:
            return Emission.OFF, False
        if s.emission is Emission.OFF and not s.emission_warning:
            return Emission.OFF, False  # it was confirmed off before, and nothing turned it on
        return Emission.UNKNOWN, True

    def _pump(self) -> None:
        try:
            while True:
                try:
                    result = self._results.get_nowait()
                except queue.Empty:
                    break
                try:
                    self._handle(result)
                except Exception:
                    logger.exception("failed to handle %s result", result.job.kind.name)
            self._check_shutdown_deadline()
            if not self._worker.is_alive() and self._snap.conn not in (ConnState.SHUTTING_DOWN,):
                self._worker_died()
        except Exception:
            logger.exception("controller pump failed")
        finally:
            self._scheduler.after(self._pump_ms, self._pump)

    def _poll_tick(self) -> None:
        try:
            if self._snap.connected and not self._snap.busy:
                self.refresh_status()
        except Exception:
            logger.exception("poll tick failed")
        finally:
            self._scheduler.after(self._poll_ms, self._poll_tick)

    def _check_shutdown_deadline(self) -> None:
        if self._shutdown_deadline is not None and time.monotonic() > self._shutdown_deadline:
            self._shutdown_deadline = None
            if self._on_unsafe:
                self._on_unsafe(True)

    def _worker_died(self) -> None:
        if self._snap.conn is ConnState.ERROR and self._snap.last_error \
                and self._snap.last_error.title == "Internal error":
            return
        msg = UserMessage("error", "Internal error",
                          "The laser connection stopped working. Restart the app and check the laser.")
        emission, warning = self._after_close(False)
        self._set(conn=ConnState.ERROR, emission=emission, emission_warning=warning, busy=False,
                  applying=None, last_error=msg)
        self._message(msg)

    def _finish_shutdown(self, confirmed: bool | None) -> None:
        self._shutdown_pending = False
        self._shutdown_deadline = None
        emission, warning = self._after_close(confirmed)
        self._set(emission=emission, emission_warning=warning)
        if warning:
            if self._on_unsafe:
                self._on_unsafe(False)
            return
        callback, self._on_shutdown, self._on_unsafe = self._on_shutdown, None, None
        self._worker.stop()
        if callback:
            callback()

    def _handle(self, result: JobResult) -> None:
        job = result.job
        self._pending.pop(job.job_id, None)
        if job.kind is JobKind.POLL:
            self._poll_in_flight = False
        busy = any(j.kind in _USER_JOBS for j in self._pending.values())

        if job.kind is JobKind.SHUTDOWN:
            self._finish_shutdown(result.value if result.ok else result.off_confirmed)
            return
        if self._snap.conn is ConnState.SHUTTING_DOWN:
            return
        if result.skipped:
            mode_lost = job.kind is JobKind.MODE and self._snap.connected
            self._set(busy=busy, applying=None if job.kind is JobKind.MODE else self._snap.applying,
                      mode=Mode.UNKNOWN if mode_lost else self._snap.mode)
            return

        if job.kind is JobKind.CONNECT:
            self._handle_connect(result, busy)
            return

        if not result.ok and result.fatal:
            if job.generation < self._generation:
                return  # a stale job failing after the connection was already dropped
            self._bump_generation()
            msg = classify(result.error, Phase.COMMAND, self._snap.port).message
            emission, warning = self._after_close(result.off_confirmed)
            self._pending.clear()
            self._set(conn=ConnState.ERROR, emission=emission, emission_warning=warning, busy=False,
                      applying=None, setpoint_mw=None, current_ma=None, last_error=msg)
            self._message(msg)
            return

        kind = job.kind
        if kind is JobKind.DISCONNECT:
            emission, warning = self._after_close(result.value)
            self._set(conn=ConnState.DISCONNECTED, emission=emission, emission_warning=warning, busy=busy,
                      applying=None, setpoint_mw=None, current_ma=None, limits=None, on_refused=False)
            if warning:
                self._message(UserMessage("error", "Laser may still be on",
                                          "The laser did not confirm the off command before the port closed. "
                                          "Check the laser."))
            return
        if kind is JobKind.POLL:
            if result.ok:
                setpoint, current = result.value
                self._set(setpoint_mw=setpoint, current_ma=current, busy=busy)
            return
        if kind is JobKind.ON:
            cause = on_refused_cause(result.warnings)
            if cause:
                # The laser answered "L=0": it is off, and confirmed so.
                self._set(emission=Emission.OFF, emission_warning=False, on_refused=True, busy=busy)
                self._message(UserMessage("warning", REFUSED_TITLE,
                                          f"The laser refused to turn on ({cause}). Fix that, then try again."))
            else:
                self._set(emission=Emission.ON, on_refused=False, busy=busy)
        elif kind is JobKind.OFF:
            self._set(emission=Emission.OFF, emission_warning=False, busy=busy)
        elif kind is JobKind.MODE:
            mode, power = job.tag
            if result.ok:
                setpoint = sequences.CAMERA_POWER_MW if mode is Mode.CAMERA else power
                if mode is Mode.MANUAL:
                    self._manual_power = power
                self._set(applying=None, busy=busy, setpoint_mw=float(setpoint))
                if mode is Mode.MANUAL:  # camera power is fixed by the sequence; don't nag about it
                    self._power_warnings(result, power)
            else:
                msg = classify(result.error, Phase.COMMAND).message
                self._set(applying=None, busy=busy, mode=Mode.UNKNOWN)
                self._message(UserMessage(msg.level, f"{mode.name.title()} mode not applied", msg.text, msg.detail))
        elif kind is JobKind.SET_POWER:
            if result.ok:
                self._manual_power = job.tag
                self._set(busy=busy, setpoint_mw=float(job.tag))
                self._power_warnings(result, job.tag)
            else:
                self._set(busy=busy)
                self._message(classify(result.error, Phase.COMMAND).message)
        self.refresh_status()

    def _handle_connect(self, result: JobResult, busy: bool) -> None:
        if result.job.generation < self._generation or (result.ok and result.value is None):
            return  # cancelled
        if not result.ok:
            msg = classify(result.error, Phase.CONNECT, result.job.tag).message
            self._set(conn=ConnState.ERROR, last_error=msg, busy=busy)
            self._message(msg)
            return
        limits, (setpoint, current) = result.value
        mode = self._snap.mode if self._snap.mode is not Mode.UNKNOWN else Mode.MANUAL
        # One update, so no observer ever sees "connected, nothing applying" with the
        # laser's leftover set point before the mode sequence is queued.
        self._set(conn=ConnState.CONNECTED, limits=limits, setpoint_mw=setpoint, current_ma=current,
                  emission=Emission.UNKNOWN, mode=mode, busy=busy, applying=mode)
        self._submit_mode(mode)

    def _power_warnings(self, result: JobResult, power: float) -> None:
        limits = self._snap.limits
        msg = power_warning(result.warnings, power, limits.nom_mw if limits else None,
                            limits.min_mw if limits else None)
        if msg:
            self._message(msg)
