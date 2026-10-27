"""Laser procedures used by the controller: connect, verified off, power and the two modes.

``laser.Laser`` sends single commands; this module combines them into the
procedures the app needs and adds the safety rules:

* "off" is always read back (``?L``) and retried, never assumed;
* a power value is checked against the laser's limits before it is sent:
  negative or above the maximum raises ``PowerRejected`` (nothing is sent),
  above nominal or below minimum is sent with an advisory message;
* the two mode set-ups follow the reference procedure for this setup:

  ===========  ==========================================================
  Manual       ``CW=1`` (continuous), ``EXT=0`` (internal control), ``P=<mW>``
  Camera       ``EXT=1`` (external control), ``CW=0`` (pulsed),
               ``ANA=1`` (current modulation), ``P=50``, ``CAL=50``
  ===========  ==========================================================

  Current modulation is only accepted in pulsed mode, so ``ANA=1`` is sent
  after ``CW=0``.

All functions run on the controller's worker thread only.
"""

from __future__ import annotations

from .laser import CommError, Laser, LaserError, LaserRefused, Limits, open_serial

__all__ = [
    "CommError", "LaserError", "LaserRefused", "Limits", "PowerRejected", "OFF_ATTEMPTS",
    "open_laser", "read_limits", "read_emitting", "read_setpoint", "read_current",
    "turn_on", "turn_off", "check_power", "set_power", "configure_manual",
    "configure_camera", "close",
]

OFF_ATTEMPTS = 3


class PowerRejected(ValueError):
    """A power value outside what the laser accepts (negative, or above its maximum).

    Raised before anything is sent, so the link is still good.
    """


def open_laser(port: str) -> Laser:
    """Open ``port`` and connect to the laser (handshake + limits)."""
    return Laser(open_serial(port), name=port)


def read_limits(laser: Laser) -> Limits:
    """The power limits read at connect time."""
    return laser.limits


def read_emitting(laser: Laser) -> bool:
    """True if the laser reports emission on."""
    return laser.is_emitting()


def read_setpoint(laser: Laser) -> float:
    """The power setpoint in mW."""
    return laser.read_setpoint()


def read_current(laser: Laser) -> float:
    """The diode current in mA."""
    return laser.read_current()


def turn_on(laser: Laser) -> None:
    """Emission on. Raises ``LaserRefused`` (with the laser's reason) or ``CommError``."""
    laser.turn_on()


def turn_off(laser: Laser) -> None:
    """Emission off, then read ``?L`` until it confirms 0; ``CommError`` after ``OFF_ATTEMPTS``."""
    last_exc: Exception | None = None
    for _ in range(OFF_ATTEMPTS):
        try:
            laser.turn_off()
            if not laser.is_emitting():
                return
        except Exception as exc:           # keep trying; report the last failure
            last_exc = exc
    raise CommError("Could not confirm the laser is off.") from last_exc


def check_power(limits: Limits, mw: float) -> list[str]:
    """Check ``mw`` against ``limits``: ``PowerRejected`` if refused, else advisory messages."""
    if mw < 0:
        raise PowerRejected(f"{mw:g} mW is negative; nothing was sent.")
    if mw > limits.max_mw:
        raise PowerRejected(f"{mw:g} mW is above the laser's maximum of "
                            f"{limits.max_mw:g} mW; nothing was sent.")
    notes = []
    if mw > limits.nominal_mw:
        notes.append(f"Power is above nominal ({limits.nominal_mw:g} mW).")
    if mw < limits.min_mw:
        notes.append(f"Power is below the laser's minimum ({limits.min_mw:g} mW).")
    return notes


def set_power(laser: Laser, mw: float) -> list[str]:
    """Check and send a power setpoint. Returns advisory messages; raises ``PowerRejected``.

    The app sets no limits of its own; only the laser's reported limits apply.
    """
    notes = check_power(laser.limits, mw)
    laser.set_power(mw)
    return notes


def configure_manual(laser: Laser) -> None:
    """Manual mode set-up: continuous wave, internal control (the power is set separately)."""
    laser.set_continuous(True)
    laser.set_external_control(False)


def configure_camera(laser: Laser, power_mw: float) -> list[str]:
    """Camera mode set-up at ``power_mw``: external, pulsed, current modulation, power, calibration.

    Returns advisory messages. ``CAL`` sends no reply, so anything stray is
    drained afterwards to keep later replies in step.
    """
    notes = check_power(laser.limits, power_mw)
    laser.set_external_control(True)
    laser.set_continuous(False)
    laser.set_current_modulation(True)     # accepted only after pulsed mode is set
    laser.set_power(power_mw)
    laser.calibrate(power_mw)
    laser.drain()
    return notes


def close(laser: Laser) -> bool:
    """Turn off (verified) and close the port. Returns True if "off" was confirmed."""
    try:
        turn_off(laser)
        confirmed = True
    except Exception:
        confirmed = False
    laser.close()
    return confirmed
