"""A simulated laser for development and tests, without hardware.

The simulator replaces the *serial port* the driver talks to, not the driver:
:func:`install` swaps ``laser_control.driver.serial`` for a module whose
``Serial`` class is :class:`FakeSerial`. The driver's own code (probing,
parsing, validation, warnings) still runs, so tests exercise the real thing.

Simulated ports (``--simulate`` lists these):

========================  ===============================================
``SIM1``                  a healthy laser (0.5 / 50 / 55 mW)
``SIM-INTERLOCK``         refuses to turn on: interlock open
``SIM-SILENT``            never answers (connect fails after the probe)
``SIM-BUSY``              the port is held by another program
``SIM-SMALL``             max 40 mW, so camera mode (50 mW) is refused
========================  ===============================================
"""

from __future__ import annotations

import random
import threading
import time
import types
from dataclasses import dataclass, field

import serial

SIM_PORTS = {
    "SIM1": "Simulated laser",
    "SIM-INTERLOCK": "Simulated: interlock open",
    "SIM-SILENT": "Simulated: no response",
    "SIM-BUSY": "Simulated: port in use",
    "SIM-SMALL": "Simulated: max 40 mW",
}

CRLF = b"\r\n"


@dataclass
class LaserSim:
    """Protocol-level model of the laser. No I/O and no sleeping.

    Attributes:
        log: Every command line received, in order (without ``\\r\\n``).
        threads: Ids of every thread that wrote to this laser (tests check it is one).
    """

    min_mw: float = 0.5
    nom_mw: float = 50.0
    max_mw: float = 55.0
    cmd_prompt: bool = False
    interlock_open: bool = False
    responsive: bool = True
    busy: bool = False
    noisy: bool = False
    emission: bool = False
    cw: int = 1
    ext: int = 0
    ana: int = 0
    setpoint: float = 5.0
    calibration: float | None = None
    log: list[str] = field(default_factory=list)
    threads: set[int] = field(default_factory=set)

    @property
    def current_ma(self) -> float:
        """Fake diode current: zero when off, rising with power when on."""
        if not self.emission:
            return 0.0
        base = 41.0 if self.cw == 0 else 28.0 + 0.42 * self.setpoint
        return base + (random.uniform(0, 0.6) if self.noisy else 0.0)

    def handle(self, line: str) -> list[str]:
        """Return the reply lines for one command line."""
        self.log.append(line)
        if not self.responsive:
            return []
        if line.startswith("?"):
            return self._query(line[1:])
        key, _, value = line.partition("=")
        if key == ">":
            self.cmd_prompt = value == "1"
            return [line, ""] if not self.cmd_prompt else [line]
        if key == "L":
            if value == "1" and self.interlock_open:
                return ["L=0", "Interlock open"]
            self.emission = value == "1"
            return [f"L={value}"]
        if key == "P":
            self.setpoint = float(value)
            return [line]
        if key == "CW":
            self.cw = int(value)
            if self.cw == 1:
                self.ana = 0  # CW forces analog power mode
            return [line]
        if key == "EXT":
            self.ext = int(value)
            return [line]
        if key == "ANA":
            self.ana = int(value) if self.cw == 0 else 0
            return [f"ANA={self.ana}"]
        if key == "CAL":
            self.calibration = float(value)
            return []  # the laser sends nothing for CAL
        if key == "CDRH":
            return [line]
        return ["?"]

    def _query(self, name: str) -> list[str]:
        values = {
            ">": int(self.cmd_prompt),
            "MAXLP": self.max_mw,
            "MINLP": self.min_mw,
            "NOMP": self.nom_mw,
            "SP": f"{self.setpoint:.2f}",
            "C": f"{self.current_ma:.1f}",
            "CW": self.cw,
            "EXT": self.ext,
            "ANA": self.ana,
            "L": int(self.emission),
        }
        if name not in values:
            return ["?"]
        return [f"{name}={values[name]}"]


def default_registry(noisy: bool = False) -> dict[str, LaserSim]:
    """Create one :class:`LaserSim` per entry in :data:`SIM_PORTS`."""
    return {
        "SIM1": LaserSim(noisy=noisy),
        "SIM-INTERLOCK": LaserSim(interlock_open=True, noisy=noisy),
        "SIM-SILENT": LaserSim(responsive=False),
        "SIM-BUSY": LaserSim(busy=True),
        "SIM-SMALL": LaserSim(max_mw=40.0, nom_mw=35.0, noisy=noisy),
    }


class FakeSerial:
    """Duck-types the part of ``serial.Serial`` the driver uses.

    Each instance has its own reply buffer, like a real port handle; the
    driver's probe connection and main connection share one :class:`LaserSim`.
    """

    registry: dict[str, LaserSim] = {}
    realtime: bool = False
    """Sleep on silent reads (capped at 1 s) to feel like real hardware."""

    _lock = threading.Lock()

    def __init__(self, port: str, baudrate: int = 19200, timeout: float | None = None,
                 write_timeout: float | None = None):
        sim = self.registry.get(port)
        if sim is None:
            raise serial.SerialException(
                f"could not open port '{port}': FileNotFoundError(2, 'The system cannot find the file specified.')")
        if sim.busy:
            raise serial.SerialException(f"could not open port '{port}': PermissionError(13, 'Access is denied.')")
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.write_timeout = write_timeout
        self.sim = sim
        self.is_open = True
        self._rx = bytearray()

    def open(self) -> None:
        self.is_open = True

    def close(self) -> None:
        self.is_open = False

    def write(self, data: bytes) -> int:
        self._check_open()
        self.sim.threads.add(threading.get_ident())
        for raw in data.split(CRLF):
            if raw:
                with self._lock:
                    replies = self.sim.handle(raw.decode())
                for reply in replies:
                    self._rx += reply.encode() + CRLF
        return len(data)

    def read_until(self, expected: bytes = b"\n", size: int | None = None) -> bytes:
        self._check_open()
        idx = self._rx.find(expected)
        if idx < 0:
            if self.realtime and self.timeout:
                time.sleep(min(self.timeout, 1.0))
            out, self._rx = bytes(self._rx), bytearray()
            return out
        end = idx + len(expected)
        out = bytes(self._rx[:end])
        del self._rx[:end]
        return out

    def _check_open(self) -> None:
        if not self.is_open:
            raise serial.SerialException("Attempting to use a port that is not open")


def install(registry: dict[str, LaserSim] | None = None, *, realtime: bool = False) -> dict[str, LaserSim]:
    """Point the driver at the simulator.

    Call before any connection is opened.

    Args:
        registry: Port name -> simulator; defaults to :func:`default_registry`.
        realtime: Make silent reads take time, as on real hardware.

    Returns:
        The registry in use, so tests can inspect ``sim.log``.
    """
    from laser_control import driver

    FakeSerial.registry = registry if registry is not None else default_registry(noisy=realtime)
    FakeSerial.realtime = realtime
    driver.serial = types.SimpleNamespace(
        Serial=FakeSerial,
        SerialException=serial.SerialException,
        SerialTimeoutException=serial.SerialTimeoutException,
    )
    return FakeSerial.registry


def uninstall() -> None:
    """Restore the real pyserial module in the driver."""
    from laser_control import driver

    driver.serial = serial
