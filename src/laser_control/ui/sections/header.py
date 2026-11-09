"""The header: the app's name, the power range, and the connection status.

::

    Laser Control
    0.5 to 50 mW                 ● Connected
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from laser_control.controller import MAX_POWER_MW
from laser_control.ui import paint
from laser_control.ui import theme as T
from laser_control.ui.paint import CONTENT_W, GAP, PAD_X

if TYPE_CHECKING:
    from laser_control.ui.window import MainWindow

HEIGHT = 48
TITLE_Y = -2      # the light title font has empty space above its letters; this lines them up with the margin
SUBTITLE_Y = 30
STATUS_Y = 38     # centre of the subtitle line, so the status sits level with it
DOT_GAP = 10      # from the status dot's centre to the start of its label


def draw(win: MainWindow, y: float) -> float:
    """Draw the header at ``y``; returns where the next section starts."""
    s, f = win.state, win.fonts

    # Title, and under it the power range once the laser has told us its minimum
    paint.text(win, PAD_X, y + TITLE_Y, "Laser Control", f.title, T.TEXT)
    sub = f"{s.min_power:g} to {MAX_POWER_MW} mW" if s.connected else "Serial laser controller"
    paint.text(win, PAD_X, y + SUBTITLE_Y, sub, f.small, T.TEXT_3)

    # Status on the right: label, colour, dot colour (None = spinner), bold?
    if s.laser_on:
        label, color, dot, bold = "Emitting", T.EMIT_TEXT, T.EMIT, True
    elif s.connected:
        label, color, dot, bold = "Connected", T.TEXT_2, T.OK, False
    elif s.connecting:
        label, color, dot, bold = "Connecting", T.TEXT_3, None, False
    elif s.message and s.message[0] == "error":
        label, color, dot, bold = "Error", T.ERR, T.ERR, False
    else:
        label, color, dot, bold = "Not connected", T.TEXT_3, T.TEXT_3, False
    font = f.label if bold else f.small
    right, cy = PAD_X + CONTENT_W, y + STATUS_Y
    paint.text(win, right, cy, label, font, color, anchor="e")   # right-aligned to the card edge

    # The dot (or spinner) just left of the label
    dx = right - paint.text_width(win, label, font) - DOT_GAP
    p = win.art.px
    if dot is None:
        paint.spinner(win, dx, cy, 5, T.TEXT_2)
    else:
        if s.laser_on:  # a soft amber halo behind the dot
            win.canvas.create_oval(p(dx - 6.5), p(cy - 6.5), p(dx + 6.5), p(cy + 6.5), fill=T.EMIT_WASH,
                                   outline="")
        win.canvas.create_oval(p(dx - 3.5), p(cy - 3.5), p(dx + 3.5), p(cy + 3.5), fill=dot, outline="")
    return y + HEIGHT + GAP
