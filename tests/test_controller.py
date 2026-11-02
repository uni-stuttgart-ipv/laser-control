"""End-to-end behaviour of the controller against the simulator (no Tk).

Safety-related tests check the *simulated laser's* real state
(``sims[port].emission``), not only what the controller believes.
"""

from __future__ import annotations

import math
import time

import pytest

from laser_control import sequences
from laser_control.controller import LaserController, controls_for
from laser_control.model import ConnState, Emission, Limits, Mode, Snapshot

from conftest import commands


@pytest.fixture
def make(sims, scheduler):
    made = []

    def factory(port="SIM1", **kw):
        ctl = LaserController(scheduler, port=port, timeout_s=0.1, **kw)
        messages = []
        ctl.subscribe(lambda s: None, messages.append)
        made.append(ctl)
        return ctl, messages

    yield factory
    for ctl in made:
        ctl._worker.stop()
        ctl._worker.join(timeout=3)  # don't let a slow job leak into the next test's simulator


def idle(ctl):
    return lambda: not ctl.snapshot.busy and ctl.snapshot.applying is None


def connected(ctl, scheduler):
    """Connect and wait until the selected mode has been applied."""
    ctl.connect()
    scheduler.run_until(lambda: ctl.snapshot.connected)
    scheduler.run_until(idle(ctl))


def ready(ctl, scheduler):
    """Connect, then press the key once to confirm the laser is off."""
    connected(ctl, scheduler)
    ctl.laser_off()
    scheduler.run_until(lambda: ctl.snapshot.emission is Emission.OFF and not ctl.snapshot.busy)


def emitting(ctl, scheduler):
    ready(ctl, scheduler)
    ctl.laser_on()
    scheduler.run_until(lambda: ctl.snapshot.emitting)


# ---- connect and modes ----

def test_connect_applies_selected_manual_mode(make, scheduler, sims):
    ctl, _ = make(manual_power_mw=7.5)
    connected(ctl, scheduler)
    s = ctl.snapshot
    assert s.limits == Limits(0.5, 50.0, 55.0)
    assert s.mode is Mode.MANUAL and s.setpoint_mw == 7.5
    assert commands(sims["SIM1"].log) == ["CW=1", "EXT=0", "P=7.5"]


def test_emission_is_unknown_after_connect_until_off_is_confirmed(make, scheduler, sims):
    ctl, _ = make()
    connected(ctl, scheduler)
    assert ctl.snapshot.emission is Emission.UNKNOWN
    assert not controls_for(ctl.snapshot).laser_on
    ctl.laser_off()
    scheduler.run_until(lambda: ctl.snapshot.emission is Emission.OFF)
    assert controls_for(ctl.snapshot).laser_on
    assert commands(sims["SIM1"].log)[-1] == "L=0"


def test_preselected_camera_mode_is_applied_on_connect(make, scheduler, sims):
    ctl, _ = make()
    ctl.select_mode(Mode.CAMERA)
    connected(ctl, scheduler)
    assert commands(sims["SIM1"].log) == ["EXT=1", "CW=0", "P=50", "CAL=50"]


def test_switching_mode_while_emitting_keeps_laser_on(make, scheduler, sims):
    ctl, _ = make()
    emitting(ctl, scheduler)
    sims["SIM1"].log.clear()
    ctl.select_mode(Mode.CAMERA)
    scheduler.run_until(idle(ctl))
    assert ctl.snapshot.emission is Emission.ON
    assert "L=0" not in sims["SIM1"].log
    assert commands(sims["SIM1"].log) == ["EXT=1", "CW=0", "P=50", "CAL=50"]


def test_off_does_not_cancel_a_queued_mode_change(make, scheduler, sims):
    ctl, _ = make()
    emitting(ctl, scheduler)
    gate = sims["SIM1"]
    original = gate.handle

    def slow(line):  # keep the worker busy so the mode job is still queued
        if line == "?SP":
            time.sleep(0.2)
        return original(line)

    gate.handle = slow
    ctl.refresh_status()
    time.sleep(0.05)
    ctl.select_mode(Mode.CAMERA)
    ctl.laser_off()
    scheduler.run_until(lambda: idle(ctl)() and ctl.snapshot.emission is Emission.OFF, timeout_s=5)
    assert ctl.snapshot.mode is Mode.CAMERA
    assert gate.cw == 0 and gate.ext == 1  # the laser really is in camera mode
    assert not gate.emission


