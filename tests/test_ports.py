"""Port list: detected ports first, then COM1–COM20; macOS filtering; labels."""

from types import SimpleNamespace

import pytest

from laser_app.hardware import ports
from laser_app.hardware.ports import PortInfo


def test_detected_then_standard_com_ports(monkeypatch):
    fake = [SimpleNamespace(device="COM3", description="USB Serial Device (COM3)"),
            SimpleNamespace(device="COM10", description="")]
    monkeypatch.setattr(ports.list_ports, "comports", lambda: fake)
    monkeypatch.setattr(ports.sys, "platform", "win32")
    result = ports.list_serial_ports()
    devices = [p.device for p in result]
    assert devices[:2] == ["COM3", "COM10"]                      # detected first
    assert devices[2:] == [f"COM{i}" for i in range(1, 21) if i not in (3, 10)]
    assert result[0].label == "COM3 – USB Serial Device"
    assert result[1].label == "COM10 · detected"
    assert result[2].label == "COM1"


def test_macos_keeps_only_callout_ports(monkeypatch):
    fake = [SimpleNamespace(device=d, description="") for d in (
        "/dev/tty.usbserial-A1",
        "/dev/cu.usbserial-A1",
        "/dev/cu.Bluetooth-Incoming-Port",
        "/dev/cu.debug-console",
        "/dev/cu.usbmodem2",
    )]
    monkeypatch.setattr(ports.list_ports, "comports", lambda: fake)
    monkeypatch.setattr(ports.sys, "platform", "darwin")
    assert [p.device for p in ports.detected_ports()] == ["/dev/cu.usbmodem2",
                                                          "/dev/cu.usbserial-A1"]


@pytest.mark.parametrize("info, label", [
    (PortInfo("COM1", "Some device", detected=False), "COM1"),          # not detected: name only
    (PortInfo("COM4"), "COM4 · detected"),                              # no description
    (PortInfo("COM4", "n/a"), "COM4 · detected"),                       # Linux placeholder
    (PortInfo("COM4", "COM4"), "COM4 · detected"),                      # description = name
    (PortInfo("COM4", "USB Serial (COM4)"), "COM4 – USB Serial"),       # repeated name dropped
    (PortInfo("/dev/cu.usbserial", "FT232R"), "/dev/cu.usbserial – FT232R"),
])
def test_port_label(info, label):
    assert info.label == label
