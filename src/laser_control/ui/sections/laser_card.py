"""The laser card: whether the laser is on, and the round key that turns it on and off.

::

    ┌──────────────────────────────────────┐
    │ Laser                                │
    │ Off                           ( ⏻ )  │
    │ Ready to turn on.                    │
    └──────────────────────────────────────┘

Three looks:

* **emitting:** amber card with an amber ring; the key looks pressed in and
  its glow "breathes" (the window's animation tick swaps :func:`pulse_sprite`
  frames on the item tagged ``key.bg``); pressing it turns the laser off;
* **off, connected:** a raised key; pressing it turns the laser on;
* **not connected:** greyed out.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from laser_control.ui import paint
from laser_control.ui import theme as T
from laser_control.ui.art import Glow, Ring, Sprite
from laser_control.ui.paint import CONTENT_W, PAD_X

if TYPE_CHECKING:
    from laser_control.ui.window import MainWindow

HEIGHT = 82
KEY = 58             # the round on/off key
KEY_RIGHT = 14       # the key sits this far inside the card's right edge
TEXT_X = 22          # the three text lines start this far inside the card
GAP_BELOW = 11       # smaller than the usual gap: the message line belongs to this card
PULSE_FRAMES = 8     # frames in one "breath" of the emitting glow


def draw(win: MainWindow, y: float) -> float:
    """Draw the laser card at ``y``; returns where the next section starts."""
    s, f, a = win.state, win.fonts, win.art

    # The card: amber with a ring and glow while emitting
    if s.laser_on:
        card = a.soft(CONTENT_W, HEIGHT, 26, "raise", gradient=(T.EMIT_WASH, T.BASE),
                      ring=Ring(T.EMIT, 2), glow=Glow(T.EMIT_GLOW, 0, 10, 30))
    else:
        card = a.soft(CONTENT_W, HEIGHT, 26, "raise")
    paint.image(win, PAD_X, y, card)

    # Three lines of text on the left: "Laser", the state, and what to do next
    if s.laser_on:
        state = "Emitting"
        sub = "Pulsed by the camera." if s.mode == "camera" else f"Continuous at {s.setpoint or s.power:.1f} mW."
        colors = (T.EMIT_TEXT, T.EMIT_TEXT, T.EMIT_TEXT)
    elif s.connected:
        state, sub = "Off", "Ready to turn on."
        colors = (T.TEXT_3, T.TEXT, T.TEXT_3)
    else:
        state = "Off"
        sub = "Waiting for the connection." if s.connecting else "Connect first."
        colors = (T.TEXT_3, T.TEXT_OFF, T.TEXT_3)
    x = PAD_X + TEXT_X
    paint.text(win, x, y + 12, "Laser", f.small, colors[0])
    paint.text(win, x, y + 25, state, f.state, colors[1])
    paint.text(win, x, y + 60, sub, f.small, colors[2])

    # The key on the right, centred vertically
    kx, ky = PAD_X + CONTENT_W - KEY_RIGHT - KEY, y + (HEIGHT - KEY) / 2
    r = KEY / 2
    if s.laser_on:
        bg, glyph = pulse_sprite(win, win.pulse_frame), T.EMIT
        looks = {"normal": bg}
    elif s.connected:
        bg, glyph = a.soft(KEY, KEY, r, "raise"), T.TEXT_2
        looks = {"normal": bg, "press": a.soft(KEY, KEY, r, "press")}
    else:
        bg, glyph = a.soft(KEY, KEY, r, "raise_sm"), T.TEXT_OFF
        looks = {"normal": bg}
    hover_glyph = T.EMIT if s.laser_on else T.AMBER_2
    tag = win.buttons.add("key", s.connected, win.laser_clicked, bg=looks,
                          fg={"normal": a.icon("power", 26, glyph, 2.25),
                              "hover": a.icon("power", 26, hover_glyph, 2.25)})
    paint.image(win, kx, ky, bg, tags=(tag, f"{tag}.bg", "key.bg"))
    paint.icon(win, kx + r, ky + r, a.icon("power", 26, glyph, 2.25), tags=(tag, f"{tag}.fg"))
    return y + HEIGHT + GAP_BELOW


def pulse_sprite(win: MainWindow, frame: int) -> Sprite:
    """One frame of the emitting key: pressed in, with an amber ring and glow that grow and shrink.

    ``t`` goes 0 → 1 → 0 over PULSE_FRAMES frames (a cosine), so the ring
    widens from 3 to 6 px while the glow fades, then back. The glow's blur
    stays the same in every frame, so every frame has the same shadow margin
    and can be swapped in without moving the image.
    """
    t = (1 - math.cos(2 * math.pi * frame / PULSE_FRAMES)) / 2
    ring = round(3 + 3 * t)
    alpha = round(0x82 - 0x3C * t)
    return win.art.soft(KEY, KEY, KEY / 2, "press", ring=Ring(T.EMIT_RING, ring),
                        glow=Glow(f"{T.EMIT_GLOW[:7]}{alpha:02X}", 0, 0, 22))
