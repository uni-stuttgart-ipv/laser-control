"""Controller behaviour against the simulated laser (real driver, in-memory serial port)."""

import threading

import pytest
from helpers import SimFactory, wait_for

from laser_app.controller import (
    _USER,
    CAMERA_POWER_MW,
    OFF_UNCONFIRMED,
    POWER_REJECTED,
    LaserController,
    MessageEvent,
    Mode,
    StatusEvent,
    validate_power,
)
from laser_app.hardware.operations import Limits

# A laser whose maximum is below CAMERA_POWER_MW, so Camera mode is unavailable.
LOW_POWER_LASER = {"max_mw": 40.0, "nominal_mw": 30.0}


@pytest.fixture
def rig(request):
    """A started controller on simulated lasers; yields ``(ctl, sim)`` (see ``SimFactory``).

    ``SimulatedDevice`` keyword arguments can be passed with
    ``@pytest.mark.parametrize("rig", [{...}], indirect=True)``.
    """
    sim = SimFactory(**getattr(request, "param", {}))
    ctl = LaserController(factory=sim, poll_interval_s=0.05)
    ctl.start()
    yield ctl, sim
    ctl.shutdown()


def drain(ctl):
    """Remove and return every queued event."""
    out = []
    while not ctl.events.empty():
        out.append(ctl.events.get())
    return out


def messages(ctl):
    """Remove every queued event and return the MessageEvents among them."""
    return [e for e in drain(ctl) if isinstance(e, MessageEvent)]


def connect(ctl, mode=Mode.MANUAL, manual=5.0):
    """Connect to the simulated port and wait until the connect has finished."""
    ctl.connect("SIM", mode, manual)
    wait_for(lambda: ctl.status.connected and not ctl.status.busy)


def wait_idle(ctl):
    """Wait until every job submitted so far has been run or skipped."""
    done = threading.Event()
    ctl._submit(_USER, done.set)
    wait_for(done.is_set)


def test_validate_power():
    lim = Limits(0.5, 40, 50)
    assert validate_power(10, lim) is None
    assert validate_power(50, lim) is None
    assert validate_power(50.1, lim)
    assert validate_power(0.4, lim)
    assert validate_power(float("nan"), lim)
    assert validate_power(10, None)


def test_connect_starts_off_in_manual(rig):
    ctl, sim = rig
    connect(ctl)
    dev = sim.devices[0]
    assert [c for c in dev.received if c.startswith("L=")][0] == "L=0"   # first: beam off
    assert ctl.status.limits == Limits(0.5, 40.0, 50.0)
    assert dev.state["CW"] == 1 and dev.state["EXT"] == 0
    assert ctl.status.setpoint_mw == 5.0


def test_camera_mode_sends_reference_sequence_at_50mw(rig):
    ctl, sim = rig
    connect(ctl, mode=Mode.CAMERA)
    dev = sim.devices[0]
    seq = [c for c in dev.received if c.split("=")[0] in ("EXT", "CW", "ANA", "P", "CAL")]
    assert CAMERA_POWER_MW == 50.0
    assert seq == ["EXT=1", "CW=0", "ANA=1", "P=50.0", "CAL=50.0"]
    assert ctl.status.mode is Mode.CAMERA
    assert dev.state["ANA"] == 1 and dev.state["CAL"] == 50.0


def test_apply_power_refused_in_camera_mode(rig):
    ctl, sim = rig
    connect(ctl, mode=Mode.CAMERA)
    messages(ctl)
    ctl.apply_power(10)
    wait_for(lambda: any(m.level == "error" for m in messages(ctl)))
    assert sim.devices[0].setpoint == 50.0


def test_on_off_and_power(rig):
    ctl, sim = rig
    connect(ctl)
    ctl.apply_power(12)
    ctl.turn_on()
    wait_for(lambda: ctl.status.emitting)
    assert sim.devices[0].setpoint == 12
    ctl.turn_off()
    wait_for(lambda: not ctl.status.emitting)


def test_power_above_max_is_rejected_without_io_and_keeps_link(rig):
    ctl, sim = rig
    connect(ctl)
    messages(ctl)
    ctl.apply_power(70)                       # above the laser's maximum: refused before sending
    errors = []
    wait_for(lambda: errors.extend(m for m in messages(ctl) if m.level == "error") or errors)
    assert errors[0].code == POWER_REJECTED
    assert not any(c.startswith("P=70") for c in sim.devices[0].received)
    assert ctl.status.connected


def test_mode_switch_turns_laser_off_and_restores_manual_power(rig):
    ctl, sim = rig
    connect(ctl, manual=8.0)
    ctl.apply_power(12)
    ctl.turn_on()
    wait_for(lambda: ctl.status.emitting)
    ctl.set_mode(Mode.CAMERA)
    wait_for(lambda: ctl.status.mode is Mode.CAMERA and not ctl.status.busy)
    assert not sim.devices[0].emitting
    ctl.set_mode(Mode.MANUAL)
    wait_for(lambda: ctl.status.mode is Mode.MANUAL and not ctl.status.busy)
    assert sim.devices[0].setpoint == 12          # last applied manual power, not 50
    assert sim.devices[0].state["CW"] == 1


