"""State.apply: what each controller result does to the screen. No Tk window needed."""
from laser_control.controller import MAX_POWER_MW
from laser_control.ui.state import State


def connected_state(mode="manual"):
    s = State("COM3")
    for result in (("connected", 0.5), ("mode", mode), ("power", 5.0)):
        s.apply(*result)
    return s


def test_starts_disconnected_in_manual_mode():
    s = State("COM3")
    assert not s.connected and not s.laser_on
    assert s.mode == "manual"
    assert s.setpoint is None and s.current is None and s.message is None


def test_connected_reads_the_limits():
    s = State("COM3")
    s.connecting = True
    s.apply("connected", 0.5)
    assert s.connected and not s.connecting
    assert s.min_power == 0.5


def test_connected_raises_a_dial_below_the_laser_minimum():
    s = State("COM3")
    s.power = 0.1
    s.apply("connected", 0.5)
    assert s.power == 0.5


def test_laser_on_and_off():
    s = connected_state()
    s.apply("laser", True)
    assert s.laser_on
    s.apply("laser", False)
    assert not s.laser_on


def test_a_refusal_shows_a_warning_and_stays_connected():
    s = connected_state()
    s.apply("refused", "Can not turn laser on due to interlock open.")
    assert s.connected and not s.laser_on
    assert s.message == ("warning", "Can not turn laser on due to interlock open.")


def test_turning_on_clears_an_old_refusal():
    s = connected_state()
    s.apply("refused", "Can not turn laser on due to interlock open.")
    s.apply("laser", True)
    assert s.message is None


def test_an_error_forgets_everything_from_the_laser_and_shows_the_message():
    s = connected_state()
    s.apply("laser", True)
    s.apply("current", 40.0)
    s.apply("error", "device disconnected")
    assert not s.connected and not s.laser_on
    assert s.setpoint is None and s.current is None
    assert s.message == ("error", "device disconnected")


def test_an_error_while_connecting_stops_connecting():
    s = State("COM3")
    s.connecting = True
    s.apply("error", "could not open port")
    assert not s.connecting and not s.connected


def test_disconnected_forgets_the_readouts_but_keeps_the_mode():
    s = connected_state("camera")
    s.apply("disconnected", None)
    assert not s.connected
    assert s.setpoint is None
    assert s.mode == "camera"   # used again on the next connect


def test_mode_power_and_current_are_shown_as_reported():
    s = connected_state()
    s.apply("mode", "camera")
    s.apply("power", 50)
    s.apply("current", 41.2)
    assert (s.mode, s.setpoint, s.current) == ("camera", 50, 41.2)


def test_clamp_keeps_the_dial_between_the_minimum_and_the_maximum():
    s = connected_state()
    assert s.clamp(80) == MAX_POWER_MW
    assert s.clamp(0) == 0.5
    assert s.clamp(12.34) == 12.3   # the dial's 0.1 mW step


def test_power_is_editable_only_when_connected_in_manual_mode():
    assert not State("COM3").power_editable
    assert connected_state("manual").power_editable
    assert not connected_state("camera").power_editable


def test_the_mode_switch_is_locked_while_the_laser_is_on():
    s = connected_state()
    assert s.can_switch_mode
    s.apply("laser", True)
    assert not s.can_switch_mode


def test_connect_button_needs_a_port():
    assert not State("").can_connect
    assert State("COM3").can_connect
