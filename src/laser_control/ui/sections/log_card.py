"""The Log tab: the controls, and the log lines in a sunk card.

::

    ☐ Technical                         ( Copy )
    ┌──────────────────────────────────────────┐
    │ 16:11:17  Connected. Laser range 0.5–50… │
    │ 16:11:17  Manual mode                    │
    │ 16:11:19  Laser on                       ▐   scroll indicator
    │ 16:11:21  Error: invalid literal for int │
    │   () with base 10: ''                    │   a long line wraps, indented
    │              ( ⌄ New lines )             │   only while scrolled up
    └──────────────────────────────────────────┘

The lines themselves, the scroll position and what the controls do live in
``ui/log_view.py``; this file only draws them. Only the rows that fit in the
card are drawn, never all 500 lines.

Colours: warnings dark amber, errors red, everything else normal text; the
time (and in the technical view the source) is grey.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Callable

from laser_control.ui import paint
from laser_control.ui import theme as T
from laser_control.ui.paint import CONTENT_W, GAP, PAD_X
from laser_control.ui.sections import laser_card, message, mode_bar, port_row, power_card, readouts

if TYPE_CHECKING:
    from laser_control.ui.log_view import Entry
    from laser_control.ui.window import MainWindow


def laser_tab_height() -> float:
    """How tall the Laser tab is below the header, in manual mode with a one-line hint.

    The Log tab is made exactly this tall, so the window keeps its size
    when you switch tabs. Each term is what that section's ``draw`` returns.
    """
    return ((port_row.ROW_H + GAP)
            + (mode_bar.BAR_H + mode_bar.HINT_GAP + mode_bar.HINT_H + GAP)
            + (power_card.HEIGHT + GAP)
            + (laser_card.HEIGHT + laser_card.GAP_BELOW)
            + (message.LINE_H + GAP)
            + (readouts.HEIGHT + readouts.BOTTOM_MARGIN))


BOTTOM_MARGIN = readouts.BOTTOM_MARGIN   # the same empty space at the bottom as the Laser tab
HEIGHT = laser_tab_height() - BOTTOM_MARGIN

# ---- the control row ----
CONTROL_H = 30       # height of the row with the checkbox and Copy
BOX = 18             # the checkbox square
BOX_GAP = 8          # between the square and "Technical"
COPY_W = 96          # the Copy pill
ROW_GAP = 10         # between the control row and the lines card

# ---- the lines card ----
PAD_LEFT = 14        # text starts this far inside the card
PAD_TOP = 12
PAD_BOTTOM = 12
TEXT_RIGHT = 22      # text ends this far inside the card's right edge (room for the scroll indicator)
TEXT_W = CONTENT_W - PAD_LEFT - TEXT_RIGHT
PREFIX_GAP = 8       # between the grey time / source and the message
INDENT = 14          # a wrapped row starts this much further in than the first
ROW_H_FRIENDLY = 19  # row height in the friendly view (body font)
ROW_H_TECHNICAL = 14 # row height in the technical view (monospace font)
SCROLL_RIGHT = 9     # the scroll indicator, from the card's right edge
THUMB_MIN = 24       # the indicator's moving part is never shorter than this
PILL_W, PILL_H = 118, 28   # the "New lines" pill
PILL_BOTTOM = 10     # ... sits this far above the card's bottom edge
PILL_CLEAR = 4       # ... with this much space between it and the last row

COLORS = {logging.ERROR: T.ERR, logging.WARNING: T.LOG_WARN}   # anything else: T.TEXT


def wrap(text: str, measure: Callable[[str], float], first_w: float, rest_w: float) -> list[str]:
    """Split ``text`` into rows: the first at most ``first_w`` px wide, the others ``rest_w``.

    Breaks between words where it can, and inside a word only when the word
    alone is too wide (a long reply such as ``b'...'``). A ``\\n`` in the
    text (a traceback) always starts a new row. Leading spaces are kept, so a
    traceback keeps its indentation.
    """
    rows: list[str] = []
    for paragraph in text.split("\n"):
        row = ""
        for piece in re.findall(r"\s+|\S+\s*", paragraph):   # each word with the spaces after it
            while piece:
                room = first_w if not rows else rest_w
                if measure(row + piece.rstrip()) <= room:
                    row, piece = row + piece, ""
                elif row.strip():                            # doesn't fit: start a new row with it
                    rows.append(row.rstrip())
                    row = ""
                else:                                        # one word wider than a whole row: cut it
                    n = _chars_that_fit(row + piece, measure, room)
                    rows.append((row + piece)[:n])
                    row, piece = "", (row + piece)[n:]
        rows.append(row.rstrip())
    return rows


def _chars_that_fit(text: str, measure: Callable[[str], float], room: float) -> int:
    """How many characters of ``text`` fit in ``room`` px (at least 1, so wrapping always moves on)."""
    lo, hi = 1, len(text)
    while lo < hi:                      # binary search: measuring is the slow part
        mid = (lo + hi + 1) // 2
        if measure(text[:mid]) <= room:
            lo = mid
        else:
            hi = mid - 1
    return lo


def draw(win: MainWindow, y: float) -> float:
    """Draw the Log tab at ``y`` (under the header); returns the window's bottom edge."""
    _draw_controls(win, y)
    _draw_lines(win, y + CONTROL_H + ROW_GAP, HEIGHT - CONTROL_H - ROW_GAP)
    return y + HEIGHT + BOTTOM_MARGIN


