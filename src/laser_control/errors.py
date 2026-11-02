"""Turn driver exceptions and warnings into messages a lab user can act on.

The driver reports problems in three different ways, all handled here:

* exceptions from pyserial (port busy, missing, unplugged, write timeout);
* ``ValueError`` when a reply is empty, which is how a read timeout shows up
  (``float('')`` / ``int('')`` inside the driver);
* ``warnings.warn`` for soft problems: ``on()`` refused, power above nominal
  or below minimum. These are captured by the worker and passed in as text.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto

import serial

from laser_control.model import UserMessage


class OffNotConfirmed(ConnectionError):
    """``off()`` was sent but the laser did not answer afterwards."""


class Phase(Enum):
    """What the app was doing when the exception happened."""

    CONNECT = auto()
    COMMAND = auto()


class ErrorKind(Enum):
    """What went wrong, independent of the wording shown to the user."""

    PORT_BUSY = auto()
    PORT_NOT_FOUND = auto()
    NO_RESPONSE = auto()
    WRONG_DEVICE = auto()
    WRITE_TIMEOUT = auto()
    LINK_LOST = auto()
    POWER_TOO_HIGH = auto()
    POWER_NEGATIVE = auto()
    ANALOG_MODE_REFUSED = auto()
    OFF_NOT_CONFIRMED = auto()
    UNEXPECTED = auto()


@dataclass(frozen=True)
class Classified:
    """Result of :func:`classify`.

    Attributes:
        kind: What went wrong.
        fatal: The connection can no longer be trusted and must be closed.
        message: Text for the UI.
    """

    kind: ErrorKind
    fatal: bool
    message: UserMessage


def classify(exc: BaseException, phase: Phase, port: str = "the port") -> Classified:
    """Classify an exception raised by the driver.

    Args:
        exc: The exception.
        phase: Whether it happened while connecting or during a command.
        port: Port name, used in the message text.

    Returns:
        The classification. Unknown exceptions during a command are fatal,
        because the reply stream may be out of step.
    """
    text = str(exc)
    detail = f"{type(exc).__name__}: {text}"
    lowered = text.lower()

    if isinstance(exc, OffNotConfirmed):
        return Classified(ErrorKind.OFF_NOT_CONFIRMED, True, UserMessage(
            "error", "Off not confirmed",
            "The laser did not answer after the off command and may still be on. Check the laser.", detail))

    if isinstance(exc, serial.SerialTimeoutException):
        return Classified(ErrorKind.WRITE_TIMEOUT, True, UserMessage(
            "error", "Laser not responding", "Writing to the laser timed out. The connection was closed.", detail))

    if isinstance(exc, (serial.SerialException, OSError)):
        if phase is Phase.CONNECT:
            if any(s in lowered for s in ("access is denied", "resource busy", "in use", "permission denied")):
                return Classified(ErrorKind.PORT_BUSY, True, UserMessage(
                    "error", "Port busy",
                    f"{port} is in use by another app. Pick another port or close that app.", detail))
            return Classified(ErrorKind.PORT_NOT_FOUND, True, UserMessage(
                "error", "Port not found",
                f"{port} could not be opened. Check the USB cable and that the laser is on, then refresh ports.",
                detail))
        return Classified(ErrorKind.LINK_LOST, True, UserMessage(
            "error", "Connection lost", "The connection to the laser was lost. Check the cable, then connect again.",
            detail))

    if isinstance(exc, ValueError):
        if text == "`power` must be non-negative.":
            return Classified(ErrorKind.POWER_NEGATIVE, False, UserMessage(
                "warning", "Power not applied", "Power must be 0 mW or more.", detail))
        if text.endswith("''"):
            if phase is Phase.CONNECT:
                return Classified(ErrorKind.NO_RESPONSE, True, UserMessage(
                    "error", "No response",
                    f"No answer on {port}. Check that this is the laser's port and that the laser is on.", detail))
            return Classified(ErrorKind.NO_RESPONSE, True, UserMessage(
                "error", "Laser not responding", "The laser stopped answering. The connection was closed.", detail))
        if phase is Phase.CONNECT:
            return Classified(ErrorKind.WRONG_DEVICE, True, UserMessage(
                "error", "Unknown device", f"The device on {port} did not answer like the laser.", detail))

    if isinstance(exc, RuntimeError):
        if "greater than the laser's maximum" in text:
            return Classified(ErrorKind.POWER_TOO_HIGH, False, UserMessage(
                "warning", "Power not applied", "That power is above the laser's maximum.", detail))
        if "analog control mode" in text:
            return Classified(ErrorKind.ANALOG_MODE_REFUSED, False, UserMessage(
                "warning", "Camera mode incomplete", "The laser refused analog current control.", detail))

    return Classified(ErrorKind.UNEXPECTED, True, UserMessage(
        "error", "Unexpected error", f"{type(exc).__name__}: {text}", detail))


def is_fatal(exc: BaseException, phase: Phase) -> bool:
    """Shortcut for ``classify(exc, phase).fatal``, used by the worker."""
    return classify(exc, phase).fatal


ON_REFUSED_PREFIX = "Can not turn laser on due to "


def on_refused_cause(warning_texts: tuple[str, ...]) -> str | None:
    """Return the cause if the captured warnings show that ``on()`` was refused.

    Args:
        warning_texts: Warning messages captured while running ``on()``.

    Returns:
        The laser's cause line (e.g. ``"Interlock open"``), or ``None`` if the
        laser turned on.
    """
    for text in warning_texts:
        if text.startswith(ON_REFUSED_PREFIX):
            return text[len(ON_REFUSED_PREFIX):].rstrip(".") or "unknown cause"
    return None


def power_warning(warning_texts: tuple[str, ...], power_mw: float, nom_mw: float | None,
                  min_mw: float | None) -> UserMessage | None:
    """Turn the driver's power warnings into a message (the value was still applied).

    Args:
        warning_texts: Warning messages captured while setting power.
        power_mw: The power that was sent.
        nom_mw: Nominal power, for the message.
        min_mw: Minimum power, for the message.
    """
    for text in warning_texts:
        if "above nominal" in text:
            return UserMessage("warning", "Above nominal",
                               f"{power_mw:g} mW is above the nominal {nom_mw:g} mW. It was applied.")
        if "below minimum" in text:
            return UserMessage("warning", "Below minimum",
                               f"{power_mw:g} mW is below the minimum {min_mw:g} mW. Output may be unstable.")
    return None
