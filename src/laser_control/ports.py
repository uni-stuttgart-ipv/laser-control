"""Serial port discovery."""

from __future__ import annotations

import re

from serial.tools import list_ports as _list_ports

from laser_control.model import DEFAULT_PORT, PortInfo


def _sort_key(device: str) -> tuple[str, int, str]:
    # COM10 after COM9: compare the numeric suffix as a number.
    match = re.match(r"^(.*?)(\d+)$", device)
    return (match.group(1), int(match.group(2)), device) if match else (device, -1, device)


def list_ports(simulate: bool = False) -> list[PortInfo]:
    """List serial ports the user can pick.

    Args:
        simulate: Return the simulator's ports (see :mod:`laser_control.sim`).

    Returns:
        Ports sorted by name, ``COMn`` numerically.
    """
    if simulate:
        from laser_control.sim import SIM_PORTS
        return [PortInfo(name, desc) for name, desc in SIM_PORTS.items()]
    found = [PortInfo(p.device, p.description or p.device) for p in _list_ports.comports()]
    return sorted(found, key=lambda p: _sort_key(p.device))


def pick_default(available: list[PortInfo], last_port: str | None) -> str:
    """Choose the port to preselect.

    Preference: the last port used, then ``COM3``, then the first port found,
    then ``COM3`` even if it is not present (the user may plug in later).
    """
    names = [p.device for p in available]
    for candidate in (last_port, DEFAULT_PORT):
        if candidate and candidate in names:
            return candidate
    return names[0] if names else (last_port or DEFAULT_PORT)
