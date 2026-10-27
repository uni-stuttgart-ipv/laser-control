"""A simulated laser that speaks the real serial protocol, for ``--simulate`` and the tests.

``SimulatedDevice`` models the laser's side of the protocol (see ``laser.py``):
it takes command lines and returns reply lines. ``SimulatedPort`` puts it
behind the same small serial interface ``pyserial`` offers, so the real
``Laser`` driver, the procedures and the controller all run unchanged:

    laser = Laser(SimulatedPort(SimulatedDevice()), name="SIM")

The tests also serve a ``SimulatedDevice`` on a pseudo-terminal to exercise
real serial I/O (``tests/serial_pty.py``).
"""

from __future__ import annotations

import random
import threading
from typing import Optional

from .laser import EOL, Laser

SIM_PORT = "SIM"


class SimulatedDevice:
    """The laser's behaviour at the protocol level.

    Attributes:
        state: the emulated settings: ``L`` (emission 0/1), ``SP`` (setpoint
            mW), ``CW`` (1 continuous / 0 pulsed), ``EXT``, ``ANA`` (0/1) and
            ``CAL`` (last calibration, or None).
        received: every command line received, in order (handy in tests).
        interlock_closed: when False, ``L=1`` is refused with "Interlock open".
        mute: when True the device stops answering (as if unplugged or hung).
        prompt: the command-prompt setting (``?>`` / ``>=``).
        banner: lines sent once before the first reply, like a power-up message.
    """

    def __init__(self, min_mw: float = 0.5, nominal_mw: float = 40.0, max_mw: float = 50.0,
                 interlock_closed: bool = True, prompt: bool = False,
                 banner: tuple[str, ...] = ()) -> None:
        self.limits = (min_mw, nominal_mw, max_mw)
        self.state: dict[str, Optional[float]] = {
            "L": 0, "SP": 5.0, "CW": 1, "EXT": 0, "ANA": 0, "CAL": None}
        self.received: list[str] = []
        self.interlock_closed = interlock_closed
        self.mute = False
        self.prompt = prompt
        self._banner = list(banner)

    # -- convenience for tests
    @property
    def emitting(self) -> bool:
        """True while emission is on."""
        return bool(self.state["L"])

    @property
    def setpoint(self) -> float:
        """The power setpoint in mW."""
        return float(self.state["SP"])

    def handle(self, line: str) -> list[str]:
        """Process one command line and return the reply lines."""
        self.received.append(line)
        if self.mute:
            return []
        replies, self._banner = self._banner, []
        return replies + self._reply(line)

    def _reply(self, cmd: str) -> list[str]:
        s = self.state
        mn, nom, mx = self.limits
        key, _, value = cmd.partition("=")
        queries = {
            "?>": lambda: f">={int(self.prompt)}",
            "?MINLP": lambda: f"MINLP={mn:.3f}",
            "?NOMP": lambda: f"NOMP={nom:.3f}",
            "?MAXLP": lambda: f"MAXLP={mx:.3f}",
            "?L": lambda: f"L={s['L']}",
            "?SP": lambda: f"SP={s['SP']:.3f}",
            "?C": lambda: f"C={self._current():.1f}",
        }
        if cmd in queries:
            return [queries[cmd]()]
        try:
            if key == ">":
                was_on, self.prompt = self.prompt, bool(int(value))
                # Switching the prompt off leaves one extra (empty) line behind.
                return [f">={int(self.prompt)}"] + ([""] if was_on and not self.prompt else [])
            if key == "L":
                if int(value) == 1 and not self.interlock_closed:
                    return ["L=0", "Interlock open"]
                s["L"] = int(value)
                return [f"L={s['L']}"]
            if key == "P":
                s["SP"] = float(value)
                return [f"P={s['SP']:.3f}"]
            if key in ("CW", "EXT"):
                s[key] = int(value)
                return [f"{key}={s[key]}"]
            if key == "ANA":
                # Current modulation (1) is only accepted in pulsed mode (CW=0).
                want = int(value)
                s["ANA"] = want if (want == 0 or s["CW"] == 0) else 0
                return [f"ANA={s['ANA']}"]
            if key == "CAL":
                s["CAL"] = float(value)
                return []                         # no reply, like the real laser
        except ValueError:
            pass
        return ["Error"]

    def _current(self) -> float:
        """A plausible diode current in mA for the present state."""
        if not self.state["L"]:
            return 0.0
        return 30.0 + 1.6 * float(self.state["SP"]) + random.uniform(-0.4, 0.4)


class SimulatedPort:
    """An in-memory stand-in for ``serial.Serial`` connected to a ``SimulatedDevice``.

    A read with nothing to return behaves like a serial timeout (it returns
    ``b""``), but without waiting. ``fail_next`` raises the given exception on
    the next write, to simulate an unplugged cable.
    """

    def __init__(self, device: SimulatedDevice) -> None:
        self.device = device
        self.is_open = True
        self.fail_next: Optional[Exception] = None
        self._pending: list[bytes] = []
        self._lock = threading.Lock()

    def write(self, data: bytes) -> int:
        with self._lock:
            if not self.is_open:
                raise OSError("port closed")
            if self.fail_next is not None:
                exc, self.fail_next = self.fail_next, None
                raise exc
            for line in data.split(EOL):
                if line:
                    self._pending += [r.encode("ascii") + EOL
                                      for r in self.device.handle(line.decode("ascii"))]
            return len(data)

    def read_until(self, expected: bytes = EOL) -> bytes:
        with self._lock:
            if not self.is_open:
                raise OSError("port closed")
            return self._pending.pop(0) if self._pending else b""

    def reset_input_buffer(self) -> None:
        with self._lock:
            self._pending.clear()

    def close(self) -> None:
        self.is_open = False


def simulated_laser(port: str = SIM_PORT, **device_options) -> Laser:
    """A connected ``Laser`` backed by a new ``SimulatedDevice`` (options go to the device)."""
    return Laser(SimulatedPort(SimulatedDevice(**device_options)), name=port)
