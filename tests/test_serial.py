"""The laser driver and the controller over a real serial port (a pty; Linux and macOS)."""

import pytest
from helpers import wait_for
from serial_pty import PtyLaser

from laser_app.controller import LaserController, Mode
from laser_app.hardware import operations as ops


@pytest.fixture
def pty():
    p = PtyLaser()
    yield p
    p.close()


def test_procedures_over_serial(pty):
    laser = ops.open_laser(pty.port)
    try:
        assert ops.read_limits(laser) == ops.Limits(0.5, 40.0, 50.0)
        ops.turn_on(laser)
        assert ops.read_emitting(laser)
        ops.turn_off(laser)
        assert not ops.read_emitting(laser)
        ops.configure_camera(laser, 50)
        s = pty.device.state
        assert (s["EXT"], s["CW"], s["ANA"], s["CAL"]) == (1, 0, 1, 50.0)
        ops.configure_manual(laser)
        ops.set_power(laser, 5)
        assert (s["CW"], s["EXT"]) == (1, 0) and ops.read_setpoint(laser) == 5.0
    finally:
        ops.close(laser)
    assert not pty.device.emitting


def test_interlock_refusal_over_serial(pty):
    pty.device.interlock_closed = False
    laser = ops.open_laser(pty.port)
    try:
        with pytest.raises(ops.LaserRefused, match="Interlock open"):
            ops.turn_on(laser)
        assert not ops.read_emitting(laser)          # replies still in step
    finally:
        laser.close()


def test_silent_device_times_out(pty):
    pty.device.mute = True
    with pytest.raises(ops.CommError):
        ops.open_laser(pty.port)


def test_controller_over_serial(pty):
    ctl = LaserController(poll_interval_s=0.1)
    ctl.start()
    try:
        ctl.connect(pty.port, Mode.MANUAL, 5.0)
        wait_for(lambda: ctl.status.connected and not ctl.status.busy, timeout=8)
        ctl.apply_power(12)
        ctl.turn_on()
        wait_for(lambda: ctl.status.emitting, timeout=5)
        assert pty.device.setpoint == 12
        ctl.set_mode(Mode.CAMERA)
        wait_for(lambda: ctl.status.mode is Mode.CAMERA and not ctl.status.busy, timeout=8)
        s = pty.device.state
        assert s["L"] == 0 and s["ANA"] == 1 and s["CAL"] == 50.0
    finally:
        ctl.shutdown(timeout=8)
    assert not pty.device.emitting
