"""Serial driver for the lab laser: one method per command of its ASCII protocol.

Protocol (19200 baud, 8N1, every line ends with CR LF):

* A query ``?KEY`` is answered with one line ``KEY=value`` (some firmware
  versions omit the ``KEY=`` part; both are accepted).
* A command ``KEY=value`` is answered with one line echoing the value the
  laser actually applied, e.g. ``ANA=0`` when current modulation is refused.
* ``L=1`` (emission on) is answered ``L=1``, or ``L=0`` followed by a second
  line with the reason (for example ``Interlock open``).
* ``CAL=value`` (pulsed-mode calibration) sends no reply.
* After power-up the laser may print a banner, and it may have its command
  prompt enabled (``?>`` answers ``>=1``); the prompt is switched off while
  the app is connected and restored on close.

Every read is strict: no reply within the timeout, or a reply that cannot be
parsed, raises ``CommError``, so a silent laser is never mistaken for a
valid value. The protocol is strictly request / reply, so unread input is
discarded before every request: a late reply to an earlier, timed-out
request can never be taken as the answer to the next one. The class talks to any object with the small ``Transport``
interface (``pyserial.Serial`` or the simulator's port).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional, Protocol

log = logging.getLogger(__name__)

BAUDRATE = 19200
EOL = b"\r\n"
DEFAULT_TIMEOUT_S = 1.0       # per read / write; the laser answers in a few ms
HANDSHAKE_TIMEOUT_S = 5.0     # first reply after opening: a laser may still be booting
PROMPT_SEARCH_LINES = 10      # lines to skip (banner) while looking for the ?> reply


class LaserError(RuntimeError):
    """Base class for every error reported by the laser driver."""


class CommError(LaserError):
    """The laser did not answer in time, or answered something that cannot be trusted."""


class LaserRefused(LaserError):
    """The laser answered but refused the command (e.g. interlock open)."""


@dataclass(frozen=True)
class Limits:
    """Power limits reported by the laser, in mW."""

    min_mw: float
    nominal_mw: float
    max_mw: float


class Transport(Protocol):
    """The part of ``serial.Serial`` the driver uses."""

    is_open: bool

    def write(self, data: bytes) -> Optional[int]: ...
    def read_until(self, expected: bytes = ...) -> bytes: ...
    def reset_input_buffer(self) -> None: ...
    def close(self) -> None: ...


def open_serial(port: str, timeout: float = DEFAULT_TIMEOUT_S) -> Transport:
    """Open ``port`` with the laser's serial settings."""
    import serial                                    # imported here: tests can run without a port
    return serial.Serial(port, baudrate=BAUDRATE, timeout=timeout, write_timeout=timeout)


