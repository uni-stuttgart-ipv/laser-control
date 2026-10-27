"""Design tokens: every colour and image margin the UI uses, in one place.

The look follows a dark "smart home" phone UI: a graphite gradient with a
soft amber glow, dark translucent tiles, dark rounded-square buttons and small
orange glyphs. Change the theme here; ``render.py`` and the widgets read these
names only.

Contrast notes (checked by ``tests/test_ui_render.py``): ``TEXT``, ``TEXT_2``
and ``ERROR`` reach 4.5:1 on every tile; ``TEXT_ON_SELECTED`` reaches 4.5:1 on
the muted-orange selected wash.
"""

from __future__ import annotations

# -- background
BG_TOP = "#4A484B"            # gradient, top
BG_MID = "#41414D"            # ... middle
BG_BOTTOM = "#2E2F3A"         # ... bottom (also the window colour behind the canvas)
GLOW = "#A87749"              # warm glow behind the tiles
GLOW_PEAK = 0.95              # glow opacity at its centre

# -- surfaces
BUTTON = "#3F3F49"            # icon buttons, dark pills, menus
ACTIVE = "#4A4C59"            # active bar item, menu highlight, disabled pills
SELECTED = "#B8742F"          # muted-orange wash of a selected tile
SURFACES = {                  # translucent tiles: (tint, opacity); the glow shows through
    "card": ("#302E35", 0.64),
    "panel": ("#2C2E3A", 0.90),
}

# -- accent and text
ACCENT = "#F7A248"            # orange: glyphs, Apply / Connect, focus ring
ON_ACCENT = "#2B2C35"         # text on the orange accent
TEXT = "#F4F4F6"              # titles and big values
TEXT_2 = "#BCBDC7"            # captions and secondary text
TEXT_3 = "#7A7C88"            # disabled labels (intentionally low contrast)
TEXT_ON_SELECTED = "#F3E4D4"  # captions on a selected tile

# -- status colours
ON = "#4ADE80"                # green: laser on, "Connected" dot
OFF = "#FF5A5A"               # red: laser off (symbol)
OFF_TEXT = "#FF6B6B"          # red text on the dark laser panel
ERROR = "#FF9C9C"             # inline error text
LEVEL_COLORS = {"info": TEXT_2, "warning": ACCENT, "error": ERROR}   # message line

# -- overlays: (colour, opacity)
# A selected tile (chosen mode, or the connection card while connected) turns
# muted orange; pressing any tile flashes a fainter orange as feedback.
WASH = {
    (False, "hover"): ("#FFFFFF", 0.05),
    (False, "pressed"): (SELECTED, 0.25),
    (True, "normal"): (SELECTED, 0.45),
    (True, "hover"): (SELECTED, 0.52),
    (True, "pressed"): (SELECTED, 0.38),
    (True, "disabled"): (SELECTED, 0.40),
}
BAR_ACTIVE = (ACTIVE, 0.7)    # backdrop of a live readback-bar item

# -- image margins (transparent border around control images, for shadows and glows)
M = 16                        # every control image; place it at (x - M, y - M)
LASER_MARGIN = 28             # the laser button's glow reaches further
