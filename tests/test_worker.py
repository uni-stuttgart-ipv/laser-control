"""The worker owns the port: one thread, priority order, safe close."""

from __future__ import annotations

import queue
import threading

from laser_control import sequences
from laser_control.worker import Job, JobKind, LaserWorker, Priority

from conftest import commands


def run(worker: LaserWorker, results: queue.SimpleQueue, n: int, timeout: float = 5.0):
    return [results.get(timeout=timeout) for _ in range(n)]


def connect_job(port="SIM1"):
    return Job(JobKind.CONNECT, fn=lambda: sequences.open_laser(port, 0.1))


def test_all_serial_io_on_one_thread(sims):
    results: queue.SimpleQueue = queue.SimpleQueue()
    worker = LaserWorker(results)
    worker.start()
    worker.submit(connect_job())
    worker.submit(Job(JobKind.MODE, fn=lambda l: sequences.apply_manual_mode(l, 5.0)))
    worker.submit(Job(JobKind.ON, fn=sequences.laser_on))
    out = run(worker, results, 3)
    worker.submit(Job(JobKind.SHUTDOWN, priority=Priority.SHUTDOWN))
    out += run(worker, results, 1)
    assert all(r.ok for r in out)
    assert worker._laser is None
    # every write, from the probe and the main connection, came from the worker thread
    assert sims["SIM1"].threads == {worker.ident}
    assert threading.get_ident() not in sims["SIM1"].threads
    # shutdown turned the laser off before closing
    assert commands(sims["SIM1"].log)[-1] == "L=0"
    worker.stop()


def test_on_refused_warning_is_captured(sims):
    results: queue.SimpleQueue = queue.SimpleQueue()
    worker = LaserWorker(results)
    worker.start()
    worker.submit(connect_job("SIM-INTERLOCK"))
    worker.submit(Job(JobKind.ON, fn=sequences.laser_on))
    _, on = run(worker, results, 2)
    assert on.ok
    assert any("Interlock open" in w for w in on.warnings)
    worker.stop()


def test_off_jumps_the_queue_and_stale_jobs_are_skipped(sims):
    results: queue.SimpleQueue = queue.SimpleQueue()
    worker = LaserWorker(results)
    # Queue before starting so ordering is decided by priority alone.
    worker.submit(Job(JobKind.SET_POWER, fn=lambda l: sequences.set_power(l, 1.0), generation=0))
    worker.generation = 1
    worker.submit(Job(JobKind.OFF, fn=sequences.laser_off, priority=Priority.OFF, generation=1))
    worker.start()
    first, second = run(worker, results, 2)
    assert first.job.kind is JobKind.OFF
    assert second.job.kind is JobKind.SET_POWER and second.skipped
    worker.stop()


def test_fatal_error_closes_port_after_off(sims):
    results: queue.SimpleQueue = queue.SimpleQueue()
    worker = LaserWorker(results)
    worker.start()
    worker.submit(connect_job())
    run(worker, results, 1)
    sims["SIM1"].responsive = False
    worker.submit(Job(JobKind.POLL, fn=sequences.read_status, priority=Priority.POLL))
    (poll,) = run(worker, results, 1)
    assert not poll.ok and poll.fatal
    assert worker._laser is None
    assert "L=0" in sims["SIM1"].log[-3:]  # off was attempted before closing
    assert poll.off_confirmed is False  # ...but the silent laser could not confirm it
    worker.stop()


def test_off_cancels_queued_on_but_not_other_commands(sims):
    results: queue.SimpleQueue = queue.SimpleQueue()
    worker = LaserWorker(results)
    worker.on_epoch = 1
    worker.submit(Job(JobKind.ON, fn=sequences.laser_on, on_epoch=0))
    worker.submit(Job(JobKind.SET_POWER, fn=lambda l: sequences.set_power(l, 1.0), on_epoch=0))
    worker.start()
    on, power = run(worker, results, 2)
    assert on.skipped
    assert not power.skipped  # it ran (and failed only because nothing is connected)
    worker.stop()


def test_worker_reports_instead_of_dying(sims):
    results: queue.SimpleQueue = queue.SimpleQueue()
    worker = LaserWorker(results)
    worker.start()

    def boom(_laser):
        raise SystemExit("not an Exception subclass")

    worker.submit(connect_job())
    run(worker, results, 1)
    worker.submit(Job(JobKind.MODE, fn=boom))
    (bad,) = run(worker, results, 1)
    assert not bad.ok and bad.fatal
    assert worker.is_alive()
    worker.stop()
