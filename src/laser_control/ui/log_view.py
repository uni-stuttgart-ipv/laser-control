"""The Log tab's lines and what the user does with them: Technical, scrolling, Copy.

This file keeps the *data*; ``sections/log_card.py`` *draws* it, like
``power.py`` and ``power_card.py``.

Two views of the same log
-------------------------
Every log record reaches the window through a :class:`laser_control.log.Feed`.
Each one is kept in up to two lists, at most 500 lines each:

* **friendly:** only the controller's plain-words lines ("Laser on",
  "Error: device disconnected"), which ``controller._report`` writes for
  every result. Shown by default.
* **technical:** everything: the library's ``writing`` / ``recieved`` lines,
  each action, and full tracebacks. Shown while "Technical" is ticked.

The log *file* always gets everything; the checkbox only changes what is shown.

Scrolling
---------
The shown lines are split into *rows* that fit the card (a long line wraps
onto more rows). ``top`` is the first row on screen, or ``None`` to follow
the newest rows. Scrolling up sets ``top``, so the rows you are reading stay
put while new lines arrive; ``unseen`` then shows the "New lines" pill.
Scrolling back to the bottom sets ``top`` to ``None`` again.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from laser_control import log

if TYPE_CHECKING:
    from laser_control.ui.window import MainWindow

MAX_LINES = 500          # kept per view
COPIED_MS = 1500         # how long Copy shows "Copied"
FRIENDLY_SOURCE = "laser_control.events"   # the controller's plain-words logger


@dataclass
class Entry:
    """One log line, ready to show.

    ``prefix`` is the time (and the source, in the technical view), drawn in
    grey before ``text``. ``rows`` is filled in by ``log_card.py`` the first
    time the line is drawn: ``text`` split into rows that fit the card.
    """

    prefix: str
    text: str
    level: int                       # logging.INFO, WARNING or ERROR: the colour
    rows: list[str] | None = None


def entries_for(record: logging.LogRecord) -> tuple[Entry | None, Entry]:
    """The friendly line (or None, if it isn't one) and the technical line for a record."""
    when = datetime.fromtimestamp(record.created)
    message = record.getMessage()
    full = message
    if record.exc_info:   # a failure: the technical line carries the whole traceback
        full += "\n" + logging.Formatter().formatException(record.exc_info)
    source = "coherent_cube" if record.name.startswith("coherent_cube") else "app"
    technical = Entry(f"{when:%H:%M:%S}.{int(record.msecs):03d}  {source:<13}", full, record.levelno)
    friendly = Entry(f"{when:%H:%M:%S}", message, record.levelno) if record.name == FRIENDLY_SOURCE else None
    return friendly, technical


class LogView:
    """The lines of both views, which one is shown, and the scroll position.

    Args:
        win: The main window; this redraws it and uses its clipboard.
    """

    def __init__(self, win: MainWindow):
        self.win = win
        self.friendly: deque[Entry] = deque(maxlen=MAX_LINES)
        self.technical_lines: deque[Entry] = deque(maxlen=MAX_LINES)
        self.technical = False        # the checkbox; off every time the app starts
        self.top: int | None = None   # first row on screen; None = follow the newest rows
        self.unseen = False           # new rows arrived while scrolled up: show "New lines"
        self.copied = False           # Copy shows "Copied" for a moment
        self._copied_job: str | None = None

        # Set by log_card.py on every draw, so scrolling knows its limits
        self.total_rows = 0
        self.visible_rows = 1

        self.feed = log.follow()
        win.canvas.bind("<Destroy>", lambda e: log.stop(self.feed), add="+")

    @property
    def lines(self) -> deque[Entry]:
        """The lines of the view that is shown."""
        return self.technical_lines if self.technical else self.friendly

    # ---- new lines ----

    def take_new(self) -> bool:
        """Collect the records that arrived; True if the shown view got new lines."""
        shown_changed = False
        for record in self.feed.take():
            friendly, technical = entries_for(record)
            if friendly:
                shown_changed |= self._append(self.friendly, friendly)
            shown_changed |= self._append(self.technical_lines, technical)
        if shown_changed and self.top is not None:
            self.unseen = True
        return shown_changed

    def _append(self, lines: deque[Entry], entry: Entry) -> bool:
        """Add a line; True if it went into the shown view."""
        shown = lines is self.lines
        if shown and self.top is not None and len(lines) == lines.maxlen:
            # The oldest line is about to drop off the top: move up with it, so the view stays put
            self.top = max(0, self.top - len(lines[0].rows or [""]))
        lines.append(entry)
        return shown

    # ---- what the user does ----

    def toggle_technical(self) -> None:
        """The Technical checkbox: switch views and jump to the newest lines."""
        self.technical = not self.technical
        self.to_bottom()

    def scroll(self, rows: int) -> None:
        """Scroll by ``rows`` (negative: up, to older lines)."""
        last_top = max(0, self.total_rows - self.visible_rows)
        top = last_top if self.top is None else self.top
        top = min(max(top + rows, 0), last_top)
        if top >= last_top:
            self.to_bottom()
            return
        self.top = top
        self.win.render()

    def to_bottom(self) -> None:
        """Show the newest lines and follow new ones (also the "New lines" pill)."""
        self.top = None
        self.unseen = False
        self.win.render()

    def copy(self) -> None:
        """Copy the shown lines to the clipboard; the button says "Copied" for a moment."""
        text = "\n".join(f"{e.prefix}  {e.text}" for e in self.lines)
        self.win.root.clipboard_clear()
        self.win.root.clipboard_append(text)
        self.copied = True
        if self._copied_job:
            self.win.root.after_cancel(self._copied_job)
        self._copied_job = self.win.root.after(COPIED_MS, self._copy_done)
        self.win.render()

    def _copy_done(self) -> None:
        self.copied = False
        self._copied_job = None
        self.win.render()