def test_queued_on_is_cancelled_by_off(make, scheduler, sims):
    ctl, _ = make()
    ready(ctl, scheduler)
    gate = sims["SIM1"]
    original = gate.handle
    gate.handle = lambda line: (time.sleep(0.2) if line == "?SP" else None) or original(line)
    ctl.refresh_status()
    time.sleep(0.05)
    ctl.laser_on()
    ctl.laser_off()
    scheduler.run_until(idle(ctl), timeout_s=5)
    assert not gate.emission
    assert ctl.snapshot.emission is Emission.OFF


def test_failed_mode_marks_mode_unknown(make, scheduler):
    ctl, messages = make("SIM-SMALL")
    ready(ctl, scheduler)
    ctl.select_mode(Mode.CAMERA)
    scheduler.run_until(idle(ctl))
    assert ctl.snapshot.mode is Mode.UNKNOWN
    assert messages[-1].title == "Camera mode not applied"
    assert not controls_for(ctl.snapshot).laser_on


# ---- power ----

def test_set_power_and_above_nominal_warning(make, scheduler):
    ctl, messages = make()
    connected(ctl, scheduler)
    ctl.set_power(52.0)
    scheduler.run_until(lambda: ctl.snapshot.setpoint_mw == 52.0)
    assert messages[-1].title == "Above nominal"
    assert ctl.manual_power_mw == 52.0


def test_power_above_max_is_not_applied(make, scheduler):
    ctl, messages = make()
    connected(ctl, scheduler)
    ctl.set_power(60.0)
    scheduler.run_until(lambda: bool(messages))
    assert messages[-1].title == "Power not applied"
    assert ctl.snapshot.connected and ctl.manual_power_mw == 5.0


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_non_finite_power_is_rejected_before_sending(make, scheduler, sims, bad):
    ctl, messages = make()
    connected(ctl, scheduler)
    sims["SIM1"].log.clear()
    assert ctl.set_power(bad) is False
    scheduler.settle()
    assert commands(sims["SIM1"].log) == []
    assert messages[-1].title == "Power not applied"


def test_mode_switch_reuses_last_applied_power(make, scheduler, sims):
    ctl, _ = make(manual_power_mw=5.0)
    connected(ctl, scheduler)
    ctl.select_mode(Mode.CAMERA)
    scheduler.run_until(idle(ctl))
    sims["SIM1"].log.clear()
    ctl.select_mode(Mode.MANUAL)
    scheduler.run_until(idle(ctl))
    assert commands(sims["SIM1"].log) == ["CW=1", "EXT=0", "P=5.0"]


def test_negative_power_is_refused_by_the_driver(make, scheduler, sims):
    ctl, messages = make()
    connected(ctl, scheduler)
    sims["SIM1"].log.clear()
    ctl.set_power(-1.0)
    scheduler.run_until(lambda: bool(messages))
    assert messages[-1].title == "Power not applied"
    assert commands(sims["SIM1"].log) == []


def test_reselecting_the_current_mode_reapplies_it(make, scheduler, sims):
    ctl, _ = make()
    ctl.select_mode(Mode.CAMERA)
    connected(ctl, scheduler)
    sims["SIM1"].log.clear()
    ctl.select_mode(Mode.CAMERA)  # e.g. repeat the calibration
    scheduler.run_until(idle(ctl))
    assert commands(sims["SIM1"].log) == ["EXT=1", "CW=0", "P=50", "CAL=50"]


def test_analog_policy_b_end_to_end(make, scheduler, sims, policy):
    sequences.ANALOG_MODE_POLICY = sequences.AnalogModePolicy.CALL_AFTER_PULSED
    ctl, messages = make()
    ctl.select_mode(Mode.CAMERA)
    connected(ctl, scheduler)
    assert commands(sims["SIM1"].log) == ["EXT=1", "CW=0", "ANA=1", "P=50", "CAL=50"]
    assert ctl.snapshot.mode is Mode.CAMERA and not messages


# ---- refusals and port errors ----

def test_interlock_refusal(make, scheduler):
    ctl, messages = make("SIM-INTERLOCK")
    ready(ctl, scheduler)
    ctl.laser_on()
    scheduler.run_until(lambda: ctl.snapshot.on_refused)
    assert ctl.snapshot.emission is Emission.OFF
    assert messages[-1].title == "Laser did not turn on"
    assert "Interlock open" in messages[-1].text


