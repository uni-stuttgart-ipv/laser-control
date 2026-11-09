"""The tab bar at the very top: switch between the Laser controls and the Log.

::

                ┌───────────┬───────────┐
                │   Laser   │    Log    │     the open tab looks pressed in
                └───────────┴───────────┘
    Laser Control
    Serial laser controller           ● Connected

It is drawn like the Camera / Manual bar (``mode_bar.py``), only smaller, and
centred in the window. The header under it stays on both tabs, so the
laser's state ("● Emitting") is always in view.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from laser_control.ui import paint
from laser_control.ui import theme as T

if TYPE_CHECKING:
    from laser_control.ui.window import MainWindow

BAR_W = 176
BAR_H = 34
INSET = 4                    # space between the bar's edge and each half
HALF_H = BAR_H - 2 * INSET   # height of each half: 26
DIVIDER_H = 14               # the thin line between the halves
GAP_BELOW = 14               # between the bar and the header

TABS = (("laser", "Laser"), ("log", "Log"))   # (tab, label)


def draw(win: MainWindow, y: float) -> float:
    """Draw the tab bar at ``y``; returns where the header starts."""
    s, f, a = win.state, win.fonts, win.art
    left = (T.WIDTH - BAR_W) / 2   # centred in the window
    mid = y + BAR_H / 2

    # The raised bar, split in two by a thin line
    paint.image(win, left, y, a.soft(BAR_W, BAR_H, BAR_H / 2, "raise_sm"))
    half = (BAR_W - 2 * INSET - 1) / 2   # the 1 px is the divider
    win.canvas.create_line(a.px(T.WIDTH / 2), a.px(mid - DIVIDER_H / 2), a.px(T.WIDTH / 2), a.px(mid + DIVIDER_H / 2),
                           fill=T.DIVIDER, width=max(1, a.px(1)))

    for i, (tab, label) in enumerate(TABS):
        x = left + INSET + i * (half + 1)
        selected = s.tab == tab
        # The open tab is not a button: clicking it again would do nothing
        tag = win.buttons.add(f"tab-{tab}", not selected, lambda t=tab: win.tab_clicked(t),
                              fg_text={"normal": T.TEXT_2, "hover": T.TEXT})
        paint.hit_area(win, x, y + INSET, half, HALF_H, (tag,))
        if selected:   # pressed in, like the chosen mode
            paint.image(win, x, y + INSET, a.soft(half, HALF_H, HALF_H / 2, "press_sm"), tags=(tag,))
        paint.text(win, x + half / 2, mid, label, f.label, T.TEXT if selected else T.TEXT_2, anchor="center",
                   tags=(tag, f"{tag}.fgt"))
    return y + BAR_H + GAP_BELOW
