"""Golden tests: lock the exact commands each sequence sends to the laser.

These run the real driver against the simulator. If one fails, the laser
would receive something different from the reference script.
"""

from __future__ import annotations

import pytest

from laser_control import driver as ld
from laser_control import sequences
from laser_control.model import Limits, Mode
from laser_control.sequences import AnalogModePolicy

from conftest import commands


def connect(sims, port="SIM1"):
    laser = sequences.open_laser(port, timeout_s=0.1)
    sim = sims[port]
    sim.log.clear()
    return laser, sim


def test_connect_reads_limits(sims):
    laser = sequences.open_laser("SIM1", timeout_s=0.1)
    assert sims["SIM1"].log == ["?>", "?MAXLP", "?MINLP", "?NOMP"]
    assert sequences.read_limits(laser) == Limits(min_mw=0.5, nom_mw=50.0, max_mw=55.0)


def test_camera_mode_as_written(sims, policy):
    sequences.ANALOG_MODE_POLICY = AnalogModePolicy.AS_WRITTEN
    laser, sim = connect(sims)
    sequences.apply_camera_mode(laser)
    assert commands(sim.log) == ["EXT=1", "CW=0", "P=50", "CAL=50"]
    # The script's assignment replaced the method on this object and sent nothing.
    assert laser.analog_control_mode is ld.AnalogControlMode.Current


def test_camera_mode_call_after_pulsed(sims, policy):
    sequences.ANALOG_MODE_POLICY = AnalogModePolicy.CALL_AFTER_PULSED
    laser, sim = connect(sims)
    sequences.apply_camera_mode(laser)
    assert commands(sim.log) == ["EXT=1", "CW=0", "ANA=1", "P=50", "CAL=50"]
    assert sim.ana == 1


def test_analog_current_mode_is_refused_in_cw(sims):
    laser, _ = connect(sims)
    laser.operation_mode = ld.OperationMode.CW
    with pytest.raises(RuntimeError):
        laser.analog_control_mode(ld.AnalogControlMode.Current)


def test_manual_mode(sims):
    laser, sim = connect(sims)
    sequences.apply_manual_mode(laser, 5.0)
    assert commands(sim.log) == ["CW=1", "EXT=0", "P=5.0"]


def test_apply_mode_dispatch(sims):
    laser, sim = connect(sims)
    sequences.apply_mode(laser, Mode.MANUAL, 12.5)
    assert commands(sim.log) == ["CW=1", "EXT=0", "P=12.5"]
    with pytest.raises(ValueError):
        sequences.apply_mode(laser, Mode.UNKNOWN, 1.0)


def test_on_off_close(sims):
    laser, sim = connect(sims)
    sequences.laser_on(laser)
    assert sim.emission
    sequences.laser_off(laser)
    sequences.close_laser(laser)
    assert commands(sim.log) == ["L=1", "L=0"]


def test_camera_mode_stops_when_50_mw_is_above_max(sims):
    laser, sim = connect(sims, "SIM-SMALL")
    with pytest.raises(RuntimeError):
        sequences.apply_camera_mode(laser)
    assert commands(sim.log) == ["EXT=1", "CW=0"]  # power validation failed before P=50 was sent


def test_read_status(sims):
    laser, _ = connect(sims)
    sequences.apply_manual_mode(laser, 7.5)
    setpoint, current = sequences.read_status(laser)
    assert setpoint == 7.5 and current == 0.0
