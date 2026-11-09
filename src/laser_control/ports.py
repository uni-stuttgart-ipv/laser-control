"""Return a list of available serial ports."""
from serial.tools import list_ports


def get_serial_ports():
    """Get a list of available serial ports."""
    sorted_ports = sorted(list_ports.comports())
    return [port.device for port in sorted_ports]
