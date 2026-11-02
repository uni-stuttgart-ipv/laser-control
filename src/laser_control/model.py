"""Plain data types shared by the controller and the UI.

Everything here is immutable and free of I/O, so it can be passed between the
worker thread and the Tk thread without locking.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Literal


class ConnState(Enum):
    """Connection state of the app (not of the laser beam)."""

    DISCONNECTED = auto()
    CONNECTING = auto()
    CONNECTED = auto()
    DISCONNECTING = auto()
    ERROR = auto()
    """The last connection attempt failed, or a connected laser stopped responding."""
    SHUTTING_DOWN = auto()


class Mode(Enum):
    """Control mode selected in the UI.

    ``CAMERA`` runs the camera sequence (pulsed, external analog control,
    50 mW calibration). ``MANUAL`` runs the manual sequence (CW, internal
    control, power from the UI). ``UNKNOWN`` means a sequence failed part way
    and the laser's mode cannot be trusted.
    """

    MANUAL = auto()
    CAMERA = auto()
    UNKNOWN = auto()


class Emission(Enum):
    """Laser emission as far as this app can tell.

    The driver cannot read emission back, so:

    * ``ON``: the last ``on()`` succeeded.
    * ``OFF``: an ``off()`` was sent *and* the laser answered a status query
      straight afterwards, so the command was received
      (:func:`laser_control.sequences.laser_off_confirmed`).
    * ``UNKNOWN``: anything else, including right after connecting (the
      laser may have been left on) and after an unconfirmed off.
    """

    OFF = auto()
    ON = auto()
    UNKNOWN = auto()


@dataclass(frozen=True)
class Limits:
    """Power limits reported by the laser at connect time, in mW."""

    min_mw: float
    nom_mw: float
    max_mw: float


@dataclass(frozen=True)
class PortInfo:
    """A serial port the user can pick.

    Attributes:
        device: Name passed to the driver, e.g. ``"COM3"`` or ``"/dev/tty.usbserial-1"``.
        description: Human-readable description from the OS.
    """

    device: str
    description: str


DEFAULT_PORT = "COM3"
"""Port preselected when nothing better is known (the lab PC's laser port)."""

MessageLevel = Literal["info", "warning", "error"]


@dataclass(frozen=True)
class UserMessage:
    """A message for the UI's message line.

    Attributes:
        level: ``"info"`` shows as a hint, ``"warning"`` and ``"error"`` as a red banner.
        title: Short name of the problem, also used in the header status (e.g. "Port busy").
        text: One or two plain sentences that say what happened and what to do.
        detail: Optional technical detail (exception text) for the log.
    """

    level: MessageLevel
    title: str
    text: str
    detail: str | None = None


@dataclass(frozen=True)
class Snapshot:
    """Everything the UI needs to draw one frame.

    Attributes:
        conn: Connection state.
        port: Selected serial port.
        mode: Selected control mode. When connected, its sequence has been applied
            (or is being applied, see ``applying``).
        emission: Emission as far as the app can tell (see :class:`Emission`).
        busy: A user command is queued or running on the worker thread.
        applying: The mode whose sequence is running right now, or ``None``.
        on_refused: The last ``on()`` was refused (interlock or key switch).
        emission_warning: The laser may still be emitting and the app could not
            confirm it is off (link lost, or off sent without an answer).
            Stays set, even after disconnecting, until an off is confirmed.
        setpoint_mw: Power set point reported by the laser (``?SP``).
        current_ma: Diode current reported by the laser (``?C``).
        limits: Power limits, known once connected.
        last_error: Why the app is in ``ConnState.ERROR``.
    """

    conn: ConnState = ConnState.DISCONNECTED
    port: str = DEFAULT_PORT
    mode: Mode = Mode.MANUAL
    emission: Emission = Emission.OFF
    busy: bool = False
    applying: Mode | None = None
    on_refused: bool = False
    emission_warning: bool = False
    setpoint_mw: float | None = None
    current_ma: float | None = None
    limits: Limits | None = None
    last_error: UserMessage | None = None

    @property
    def connected(self) -> bool:
        """True while a laser is connected and usable."""
        return self.conn is ConnState.CONNECTED

    @property
    def emitting(self) -> bool:
        """True while the laser is (as far as this app knows) emitting."""
        return self.connected and self.emission is Emission.ON
