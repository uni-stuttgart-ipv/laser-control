"""Shared test helpers: a fake laser and a controller that uses it; a fake controller and a window."""
import threading
import tkinter as tk
import warnings

import pytest
import serial

from laser_control import controller
from laser_control.ui.window import MainWindow

# The CoherentCube properties that send a command when you assign to them.
# analog_control_mode is missing on purpose: in the library it is a method, so
# assigning to it sends nothing (see camera.py).
SENDING_PROPERTIES = {"power", "operation_mode", "analog_control"}


class FakeLaser:
    """Stands in for CoherentCube: records every command instead of sending it."""

    min_power = 0.5

    def __init__(self, port, timeout=None, write_timeout=None):
        self.port = port
        self.sent = []              # every command, in order: (name, value)
        self.refuse_reason = None   # set it to make on() refuse, like an open interlock
        self.broken = False         # set it to make every command fail, like a pulled cable
        self.current_ma = 0.0

    def __setattr__(self, name, value):
        if name in SENDING_PROPERTIES:
            self._send(name, value)
        object.__setattr__(self, name, value)

    def _send(self, name, value=None):
        if self.broken:
            raise serial.SerialException("device disconnected")
        self.sent.append((name, value))

    def on(self):
        self._send("on")
        if self.refuse_reason:
            warnings.warn(f"Can not turn laser on due to {self.refuse_reason}.")

    def off(self):
        self._send("off")

    def calibrate(self, power):
        self._send("calibrate", power)

    def close(self):
        self.sent.append(("close", None))   # closing works even with the cable pulled

    @property
    def current(self):
        self._send("current")
        return self.current_ma


@pytest.fixture
def ctl(monkeypatch):
    """A Controller whose CoherentCube is the FakeLaser."""
    monkeypatch.setattr(controller, "CoherentCube", FakeLaser)
    c = controller.Controller()
    yield c
    c.shut_down()


def wait(ctl):
    """Wait until every queued job has run, then return the results.

    Jobs run in order, so once this marker job runs, all earlier ones are done.
    """
    done = threading.Event()
    ctl._jobs.put((done.set, ()))
    assert done.wait(timeout=2), "the controller's thread did not finish its jobs"
    return ctl.get_results()


def connect(ctl, mode="manual", power=5):
    """Connect to a fake laser, and return it with its command log cleared."""
    ctl.connect("COM3", mode, power)
    wait(ctl)
    laser = ctl.laser
    laser.sent.clear()
    return laser


# ---- the window, with a fake controller ----


class FakeController:
    """Records what the window asks for; the test decides what the laser answers."""

    def __init__(self):
        self.calls = []
        self.results = []

    def get_ports(self):
        return ["COM3"]

    def get_results(self):
        results, self.results = self.results, []
        return results

    def connect(self, port, mode, power):
        self.calls.append(("connect", port, mode, power))

    def disconnect(self):
        self.calls.append(("disconnect",))

    def turn_on(self):
        self.calls.append(("turn_on",))

    def turn_off(self):
        self.calls.append(("turn_off",))

    def use_mode(self, mode, power):
        self.calls.append(("use_mode", mode, power))

    def set_power(self, power):
        self.calls.append(("set_power", power))


@pytest.fixture
def root():
    try:
        root = tk.Tk()
    except tk.TclError as error:
        pytest.skip(f"Tk could not start: {error}")   # the reason is printed at the end of the run
    root.withdraw()
    yield root
    root.destroy()


@pytest.fixture
def win(root):
    return MainWindow(root, FakeController())


def answer(win, *results):
    """Let the fake laser answer, then let the window collect it like its 100 ms poll does."""
    win.ctl.results.extend(results)
    win._poll()


def run_for(root, ms):
    """Run the Tk event loop for `ms` milliseconds, so after() timers can fire."""
    root.after(ms, root.quit)
    root.mainloop()


def connected(win, mode="manual"):
    answer(win, ("connected", 0.5), ("mode", mode), ("power", 5.0))
    return win
