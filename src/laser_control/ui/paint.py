"""Shared drawing helpers and layout sizes, used by every file in ``sections/``.

Logical and device pixels
-------------------------
All sizes in the UI code are *logical* pixels: the window is designed 400 px
wide. On a high-DPI Windows screen, Tk works in *device* pixels, so a logical
size is multiplied by ``win.scale`` (for example 1.5 at 150 % scaling).
``win.art.px()`` does that conversion. The helpers below take logical pixels
and convert them, so the section files never have to.

Why "paint" and not "draw"
--------------------------
Each section file has a function called ``draw(win, y)``. A helper module
called ``draw`` would clash with that name, hence ``paint``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from laser_control.ui import theme as T
from laser_control.ui.art import Sprite

if TYPE_CHECKING:  # only for type hints; avoids a circular import at runtime
    from laser_control.ui.window import MainWindow

# ---- layout sizes shared by several sections (logical px) ----
PAD_X = 22                       # left and right margin of every card
CONTENT_W = T.WIDTH - 2 * PAD_X  # width of every card: 356
GAP = 15                         # vertical space between cards


def image(win: MainWindow, x: float, y: float, sprite: Sprite, tags: tuple[str, ...] = ()) -> int:
    """Place a sprite so its *shape* (not its shadow margin) starts at ``(x, y)``.

    Sprites from :mod:`art` include a margin around the shape for the soft
    shadow (``sprite.pad``). Subtracting it puts the shape itself at ``(x, y)``.
    A button's background (tag ending in ``.bg``) also has its position
    remembered, so its pressed / hover image can be swapped in at the same spot
    (see :meth:`ButtonLayer.show`).
    """
    for tag in tags:
        if tag.endswith(".bg"):
            win.buttons.remember_origin(tag, x, y)
    return win.canvas.create_image(win.art.px(x) - sprite.pad, win.art.px(y) - sprite.pad,
                                   image=sprite.photo, anchor="nw", tags=tags)


def icon(win: MainWindow, cx: float, cy: float, sprite: Sprite, tags: tuple[str, ...] = ()) -> int:
    """Place an icon (a sprite without shadow) centred on ``(cx, cy)``."""
    return win.canvas.create_image(win.art.px(cx), win.art.px(cy), image=sprite.photo,
                                   anchor="center", tags=tags)


def text(win: MainWindow, x: float, y: float, string: str, font, fill: str, anchor: str = "nw",
         tags: tuple[str, ...] = (), width: float | None = None) -> int:
    """Draw text at ``(x, y)``.

    Args:
        anchor: Which point of the text sits at ``(x, y)``: ``"nw"`` top left,
            ``"w"`` middle left, ``"e"`` middle right, ``"center"``, …
        width: Wrap the text onto more lines beyond this width (logical px).
    """
    wrap = {"width": win.art.px(width)} if width else {}
    return win.canvas.create_text(win.art.px(x), win.art.px(y), text=string, font=font, fill=fill,
                                  anchor=anchor, tags=tags, **wrap)


def hit_area(win: MainWindow, x: float, y: float, w: float, h: float, tags: tuple[str, ...],
             fill: str = T.BASE) -> None:
    """An invisible clickable rectangle, for buttons that are only text or icons.

    A canvas shape only receives clicks where it is filled, so it is filled
    with the colour underneath, which makes it invisible. Only use it over flat
    parts of a card, or it would hide the shading.
    """
    p = win.art.px
    win.canvas.create_rectangle(p(x), p(y), p(x + w), p(y + h), fill=fill, outline="", tags=tags)


def spinner(win: MainWindow, cx: float, cy: float, r: float, color: str) -> None:
    """A loading spinner: a grey ring with a coloured quarter arc.

    The arc is tagged ``spinner``; the window's animation tick turns it by
    changing its start angle, without a redraw.
    """
    p = win.art.px
    box = (p(cx - r), p(cy - r), p(cx + r), p(cy + r))
    win.canvas.create_oval(*box, outline=T.TEXT_OFF, width=max(1, p(2)))
    win.canvas.create_arc(*box, start=win.spin, extent=90, style="arc", outline=color,
                          width=max(1, p(2.2)), tags=("spinner",))


def text_width(win: MainWindow, string: str, font) -> float:
    """Width of ``string`` in ``font``, in logical px (for centring and right-aligning)."""
    return font.measure(string) / win.scale
