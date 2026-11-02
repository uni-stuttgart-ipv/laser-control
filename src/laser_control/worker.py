"""The single thread that owns the serial port.

Every reply from the laser is one line, read right after its command. Two
threads talking to the port at once would read each other's replies, so all
driver calls run here, one at a time, in priority order.

The Tk thread never blocks: it submits :class:`Job` objects and later drains
:class:`JobResult` objects from a queue (see ``LaserController._pump``).

Two counters let the controller drop queued work it no longer wants:

* ``generation`` is bumped on disconnect, shutdown, cancel and fatal errors.
  Every queued job from an older generation is skipped, except the ones that
  turn the laser off or close the port.
* ``on_epoch`` is bumped by every Off. It only drops queued ``ON`` jobs, so a
  turn-on queued before an Off can never run after it. Mode and power
  changes are *not* dropped by Off; they still run, with the laser off.
"""

from __future__ import annotations

import itertools
import logging
import queue
import re
import threading
import time
import warnings
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable

from laser_control import sequences
from laser_control.driver import Laser
from laser_control.errors import OffNotConfirmed, Phase, is_fatal

logger = logging.getLogger(__name__)


class JobKind(Enum):
    """What a :class:`Job` does; the controller reacts to each kind differently."""

    CONNECT = auto()
    DISCONNECT = auto()
    SHUTDOWN = auto()
    ON = auto()
    OFF = auto()
    MODE = auto()
    SET_POWER = auto()
    POLL = auto()


class Priority:
    """Lower runs first. OFF beats every user command; polls run last."""

    SHUTDOWN = 0
    OFF = 1
    COMMAND = 2
    POLL = 3


_ids = itertools.count(1)


@dataclass(frozen=True)
class Job:
    """One unit of work for the worker.

    Attributes:
        kind: What the job does. ``CONNECT``, ``OFF``, ``DISCONNECT`` and
            ``SHUTDOWN`` are implemented by the worker itself.
        fn: For ``CONNECT``, a function returning a new :class:`Laser`. For
            ``ON``, ``MODE``, ``SET_POWER`` and ``POLL``, a function taking the
            open :class:`Laser`. Unused otherwise.
        priority: See :class:`Priority`.
        generation: Skipped if older than the worker's ``generation`` (see module docs).
        on_epoch: For ``ON`` only: skipped if older than the worker's ``on_epoch``.
        tag: Free-form data the controller wants back with the result.
        job_id: Unique, increasing id; also breaks priority ties in FIFO order.
    """

    kind: JobKind
    fn: Callable[..., Any] | None = None
    priority: int = Priority.COMMAND
    generation: int = 0
    on_epoch: int = 0
    tag: Any = None
    job_id: int = field(default_factory=lambda: next(_ids))


@dataclass(frozen=True)
class JobResult:
    """Outcome of a :class:`Job`.

    Attributes:
        job: The job that ran.
        ok: True if the job finished without raising.
        value: The job's return value. For ``OFF``, ``DISCONNECT`` and
            ``SHUTDOWN`` this is whether the off was confirmed.
        warnings: Text of every warning the driver raised while the job ran.
        error: The exception, if ``ok`` is False.
        skipped: The job was stale and never ran.
        fatal: The error closed the connection.
        off_confirmed: After a fatal error: whether the worker's best-effort
            off was confirmed before closing (``None`` if no port was open).
        elapsed_s: Wall time spent running the job.
    """

    job: Job
    ok: bool
    value: Any = None
    warnings: tuple[str, ...] = ()
    error: BaseException | None = None
    skipped: bool = False
    fatal: bool = False
    off_confirmed: bool | None = None
    elapsed_s: float = 0.0


_NEVER_SKIPPED = (JobKind.OFF, JobKind.DISCONNECT, JobKind.SHUTDOWN)
_LOGGED = (JobKind.CONNECT, JobKind.DISCONNECT, JobKind.SHUTDOWN, JobKind.ON, JobKind.OFF,
           JobKind.MODE, JobKind.SET_POWER)


_DRIVER_FILE = re.compile(r"laser_control[/\\]driver\.pyc?$")


def _driver_warning(w: warnings.WarningMessage) -> bool:
    # ``catch_warnings`` is process-wide; keep only warnings raised by the driver
    # (source, compiled, or frozen by PyInstaller).
    return bool(_DRIVER_FILE.search(w.filename))


