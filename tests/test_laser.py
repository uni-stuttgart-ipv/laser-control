"""The serial driver (``hardware.laser``) and procedures against the simulated device."""

import pytest

from laser_app.hardware import operations as ops
from laser_app.hardware.laser import CommError, Laser, LaserError, LaserRefused, Limits
from laser_app.hardware.simulator import SimulatedDevice, SimulatedPort


def connect(**device_options):
    device = SimulatedDevice(**device_options)
    port = SimulatedPort(device)
    return Laser(port, name="SIM"), device, port


def test_handshake_reads_limits():
    laser, device, _ = connect()
    assert laser.limits == Limits(0.5, 40.0, 50.0)
    assert device.received[:4] == ["?>", "?MINLP", "?NOMP", "?MAXLP"]


def test_handshake_skips_banner_and_restores_prompt():
    laser, device, port = connect(prompt=True, banner=("Laser", "v3.0", ""))
    assert ">=0" in device.received and not device.prompt     # prompt off while connected
    laser.close()
    assert device.received[-1] == ">=1" and device.prompt     # restored on close
    assert not port.is_open


def test_wrong_device_is_rejected():
    class Echo(SimulatedDevice):
        def handle(self, line):
            self.received.append(line)
            return ["garbage"]
    port = SimulatedPort(Echo())
    with pytest.raises(CommError, match="does not answer like the laser"):
        Laser(port)
    assert not port.is_open


def test_silent_laser_raises_comm_error():
    laser, device, _ = connect()
    device.mute = True
    with pytest.raises(CommError, match="timeout"):
        laser.is_emitting()


def test_bare_and_prefixed_replies():
    laser, device, _ = connect()
    assert laser.read_setpoint() == 5.0                       # "SP=5.000"
    assert laser._value("SP", "7.5") == "7.5"                 # some firmware omits "KEY="


def test_garbled_number_is_comm_error():
    laser, device, _ = connect()
    device.state["SP"] = "abc"                                # type: ignore[assignment]
    with pytest.raises((CommError, ValueError)):
        laser.read_setpoint()


def test_turn_on_refusal_carries_reason():
    laser, device, _ = connect(interlock_closed=False)
    with pytest.raises(LaserRefused, match="Interlock open"):
        laser.turn_on()
    assert not laser.is_emitting()                            # reason line consumed: in step


def test_current_modulation_needs_pulsed_mode():
    laser, device, _ = connect()
    with pytest.raises(LaserError):
        laser.set_current_modulation(True)                    # still in CW mode
    laser.set_continuous(False)
    laser.set_current_modulation(True)
    assert device.state["ANA"] == 1


def test_check_power():
    lim = Limits(0.5, 40.0, 50.0)
    assert ops.check_power(lim, 10) == []
    assert ops.check_power(lim, 45) == ["Power is above nominal (40 mW)."]
    assert ops.check_power(lim, 0.2) == ["Power is below the laser's minimum (0.5 mW)."]
    for bad in (-1, 50.1):
        with pytest.raises(ops.PowerRejected):
            ops.check_power(lim, bad)


def test_verified_off_retries_then_fails():
    laser, device, _ = connect()
    laser.turn_on()
    ops.turn_off(laser)
    assert not device.emitting
    device.mute = True
    with pytest.raises(CommError, match="confirm"):
        ops.turn_off(laser)
    assert device.received.count("L=0") >= 1 + ops.OFF_ATTEMPTS


def test_camera_sequence_order():
    laser, device, _ = connect()
    notes = ops.configure_camera(laser, 50)
    sent = [c for c in device.received if c.split("=")[0] in ("EXT", "CW", "ANA", "P", "CAL")]
    assert sent == ["EXT=1", "CW=0", "ANA=1", "P=50", "CAL=50"]
    assert notes == ["Power is above nominal (40 mW)."]


def test_stale_reply_is_discarded_before_each_request():
    laser, device, port = connect()
    port._pending.append(b"L=0\r\n")                          # a late reply to an old request
    laser.turn_on()                                           # must not read the stale "L=0"
    assert device.emitting and laser.is_emitting()
    port._pending.append(b"L=0\r\n")
    assert laser.is_emitting()                                # not fooled into "off"


def test_prompt_handshake_consumes_extra_line():
    laser, device, _ = connect(prompt=True)
    assert laser.read_setpoint() == 5.0                       # replies in step after the extra line


def test_failed_handshake_restores_prompt():
    device = SimulatedDevice(prompt=True, min_mw=10, nominal_mw=5)   # implausible limits
    port = SimulatedPort(device)
    with pytest.raises(CommError, match="Implausible"):
        Laser(port)
    assert device.prompt and not port.is_open
