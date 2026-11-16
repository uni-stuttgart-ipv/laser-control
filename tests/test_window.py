"""The window's wiring: what it asks the controller to do. (What results do to the screen: test_state.py;
the Log tab: test_log_tab.py.)"""
import pytest

from conftest import answer, connected, run_for
from laser_control.controller import MAX_POWER_MW
from laser_control.ui.paint import PAD_X
from laser_control.ui.power import SEND_DELAY_MS, dial_value
from laser_control.ui.sections import port_row


def type_power(win, text):
    win.power_input.open_editor()
    win.power_input.editor.delete(0, "end")
    win.power_input.editor.insert(0, text)
    win.power_input.commit_editor()


# ---- connecting ----

def test_connect_sends_the_port_mode_and_power(win):
    win.connect_clicked()
    assert win.ctl.calls == [("connect", "COM3", "manual", 5.0)]
    assert win.state.connecting


def test_disconnect_when_connected(win):
    connected(win)
    win.connect_clicked()
    assert win.ctl.calls == [("disconnect",)]


def test_results_reach_the_state(win):
    connected(win)
    assert win.state.connected and win.state.setpoint == 5.0


# ---- power ----

def test_quick_plus_clicks_send_the_power_once(win, root):
    connected(win)
    for _ in range(5):
        win.power_input.nudge(0.1)
    assert win.ctl.calls == []                     # nothing yet: waiting for the pause
    run_for(root, SEND_DELAY_MS + 200)
    assert win.ctl.calls == [("set_power", 5.5)]


def test_dial_drag_sends_after_release(win, root):
    connected(win)
    win.power_input.set_value(20)                  # what a drag does on every mouse move
    win.power_input.release_dial()
    run_for(root, SEND_DELAY_MS + 200)
    assert win.ctl.calls == [("set_power", 20)]


def test_power_is_not_sent_before_connecting(win, root):
    win.power_input.nudge(1)
    run_for(root, SEND_DELAY_MS + 200)
    assert win.ctl.calls == []


def test_power_is_not_sent_in_camera_mode(win, root):
    connected(win, "camera")
    win.power_input.nudge(1)
    run_for(root, SEND_DELAY_MS + 200)
    assert win.ctl.calls == []


def test_dial_stays_within_the_laser_minimum_and_the_maximum(win):
    connected(win)
    win.power_input.set_value(80)
    assert win.state.power == MAX_POWER_MW
    win.power_input.set_value(0)
    assert win.state.power == 0.5


def test_typed_power_is_sent_on_enter(win):
    connected(win)
    type_power(win, "12,5")                        # a comma works too
    assert win.ctl.calls == [("set_power", 12.5)]


def test_typed_text_that_is_not_a_number_is_not_sent(win):
    connected(win)
    type_power(win, "abc")
    assert win.ctl.calls == []
    assert win.state.message[0] == "warning"


def test_the_text_field_closes_when_the_connection_drops(win):
    connected(win)
    win.power_input.open_editor()
    answer(win, ("error", "device disconnected"))
    assert win.power_input.editor is None


def test_dial_positions():
    assert dial_value(-1, 1, 50) == 0              # bottom left: the start of the arc
    assert dial_value(0, -1, 50) == pytest.approx(25)   # top: half way
    assert dial_value(1, 1, 50) == 50              # bottom right: the end of the arc
    assert dial_value(0, 1, 50) in (0, 50)         # the gap at the bottom snaps to an end


# ---- laser and mode ----

def test_the_key_turns_on_then_off(win):
    connected(win)
    win.laser_clicked()
    answer(win, ("laser", True))
    win.laser_clicked()
    assert win.ctl.calls == [("turn_on",), ("turn_off",)]


def test_mode_buttons_work_while_the_laser_is_on(win):
    connected(win)
    answer(win, ("laser", True))
    assert win.buttons.registered["btn:mode-camera"].enabled
    win.mode_clicked("camera")
    assert win.ctl.calls == [("use_mode", "camera", 5.0)]


def test_choosing_a_mode_before_connecting_only_remembers_it(win):
    win.mode_clicked("camera")
    assert win.state.mode == "camera"
    assert win.ctl.calls == []
    win.connect_clicked()
    assert win.ctl.calls == [("connect", "COM3", "camera", 5.0)]


def test_choosing_a_mode_while_connected_applies_it(win):
    connected(win)
    win.mode_clicked("camera")
    assert win.ctl.calls == [("use_mode", "camera", 5.0)]


def test_reset_is_drawn_only_in_camera_mode(win):
    connected(win)
    assert "btn:reset" not in win.buttons.registered
    answer(win, ("mode", "camera"))
    assert win.buttons.registered["btn:reset"].enabled


def test_reset_shows_greyed_out_in_camera_mode_before_connecting(win):
    win.mode_clicked("camera")
    assert not win.buttons.registered["btn:reset"].enabled


def test_reset_is_the_same_size_as_the_on_off_key(win):
    win.mode_clicked("camera")
    reset, key = win.canvas.bbox("btn:reset.fg"), win.canvas.bbox("btn:key.fg")
    assert win.canvas.bbox("btn:reset")[3] - win.canvas.bbox("btn:reset")[1] == \
        win.canvas.bbox("btn:key")[3] - win.canvas.bbox("btn:key")[1]
    assert (reset[1] + reset[3]) // 2 == (key[1] + key[3]) // 2   # centred on the same line


