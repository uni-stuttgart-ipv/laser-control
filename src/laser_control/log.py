"""A log file of everything sent to and read from the laser.

coherent-cube already records every line it writes ("writing L=1") and reads
("recieved b'L=1\\r\\n'"); this turns that on and saves it to a file. The
controller adds a line for each action and the full error when one fails.

A read that timed out shows as ``recieved b''``. The times are to the
millisecond, so you can see how long the laser took to answer.

The window's Log tab gets the same lines live, through a :class:`Feed`.
"""
import logging
import queue
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_FILE = Path.home() / "LaserControl" / "laser_control.log"   # Windows: C:\Users\<you>\LaserControl\
MAX_BYTES = 1_000_000   # start a new file after 1 MB ...
BACKUPS = 3             # ... and keep the 3 before it (laser_control.log.1, .2, .3)


def start(path=LOG_FILE):
    """Send the app's and the library's log lines to `path`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(path, maxBytes=MAX_BYTES, backupCount=BACKUPS, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s.%(msecs)03d  %(name)-22s %(message)s",
                                           datefmt="%Y-%m-%d %H:%M:%S"))
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.INFO)   # INFO: every write and read; DEBUG would add byte counts
    logging.getLogger(__name__).info("---- app started ----")


class Feed(logging.Handler):
    """Hands every new log record to the window's Log tab.

    Records arrive from any thread (most from the controller's), so they wait
    in a queue; the window takes them in its 100 ms poll with :meth:`take`.
    """

    def __init__(self):
        super().__init__(level=logging.INFO)
        self._new = queue.SimpleQueue()

    def emit(self, record):
        self._new.put(record)

    def take(self):
        """Return the records since the last call, oldest first."""
        records = []
        while not self._new.empty():
            records.append(self._new.get())
        return records


def follow():
    """Start a Feed for the Log tab; stop it again with ``stop(feed)``."""
    feed = Feed()
    root = logging.getLogger()
    root.addHandler(feed)
    if root.getEffectiveLevel() > logging.INFO:   # without start() the root logger only passes warnings
        root.setLevel(logging.INFO)
    return feed


def stop(feed):
    """Stop a Feed (when its window closes)."""
    logging.getLogger().removeHandler(feed)
