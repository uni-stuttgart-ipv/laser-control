"""Shared test helpers."""

import time

from laser_app.hardware.laser import Laser
from laser_app.hardware.simulator import SimulatedDevice, SimulatedPort


def wait_for(pred, timeout=5.0):
    """Poll ``pred()`` until it is true; fail the test after ``timeout`` seconds."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.02)
    raise AssertionError("condition not met in time")


class SimFactory:
    """A controller ``factory(port)`` that builds simulated lasers and keeps hold of them.

    ``devices[i]`` and ``ports[i]`` are the device model and serial port of the
    i-th laser opened, so tests can inspect what was sent or inject faults.
    Keyword arguments go to every ``SimulatedDevice``.
    """

    def __init__(self, **device_options):
        self.device_options = device_options
        self.devices: list[SimulatedDevice] = []
        self.ports: list[SimulatedPort] = []

    def __call__(self, port: str) -> Laser:
        device = SimulatedDevice(**self.device_options)
        transport = SimulatedPort(device)
        self.devices.append(device)
        self.ports.append(transport)
        return Laser(transport, name=port)

    @property
    def device(self) -> SimulatedDevice:
        """The most recently opened device."""
        return self.devices[-1]
