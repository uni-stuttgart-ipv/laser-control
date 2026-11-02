"""The simulator speaks the protocol the driver expects."""

from __future__ import annotations

import pytest
import serial

from laser_control.sim import FakeSerial, LaserSim


def test_query_and_command_replies():
    sim = LaserSim()
    assert sim.handle("?MAXLP") == ["MAXLP=55.0"]
    assert sim.handle("P=12.5") == ["P=12.5"]
    assert sim.handle("?SP") == ["SP=12.50"]
    assert sim.handle("CAL=50") == []


def test_interlock_refuses_on():
    sim = LaserSim(interlock_open=True)
    assert sim.handle("L=1") == ["L=0", "Interlock open"]
    assert not sim.emission


def test_analog_current_needs_pulsed():
    sim = LaserSim()
    assert sim.handle("ANA=1") == ["ANA=0"]
    sim.handle("CW=0")
    assert sim.handle("ANA=1") == ["ANA=1"]


def test_fake_serial_ports(sims):
    with pytest.raises(serial.SerialException, match="Access is denied"):
        FakeSerial("SIM-BUSY")
    with pytest.raises(serial.SerialException, match="could not open port"):
        FakeSerial("NOPE")
    silent = FakeSerial("SIM-SILENT", timeout=0.1)
    silent.write(b"?>\r\n")
    assert silent.read_until(b"\r\n") == b""
