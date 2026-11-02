"""Shared fixtures: a fresh simulated laser per test and a fake Tk scheduler."""

from __future__ import annotations

import gc
import time
from typing import Callable

import pytest

from laser_control import sequences, sim


@pytest.fixture(autouse=True)
def collect_garbage_on_main_thread():
    """Free leftovers from earlier tests here, on the main thread, before each test.

    Destroyed Tk windows from the window tests linger in reference cycles until
    Python's garbage collector runs, and it runs in whichever thread happens to
    trigger it. Tk objects must be freed on the thread that created them: when
    the collector ran inside a laser worker thread on Linux CI, freeing a Tk
    interpreter there blocked the worker and a worker test timed out.
    """
    gc.collect()
    yield


@pytest.fixture
def sims():
    """Install the simulator for one test; yields the port -> LaserSim registry."""
    registry = sim.install(sim.default_registry(), realtime=False)
    yield registry
    sim.uninstall()


@pytest.fixture
def policy():
    """Restore the analog-mode policy after tests that change it."""
    saved = sequences.ANALOG_MODE_POLICY
    yield
    sequences.ANALOG_MODE_POLICY = saved


def commands(log: list[str]) -> list[str]:
    """Drop queries from a simulator log, leaving only state-changing commands."""
    return [line for line in log if not line.startswith("?")]


class FakeScheduler:
    """Stands in for ``tk.Tk.after`` with a virtual clock.

    ``step()`` advances virtual time by ``tick_ms`` and runs whatever is due.
    The controller's worker thread is real, so tests wait on it with
    :meth:`run_until`.
    """

    def __init__(self, tick_ms: int = 50):
        self.now = 0
        self.tick_ms = tick_ms
        self._queue: list[tuple[int, int, Callable[[], None]]] = []
        self._seq = 0

    def after(self, ms: int, func: Callable[[], None]) -> str:
        self._seq += 1
        self._queue.append((self.now + ms, self._seq, func))
        return str(self._seq)

    def after_cancel(self, id: str) -> None:
        self._queue = [item for item in self._queue if str(item[1]) != id]

    def step(self) -> None:
        self.now += self.tick_ms
        due = sorted(item for item in self._queue if item[0] <= self.now)
        self._queue = [item for item in self._queue if item[0] > self.now]
        for _, _, func in due:
            func()

    def run_until(self, predicate: Callable[[], bool], timeout_s: float = 5.0) -> None:
        """Step until ``predicate()`` is true; fail the test after ``timeout_s`` of real time."""
        end = time.monotonic() + timeout_s
        while not predicate():
            if time.monotonic() > end:
                raise AssertionError("condition not reached in time")
            self.step()
            time.sleep(0.002)

    def settle(self, steps: int = 10) -> None:
        """Run a few steps, giving the worker time to finish queued jobs."""
        for _ in range(steps):
            self.step()
            time.sleep(0.005)


@pytest.fixture
def scheduler():
    return FakeScheduler()
