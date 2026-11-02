"""Window behaviour with a real Tk root and synthetic mouse/keyboard events.

Skipped where Tk cannot open a display (e.g. a headless Linux box).
"""

from __future__ import annotations

import math
import time

import pytest

from laser_control.controller import LaserController
from laser_control.model import ConnState, Emission, Mode
from laser_control.ui.window import DIAL_A0, DIAL_SWEEP, MainWindow, dial_value

tk = pytest.importorskip("tkinter")


@pytest.fixture
def app(sims):
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"no display: {exc}")
    root.geometry("+40+40")
    ctl = LaserController(root, port="SIM1", manual_power_mw=5.0, timeout_s=0.1)
    win = MainWindow(root, ctl)
    end = time.monotonic() + 0.4  # synthetic events are dropped until the window is mapped
    while time.monotonic() < end:
        root.update()
        time.sleep(0.01)
    yield root, ctl, win
    ctl._worker.stop()
    ctl._worker.join(timeout=3)  # don't let a slow job leak into the next test's simulator
    root.destroy()


def pump(root, until=lambda: True, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        root.update()
        if until():
            return
        time.sleep(0.01)
    raise AssertionError("condition not reached")


def center(win, tag):
    x1, y1, x2, y2 = win.canvas.bbox(tag)
    return (x1 + x2) // 2, (y1 + y2) // 2


def click(root, win, tag, between=None):
    c = win.canvas
    x, y = center(win, tag)
    c.event_generate("<Motion>", x=x, y=y)
    c.event_generate("<ButtonPress-1>", x=x, y=y)
    if between:
        between()
    c.event_generate("<ButtonRelease-1>", x=x, y=y)
    root.update()


def connect_and_confirm_off(root, ctl, win):
    click(root, win, "btn:connect")
    pump(root, lambda: ctl.snapshot.connected and not ctl.snapshot.busy and ctl.snapshot.applying is None)
    assert ctl.snapshot.emission is Emission.UNKNOWN
    click(root, win, "btn:key")  # in the unknown state the key sends off
    pump(root, lambda: ctl.snapshot.emission is Emission.OFF)


def test_dial_value_mapping():
    assert dial_value(math.cos(math.radians(DIAL_A0)), math.sin(math.radians(DIAL_A0)), 55) == 0
    assert dial_value(0, -1, 55) == pytest.approx(27.5)  # straight up is half way
    end = math.radians(DIAL_A0 + DIAL_SWEEP)
    assert dial_value(math.cos(end), math.sin(end), 55) == pytest.approx(55)
    assert dial_value(-0.1, 1, 55) == 0  # bottom gap, left of centre: snaps to the start
    assert dial_value(0.1, 1, 55) == 55  # bottom gap, right of centre: snaps to the end


def test_key_sends_off_when_unknown_then_on(app):
    root, ctl, win = app
    connect_and_confirm_off(root, ctl, win)
    click(root, win, "btn:key")
    pump(root, lambda: ctl.snapshot.emitting)


def test_click_survives_a_redraw_between_press_and_release(app):
    root, ctl, win = app
    connect_and_confirm_off(root, ctl, win)
    click(root, win, "btn:key")
    pump(root, lambda: ctl.snapshot.emitting)
    click(root, win, "btn:key", between=win.render)  # e.g. a status poll lands mid-click
    pump(root, lambda: ctl.snapshot.emission is Emission.OFF)


def test_dial_drag_follows_the_pointer(app):
    root, ctl, win = app
    connect_and_confirm_off(root, ctl, win)
    c = win.canvas
    cx, cy = (win.art.px(v) for v in win._dial_center)
    r = win.art.px(63)
    seen = []
    points = [DIAL_A0 + DIAL_SWEEP * f for f in (0.1, 0.3, 0.5, 0.7)]
    for i, angle in enumerate(points):
        x = cx + round(r * math.cos(math.radians(angle)))
        y = cy + round(r * math.sin(math.radians(angle)))
        c.event_generate("<Motion>" if i == 0 else "<B1-Motion>", x=x, y=y)
        if i == 0:
            c.event_generate("<ButtonPress-1>", x=x, y=y)
        root.update()
        seen.append(win.power)
    c.event_generate("<ButtonRelease-1>", x=x, y=y)
    assert seen == sorted(seen) and len(set(seen)) == len(seen), seen
    assert seen[-1] == pytest.approx(0.7 * 55, abs=0.6)
    assert not win._dragging


def test_unapplied_dial_value_is_never_sent_by_a_mode_switch(app, sims):
    root, ctl, win = app
    connect_and_confirm_off(root, ctl, win)
    win._set_power(45.0)
    assert win._dirty()
    ctl.select_mode(Mode.CAMERA)
    pump(root, lambda: ctl.snapshot.applying is None and not ctl.snapshot.busy)
    assert win.power == 5.0  # the dial snapped back to the applied value
    sims["SIM1"].log.clear()
    ctl.select_mode(Mode.MANUAL)
    pump(root, lambda: ctl.snapshot.applying is None and not ctl.snapshot.busy)
    assert "P=45.0" not in sims["SIM1"].log and "P=5.0" in sims["SIM1"].log


def test_editor_rejects_nan_and_closes_on_mode_switch(app, sims):
    root, ctl, win = app
    connect_and_confirm_off(root, ctl, win)
    win._open_editor()
    win._editor.delete(0, "end")
    win._editor.insert(0, "nan")
    win._commit_editor()
    assert win.banner and win.banner.title == "Not a number"
    assert math.isfinite(win.power)
    win._open_editor()
    win._mode_clicked(Mode.CAMERA)
    assert win._editor is None


def test_cancel_while_connecting(app, sims):
    root, ctl, win = app
    original = sims["SIM1"].handle
    sims["SIM1"].handle = lambda line: (time.sleep(0.3) if line == "?>" else None) or original(line)
    click(root, win, "btn:connect")
    assert ctl.snapshot.conn is ConnState.CONNECTING
    click(root, win, "btn:connect")  # the same button now reads "Cancel"
    assert ctl.snapshot.conn is ConnState.DISCONNECTED


def test_dial_image_cache_is_bounded(app):
    from laser_control.ui.art import DIAL_CACHE_SIZE
    root, ctl, win = app
    for tenth in range(0, 550, 3):
        win.art.dial(tenth / 10, 55.0, 50.0, True)
    assert len(win.art._dials) == DIAL_CACHE_SIZE


def test_smoke_test_entry_point(sims):
    from laser_control.app import smoke_test
    assert smoke_test() == 0


def test_pressed_buttons_stay_in_place(app):
    """Swapping a button to its pressed image must not move it.

    State images can have different shadow/glow margins (for example the
    amber Connect/Retry pill glows, its pressed image doesn't), so the item
    has to be re-placed on every swap.
    """
    root, ctl, win = app
    connect_and_confirm_off(root, ctl, win)  # draws Disconnect, the ± keys and the laser key
    win._set_power(20.0)  # makes Apply appear
    c = win.canvas

    def centre(tag):
        item = c.find_withtag(f"{tag}.bg")[0]
        x, y = c.coords(item)
        img = c.itemcget(item, "image")
        return x + root.tk.call("image", "width", img) / 2, y + root.tk.call("image", "height", img) / 2

    checked = []
    for tag, button in list(win._buttons.items()):
        if "press" not in button.bg or not c.find_withtag(f"{tag}.bg"):
            continue
        before = centre(tag)
        win._show(tag, "press")
        during = centre(tag)
        win._show(tag, "normal")
        assert during == pytest.approx(before, abs=0.5), tag
        checked.append(tag)
    assert {"btn:connect", "btn:apply", "btn:key"} <= set(checked), checked
