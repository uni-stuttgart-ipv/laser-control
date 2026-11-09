"""ports.py lists the serial port names for the dropdown."""
from serial.tools.list_ports_common import ListPortInfo

from laser_control import ports


def fake_ports(*names):
    return [ListPortInfo(name, skip_link_detection=True) for name in names]


def test_returns_port_names_in_number_order(monkeypatch):
    monkeypatch.setattr(ports.list_ports, "comports", lambda: fake_ports("COM10", "COM3", "COM1"))
    assert ports.get_serial_ports() == ["COM1", "COM3", "COM10"]   # COM10 after COM3, not before


def test_no_ports_gives_an_empty_list(monkeypatch):
    monkeypatch.setattr(ports.list_ports, "comports", lambda: [])
    assert ports.get_serial_ports() == []