def test_reset_runs_the_camera_mode_again_once(win, root):
    connected(win, "camera")
    root.deiconify()
    root.update()
    click(win, root, "btn:reset")
    click(win, root, "btn:reset")                    # a second click while it runs does nothing
    assert win.ctl.calls == [("use_mode", "camera", 5.0)]
    assert not win.buttons.registered["btn:reset"].enabled
    answer(win, ("laser", True), ("mode", "camera"), ("power", 50))
    assert win.buttons.registered["btn:reset"].enabled


def press_escape(root, widget):
    """Press Esc in `widget`. Keys only reach a widget with focus, so the window is shown for a moment."""
    root.deiconify()
    widget.focus_force()
    root.update()
    widget.event_generate("<KeyPress-Escape>")
    root.update()


def test_escape_does_not_turn_the_laser_off(win, root):
    connected(win)
    answer(win, ("laser", True))
    press_escape(root, win.canvas)
    assert win.ctl.calls == []
    assert root.bind_all("<Escape>") == ""          # no window-wide Esc shortcut at all


def test_escape_still_cancels_typing_in_the_power_field(win, root):
    connected(win)
    win.power_input.open_editor()
    press_escape(root, win.power_input.editor)
    assert win.power_input.editor is None
    assert win.ctl.calls == []


# ---- clicking while typing a power: the click cancels the typing, then does its job ----

def start_typing(win, root, text):
    """Open the power field and type `text` without pressing Enter; the window is shown so clicks arrive."""
    connected(win)
    root.deiconify()
    win.power_input.open_editor()
    win.power_input.editor.delete(0, "end")
    win.power_input.editor.insert(0, text)
    root.update()


def click(win, root, tag):
    """A real mouse click (press + release) in the middle of the canvas item(s) tagged `tag`."""
    x1, y1, x2, y2 = win.canvas.bbox(tag)
    x, y = (x1 + x2) // 2, (y1 + y2) // 2
    win.canvas.event_generate("<ButtonPress-1>", x=x, y=y)
    win.canvas.event_generate("<ButtonRelease-1>", x=x, y=y)
    root.update()


def test_plus_while_typing_cancels_the_typing_and_steps_the_power(win, root):
    start_typing(win, root, "2")
    click(win, root, "btn:inc")
    assert win.power_input.editor is None
    assert win.state.power == 5.1                  # stepped from the dial's value; "2" was dropped
    run_for(root, SEND_DELAY_MS + 200)
    assert win.ctl.calls == [("set_power", 5.1)]


def test_the_key_while_typing_cancels_the_typing_before_turning_on(win, root):
    start_typing(win, root, "2")
    click(win, root, "btn:key")
    assert win.power_input.editor is None
    assert win.state.power == 5.0                  # the dial shows what the laser really has
    run_for(root, SEND_DELAY_MS + 200)
    assert win.ctl.calls == [("turn_on",)]         # "2" is never sent


def test_the_wheel_over_the_dial_while_typing_cancels_and_turns_it(win, root):
    start_typing(win, root, "2")
    x1, y1, x2, y2 = win.canvas.bbox("dial")
    win.buttons._on_wheel((x1 + x2) // 2, (y1 + y2) // 2, 120)
    assert win.power_input.editor is None
    assert win.state.power == 5.1


# ---- ports ----

def test_refresh_picks_the_first_port_when_the_chosen_one_is_gone(win):
    win.state.port = "COM9"
    win.refresh_ports()
    assert win.state.port == "COM3"


LONG_PORT = "/dev/cu.Bluetooth-Incoming-Port"


def drawn_port_name(win):
    """The port name text item as drawn on the canvas, and where it ends (logical px)."""
    for item in win.canvas.find_all():
        if win.canvas.type(item) == "text" and win.canvas.itemcget(item, "font") == str(win.fonts.port):
            x1 = win.canvas.bbox(item)[2]
            return win.canvas.itemcget(item, "text"), x1 / win.scale


def test_a_short_port_name_is_drawn_in_full(win):
    assert port_row.fit_port_name(win, "COM3", port_row.NAME_ROOM) == "COM3"


def test_a_long_port_name_keeps_its_end_and_fits_before_the_refresh_button(win):
    win.state.port = LONG_PORT
    win.render()
    name, right_edge = drawn_port_name(win)
    assert name.startswith("…") and LONG_PORT.endswith(name[1:])
    refresh_left = PAD_X + port_row.FIELD_W - port_row.INSET - port_row.REFRESH
    assert right_edge + port_row.CHEVRON_W <= refresh_left
    assert win.state.port == LONG_PORT          # only the drawing is shortened


def test_a_long_port_name_fits_the_field_while_connected(win):
    win.state.port = LONG_PORT
    connected(win)
    name, right_edge = drawn_port_name(win)
    assert LONG_PORT.endswith(name.lstrip("…"))
    assert right_edge <= PAD_X + port_row.FIELD_W