class LaserWorker(threading.Thread):
    """Runs jobs against the laser on a dedicated daemon thread.

    Args:
        results: Queue the worker puts a :class:`JobResult` on after every job.
    """

    def __init__(self, results: queue.SimpleQueue[JobResult]):
        super().__init__(name="laser-io", daemon=True)
        self._results = results
        self._jobs: queue.PriorityQueue[tuple[int, int, Job | None]] = queue.PriorityQueue()
        self._laser: Laser | None = None
        self._stop = threading.Event()
        self.generation = 0
        """Set by the controller; a plain int write is atomic."""
        self.on_epoch = 0
        """Set by the controller on every Off."""

    # ---- called from the Tk thread ----

    def submit(self, job: Job) -> None:
        """Queue a job. Thread-safe."""
        self._jobs.put((job.priority, job.job_id, job))

    def stop(self) -> None:
        """Ask the thread to exit after the current job. Does not close the port."""
        self._stop.set()
        self._jobs.put((-1, 0, None))

    def stop_when_idle(self) -> None:
        """Ask the thread to exit once every job queued so far has run."""
        self._jobs.put((10**6, next(_ids), None))

    # ---- worker thread ----

    def run(self) -> None:
        while not self._stop.is_set():
            _, _, job = self._jobs.get()
            if job is None:
                break
            try:
                if self._is_stale(job):
                    self._results.put(JobResult(job, ok=False, skipped=True))
                else:
                    self._results.put(self._execute(job))
            except BaseException:  # never let the port owner die silently
                logger.exception("worker crashed on %s", job.kind.name)
                self._results.put(JobResult(job, ok=False, fatal=True,
                                            error=RuntimeError("internal error in the laser worker")))

    def _is_stale(self, job: Job) -> bool:
        if job.kind in _NEVER_SKIPPED:
            return False
        if job.generation < self.generation:
            return True
        return job.kind is JobKind.ON and job.on_epoch < self.on_epoch

    def _execute(self, job: Job) -> JobResult:
        start = time.monotonic()
        off_confirmed = None
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            try:
                value = self._dispatch(job)
                ok, error, fatal = True, None, False
            except Exception as exc:  # every failure goes back to the controller
                value, ok, error = None, False, exc
                phase = Phase.CONNECT if job.kind is JobKind.CONNECT else Phase.COMMAND
                fatal = is_fatal(exc, phase)
                logger.warning("job %s failed: %r", job.kind.name, exc)
                if fatal and self._laser is not None:
                    off_confirmed = self._close(send_off=True)
        texts = tuple(str(w.message) for w in caught if _driver_warning(w))
        elapsed = time.monotonic() - start
        if job.kind in _LOGGED:
            logger.info("job %s %s value=%r warnings=%s (%.0f ms)", job.kind.name, "ok" if ok else "FAILED",
                        value if not isinstance(value, tuple) else "…", texts or "-", elapsed * 1000)
        return JobResult(job, ok=ok, value=value, warnings=texts, error=error, fatal=fatal,
                         off_confirmed=off_confirmed, elapsed_s=elapsed)

    def _dispatch(self, job: Job) -> Any:
        if job.kind is JobKind.CONNECT:
            if self._laser is not None:
                self._close(send_off=False)
            laser = job.fn()
            try:
                info = sequences.read_limits(laser), sequences.read_status(laser)
            except Exception:
                laser.close()
                raise
            if job.generation < self.generation:
                # Cancelled while the driver was connecting: release the port.
                laser.close()
                return None
            self._laser = laser
            return info
        if job.kind in (JobKind.DISCONNECT, JobKind.SHUTDOWN):
            return self._close(send_off=True)
        if self._laser is None:
            raise ConnectionError("not connected")
        if job.kind is JobKind.OFF:
            if not sequences.laser_off_confirmed(self._laser):
                raise OffNotConfirmed("the laser did not answer after the off command")
            return True
        return job.fn(self._laser)

    def _close(self, send_off: bool) -> bool | None:
        """Best effort: turn the laser off (confirmed), then close the port.

        Each step is attempted even if the previous one fails. The reference
        is dropped here, on this thread, so the driver's ``__del__`` never does
        serial I/O on another thread.

        Returns:
            Whether the off was confirmed; ``None`` if no port was open or no
            off was requested.
        """
        laser, self._laser = self._laser, None
        if laser is None:
            return None
        confirmed = None
        if send_off:
            try:
                confirmed = sequences.laser_off_confirmed(laser)
            except Exception as exc:
                logger.warning("off() during close failed: %r", exc)
                confirmed = False
            if not confirmed:
                logger.error("off was NOT confirmed before closing the port; the laser may still be on")
        try:
            sequences.close_laser(laser)
        except Exception as exc:
            logger.warning("close() failed: %r", exc)
        return confirmed
