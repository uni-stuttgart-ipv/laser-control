"""The controller: every situation in the behaviour table, against a fake laser."""
import coherent_cube as cc
import serial

from conftest import FakeLaser, connect, wait
from laser_control import controller
from laser_control.controller import CAMERA_POWER_MW, MAX_POWER_MW


# ---- connecting ----

def test_connect_turns_the_laser_off_then_applies_manual(ctl):
    ctl.connect("COM3", "manual", 5)
    results = wait(ctl)
    assert ctl.laser.port == "COM3"
    assert ctl.laser.sent == [
        ("off", None),
        ("operation_mode", cc.OperationMode.CW),
        ("analog_control", cc.AnalogControl.Internal),
        ("power", 5),
    ]
    assert results == [("connected", FakeLaser.min_power), ("mode", "manual"), ("power", 5)]


def test_connect_in_camera_mode_calibrates_and_asks_nothing_after(ctl):
    ctl.connect("COM3", "camera", 5)
    results = wait(ctl)
    assert ctl.laser.sent[-1] == ("calibrate", CAMERA_POWER_MW)   # no query right after calibrate
    assert results[-2:] == [("mode", "camera"), ("power", CAMERA_POWER_MW)]


def test_connect_to_a_missing_port_reports_an_error(ctl, monkeypatch):
    def no_laser(port, timeout=None, write_timeout=None):
        raise serial.SerialException(f"could not open port {port}")

    monkeypatch.setattr(controller, "CoherentCube", no_laser)
    ctl.connect("COM9", "manual", 5)
    assert wait(ctl) == [("error", "could not open port COM9")]
    assert ctl.laser is None


def test_connect_works_again_after_a_failed_connect(ctl, monkeypatch):
    def no_laser(port, timeout=None, write_timeout=None):
        raise serial.SerialException("could not open port")

    monkeypatch.setattr(controller, "CoherentCube", no_laser)
    ctl.connect("COM9", "manual", 5)
    wait(ctl)
    monkeypatch.setattr(controller, "CoherentCube", FakeLaser)
    ctl.connect("COM3", "manual", 5)
    assert ("connected", FakeLaser.min_power) in wait(ctl)   # the thread survived the error


def test_connect_power_is_kept_within_the_limits(ctl):
    ctl.connect("COM3", "manual", 80)
    assert wait(ctl)[-1] == ("power", MAX_POWER_MW)


# ---- turning on and off ----

def test_turn_on(ctl):
    laser = connect(ctl)
    laser.current_ma = 41.2
    ctl.turn_on()
    assert wait(ctl) == [("laser", True), ("current", 41.2)]
    assert ctl.laser_is_on


def test_turn_on_refused_by_the_interlock_stays_connected(ctl):
    laser = connect(ctl)
    laser.refuse_reason = "interlock open"
    ctl.turn_on()
    results = wait(ctl)
    assert results[0] == ("refused", "Can not turn laser on due to interlock open.")
    assert not ctl.laser_is_on
    assert ctl.laser is laser   # still connected


def test_turn_off(ctl):
    laser = connect(ctl)
    ctl.turn_on()
    ctl.turn_off()
    results = wait(ctl)
    assert ("laser", False) in results
    assert laser.sent[-2] == ("off", None)
    assert not ctl.laser_is_on


# ---- power ----

def test_set_power(ctl):
    laser = connect(ctl)
    ctl.set_power(12.5)
    assert wait(ctl)[0] == ("power", 12.5)
    assert laser.sent[0] == ("power", 12.5)


def test_power_above_the_maximum_is_limited(ctl):
    laser = connect(ctl)
    ctl.set_power(80)
    wait(ctl)
    assert laser.sent[0] == ("power", MAX_POWER_MW)


def test_power_below_the_laser_minimum_is_raised(ctl):
    laser = connect(ctl)
    ctl.set_power(0)
    wait(ctl)
    assert laser.sent[0] == ("power", FakeLaser.min_power)


def test_power_changes_are_sent_in_order(ctl):
    laser = connect(ctl)
    for power in (6, 7, 8):
        ctl.set_power(power)
    wait(ctl)
    assert [value for name, value in laser.sent if name == "power"] == [6, 7, 8]


# ---- switching mode ----

def test_switch_to_camera_while_off(ctl):
    laser = connect(ctl)
    ctl.use_mode("camera", 5)
    assert wait(ctl) == [("mode", "camera"), ("power", CAMERA_POWER_MW)]
    assert laser.sent[-1] == ("calibrate", CAMERA_POWER_MW)


def test_switch_mode_while_on_is_refused_and_sends_nothing(ctl):
    laser = connect(ctl)
    ctl.turn_on()
    wait(ctl)
    laser.sent.clear()
    ctl.use_mode("camera", 5)
    assert wait(ctl) == [("refused", "Turn the laser off to switch mode.")]
    assert laser.sent == []


# ---- errors ----

def test_lost_connection_reports_an_error_and_closes_the_port(ctl):
    laser = connect(ctl)
    laser.broken = True
    ctl.set_power(10)
    assert wait(ctl) == [("error", "device disconnected")]
    assert laser.sent[-1] == ("close", None)
    assert ctl.laser is None
    assert not ctl.laser_is_on


def test_lost_connection_while_on_tries_to_turn_off_first(ctl):
    laser = connect(ctl)
    ctl.turn_on()
    wait(ctl)
    laser.broken = True
    ctl.turn_off()
    wait(ctl)
    assert laser.sent[-1] == ("close", None)
    assert not ctl.laser_is_on


def test_a_command_while_disconnected_reports_an_error_not_a_crash(ctl):
    ctl.turn_on()
    kind, _ = wait(ctl)[0]
    assert kind == "error"


# ---- disconnecting and closing ----

def test_disconnect_turns_off_then_closes(ctl):
    laser = connect(ctl)
    ctl.disconnect()
    assert wait(ctl) == [("disconnected", None)]
    assert laser.sent == [("off", None), ("close", None)]
    assert ctl.laser is None


def test_disconnect_when_not_connected_does_nothing_harmful(ctl):
    ctl.disconnect()
    assert wait(ctl) == [("disconnected", None)]


def test_shut_down_turns_the_laser_off_and_stops_the_thread(ctl):
    laser = connect(ctl)
    ctl.turn_on()
    ctl.shut_down()
    assert laser.sent[-2:] == [("off", None), ("close", None)]
    assert not ctl._thread.is_alive()


def test_get_results_returns_each_result_once(ctl):
    connect(ctl)
    ctl.disconnect()
    wait(ctl)
    assert ctl.get_results() == []
