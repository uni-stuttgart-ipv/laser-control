"""Serial port list for the Connection dropdown (Windows, macOS and Linux)."""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass

from serial.tools import list_ports

STANDARD_COM_PORTS = [f"COM{i}" for i in range(1, 21)]   # always offered: COM1–COM20


@dataclass(frozen=True)
class PortInfo:
    """One entry in the port list.

    Attributes:
        device: the name to open (``COM3``, ``/dev/cu.usbserial-1``, ...).
        description: the OS description of the device, if any.
        detected: True if the port was found on this computer right now; False
            for the standard COM1-COM20 names that are always offered.
    """

    device: str
    description: str = ""
    detected: bool = True

    @property
    def label(self) -> str:
        """Text for the dropdown: ``"COM3 – USB Serial Device"``, ``"COM10 · detected"`` or ``"COM1"``."""
        desc = self.description
        # "COM3 – USB Serial Device (COM3)": drop the repeated port name.
        desc = re.sub(rf"\s*\({re.escape(self.device)}\)\s*$", "", desc or "")
        if not self.detected:
            return self.device
        if not desc or desc == "n/a" or desc == self.device:
            return f"{self.device} · detected"
        return f"{self.device} – {desc}"


def _natural_key(name: str):
    """Sort key so COM2 comes before COM10."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


def detected_ports() -> list[PortInfo]:
    """Ports pyserial finds on this computer, naturally sorted.

    On macOS only the ``/dev/cu.*`` call-out nodes are kept (Bluetooth and
    debug-console ports are dropped too).
    """
    ports = []
    for p in list_ports.comports():
        dev = p.device
        if sys.platform == "darwin":
            # /dev/tty.* can block on open waiting for carrier; /dev/cu.* is the right node.
            if dev.startswith("/dev/tty.") or "Bluetooth" in dev or "debug-console" in dev:
                continue
        ports.append(PortInfo(dev, p.description or ""))
    return sorted(ports, key=lambda p: _natural_key(p.device))


def list_serial_ports() -> list[PortInfo]:
    """Detected ports first, then COM1–COM20 (those not already detected)."""
    found = detected_ports()
    names = {p.device.upper() for p in found}
    return found + [PortInfo(c, detected=False) for c in STANDARD_COM_PORTS if c not in names]
