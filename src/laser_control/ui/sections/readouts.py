"""The readouts at the bottom: set point, diode current, and the mode.

::

    ┌────────────┬────────────┬────────────┐
    │  5.0 mW    │  41.2 mA   │    CW      │
    │ Set point  │ Diode curr │  Manual    │
    └────────────┴────────────┴────────────┘

The values come from the laser and are refreshed after each action (the
controller doesn't poll). "—" means the laser hasn't reported a value yet.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from laser_control.ui import paint
from laser_control.ui import theme as T
from laser_control.ui.paint import CONTENT_W, PAD_X

if TYPE_CHECKING:
    from laser_control.ui.window import MainWindow

HEIGHT = 56
INSET = 6             # space between the card's edge and the three cells
BOTTOM_MARGIN = 16    # empty space under the last card, at the bottom of the window


def draw(win: MainWindow, y: float) -> float:
    """Draw the readouts at ``y``; returns the window's bottom edge."""
    s, f, p = win.state, win.fonts, win.art.px
    paint.image(win, PAD_X, y, win.art.soft(CONTENT_W, HEIGHT, 24, "raise"))

    on = s.connected
    setpoint = f"{s.setpoint:.1f} mW" if on and s.setpoint is not None else "— mW"
    current = f"{s.current:.1f} mA" if on and s.current is not None else "— mA"
    camera = s.mode == "camera"
    cells = (  # (value, label, colour)
        (setpoint, "Set point", T.TEXT),
        (current, "Diode current", T.EMIT_TEXT if s.laser_on else T.TEXT),
        ("Pulsed" if camera else "CW", "Camera" if camera else "Manual", T.TEXT),
    )

    cell = (CONTENT_W - 2 * INSET) / 3
    for i, (value, label, color) in enumerate(cells):
        cx = PAD_X + INSET + cell * (i + 0.5)   # centre of cell i
        paint.text(win, cx, y + 20, value, f.readout, color if on else T.TEXT_OFF, anchor="center")
        paint.text(win, cx, y + 40, label, f.tiny, T.TEXT_3, anchor="center")
        if i:  # a thin line between cells
            x = PAD_X + INSET + cell * i
            win.canvas.create_line(p(x), p(y + 14), p(x), p(y + 42), fill=T.DIVIDER, width=max(1, p(1)))
    return y + HEIGHT + BOTTOM_MARGIN
