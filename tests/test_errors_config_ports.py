"""Error classification, settings file and port helpers."""

from __future__ import annotations

import json

import pytest
import serial

from laser_control.config import AppConfig, load_config, save_config
from laser_control.errors import ErrorKind, Phase, classify, on_refused_cause, power_warning
from laser_control.model import PortInfo
from laser_control.ports import pick_default


@pytest.mark.parametrize("exc, phase, kind, fatal", [
    (serial.SerialException("could not open port 'COM3': PermissionError(13, 'Access is denied.')"),
     Phase.CONNECT, ErrorKind.PORT_BUSY, True),
    (serial.SerialException("could not open port 'COM9': FileNotFoundError(2, ...)"),
     Phase.CONNECT, ErrorKind.PORT_NOT_FOUND, True),
    (ValueError("could not convert string to float: ''"), Phase.CONNECT, ErrorKind.NO_RESPONSE, True),
    (ValueError("could not convert string to float: ''"), Phase.COMMAND, ErrorKind.NO_RESPONSE, True),
    (ValueError("could not convert string to float: 'xyz'"), Phase.CONNECT, ErrorKind.WRONG_DEVICE, True),
    (serial.SerialTimeoutException("Write timeout"), Phase.COMMAND, ErrorKind.WRITE_TIMEOUT, True),
    (serial.SerialException("device reports readiness to read but returned no data"),
     Phase.COMMAND, ErrorKind.LINK_LOST, True),
    (RuntimeError("`power` is greater than the laser's maximum."), Phase.COMMAND, ErrorKind.POWER_TOO_HIGH, False),
    (ValueError("`power` must be non-negative."), Phase.COMMAND, ErrorKind.POWER_NEGATIVE, False),
    (KeyError("boom"), Phase.COMMAND, ErrorKind.UNEXPECTED, True),
])
def test_classify(exc, phase, kind, fatal):
    result = classify(exc, phase, "COM3")
    assert result.kind is kind
    assert result.fatal is fatal
    assert result.message.text


def test_on_refused_cause():
    assert on_refused_cause(("Can not turn laser on due to Interlock open.",)) == "Interlock open"
    assert on_refused_cause(("`power` is above nominal.",)) is None


def test_power_warning():
    msg = power_warning(("`power` is above nominal.",), 52.0, 50.0, 0.5)
    assert msg and msg.title == "Above nominal"
    assert power_warning((), 5.0, 50.0, 0.5) is None


def test_config_round_trip(tmp_path):
    path = tmp_path / "sub" / "config.json"
    save_config(AppConfig(last_port="COM7", last_power_mw=12.5), path)
    assert load_config(path) == AppConfig(last_port="COM7", last_power_mw=12.5)
    assert json.loads(path.read_text())["version"] == 1


def test_config_corrupt_or_missing(tmp_path):
    assert load_config(tmp_path / "missing.json") == AppConfig()
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert load_config(bad) == AppConfig()


def test_pick_default():
    ports = [PortInfo("COM1", ""), PortInfo("COM3", ""), PortInfo("COM10", "")]
    assert pick_default(ports, "COM10") == "COM10"
    assert pick_default(ports, "COM99") == "COM3"
    assert pick_default([PortInfo("COM4", "")], None) == "COM4"
    assert pick_default([], None) == "COM3"


# Real pyserial messages as raised on Windows (serialwin32.py), so a pyserial or
# Windows update that changes them shows up here rather than as a wrong banner.
@pytest.mark.parametrize("text, phase, kind", [
    ("could not open port 'COM3': PermissionError(13, 'Access is denied.', None, 5)",
     Phase.CONNECT, ErrorKind.PORT_BUSY),
    ("could not open port 'COM9': FileNotFoundError(2, 'The system cannot find the file specified.', None, 2)",
     Phase.CONNECT, ErrorKind.PORT_NOT_FOUND),
    ("could not open port 'COM4': PermissionError(13, 'A device attached to the system is not functioning.', "
     "None, 31)", Phase.CONNECT, ErrorKind.PORT_NOT_FOUND),
    ("could not open port /dev/ttyUSB0: [Errno 13] Permission denied: '/dev/ttyUSB0'",
     Phase.CONNECT, ErrorKind.PORT_BUSY),
    ("WriteFile failed (PermissionError(13, 'The device does not recognize the command.', None, 22))",
     Phase.COMMAND, ErrorKind.LINK_LOST),
    ("ClearCommError failed (OSError(22, 'The parameter is incorrect.', None, 87))",
     Phase.COMMAND, ErrorKind.LINK_LOST),
])
def test_classify_real_windows_messages(text, phase, kind):
    result = classify(serial.SerialException(text), phase, "COM3")
    assert result.kind is kind
    assert result.fatal


def test_off_not_confirmed_is_fatal_with_clear_message():
    from laser_control.errors import OffNotConfirmed
    result = classify(OffNotConfirmed("no answer"), Phase.COMMAND)
    assert result.kind is ErrorKind.OFF_NOT_CONFIRMED and result.fatal
    assert "may still be on" in result.message.text


@pytest.mark.parametrize("stored, expected", [
    ({"timeout_s": 0}, dict(timeout_s=0.2)),
    ({"timeout_s": 999}, dict(timeout_s=30.0)),
    ({"timeout_s": "abc"}, dict(timeout_s=2.0)),
    ({"poll_interval_ms": 10}, dict(poll_interval_ms=250)),
    ({"last_power_mw": -5}, dict(last_power_mw=0.0)),
    ({"last_power_mw": "nan"}, dict(last_power_mw=5.0)),
    ({"last_port": ""}, dict(last_port="COM3")),
])
def test_config_values_are_clamped(tmp_path, stored, expected):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(stored))
    cfg = load_config(path)
    for name, value in expected.items():
        assert getattr(cfg, name) == value, name