class Laser:
    """A connected laser. Not thread-safe: use it from one thread (the controller's worker).

    Args:
        transport: an open serial port (see ``open_serial``) or a simulated one.
        name: the port name, for messages and logs.

    Opening performs the handshake: drop any power-up banner, switch the
    command prompt off if it is on, and read the power ``limits``.
    """

    def __init__(self, transport: Transport, name: str = "") -> None:
        self._io = transport
        self.name = name
        self._prompt_was_on = False
        try:
            self._handshake()
            self.limits = self.read_limits()
        except Exception:
            self.close()                                 # also restores the prompt
            raise

    # ------------------------------------------------------------------ line I/O
    def _request(self, line: str) -> None:
        """Send a request line after discarding any unread (stale) input."""
        try:
            self._io.reset_input_buffer()
        except Exception as exc:
            raise CommError(f"Could not access the serial port: {exc}") from exc
        self._write(line)

    def _write(self, line: str) -> None:
        log.debug("%s <- %s", self.name, line)
        try:
            self._io.write(line.encode("ascii") + EOL)
        except Exception as exc:
            raise CommError(f"Could not write to the laser: {exc}") from exc

    def _readline(self) -> str:
        """One reply line without its line ending. Raises ``CommError`` on timeout."""
        try:
            raw = self._io.read_until(EOL)
        except Exception as exc:
            raise CommError(f"Could not read from the laser: {exc}") from exc
        if not raw.endswith(EOL):
            raise CommError("No reply from the laser (timeout).")
        line = raw[:-len(EOL)].decode("ascii", errors="replace").strip()
        log.debug("%s -> %s", self.name, line)
        return line

    def drain(self) -> None:
        """Discard every line the laser has sent but nobody read (stops at the first timeout)."""
        while True:
            try:
                raw = self._io.read_until(EOL)
            except Exception as exc:
                raise CommError(f"Could not read from the laser: {exc}") from exc
            if not raw.endswith(EOL):
                return
            log.debug("%s -> %s (discarded)", self.name, raw.strip())

    @staticmethod
    def _value(key: str, line: str) -> str:
        """``'KEY=value'`` (or a bare ``'value'``) -> ``'value'``."""
        prefix = f"{key}="
        return line[len(prefix):] if line.startswith(prefix) else line

    def query(self, key: str) -> str:
        """Send ``?KEY`` and return the value of the reply."""
        self._request(f"?{key}")
        return self._value(key, self._readline())

    def command(self, key: str, value: object) -> str:
        """Send ``KEY=value`` and return the value the laser echoes back."""
        self._request(f"{key}={value}")
        return self._value(key, self._readline())

    def query_number(self, key: str, what: str) -> float:
        """``query`` parsed as a float; ``CommError`` naming ``what`` if it is not a number."""
        reply = self.query(key)
        try:
            return float(reply)
        except ValueError:
            raise CommError(f"No valid {what} reply from the laser (got {reply!r}).") from None

    def _flag(self, key: str, reply: str) -> bool:
        """A ``0`` / ``1`` reply as a bool; anything else is a ``CommError``."""
        if reply not in ("0", "1"):
            raise CommError(f"Unexpected reply to {key} from the laser: {reply!r}.")
        return reply == "1"

    # ------------------------------------------------------------------ connection
    def _handshake(self) -> None:
        self.drain()                                     # power-up banner, stale replies
        self._request("?>")
        line = ""
        normal_timeout = getattr(self._io, "timeout", None)
        if normal_timeout is not None:                   # give a booting laser time to answer
            self._io.timeout = max(normal_timeout, HANDSHAKE_TIMEOUT_S)
        try:
            for _ in range(PROMPT_SEARCH_LINES):         # skip banner lines until ">=" arrives
                try:
                    line = self._readline()
                except CommError:
                    line = ""                            # silence: not (or not yet) the laser
                    break
                if line.startswith(">="):
                    self._prompt_was_on = self._flag("?>", self._value(">", line))
                    break
        finally:
            if normal_timeout is not None:
                self._io.timeout = normal_timeout
        if not line.startswith(">="):
            raise CommError("The device on this port does not answer like the laser "
                            "(check the port and that the laser is switched on).")
        if self._prompt_was_on:
            self.command(">", 0)                         # replies must be plain lines
            self.drain()

    def close(self) -> None:
        """Restore the command prompt if it was on, then close the port. Never raises."""
        try:
            if self._prompt_was_on and self._io.is_open:
                self._request(">=1")
                self._io.read_until(EOL)                 # wait for the echo: it was sent
        except Exception:
            pass
        try:
            self._io.close()
        except Exception:
            pass

    # ------------------------------------------------------------------ readings
    def read_limits(self) -> Limits:
        """Read the minimum, nominal and maximum power (``?MINLP``, ``?NOMP``, ``?MAXLP``)."""
        limits = Limits(
            min_mw=self.query_number("MINLP", "minimum power"),
            nominal_mw=self.query_number("NOMP", "nominal power"),
            max_mw=self.query_number("MAXLP", "maximum power"),
        )
        if not 0 <= limits.min_mw <= limits.nominal_mw <= limits.max_mw:
            raise CommError(f"Implausible power limits from the laser: {limits}")
        return limits

    def is_emitting(self) -> bool:
        """True if emission is on (``?L``)."""
        return self._flag("?L", self.query("L"))

    def read_setpoint(self) -> float:
        """The power setpoint in mW (``?SP``)."""
        return self.query_number("SP", "power setpoint")

    def read_current(self) -> float:
        """The diode current in mA (``?C``)."""
        return self.query_number("C", "current")

    # ------------------------------------------------------------------ commands
    def turn_on(self) -> None:
        """Emission on (``L=1``). Raises ``LaserRefused`` with the laser's reason if refused."""
        if not self._flag("L=1", self.command("L", 1)):
            reason = self._readline()
            raise LaserRefused(f"The laser refused to turn on: {reason or 'no reason given'}.")

    def turn_off(self) -> None:
        """Emission off (``L=0``). Does not read the state back; see ``operations.turn_off``."""
        self.command("L", 0)

    def set_power(self, mw: float) -> None:
        """Set the output power in mW (``P=``). No range check: see ``operations.set_power``."""
        self.command("P", mw)

    def set_continuous(self, cw: bool) -> None:
        """Continuous-wave (True, ``CW=1``) or pulsed (False, ``CW=0``) operation."""
        self.command("CW", int(cw))

    def set_external_control(self, external: bool) -> None:
        """Analog control from the external input (True, ``EXT=1``) or internal (``EXT=0``)."""
        self.command("EXT", int(external))

    def set_current_modulation(self, current: bool) -> None:
        """Analog input modulates the current (True, ``ANA=1``) or the power (``ANA=0``).

        The laser accepts current modulation only in pulsed mode; it then
        echoes ``ANA=0``, which raises ``LaserError``.
        """
        if self._flag("ANA", self.command("ANA", int(current))) != current:
            raise LaserError("The laser did not accept the analog modulation mode "
                             "(current modulation needs pulsed mode).")

    def calibrate(self, mw: float) -> None:
        """Pulsed-mode calibration power in mW (``CAL=``). The laser sends no reply."""
        self._request(f"CAL={mw}")
