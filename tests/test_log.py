"""The log: the file, the plain-words line for each result, and the feed to the Log tab."""
import logging

import pytest

from conftest import connect, wait
from laser_control import log
from laser_control.controller import describe


@pytest.fixture
def log_file(tmp_path):
    """Start the log in a temporary folder; remove it again after the test."""
    path = tmp_path / "LaserControl" / "laser_control.log"
    log.start(path)
    yield path
    root = logging.getLogger()
    for handler in root.handlers[:]:
        if getattr(handler, "baseFilename", None) == str(path):
            root.removeHandler(handler)
            handler.close()


def test_start_creates_the_folder_and_the_file(log_file):
    assert "app started" in log_file.read_text()


def test_each_action_is_logged(log_file, ctl):
    connect(ctl)
    ctl.turn_on()
    wait(ctl)
    text = log_file.read_text()
    assert "connect ('COM3', 'manual', 5)" in text
    assert "turn_on ()" in text


def test_a_failure_is_logged_with_the_full_error(log_file, ctl):
    laser = connect(ctl)
    laser.broken = True
    ctl.turn_on()
    wait(ctl)
    text = log_file.read_text()
    assert "failed, closing the port" in text
    assert "Traceback" in text and "device disconnected" in text


def test_a_refusal_is_logged(log_file, ctl):
    laser = connect(ctl)
    laser.refuse_reason = "interlock open"
    ctl.turn_on()
    wait(ctl)
    assert "Can not turn laser on due to interlock open." in log_file.read_text()


# ---- the plain-words lines (controller._report) ----

def test_each_result_in_plain_words():
    assert describe("connected", 0.5) == "Connected. Laser range 0.5–50 mW"
    assert describe("disconnected", None) == "Disconnected"
    assert describe("laser", True) == "Laser on"
    assert describe("laser", False) == "Laser off"
    assert describe("mode", "camera") == "Camera mode"
    assert describe("power", 12.5) == "Power set to 12.5 mW"
    assert describe("current", 41.23) == "Diode current 41.2 mA"
    assert describe("refused", "Can not turn laser on due to interlock open.") == \
        "Can not turn laser on due to interlock open."
    assert describe("error", "device disconnected") == "Error: device disconnected"


def events(caplog):
    """The plain-words lines logged so far, as (level, text)."""
    return [(r.levelname, r.getMessage()) for r in caplog.records if r.name == "laser_control.events"]


def test_every_result_the_window_gets_is_also_logged(ctl, caplog):
    caplog.set_level(logging.INFO)
    connect(ctl)
    ctl.turn_on()
    results = wait(ctl)
    assert [describe(kind, value) for kind, value in results] == [text for _, text in events(caplog)][-2:]
    assert ("INFO", "Laser on") in events(caplog)


def test_a_refusal_is_a_warning_and_an_error_is_an_error(ctl, caplog):
    caplog.set_level(logging.INFO)
    laser = connect(ctl)
    laser.refuse_reason = "interlock open"
    ctl.turn_on()
    wait(ctl)
    laser.broken = True
    ctl.turn_on()
    wait(ctl)
    assert ("WARNING", "Can not turn laser on due to interlock open.") in events(caplog)
    assert ("ERROR", "Error: device disconnected") in events(caplog)


# ---- the feed to the Log tab ----

def test_the_feed_passes_each_new_record_once():
    feed = log.follow()
    try:
        logging.getLogger("laser_control.events").info("Laser on")
        logging.getLogger("coherent_cube.lib").info("writing L=1")
        assert [r.getMessage() for r in feed.take()] == ["Laser on", "writing L=1"]
        assert feed.take() == []
    finally:
        log.stop(feed)
    logging.getLogger("laser_control.events").info("after stop")
    assert feed.take() == []
