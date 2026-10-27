"""Serve a ``SimulatedDevice`` on a pseudo-terminal (Linux/macOS).

The driver then talks to it through a real ``pyserial`` port, so serial
framing, timeouts and the controller are exercised end to end.
"""

from __future__ import annotations

import os
import select
import threading
import tty

from laser_app.hardware.laser import EOL
from laser_app.hardware.simulator import SimulatedDevice


class PtyLaser:
    """A ``SimulatedDevice`` answering on the master side of a pty; ``port`` is the device path."""

    def __init__(self, **device_options) -> None:
        self.device = SimulatedDevice(**device_options)
        self.master, slave = os.openpty()
        tty.setraw(slave)
        self.port = os.ttyname(slave)
        self._slave = slave                     # keep open so the pty stays alive
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def close(self) -> None:
        """Stop serving and close the pty."""
        self._stop.set()
        self._thread.join(1)
        for fd in (self.master, self._slave):
            try:
                os.close(fd)
            except OSError:
                pass

    def _serve(self) -> None:
        buf = b""
        while not self._stop.is_set():
            ready, _, _ = select.select([self.master], [], [], 0.05)
            if not ready:
                continue
            try:
                buf += os.read(self.master, 1024)
            except OSError:
                return
            while EOL in buf:
                raw, buf = buf.split(EOL, 1)
                for reply in self.device.handle(raw.decode("ascii")):
                    os.write(self.master, reply.encode("ascii") + EOL)
