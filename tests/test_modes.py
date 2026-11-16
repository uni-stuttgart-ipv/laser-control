"""The mode files send the expected commands, in order."""
import coherent_cube as cc

from conftest import FakeLaser
from laser_control import camera, manual


def test_manual_apply_sets_continuous_internal_control_and_the_power():
    laser = FakeLaser("COM3")
    manual.apply(laser, 12.5)
    assert laser.sent == [
        ("operation_mode", cc.OperationMode.CW),
        ("analog_control", cc.AnalogControl.Internal),
        ("power", 12.5),
    ]


def test_manual_set_power_sends_only_the_power():
    laser = FakeLaser("COM3")
    manual.set_power(laser, 7)
    assert laser.sent == [("power", 7)]


def test_camera_apply_runs_continuous_at_full_power_then_calibrates_in_pulse_mode():
    laser = FakeLaser("COM3")
    camera.apply(laser, 50)
    assert laser.sent == [
        ("operation_mode", cc.OperationMode.CW),          # continuous at 50 mW, like manual mode ...
        ("analog_control", cc.AnalogControl.Internal),
        ("power", 50),
        ("on", None),
        ("analog_control", cc.AnalogControl.External),    # ... then pulsed, external control, calibrated at 50 mW
        ("operation_mode", cc.OperationMode.Pulsed),
        ("power", 50),
        ("calibrate", 50),
    ]


def test_camera_apply_keeps_the_analog_control_mode_line():
    # The line runs, but sends nothing: it only replaces the method on the object.
    laser = FakeLaser("COM3")
    camera.apply(laser, 50)
    assert laser.analog_control_mode == cc.AnalogControlMode.Current
    assert "analog_control_mode" not in [name for name, _ in laser.sent]


def test_camera_apply_waits_before_calibrating(monkeypatch):
    waits = []
    monkeypatch.setattr(camera.time, "sleep", waits.append)
    camera.apply(FakeLaser("COM3"), 50)
    assert waits == [camera.WARM_UP_S]
