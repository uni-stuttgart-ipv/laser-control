"""pytest configuration shared by all tests."""

import sys

# The pty-based laser emulator needs os.openpty / tty (Linux, macOS).
collect_ignore = ["test_serial.py", "serial_pty.py"] if sys.platform == "win32" else []
