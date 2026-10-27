"""Window geometry: every position and size of the fixed 440 x 712 layout.

Top to bottom (``*`` marks a tile's orange glyph)::

     [⟳]            Laser Control           [plug]   header: refresh | connect
                    Connected · COM3
    ( *       COM3       │  [ Disconnect ]    )   connection card: port menu |
    (         port ⌄     │   ● Connected      )   action button + status line
    ( *   Camera     ) ( *   Manual       )   mode tiles
    (     mode       ) (     mode         )
    ( *      12.0 mW           [ Apply ]     )   Power tile: Manual only
    (       power                           )
    (                 Laser                 )   laser panel
    (                Laser on               )
    (                 [ ⏻ ]                 )   on / off button
                 Laser on.                      latest message
      [12.0 mW]    [49.0 mA]    [manual]        readback bar

The laser panel and the bar are pinned to the bottom, so switching to Camera
only hides the Power tile; the window never changes size. Spacing follows an
8 px rhythm.
"""

from __future__ import annotations

from ..controller import Mode

Rect = tuple[int, int, int, int]          # (x0, y0, x1, y1)

WIDTH, HEIGHT = 440, 712
MARGIN = 16
GAP = 8                                   # between tiles
X0, X1 = MARGIN, WIDTH - MARGIN           # tile columns 16..424
CX = WIDTH // 2
CARD_R = 28                               # tile corner radius
PANEL_R = 32                              # laser panel corner radius

# Header
HEAD_Y0 = 16
ICON_BTN, ICON_BTN_R = 56, 20             # refresh / plug buttons
TITLE_Y = HEAD_Y0 + 18
SUBTITLE_Y = HEAD_Y0 + 42

# Tiles
TILE_H = 96
VALUE_DY = 46                             # value's centre line, below the tile top
CAPTION_DY = 74                           # caption's centre line
GLYPH, GLYPH_D = 20, 18                   # tile glyph size and inset from the corner
CONN_Y0 = HEAD_Y0 + ICON_BTN + 16         # 88
CONN_Y1 = CONN_Y0 + TILE_H                # 184
MODE_Y0 = CONN_Y1 + GAP                   # 192
MODE_Y1 = MODE_Y0 + TILE_H                # 288
MODE_W = (X1 - X0 - GAP) // 2             # 200
POWER_Y0 = MODE_Y1 + GAP                  # 296
POWER_Y1 = POWER_Y0 + TILE_H              # 392

# Connection card, right half: Connect / Disconnect pill and status line
CONN_BTN_W, CONN_BTN_H = 144, 38
CONN_BTN_DY = 21                          # pill top, below the card top
CONN_STATUS_DY = 75                       # status line centre

# Power tile: the flat area behind the Entry, and Apply
FIELD: Rect = (56, POWER_Y0 + 26, 292, POWER_Y0 + 62)
FIELD_R = 18
APPLY_W, APPLY_H = 88, 38

# Bottom: readback bar, message line, laser panel
BAR_Y1 = HEIGHT - MARGIN                  # 696
BAR_Y0 = BAR_Y1 - 64                      # 632
BAR_ITEM_W = 120
MSG_Y = BAR_Y0 - 16                       # 616
LASER_Y1 = MSG_Y - 16                     # 600
LASER_Y0 = LASER_Y1 - 184                 # 416
LASER_TITLE_Y = LASER_Y0 + 32
LASER_SUB_Y = LASER_Y0 + 56
LASER_BTN, LASER_BTN_R = 96, 26
LASER_CY = LASER_Y0 + 72 + LASER_BTN // 2  # 536

# Background glow
GLOW_CENTER, GLOW_RADIUS = (CX, CONN_Y1 + 8), (200, 230)

# Modes, in tile order (Camera | Manual), and their glyphs
MODES = [Mode.CAMERA, Mode.MANUAL]
MODE_ICONS = {Mode.CAMERA: "camera", Mode.MANUAL: "slider"}

# Rectangles reused by the scene and the widgets
CONN_CARD: Rect = (X0, CONN_Y0, X1, CONN_Y1)
MODE_CARDS: dict[Mode, Rect] = {
    Mode.CAMERA: (X0, MODE_Y0, X0 + MODE_W, MODE_Y1),
    Mode.MANUAL: (X1 - MODE_W, MODE_Y0, X1, MODE_Y1),
}
POWER_CARD: Rect = (X0, POWER_Y0, X1, POWER_Y1)
LASER_PANEL: Rect = (X0, LASER_Y0, X1, LASER_Y1)
SCENE_DIVIDERS = [(CX, CONN_Y0 + 28, CONN_Y1 - 28)]   # between the connection card's halves


def scene_cards(manual: bool) -> list[tuple[Rect, int, str]]:
    """The tiles and panels of the background as ``(box, radius, kind)`` for ``render_scene``.

    Args:
        manual: True to include the Power tile (Manual mode only).
    """
    cards = [(CONN_CARD, CARD_R, "card")] + [(MODE_CARDS[m], CARD_R, "card") for m in MODES]
    if manual:
        cards.append((POWER_CARD, CARD_R, "card"))
    cards.append((LASER_PANEL, PANEL_R, "panel"))
    return cards


def scene_flats(manual: bool) -> list[tuple[Rect, int]]:
    """The flat areas of the background (the power field, Manual only) for ``render_scene``."""
    return [(FIELD, FIELD_R)] if manual else []
