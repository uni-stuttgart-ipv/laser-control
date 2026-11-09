"""The message line under the laser card: a hint, or a warning / error banner.

::

    ⓘ Set the power, then turn the laser on.          a hint (no banner)

    ┌──────────────────────────────────────┐
    │ ⚠ Can not turn laser on due to …   ✕ │        a banner: red, with a ✕ to dismiss
    └──────────────────────────────────────┘

While the laser emits, "Wear eye protection while the laser is on." is always
shown; a banner is added under it instead of replacing it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from laser_control.ui import paint
from laser_control.ui import theme as T
from laser_control.ui.paint import CONTENT_W, GAP, PAD_X

if TYPE_CHECKING:
    from laser_control.ui.window import MainWindow

EYE_WARNING = "Wear eye protection while the laser is on."
LINE_H = 32           # height of a one-line hint or banner
TWO_LINES_H = 48      # height of a banner whose text wraps
EYE_LINE_H = 28       # the eye-protection line, when a banner follows it
TEXT_X = 37           # text starts this far inside the card, after the icon
DISMISS_RIGHT = 19    # centre of the ✕, from the card's right edge
DISMISS_HIT = 20      # the ✕'s clickable square


def draw(win: MainWindow, y: float) -> float:
    """Draw the message line at ``y``; returns where the next section starts."""
    s, f, a = win.state, win.fonts, win.art
    top = y

    # While emitting with a banner: the eye-protection line first, the banner below it
    if s.laser_on and s.message:
        paint.icon(win, PAD_X + 22, y + 12, a.icon("warn", 16, T.EMIT_TEXT))
        paint.text(win, PAD_X + TEXT_X, y + 12, EYE_WARNING, f.body, T.EMIT_TEXT, anchor="w")
        y += EYE_LINE_H

    if s.message:
        level, text = s.message
        width = CONTENT_W - TEXT_X - 34                  # leave room for the ✕
        lines = 1 if paint.text_width(win, text, f.body) <= width else 2
        h = LINE_H if lines == 1 else TWO_LINES_H
        fill = T.WARN_BG if level == "warning" else T.ERR_BG
        color = T.WARN if level == "warning" else T.ERR
        paint.image(win, PAD_X, y, a.soft(CONTENT_W, h, 16, "press_sm", fill=fill))
        paint.icon(win, PAD_X + 23, y + h / 2, a.icon("warn", 18, color))
        paint.text(win, PAD_X + TEXT_X, y + h / 2, text, f.body, T.TEXT, anchor="w", width=width)

        # The ✕ button: an invisible square under the icon, filled with the banner's colour
        dx = PAD_X + CONTENT_W - DISMISS_RIGHT
        tag = win.buttons.add("dismiss", True, win.dismiss,
                              fg={"normal": a.icon("x", 15, T.TEXT_2), "hover": a.icon("x", 15, T.TEXT)})
        paint.hit_area(win, dx - DISMISS_HIT / 2, y + h / 2 - DISMISS_HIT / 2, DISMISS_HIT, DISMISS_HIT, (tag,), fill=fill)
        paint.icon(win, dx, y + h / 2, a.icon("x", 15, T.TEXT_2), tags=(tag, f"{tag}.fg"))
        return y + h + GAP

    # No banner: the eye-protection line while emitting, otherwise a hint
    if s.laser_on:
        icon, color, text = a.icon("warn", 16, T.EMIT_TEXT), T.EMIT_TEXT, EYE_WARNING
    else:
        icon, color, text = a.icon("info", 15, T.TEXT_3), T.TEXT_3, hint(win)
    paint.icon(win, PAD_X + 22, top + LINE_H / 2, icon)
    paint.text(win, PAD_X + TEXT_X, top + LINE_H / 2, text, f.body, color, anchor="w", width=CONTENT_W - 40)
    return top + LINE_H + GAP


def hint(win: MainWindow) -> str:
    """What the user should do next, for the hint line."""
    s = win.state
    if s.connecting:
        return f"Opening {s.port}. This can take a while if the laser does not answer."
    if not s.connected:
        return "Pick the laser’s port and connect."
    if s.mode == "camera":
        return "The camera controls power. Turn the laser on when ready."
    return "Set the power, then turn the laser on."