def _draw_controls(win: MainWindow, y: float) -> None:
    """☐ Technical on the left, Copy on the right."""
    view, f, a = win.log_view, win.fonts, win.art
    mid = y + CONTROL_H / 2

    # The checkbox: a sunk square, or an amber one with a tick
    label_w = paint.text_width(win, "Technical", f.body)
    tag = win.buttons.add("technical", True, view.toggle_technical, fg_text={"normal": T.TEXT_2, "hover": T.TEXT})
    paint.hit_area(win, PAD_X, y, BOX + BOX_GAP + label_w + 4, CONTROL_H, (tag,))
    box_x = PAD_X + 2
    if view.technical:
        paint.image(win, box_x, mid - BOX / 2,
                    a.soft(BOX, BOX, 5, "raise_sm", gradient=(T.AMBER_1, T.AMBER_2)), tags=(tag,))
        paint.icon(win, box_x + BOX / 2, mid, a.icon("check", 14, T.AMBER_INK, 2.2), tags=(tag,))
    else:
        paint.image(win, box_x, mid - BOX / 2, a.soft(BOX, BOX, 5, "press_sm"), tags=(tag,))
    paint.text(win, box_x + BOX + BOX_GAP, mid, "Technical", f.body, T.TEXT_2, anchor="w", tags=(tag, f"{tag}.fgt"))

    # Copy: a small pill; "✓ Copied" in green for a moment after a click
    x = PAD_X + CONTENT_W - COPY_W
    raised, sunk = a.soft(COPY_W, CONTROL_H, CONTROL_H / 2, "raise_sm"), a.soft(COPY_W, CONTROL_H, CONTROL_H / 2, "press_sm")
    enabled = bool(view.lines)
    tag = win.buttons.add("copy", enabled, view.copy, bg={"normal": raised, "press": sunk})
    paint.image(win, x, y, raised, tags=(tag, f"{tag}.bg"))
    if view.copied:
        width = 14 + 6 + paint.text_width(win, "Copied", f.label)   # tick + gap + label, centred together
        left = x + COPY_W / 2 - width / 2
        paint.icon(win, left + 7, mid, a.icon("check", 14, T.OK, 2.2), tags=(tag,))
        paint.text(win, left + 20, mid, "Copied", f.label, T.OK, anchor="w", tags=(tag,))
    else:
        paint.text(win, x + COPY_W / 2, mid, "Copy", f.label, T.TEXT if enabled else T.TEXT_OFF, anchor="center",
                   tags=(tag,))


