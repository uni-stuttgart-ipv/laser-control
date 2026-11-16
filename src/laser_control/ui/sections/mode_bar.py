"""The mode bar: the Camera / Manual switch, and a hint line under it.

::

    ┌───────────────┬───────────────┐
    │   ⌷ Camera    │  ⚟ Manual     │   the chosen mode looks pressed in
    └───────────────┴───────────────┘
    Continuous. You set the power on the dial.

The mode can be switched while the laser is on or off; the laser stays as it
was. Only while connecting is the switch locked (``State.can_switch_mode``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from laser_control.controller import CAMERA_POWER_MW
from laser_control.ui import paint
from laser_control.ui import theme as T
from laser_control.ui.paint import CONTENT_W, GAP, PAD_X

if TYPE_CHECKING:
    from laser_control.ui.window import MainWindow

BAR_H = 52
INSET = 6                    # space between the bar's edge and each half
HALF_H = BAR_H - 2 * INSET   # height of each half: 40
DIVIDER_H = 22               # the thin line between the halves
ICON = 18
ICON_GAP = 9                 # between the icon and the label
HINT_GAP = 9                 # between the bar and the hint line
HINT_H = 16

MODES = (("camera", "camera", "Camera"), ("manual", "sliders", "Manual"))   # (mode, icon, label)


def draw(win: MainWindow, y: float) -> float:
    """Draw the mode bar and its hint at ``y``; returns where the next section starts."""
    s, f, a = win.state, win.fonts, win.art
    mid = y + BAR_H / 2

    # The raised bar, split in two by a thin line
    paint.image(win, PAD_X, y, a.soft(CONTENT_W, BAR_H, BAR_H / 2, "raise"))
    half = (CONTENT_W - 2 * INSET - 1) / 2   # the 1 px is the divider
    win.canvas.create_line(a.px(T.WIDTH / 2), a.px(mid - DIVIDER_H / 2), a.px(T.WIDTH / 2), a.px(mid + DIVIDER_H / 2),
                           fill=T.DIVIDER, width=max(1, a.px(1)))

    for i, (mode, icon, label) in enumerate(MODES):
        x = PAD_X + INSET + i * (half + 1)
        selected = s.mode == mode
        # Clicking the chosen mode again while connected re-runs it
        # (for example to repeat the camera calibration).
        enabled = s.can_switch_mode and (not selected or s.connected)
        tag = win.buttons.add(f"mode-{mode}", enabled, lambda m=mode: win.mode_clicked(m),
                              fg_text={"normal": T.TEXT_2, "hover": T.TEXT})
        paint.hit_area(win, x, y + INSET, half, HALF_H, (tag,))

        # Chosen: pressed in, amber icon. Otherwise grey, and paler while locked.
        if selected:
            paint.image(win, x, y + INSET, a.soft(half, HALF_H, HALF_H / 2, "press_sm"), tags=(tag,))
            icon_color, text_color = T.AMBER_2, T.TEXT
        elif s.can_switch_mode:
            icon_color, text_color = T.TEXT_3, T.TEXT_2
        else:
            icon_color, text_color = T.TEXT_OFF, T.TEXT_OFF

        # Icon + label, centred together in the half
        width = ICON + ICON_GAP + paint.text_width(win, label, f.mode)
        left = x + half / 2 - width / 2
        paint.icon(win, left + ICON / 2, mid, a.icon(icon, ICON, icon_color, 1.9), tags=(tag,))
        paint.text(win, left + ICON + ICON_GAP, mid, label, f.mode, text_color, anchor="w", tags=(tag, f"{tag}.fgt"))

    # The hint line under the bar
    hint_y = y + BAR_H + HINT_GAP
    if s.mode == "camera":
        hint = f"Pulsed. The camera drives power, calibrated at {CAMERA_POWER_MW} mW."
    else:
        hint = "Continuous. You set the power on the dial."
    paint.text(win, PAD_X + 4, hint_y, hint, f.small, T.TEXT_3)
    return hint_y + HINT_H + GAP