def test_manual_restore_falls_back_to_minimum_when_power_rejected(rig):
    ctl, sim = rig
    connect(ctl, mode=Mode.CAMERA, manual=70.0)   # 70 mW is above this laser's max
    assert sim.devices[0].setpoint == 50.0
    messages(ctl)
    ctl.set_mode(Mode.MANUAL)
    wait_for(lambda: ctl.status.mode is Mode.MANUAL and not ctl.status.busy)
    assert sim.devices[0].setpoint == 0.5               # the laser minimum, not the camera power
    assert ctl.status.setpoint_mw == 0.5 and ctl.status.connected
    assert "P=70.0" not in sim.devices[0].received
    msgs = messages(ctl)
    assert any(m.level == "warning" and "0.5 mW instead" in m.text for m in msgs)


def test_turn_off_cancels_queued_turn_on(rig):
    ctl, sim = rig
    connect(ctl)
    gate = threading.Event()
    ctl._submit(_USER, lambda: gate.wait(5))      # keep the worker busy
    ctl.turn_on()
    ctl.turn_off()
    gate.set()
    wait_idle(ctl)
    assert not sim.devices[0].emitting
    assert "L=1" not in sim.devices[0].received


def test_interlock_refusal_reported(rig):
    ctl, sim = rig
    connect(ctl)
    sim.devices[0].interlock_closed = False
    messages(ctl)
    ctl.turn_on()
    wait_for(lambda: any("Interlock" in m.text and m.level == "error" for m in messages(ctl)))
    assert ctl.status.connected and not ctl.status.emitting


def test_comm_error_drops_connection_and_turns_off(rig):
    ctl, sim = rig
    connect(ctl)
    ctl.turn_on()
    wait_for(lambda: ctl.status.emitting)
    sim.ports[0].fail_next = OSError("cable unplugged")
    wait_for(lambda: not ctl.status.connected)
    assert not sim.ports[0].is_open


def test_disconnect_and_shutdown_turn_off(rig):
    ctl, sim = rig
    connect(ctl)
    ctl.turn_on()
    wait_for(lambda: ctl.status.emitting)
    ctl.disconnect()
    wait_for(lambda: not ctl.status.connected)
    assert not sim.devices[0].emitting and not sim.ports[0].is_open
    connect(ctl)
    ctl.turn_on()
    wait_for(lambda: ctl.status.emitting)
    ctl.shutdown()
    assert not sim.devices[1].emitting and not sim.ports[1].is_open


def test_unanswered_laser_drops_connection_and_warns_off_unconfirmed(rig):
    ctl, sim = rig
    connect(ctl)
    ctl.turn_on()
    wait_for(lambda: ctl.status.emitting)
    messages(ctl)
    sim.devices[0].mute = True                # laser stops answering (reads time out)
    wait_for(lambda: not ctl.status.connected)
    msgs = messages(ctl)
    assert any(m.text == OFF_UNCONFIRMED and m.level == "error" for m in msgs)


def test_garbled_on_reply_turns_off_and_disconnects(rig):
    ctl, sim = rig
    connect(ctl)
    sim.devices[0].mute = True
    ctl.turn_on()
    wait_for(lambda: not ctl.status.connected)
    assert sim.devices[0].received.count("L=0") >= 2     # off attempted after the failed ON


@pytest.mark.parametrize("rig", [LOW_POWER_LASER], indirect=True)
def test_camera_mode_refused_on_laser_below_50mw(rig):
    ctl, sim = rig
    connect(ctl)
    ctl.apply_power(12)
    ctl.turn_on()
    wait_for(lambda: ctl.status.emitting)
    messages(ctl)
    ctl.set_mode(Mode.CAMERA)
    wait_for(lambda: any(m.level == "error" for m in messages(ctl)))
    assert ctl.status.emitting and ctl.status.mode is Mode.MANUAL   # untouched
    assert "EXT=1" not in sim.devices[0].received


@pytest.mark.parametrize("rig", [LOW_POWER_LASER], indirect=True)
def test_rejected_set_mode_reports_busy_then_idle(rig):
    ctl, _ = rig
    connect(ctl)
    drain(ctl)
    ctl.set_mode(Mode.CAMERA)
    events = []
    wait_for(lambda: events.extend(drain(ctl)) or any(
        isinstance(e, MessageEvent) and e.level == "error" for e in events))
    wait_idle(ctl)
    events.extend(drain(ctl))
    busy = [e.status.busy for e in events if isinstance(e, StatusEvent)]
    # Polling may add busy=False snapshots around it, but the attempt itself
    # publishes exactly one busy=True, immediately followed by busy=False.
    assert busy.count(True) == 1
    assert busy[busy.index(True) + 1] is False
    assert not ctl.status.busy and ctl.status.mode is Mode.MANUAL


def test_manual_power_has_no_app_limit(rig):
    ctl, sim = rig
    connect(ctl)
    ctl.apply_power(0.2)                      # below the laser's minimum: still sent
    wait_for(lambda: ctl.status.setpoint_mw == 0.2)
    assert "P=0.2" in sim.devices[0].received


def test_refused_turn_on_is_followed_by_verified_off(rig):
    ctl, sim = rig
    connect(ctl)
    sim.devices[0].interlock_closed = False
    n = len(sim.devices[0].received)
    ctl.turn_on()
    wait_for(lambda: "?L" in sim.devices[0].received[n + 1:])
    wait_idle(ctl)
    sent = sim.devices[0].received[n:]
    assert sent[0] == "L=1" and "L=0" in sent                # off sent and read back
    assert not ctl.status.emitting and ctl.status.connected