def test_busy_port(make, scheduler):
    ctl, _ = make("SIM-BUSY")
    ctl.connect()
    scheduler.run_until(lambda: ctl.snapshot.conn is ConnState.ERROR)
    assert ctl.snapshot.last_error.title == "Port busy"


def test_silent_port(make, scheduler):
    ctl, _ = make("SIM-SILENT")
    ctl.connect()
    scheduler.run_until(lambda: ctl.snapshot.conn is ConnState.ERROR)
    assert ctl.snapshot.last_error.title == "No response"


def test_select_port_clears_error(make, scheduler):
    ctl, _ = make("SIM-BUSY")
    ctl.connect()
    scheduler.run_until(lambda: ctl.snapshot.conn is ConnState.ERROR)
    ctl.select_port("SIM1")
    assert ctl.snapshot.conn is ConnState.DISCONNECTED and ctl.snapshot.last_error is None


def test_cancel_connect(make, scheduler, sims):
    ctl, _ = make()
    original = sims["SIM1"].handle
    sims["SIM1"].handle = lambda line: (time.sleep(0.3) if line == "?>" else None) or original(line)
    ctl.connect()
    assert controls_for(ctl.snapshot).connect_label == "Cancel"
    ctl.cancel_connect()
    assert ctl.snapshot.conn is ConnState.DISCONNECTED
    scheduler.settle(40)
    assert ctl.snapshot.conn is ConnState.DISCONNECTED  # the late connect result is ignored
    assert ctl._worker._laser is None  # and its port was released


# ---- disconnect, lost link, off not confirmed ----

def test_disconnect_turns_laser_off(make, scheduler, sims):
    ctl, messages = make()
    emitting(ctl, scheduler)
    ctl.disconnect()
    scheduler.run_until(lambda: ctl.snapshot.conn is ConnState.DISCONNECTED)
    assert sims["SIM1"].emission is False
    assert ctl.snapshot.emission is Emission.OFF and not ctl.snapshot.emission_warning


def test_lost_link_while_emitting_warns_that_laser_may_be_on(make, scheduler, sims):
    ctl, messages = make()
    emitting(ctl, scheduler)
    sims["SIM1"].responsive = False
    ctl.refresh_status()
    scheduler.run_until(lambda: ctl.snapshot.conn is ConnState.ERROR)
    assert sims["SIM1"].emission is True  # the off could not reach it
    assert ctl.snapshot.emission is Emission.UNKNOWN and ctl.snapshot.emission_warning
    assert messages[-1].level == "error"


def test_off_to_silent_laser_is_not_reported_as_off(make, scheduler, sims):
    ctl, messages = make()
    emitting(ctl, scheduler)
    sims["SIM1"].responsive = False
    ctl.laser_off()
    scheduler.run_until(lambda: ctl.snapshot.conn is ConnState.ERROR)
    assert sims["SIM1"].emission is True
    assert ctl.snapshot.emission_warning
    assert any(m.title == "Off not confirmed" for m in messages)


def test_disconnect_from_silent_laser_keeps_warning(make, scheduler, sims):
    ctl, messages = make()
    emitting(ctl, scheduler)
    sims["SIM1"].responsive = False
    ctl.disconnect()
    scheduler.run_until(lambda: ctl.snapshot.conn is ConnState.DISCONNECTED)
    assert ctl.snapshot.emission_warning
    assert messages[-1].title == "Laser may still be on"


def test_lost_link_while_off_does_not_warn(make, scheduler, sims):
    ctl, _ = make()
    ready(ctl, scheduler)
    sims["SIM1"].responsive = False
    ctl.refresh_status()
    scheduler.run_until(lambda: ctl.snapshot.conn is ConnState.ERROR)
    assert ctl.snapshot.emission is Emission.OFF and not ctl.snapshot.emission_warning


# ---- shutdown ----

def test_shutdown_turns_off_and_calls_back(make, scheduler, sims):
    ctl, _ = make()
    emitting(ctl, scheduler)
    done = []
    ctl.shutdown(on_done=lambda: done.append(True))
    scheduler.run_until(lambda: bool(done))
    assert sims["SIM1"].emission is False


