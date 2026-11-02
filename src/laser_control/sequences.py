"""The laser command sequences: the only code that changes the laser's state.

Each function mirrors the reference script line for line::

    laser = Laser("COM3")
    laser.on()
    laser.off()

    # camera control
    laser.analog_control_mode = ld.AnalogControlMode.Current
    laser.analog_control = ld.AnalogControl.External
    laser.operation_mode = ld.OperationMode.Pulsed
    laser.power = 50
    laser.calibrate(50)

    # manual control
    laser.operation_mode = ld.OperationMode.CW
    laser.analog_control = ld.AnalogControl.Internal
    laser.power = 5

    laser.close()

Rules for this module:

* Keep the order and the calls exactly as above. Tests in
  ``tests/test_sequences.py`` lock the bytes sent to the laser.
* Every function runs on the worker thread (see :mod:`laser_control.worker`);
  never call these from the Tk thread.
* Read-only helpers at the bottom only query the laser; they never change it.
"""

from __future__ import annotations

from enum import Enum

from laser_control import driver as ld
from laser_control.driver import Laser
from laser_control.model import Limits, Mode

CAMERA_POWER_MW = 50
"""Camera-mode power and calibration value from the reference script.

An ``int`` on purpose: the driver sends ``str(power)``, so this goes out as
``P=50`` / ``CAL=50`` exactly as in the script.
"""


class AnalogModePolicy(Enum):
    """How to treat the script's ``analog_control_mode`` line.

    In the driver ``analog_control_mode`` is a method, not a property, so the
    script's assignment sends nothing to the laser (it only replaces the method
    on that one object). Calling the method where the script assigns it would
    always fail, because the laser accepts analog *current* mode only once it
    is in Pulsed mode.
    """

    AS_WRITTEN = "as_written"
    """Keep the script's line verbatim. Nothing is sent for analog mode."""

    CALL_AFTER_PULSED = "call_after_pulsed"
    """Send the real ``ANA=1`` command, right after switching to Pulsed."""


ANALOG_MODE_POLICY = AnalogModePolicy.AS_WRITTEN
"""Open decision for the lab: change this one line to switch policy."""


def open_laser(port: str, timeout_s: float) -> Laser:
    """Connect to the laser on ``port``.

    The driver first probes the port with its own fixed 5 s timeout (up to ten
    reads), so a port with nothing listening can take about 50 s to fail.

    Args:
        port: Serial port name, e.g. ``"COM3"``.
        timeout_s: Read and write timeout for the main connection, in seconds.

    Returns:
        The connected driver object. Its power limits are already cached.
    """
    return Laser(port, timeout=timeout_s, write_timeout=timeout_s)


def laser_on(laser: Laser) -> None:
    """Turn emission on.

    The driver does not raise when the laser refuses (open interlock, key
    switch); it issues a ``UserWarning`` instead. The worker records it.
    """
    laser.on()


def laser_off(laser: Laser) -> None:
    """Turn emission off."""
    laser.off()


def laser_off_confirmed(laser: Laser) -> bool:
    """Turn emission off, then check that the laser actually heard it.

    The driver does not notice when a *command* gets no reply (a read timeout
    returns an empty line, which is discarded), so ``off()`` alone "succeeds"
    even if the laser is unplugged. A status query right afterwards does fail
    on an empty reply, so it tells us the off command reached a laser that is
    answering.

    Returns:
        True if the laser answered the follow-up query.

    Raises:
        Whatever ``off()`` raises (for example a write error on a lost port).
    """
    laser.off()
    try:
        read_status(laser)
    except Exception:
        return False
    return True


def close_laser(laser: Laser) -> None:
    """Close the serial port, as the reference script ends."""
    laser.close()


def apply_camera_mode(laser: Laser) -> None:
    """Configure the laser to be driven by the camera's analog signal.

    Sequence: (analog current mode) -> external control -> pulsed ->
    power 50 mW -> calibrate at 50 mW. See :class:`AnalogModePolicy` for the
    first step.

    Raises:
        RuntimeError: 50 mW is above the laser's maximum, or (policy
            ``CALL_AFTER_PULSED`` only) the laser refused analog current mode.
    """
    if ANALOG_MODE_POLICY is AnalogModePolicy.AS_WRITTEN:
        laser.analog_control_mode = ld.AnalogControlMode.Current  # verbatim from the script: sends nothing
    laser.analog_control = ld.AnalogControl.External
    laser.operation_mode = ld.OperationMode.Pulsed
    if ANALOG_MODE_POLICY is AnalogModePolicy.CALL_AFTER_PULSED:
        laser.analog_control_mode(ld.AnalogControlMode.Current)
    laser.power = CAMERA_POWER_MW
    laser.calibrate(CAMERA_POWER_MW)


def apply_manual_mode(laser: Laser, power_mw: float) -> None:
    """Configure continuous output at a power set in the UI.

    Sequence: CW -> internal control -> power.

    Args:
        power_mw: Output power in mW, already rounded by the caller.

    Raises:
        ValueError: ``power_mw`` is negative.
        RuntimeError: ``power_mw`` is above the laser's maximum.
    """
    laser.operation_mode = ld.OperationMode.CW
    laser.analog_control = ld.AnalogControl.Internal
    laser.power = power_mw


def set_power(laser: Laser, power_mw: float) -> None:
    """Change the power while already in manual mode (the UI's Apply button).

    Raises:
        ValueError: ``power_mw`` is negative.
        RuntimeError: ``power_mw`` is above the laser's maximum.
    """
    laser.power = power_mw


def apply_mode(laser: Laser, mode: Mode, power_mw: float) -> None:
    """Run the sequence for ``mode``.

    Args:
        mode: ``Mode.CAMERA`` or ``Mode.MANUAL``.
        power_mw: Used by manual mode only.

    Raises:
        ValueError: ``mode`` is ``Mode.UNKNOWN``.
    """
    if mode is Mode.CAMERA:
        apply_camera_mode(laser)
    elif mode is Mode.MANUAL:
        apply_manual_mode(laser, power_mw)
    else:
        raise ValueError(f"cannot apply {mode}")


# ---- read-only helpers (never change the laser) ----

def read_limits(laser: Laser) -> Limits:
    """Return the power limits the driver read at connect time (no I/O)."""
    return Limits(min_mw=laser._min_power, nom_mw=laser._nom_power, max_mw=laser._max_power)


def read_status(laser: Laser) -> tuple[float, float]:
    """Query the power set point (``?SP``, mW) and diode current (``?C``, mA)."""
    return laser.power, laser.current
