"""The Log tab: the two views, the 500-line limit, scrolling, Copy, keys, and its size."""
import logging

import pytest

from conftest import connected, run_for
from laser_control.ui import log_view
from laser_control.ui.power import SEND_DELAY_MS
from laser_control.ui.sections.log_card import wrap

events = logging.getLogger("laser_control.events")   # the controller's plain-words lines
library = logging.getLogger("coherent_cube.lib")     # the library's writing / recieved lines


@pytest.fixture
def log_tab(win):
    """The window with the Log tab open."""
    logging.getLogger().setLevel(logging.INFO)
    win.tab_clicked("log")
    return win


def arrive(win, *lines):
    """Log (logger, text) lines, then let the window collect them like its 100 ms poll does."""
    for logger, text in lines:
        logger.info(text)
    win._poll()


def shown(win):
    return [entry.text for entry in win.log_view.lines]


def fill(win, n):
    """More friendly lines than fit in the card."""
    arrive(win, *[(events, f"Power set to {i}.0 mW") for i in range(n)])


# ---- the two views ----

def test_friendly_view_by_default_shows_only_plain_words(log_tab):
    arrive(log_tab, (events, "Laser on"), (library, "writing L=1"))
    assert not log_tab.log_view.technical
    assert shown(log_tab) == ["Laser on"]


def test_technical_view_shows_everything_with_its_source(log_tab):
    arrive(log_tab, (events, "Laser on"), (library, "writing L=1"))
    log_tab.log_view.toggle_technical()
    assert shown(log_tab) == ["Laser on", "writing L=1"]
    sources = [entry.prefix.split()[-1] for entry in log_tab.log_view.lines]
    assert sources == ["app", "coherent_cube"]


def test_technical_view_has_the_full_traceback(log_tab):
    try:
        int("")
    except ValueError:
        logging.getLogger("laser_control.controller").exception("failed, closing the port")
    log_tab._poll()
    log_tab.log_view.toggle_technical()
    text = shown(log_tab)[-1]
    assert text.startswith("failed, closing the port\nTraceback")
    assert "ValueError" in text


def test_warnings_and_errors_keep_their_level_for_the_colour(log_tab):
    events.warning("Can not turn laser on due to interlock open.")
    events.error("Error: device disconnected")
    log_tab._poll()
    assert [e.level for e in log_tab.log_view.lines] == [logging.WARNING, logging.ERROR]


def test_each_view_keeps_its_own_last_500_lines(log_tab):
    arrive(log_tab, (events, "Laser on"))
    arrive(log_tab, *[(library, f"writing P={i}") for i in range(600)])
    view = log_tab.log_view
    assert len(view.technical_lines) == log_view.MAX_LINES
    assert view.technical_lines[-1].text == "writing P=599"
    assert [e.text for e in view.friendly] == ["Laser on"]   # not pushed out by the technical lines


def test_lines_are_collected_on_the_laser_tab_too(win):
    logging.getLogger().setLevel(logging.INFO)
    arrive(win, (events, "Laser on"))
    win.tab_clicked("log")
    assert shown(win) == ["Laser on"]


# ---- scrolling ----

def test_new_lines_keep_the_view_at_the_bottom(log_tab):
    fill(log_tab, 60)
    arrive(log_tab, (events, "Laser on"))
    assert log_tab.log_view.top is None and not log_tab.log_view.unseen


def test_scrolled_up_the_view_stays_put_and_shows_new_lines(log_tab):
    fill(log_tab, 60)
    log_tab.log_view.scroll(-10)
    top = log_tab.log_view.top
    arrive(log_tab, (events, "Laser on"))
    assert log_tab.log_view.top == top
    assert "btn:new-lines" in log_tab.buttons.registered
    log_tab.buttons.registered["btn:new-lines"].on_click()
    assert log_tab.log_view.top is None and "btn:new-lines" not in log_tab.buttons.registered


def test_scrolling_back_down_follows_again(log_tab):
    fill(log_tab, 60)
    log_tab.log_view.scroll(-5)
    log_tab.log_view.scroll(5)
    assert log_tab.log_view.top is None


def test_scrolling_stops_at_the_oldest_line(log_tab):
    fill(log_tab, 60)
    log_tab.log_view.scroll(-1000)
    assert log_tab.log_view.top == 0


def test_ticking_technical_jumps_to_the_newest_lines(log_tab):
    fill(log_tab, 60)
    log_tab.log_view.scroll(-10)
    log_tab.buttons.registered["btn:technical"].on_click()
    assert log_tab.log_view.technical and log_tab.log_view.top is None


# ---- Copy ----

def test_copy_puts_the_shown_lines_on_the_clipboard(log_tab, root):
    arrive(log_tab, (events, "Laser on"), (library, "writing L=1"))
    log_tab.buttons.registered["btn:copy"].on_click()
    copied = root.clipboard_get()
    assert copied.endswith("Laser on") and "writing" not in copied
    assert log_tab.log_view.copied
    run_for(root, log_view.COPIED_MS + 200)
    assert not log_tab.log_view.copied


def test_copy_is_off_while_there_is_nothing_to_copy(log_tab):
    assert not log_tab.buttons.registered["btn:copy"].enabled


# ---- keys and tabs ----

def test_arrows_scroll_the_log_and_leave_the_power_alone(log_tab, root):
    connected(log_tab)
    fill(log_tab, 60)
    log_tab.on_arrow(0.1, -1)
    assert log_tab.log_view.top is not None
    run_for(root, SEND_DELAY_MS + 200)
    assert log_tab.state.power == 5.0 and log_tab.ctl.calls == []


def test_arrows_change_the_power_on_the_laser_tab(win):
    connected(win)
    win.on_arrow(0.1, -1)
    assert win.state.power == 5.1


def test_the_app_opens_on_the_laser_tab_and_the_open_tab_is_not_a_button(win):
    assert win.state.tab == "laser"
    assert not win.buttons.registered["btn:tab-laser"].enabled
    assert win.buttons.registered["btn:tab-log"].enabled


def test_switching_tabs_closes_the_power_field(win):
    connected(win)
    win.power_input.open_editor()
    win.tab_clicked("log")
    assert win.power_input.editor is None


def test_the_log_tab_is_as_tall_as_the_laser_tab_in_manual_mode(win):
    connected(win)
    laser_height = win.height
    win.tab_clicked("log")
    assert win.height == laser_height


# ---- wrapping long lines (pure: one character = 1 px) ----

def test_wrap_breaks_between_words():
    assert wrap("Laser on now", len, 8, 8) == ["Laser on", "now"]


def test_wrap_cuts_a_word_that_is_wider_than_a_row():
    assert wrap("b'MAXLP=55.0'", len, 5, 5) == ["b'MAX", "LP=55", ".0'"]


def test_wrap_uses_the_first_width_for_the_first_row_only():
    assert wrap("aa bb cc dd", len, 2, 5) == ["aa", "bb cc", "dd"]


def test_wrap_starts_a_new_row_at_each_newline_and_keeps_indentation():
    assert wrap("failed\n  File x", len, 20, 20) == ["failed", "  File x"]