def test_shutdown_with_silent_laser_asks_instead_of_closing(make, scheduler, sims):
    ctl, _ = make()
    emitting(ctl, scheduler)
    sims["SIM1"].responsive = False
    done, unsafe = [], []
    ctl.shutdown(on_done=lambda: done.append(True), on_unsafe=unsafe.append)
    scheduler.run_until(lambda: bool(unsafe))
    assert unsafe == [False] and not done
    ctl.cancel_shutdown()  # the user chose to stay
    assert ctl.snapshot.conn is ConnState.DISCONNECTED and ctl.snapshot.emission_warning


def test_shutdown_timeout_then_keep_waiting(make, scheduler, sims):
    ctl, _ = make()
    emitting(ctl, scheduler)
    original = sims["SIM1"].handle
    sims["SIM1"].handle = lambda line: (time.sleep(0.6) if line == "L=0" else None) or original(line)
    done, unsafe = [], []
    ctl.shutdown(on_done=lambda: done.append(True), on_unsafe=unsafe.append, timeout_s=0.1)
    scheduler.run_until(lambda: bool(unsafe))
    assert unsafe == [True]
    ctl.shutdown(on_done=lambda: done.append(True), on_unsafe=unsafe.append, timeout_s=5)  # "No": keep waiting
    scheduler.run_until(lambda: bool(done))
    assert sims["SIM1"].emission is False


def test_shutdown_while_connecting_closes_at_once(make, scheduler, sims):
    ctl, _ = make()
    original = sims["SIM1"].handle
    sims["SIM1"].handle = lambda line: (time.sleep(0.3) if line == "?>" else None) or original(line)
    ctl.connect()
    done, unsafe = [], []
    ctl.shutdown(on_done=lambda: done.append(True), on_unsafe=unsafe.append)
    scheduler.run_until(lambda: bool(done), timeout_s=1)
    assert not unsafe


def test_closing_twice_does_not_queue_a_second_shutdown(make, scheduler, sims):
    ctl, _ = make()
    emitting(ctl, scheduler)
    done = []
    ctl.shutdown(on_done=lambda: done.append(1))
    ctl.shutdown(on_done=lambda: done.append(2))  # user clicks the close button again
    scheduler.run_until(lambda: bool(done))
    scheduler.settle()
    assert done == [2]  # one shutdown, latest callback
    assert sims["SIM1"].emission is False


# ---- resilience ----

def test_pump_survives_a_failing_ui_callback(make, scheduler, sims):
    ctl, _ = make()
    calls = []

    def bad(_snap):
        calls.append(1)
        raise RuntimeError("UI bug")

    ctl.subscribe(lambda s: None)
    ctl._state_cbs.append(bad)
    connected(ctl, scheduler)  # would hang if the pump had died
    assert calls and ctl.snapshot.connected


@pytest.mark.parametrize("snap, expected", [
    (Snapshot(), dict(port_select=True, connect=True, connect_label="Connect", mode_select=True,
                      power_edit=False, laser_on=False, laser_off=False)),
    (Snapshot(conn=ConnState.CONNECTING), dict(port_select=False, connect=True, connect_label="Cancel",
                                               mode_select=False)),
    (Snapshot(conn=ConnState.CONNECTED), dict(connect_label="Disconnect", power_edit=True, laser_on=True,
                                              laser_off=True)),
    (Snapshot(conn=ConnState.CONNECTED, emission=Emission.UNKNOWN), dict(laser_on=False, laser_off=True)),
    (Snapshot(conn=ConnState.CONNECTED, mode=Mode.CAMERA), dict(power_edit=False, laser_on=True)),
    (Snapshot(conn=ConnState.CONNECTED, busy=True, emission=Emission.ON), dict(laser_on=False, laser_off=True)),
    (Snapshot(conn=ConnState.CONNECTED, applying=Mode.CAMERA), dict(mode_select=False, laser_on=False)),
    (Snapshot(conn=ConnState.ERROR), dict(connect_label="Retry", port_select=True, laser_off=False)),
])
def test_controls_for(snap, expected):
    controls = controls_for(snap)
    for name, value in expected.items():
        assert getattr(controls, name) == value, name


def test_confirmed_off_helper(sims):
    laser = sequences.open_laser("SIM1", 0.1)
    assert sequences.laser_off_confirmed(laser) is True
    sims["SIM1"].responsive = False
    assert sequences.laser_off_confirmed(laser) is False