def _draw_lines(win: MainWindow, y: float, height: float) -> None:
    """The sunk card with the rows that fit, the scroll indicator, and the "New lines" pill."""
    view, f, a = win.log_view, win.fonts, win.art
    paint.image(win, PAD_X, y, a.soft(CONTENT_W, height, 18, "press"))

    if not view.lines:
        mid = y + height / 2
        paint.text(win, PAD_X + CONTENT_W / 2, mid - 10, "Nothing logged yet.", f.body, T.TEXT_3, anchor="center")
        paint.text(win, PAD_X + CONTENT_W / 2, mid + 10, "Connect to the laser to see what happens.", f.small,
                   T.TEXT_3, anchor="center")
        view.total_rows = 0
        return

    font = f.mono if view.technical else f.body
    row_h = ROW_H_TECHNICAL if view.technical else ROW_H_FRIENDLY
    rows = [(entry, i, text) for entry in view.lines for i, text in enumerate(_rows_of(win, entry, font))]
    rows_h = height - PAD_TOP - PAD_BOTTOM
    if view.unseen:   # the rows stop above the "New lines" pill instead of running under it
        rows_h -= PILL_H + PILL_BOTTOM - PAD_BOTTOM + PILL_CLEAR
    visible = max(1, int(rows_h // row_h))
    view.total_rows, view.visible_rows = len(rows), visible
    top = max(0, len(rows) - visible) if view.top is None else view.top

    # The rows: grey prefix + coloured message on a line's first row, the message alone (indented) after
    x = PAD_X + PAD_LEFT
    for k, (entry, i, text) in enumerate(rows[top:top + visible]):
        ry = y + PAD_TOP + k * row_h
        color = COLORS.get(entry.level, T.TEXT)
        if i == 0:
            paint.text(win, x, ry, entry.prefix, font, T.TEXT_3)
            paint.text(win, x + _prefix_w(win, entry, font), ry, text, font, color)
        else:
            paint.text(win, x + INDENT, ry, text, font, color)

    # The scroll indicator: only when there is more than fits
    if len(rows) > visible:
        p = a.px
        track_top, track_h = y + PAD_TOP, height - PAD_TOP - PAD_BOTTOM
        thumb_h = max(THUMB_MIN, track_h * visible / len(rows))
        thumb_y = track_top + (track_h - thumb_h) * top / (len(rows) - visible)
        sx = PAD_X + CONTENT_W - SCROLL_RIGHT
        win.canvas.create_line(p(sx), p(thumb_y), p(sx), p(thumb_y + thumb_h), fill=T.TEXT_OFF,
                               width=max(2, p(3)), capstyle="round")

    # "New lines": while scrolled up and lines arrived; it jumps to the newest
    if view.unseen:
        px_, py_ = PAD_X + (CONTENT_W - PILL_W) / 2, y + height - PILL_BOTTOM - PILL_H
        normal = a.soft(PILL_W, PILL_H, PILL_H / 2, "raise_sm", gradient=(T.AMBER_1, T.AMBER_2))
        pressed = a.soft(PILL_W, PILL_H, PILL_H / 2, "flat", gradient=(T.AMBER_2, T.AMBER_1))
        tag = win.buttons.add("new-lines", True, view.to_bottom, bg={"normal": normal, "press": pressed})
        paint.image(win, px_, py_, normal, tags=(tag, f"{tag}.bg"))
        width = 14 + 6 + paint.text_width(win, "New lines", f.label)
        left = px_ + PILL_W / 2 - width / 2
        paint.icon(win, left + 7, py_ + PILL_H / 2, a.icon("chev", 14, T.AMBER_INK, 2.2), tags=(tag,))
        paint.text(win, left + 20, py_ + PILL_H / 2, "New lines", f.label, T.AMBER_INK, anchor="w", tags=(tag,))


def _prefix_w(win: MainWindow, entry: Entry, font) -> float:
    """Where a line's message starts, after its grey time / source."""
    return paint.text_width(win, entry.prefix, font) + PREFIX_GAP


def _rows_of(win: MainWindow, entry: Entry, font) -> list[str]:
    """``entry.text`` wrapped to the card, worked out once per line and kept on the entry."""
    if entry.rows is None:
        def measure(s: str) -> float:
            return paint.text_width(win, s, font)
        entry.rows = wrap(entry.text, measure, TEXT_W - _prefix_w(win, entry, font), TEXT_W - INDENT)
    return entry.rows
