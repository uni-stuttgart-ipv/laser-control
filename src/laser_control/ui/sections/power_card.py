"""The power card (manual mode only): the dial, the − / + buttons, and whether the laser has the value.

::

    ┌──────────────────────────────────────┐
    │   ╭───────╮    Power                 │
    │  ╱  5.0 mW ╲   Drag the dial, or …   │
    │ │ set point │  (−) (+)               │
    │  ╲         ╱   ✓ Applied             │
    │   ╰──● ───╯                          │
    └──────────────────────────────────────┘
      dial           side column

Only the drawing is here. What a drag, click or typed value *does* is in
:mod:`power`; this file tags the dial ``dial`` so the mouse events reach it,
and tells it where the dial's centre is.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from laser_control.controller import MAX_POWER_MW
from laser_control.ui import paint
from laser_control.ui import theme as T
from laser_control.ui.paint import CONTENT_W, GAP, PAD_X
from laser_control.ui.power import READING_RADIUS

if TYPE_CHECKING:
    from laser_control.ui.window import MainWindow

HEIGHT = 176
DIAL = 152                       # the dial's diameter
INSET = (HEIGHT - DIAL) / 2      # the dial sits this far inside the card, top, bottom and left: 12
READING = 2 * READING_RADIUS     # the raised disc in the middle of the dial; clicking it opens the text field
STEP = 38                        # the round − and + buttons
STEP_GAP = 12                    # between − and +
SIDE_RIGHT = 16                  # the side column's text wraps this far inside the card's right edge
TITLE_H, LINE_H, ROW_GAP = 18, 16, 10   # side column: "Power" line, each hint line, gap between rows


def draw(win: MainWindow, y: float) -> float:
    """Draw the power card at ``y``; returns where the next section starts."""
    s, f, a, p = win.state, win.fonts, win.art, win.art.px
    on = s.connected
    tags = ("dial",) if s.power_editable else ()   # untagged = the mouse ignores the dial

    paint.image(win, PAD_X, y, a.soft(CONTENT_W, HEIGHT, 26, "raise"))

    # ---- the dial ----
    dx, dy = PAD_X + INSET, y + INSET
    cx, cy = dx + DIAL / 2, dy + DIAL / 2
    win.power_input.dial_center = (cx, cy)   # power.py needs it to turn a pointer position into a value
    paint.image(win, dx, dy, a.dial(s.power, MAX_POWER_MW, None, on), tags=tags)
    paint.image(win, cx - READING / 2, cy - READING / 2, a.soft(READING, READING, READING / 2, "raise_sm"), tags=tags)

    # The reading in the middle: the number, or the text field while typing
    if win.power_input.editor is not None:
        win.canvas.create_window(p(cx), p(cy - 4), window=win.power_input.editor, width=p(80), anchor="center")
    else:
        num = f"{s.power:.1f}"
        w_num, w_unit = paint.text_width(win, num, f.reading), paint.text_width(win, "mW", f.tiny)
        left = cx - (w_num + 2 + w_unit) / 2   # number + 2 px + "mW", centred together
        paint.text(win, left, cy + 7, num, f.reading, T.AMBER_NUM if on else T.TEXT_OFF, anchor="sw", tags=tags)
        paint.text(win, left + w_num + 2, cy + 3, "mW", f.tiny, T.TEXT_2, anchor="sw", tags=tags)
    paint.text(win, cx, cy + 12, "set point", f.tiny, T.TEXT_3, anchor="n", tags=tags)

    # ---- the side column: title, hint, − +, status; centred vertically in the card ----
    sx = dx + DIAL + INSET
    sw = CONTENT_W - INSET - DIAL - INSET - SIDE_RIGHT
    hint = "Drag the dial, or use − and +." if on else "Limits load when connected."
    lines = 1 if paint.text_width(win, hint, f.small) <= sw else 2
    total = TITLE_H + LINE_H * lines + ROW_GAP + STEP + ROW_GAP + STEP   # the status row is as tall as a button
    ty = y + (HEIGHT - total) / 2
    paint.text(win, sx, ty, "Power", f.label, T.TEXT)
    paint.text(win, sx, ty + TITLE_H, hint, f.small, T.TEXT_3, width=sw)

    # − and +: Shift + click steps 1 mW instead of 0.1; each is greyed out at its limit
    ky = ty + TITLE_H + LINE_H * lines + ROW_GAP
    for i, (name, delta, icon) in enumerate((("dec", -0.1, "minus"), ("inc", 0.1, "plus"))):
        at_limit = s.power <= s.min_power if delta < 0 else s.power >= MAX_POWER_MW
        enabled = s.power_editable and not at_limit
        normal, pressed = a.soft(STEP, STEP, STEP / 2, "raise_sm"), a.soft(STEP, STEP, STEP / 2, "press_sm")
        tag = win.buttons.add(name, enabled,
                              lambda d=delta: win.power_input.nudge(d * (10 if win.buttons.shift_held else 1)),
                              bg={"normal": normal, "press": pressed})
        bx = sx + i * (STEP + STEP_GAP)
        paint.image(win, bx, ky, normal, tags=(tag, f"{tag}.bg"))
        paint.icon(win, bx + STEP / 2, ky + STEP / 2, a.icon(icon, 16, T.TEXT if enabled else T.TEXT_OFF, 2), tags=(tag,))

    # Status: does the laser have the dial's value yet? (power.py sends it 0.5 s after the last change)
    status_y = ky + STEP + ROW_GAP + STEP / 2
    if on and s.power == s.setpoint:
        paint.icon(win, sx + 8, status_y, a.icon("check", 15, T.OK, 2.25))
        paint.text(win, sx + 21, status_y, "Applied", f.label, T.OK, anchor="w")
    elif on:
        paint.text(win, sx, status_y, "Sending…", f.label, T.TEXT_3, anchor="w")
    return y + HEIGHT + GAP
