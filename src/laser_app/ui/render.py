"""Pillow rendering for the Laser Control theme (no Tk; testable without a display).

Every function is pure: it takes sizes, colours and a state name and returns a
new Pillow image (or paints into one it is given). ``widgets.Images`` turns the
results into ``ImageTk.PhotoImage`` objects once and caches them per state.

Tk widgets cannot be translucent, so the window is one ``tk.Canvas``:

* ``render_background`` + ``render_scene`` build the opaque base image: the
  gradient and glow with the tiles composited on top, so the glow tints them;
* ``render_wash`` builds translucent tile overlays (hover / pressed /
  selected) and the other ``render_*`` functions build an RGBA image for each
  state of a control (``"normal"``, ``"hover"``, ``"pressed"``, ``"disabled"``).

Shapes are drawn as masks at ``SS`` times the final size and downsampled with
LANCZOS, so curves stay smooth. Control images carry a transparent margin of
``M`` pixels (``LASER_MARGIN`` for the laser button) so shadows and glows are
not clipped; place them at ``(x - M, y - M)``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Iterable, Optional

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageStat

from .theme import (ACCENT, ACTIVE, BG_BOTTOM, BG_MID, BG_TOP, BUTTON, GLOW, GLOW_PEAK,
                    LASER_MARGIN, SURFACES, TEXT_3, M)

SS = 3                        # supersampling factor for every shape
RGB = tuple[int, int, int]
Box = tuple[float, float, float, float]   # (x0, y0, x1, y1), x1/y1 exclusive
SHADOW = (8, 8, 14)           # tint of every drop shadow
WHITE = (255, 255, 255)


# ==========================================================================
# Colour helpers
# ==========================================================================
def hex_to_rgb(h: str) -> RGB:
    """Convert ``"#RRGGBB"`` to an ``(r, g, b)`` tuple."""
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def rgb_to_hex(c: Iterable[float]) -> str:
    """Convert an ``(r, g, b)`` tuple (floats allowed, clamped) to ``"#RRGGBB"``."""
    return "#%02X%02X%02X" % tuple(max(0, min(255, round(v))) for v in c)


def _mix(c, target, t) -> tuple[int, ...]:
    return tuple(round(x + (y - x) * t) for x, y in zip(c, target))


def _lighten(c, t) -> tuple[int, ...]:
    return _mix(c, WHITE, t)


def _darken(c, t) -> tuple[int, ...]:
    return _mix(c, (0, 0, 0), t)


def _tint(color: str, state: str, hover: float, pressed: float) -> tuple[int, ...]:
    """``color`` lightened by ``hover`` in the hover state, darkened by ``pressed`` when pressed."""
    base = hex_to_rgb(color)
    if state == "hover":
        return _lighten(base, hover)
    if state == "pressed":
        return _darken(base, pressed)
    return base


# ==========================================================================
# Mask and layer primitives
# ==========================================================================
Painter = Callable[[ImageDraw.ImageDraw, int], None]


def _mask(size, draw: Painter) -> Image.Image:
    """An antialiased L mask: ``draw(d, s)`` paints at s-times scale, then LANCZOS down."""
    w, h = size
    m = Image.new("L", (round(w) * SS, round(h) * SS), 0)
    draw(ImageDraw.Draw(m), SS)
    return m.resize((round(w), round(h)), Image.LANCZOS)


def _rr(box: Box, r: float) -> Painter:
    """Mask painter for a rounded rectangle (box in final pixels, exclusive end)."""
    x0, y0, x1, y1 = box
    r = max(0.0, min(r, (x1 - x0) / 2, (y1 - y0) / 2))

    def paint(d, s):
        d.rounded_rectangle([x0 * s, y0 * s, x1 * s - 1, y1 * s - 1], radius=r * s, fill=255)
    return paint


def _ellipse(box: Box) -> Painter:
    """Mask painter for an ellipse filling ``box``."""
    x0, y0, x1, y1 = box

    def paint(d, s):
        d.ellipse([x0 * s, y0 * s, x1 * s - 1, y1 * s - 1], fill=255)
    return paint


def _ring(size, box: Box, r: float, width: float) -> Image.Image:
    """A ``width``-px stroke just inside the rounded rectangle ``box``."""
    x0, y0, x1, y1 = box
    inner = (x0 + width, y0 + width, x1 - width, y1 - width)
    return ImageChops.subtract(_mask(size, _rr(box, r)), _mask(size, _rr(inner, max(0, r - width))))


def _vgrad(size, top: float, bottom: float, y0: float = 0.0, y1: Optional[float] = None) -> Image.Image:
    """L image, value ``top`` at row y0 to ``bottom`` at row y1 (clamped outside)."""
    w, h = size
    y1 = h if y1 is None else y1
    col = []
    for y in range(h):
        t = 0.0 if y1 <= y0 else min(1.0, max(0.0, (y + 0.5 - y0) / (y1 - y0)))
        col.append(round(top + (bottom - top) * t))
    g = Image.new("L", (1, h))
    g.putdata(col)
    return g.resize((w, h))


def _layer(size, rgb, alpha_mask: Image.Image, opacity: float = 1.0) -> Image.Image:
    """Solid colour layer whose alpha is ``alpha_mask * opacity``."""
    img = Image.new("RGBA", size, tuple(rgb) + (0,))
    if opacity < 1.0:
        alpha_mask = alpha_mask.point(lambda v: round(v * opacity))
    img.putalpha(alpha_mask)
    return img


def _vfill(size, top_rgba, bottom_rgba, y0: float = 0, y1: Optional[float] = None) -> Image.Image:
    """RGBA vertical gradient from ``top_rgba`` at row y0 to ``bottom_rgba`` at row y1."""
    return Image.merge("RGBA", [_vgrad(size, top_rgba[i], bottom_rgba[i], y0, y1) for i in range(4)])


def _clip(img: Image.Image, mask: Image.Image) -> Image.Image:
    """Multiply ``img``'s alpha by ``mask`` (in place) and return it."""
    img.putalpha(ImageChops.multiply(img.getchannel("A"), mask))
    return img


def _paste(img: Image.Image, layer: Image.Image, x: int, y: int) -> None:
    """``alpha_composite`` that accepts a layer partly outside ``img`` (it is cropped)."""
    sx, sy = max(0, -x), max(0, -y)
    if sx >= layer.width or sy >= layer.height:
        return
    img.alpha_composite(layer, (max(0, x), max(0, y)), (sx, sy))


def _shadow(img: Image.Image, box: Box, r: float, rgb, opacity: float, blur: float, dy: float,
            spread: float = 0.0) -> None:
    """Composite a blurred, offset copy of the rounded rectangle ``box`` into ``img``.

    Only the region around the box is rendered, so this is cheap on big images.
    """
    pad = math.ceil(3 * blur + abs(spread)) + 2
    x0, y0, x1, y1 = box
    ox, oy = math.floor(x0) - pad, math.floor(y0 + dy) - pad
    size = (math.ceil(x1 - x0) + 2 * pad + 1, math.ceil(y1 - y0) + 2 * pad + 1)
    local = (x0 - ox - spread, y0 + dy - oy - spread, x1 - ox + spread, y1 + dy - oy + spread)
    m = _mask(size, _rr(local, r + spread))
    if blur:
        m = m.filter(ImageFilter.GaussianBlur(blur))
    _paste(img, _layer(size, rgb, m, opacity), ox, oy)


def _paste_glyph(img: Image.Image, name: str, size: int, color: str, center: float,
                 pressed: bool) -> None:
    """Draw glyph ``name`` centred at (``center``, ``center``); it sinks 1 px when pressed."""
    off = round(center - size / 2)
    img.alpha_composite(render_icon(name, size, color), (off, off + (1 if pressed else 0)))


def render_shape(w: int, h: int, r: float, fill_top, fill_bottom, *, border=None,
                 shadows=()) -> Image.Image:
    """A pill / rounded rect with soft shadows, a gradient fill and a 1 px inner border.

    Args:
        w, h, r: shape size and corner radius; the image is ``M`` px larger on every side.
        fill_top, fill_bottom: RGBA tuples of the vertical fill gradient.
        border: ``(rgb, top_alpha, bottom_alpha)`` for the inner hairline, or None.
        shadows: iterable of ``(rgb, opacity, blur, dy, spread)``.
    """
    size = (w + 2 * M, h + 2 * M)
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    box = (M, M, M + w, M + h)
    for rgb, opacity, blur, dy, spread in shadows:
        _shadow(img, box, r, rgb, opacity, blur, dy, spread)
    shape = _mask(size, _rr(box, r))
    img.alpha_composite(_clip(_vfill(size, fill_top, fill_bottom, box[1], box[3]), shape))
    if border:
        rgb, top, bottom = border
        g = _vgrad(size, 255 * top, 255 * bottom, box[1], box[3])
        img.alpha_composite(_layer(size, rgb, ImageChops.multiply(g, _ring(size, box, r, 1))))
    return img


# ==========================================================================
# Background and tiles
# ==========================================================================
def render_background(w: int, h: int, glow_center: tuple[float, float],
                      glow_radius: tuple[float, float], noise: float = 2.2) -> Image.Image:
    """The window background: a dark vertical gradient with a soft warm radial glow.

    Args:
        glow_center: ``(x, y)`` of the glow's centre, in pixels.
        glow_radius: ``(rx, ry)``: where the glow has faded to about 20 %.
        noise: strength of the random dither that hides banding (0: none, for tests).

    Returns:
        An RGB image of size ``(w, h)``, with a little noise against banding.
    """
    top, mid, bottom = (hex_to_rgb(c) for c in (BG_TOP, BG_MID, BG_BOTTOM))
    col = []
    for y in range(h):
        t = y / max(1, h - 1)
        col.append(_mix(top, mid, t / 0.5) if t < 0.5 else _mix(mid, bottom, (t - 0.5) / 0.5))
    g = Image.new("RGB", (1, h))
    g.putdata(col)
    img = g.resize((w, h)).convert("RGBA")
    # Gaussian glow, computed on a coarse grid and scaled up (it is very smooth).
    s = 4
    sw, sh = w // s + 1, h // s + 1
    cx, cy = glow_center
    rx, ry = glow_radius
    data = []
    for j in range(sh):
        dy = (j * s - cy) / ry
        for i in range(sw):
            dx = (i * s - cx) / rx
            data.append(round(255 * GLOW_PEAK * math.exp(-1.6 * (dx * dx + dy * dy))))
    glow = Image.new("L", (sw, sh))
    glow.putdata(data)
    glow = glow.resize((sw * s, sh * s), Image.BICUBIC).crop((0, 0, w, h))
    img.alpha_composite(_layer((w, h), hex_to_rgb(GLOW), glow))
    if not noise:
        return img.convert("RGB")
    dither = Image.effect_noise((w, h), noise).convert("RGB")
    return ImageChops.add(img.convert("RGB"), dither, 1.0, -128)


def paint_card(scene: Image.Image, box: tuple[int, int, int, int], r: int, kind: str = "card") -> None:
    """Composite one translucent tile or panel into ``scene`` (RGBA, modified in place).

    Args:
        box: integer bounds ``(x0, y0, x1, y1)``.
        r: corner radius.
        kind: a key of ``SURFACES`` (``"card"`` or ``"panel"``).
    """
    x0, y0, x1, y1 = box
    local = (x1 - x0, y1 - y0)
    tint, opacity = SURFACES[kind]
    _shadow(scene, box, r, SHADOW, 0.20, 14, 8, -6)
    shape = _mask(local, _rr((0, 0) + local, r))
    scene.alpha_composite(_layer(local, hex_to_rgb(tint), shape, opacity), (x0, y0))
    # A very faint lighter edge, strongest at the top.
    g = _vgrad(local, 255 * 0.07, 255 * 0.02, 0, local[1])
    ring = _ring(local, (0, 0) + local, r, 1)
    scene.alpha_composite(_layer(local, WHITE, ImageChops.multiply(ring, g)), (x0, y0))


def paint_divider(scene: Image.Image, x: int, y0: int, y1: int) -> None:
    """A faint 1 px vertical divider at column ``x`` that fades out at both ends."""
    h = y1 - y0
    col = [round(255 * 0.08 * math.sin(math.pi * (y + 0.5) / h)) for y in range(h)]
    a = Image.new("L", (1, h))
    a.putdata(col)
    scene.alpha_composite(_layer((1, h), WHITE, a), (x, y0))


def flatten(scene: Image.Image, box: tuple[int, int, int, int], r: int, feather: int = 12) -> str:
    """Paint a rounded area of ``scene`` in its own average colour and return that colour.

    Used under the power ``tk.Entry``, whose background must be one opaque
    colour. ``box`` becomes exactly that colour; the flat paint then fades out
    over ``feather`` pixels around it, so the tile's glow gradient has no hard edge.
    """
    x0, y0, x1, y1 = box
    color = rgb_to_hex(ImageStat.Stat(scene.crop(box).convert("RGB")).mean)
    f = feather
    local = (x1 - x0 + 2 * f, y1 - y0 + 2 * f)
    core = _mask(local, _rr((f, f, f + x1 - x0, f + y1 - y0), r))
    soft = _mask(local, _rr((f / 2, f / 2, local[0] - f / 2, local[1] - f / 2), r + f / 2))
    soft = ImageChops.lighter(core, soft.filter(ImageFilter.GaussianBlur(f / 3)))
    _paste(scene, _layer(local, hex_to_rgb(color), soft), x0 - f, y0 - f)
    return color


def render_scene(background: Image.Image,
                 cards: Iterable[tuple[tuple[int, int, int, int], int, str]],
                 dividers: Iterable[tuple[int, int, int]] = (),
                 flats: Iterable[tuple[tuple[int, int, int, int], int]] = ()
                 ) -> tuple[Image.Image, list[str]]:
    """The opaque base image: ``background`` with tiles, dividers and flat areas on top.

    Args:
        cards: ``(box, radius, kind)`` for each tile or panel, painted in order
            (see ``paint_card``).
        dividers: ``(x, y0, y1)`` for each divider (see ``paint_divider``).
        flats: ``(box, radius)`` areas to paint flat (see ``flatten``).

    Returns:
        ``(image, colours)``: an opaque RGB image the size of ``background`` and
        the colour of each flat area, in order.
    """
    scene = background.convert("RGBA")
    for box, r, kind in cards:
        paint_card(scene, box, r, kind)
    for x, y0, y1 in dividers:
        paint_divider(scene, x, y0, y1)
    colors = [flatten(scene, box, r) for box, r in flats]
    return scene.convert("RGB"), colors


# ==========================================================================
# Controls (each returns an RGBA image with an M-px margin unless noted)
# ==========================================================================
def render_wash(w: int, h: int, r: float, color: str, opacity: float,
                clip: Optional[tuple[int, int]] = None) -> Image.Image:
    """Translucent overlay shaped like a ``w`` x ``h`` tile (no margin).

    Lightens or darkens a tile for hover / pressed / selected states, and draws
    the lighter rounded rect of an active bar item.

    Args:
        clip: ``(x0, x1)`` to keep only those columns (e.g. one half of a split
            tile); the returned image is then ``x1 - x0`` wide.
    """
    img = _layer((w, h), hex_to_rgb(color), _mask((w, h), _rr((0, 0, w, h), r)), opacity)
    return img.crop((clip[0], 0, clip[1], h)) if clip else img


def render_dot(size: int, color: str) -> Image.Image:
    """An antialiased filled circle, ``size`` px (status dots; no margin)."""
    return _layer((size, size), hex_to_rgb(color), _mask((size, size), _ellipse((0, 0, size, size))))


def render_ring(w: int, h: int, r: float, color: str, opacity: float, width: float = 2) -> Image.Image:
    """A ``width``-px ring hugging the outside of a ``w`` x ``h`` rounded rect (focus / error)."""
    size = (w + 2 * M, h + 2 * M)
    box = (M - width, M - width, M + w + width, M + h + width)
    return _layer(size, hex_to_rgb(color), _ring(size, box, r + width, width), opacity)


def render_icon_button(size: int, r: float, icon: str, icon_color: str, state: str,
                       icon_size: int = 24) -> Image.Image:
    """Dark rounded-square button with a centred glyph (header buttons).

    Args:
        icon: a key of ``ICONS``.
        state: ``"normal"``, ``"hover"``, ``"pressed"`` or ``"disabled"``.
    """
    base = _tint(BUTTON, state, 0.07, 0.18)
    alpha = 170 if state == "disabled" else 255
    shadows = [] if state in ("pressed", "disabled") else [(SHADOW, 0.30, 8, 4, -2)]
    img = render_shape(size, size, r, _lighten(base, 0.03) + (alpha,), base + (alpha,),
                       border=(WHITE, 0.08, 0.02), shadows=shadows)
    off = M + (size - icon_size) // 2
    _paste_glyph(img, icon, icon_size, icon_color, off + icon_size / 2, state == "pressed")
    return img


@dataclass(frozen=True)
class PillStyle:
    """How one kind of pill button looks; see ``PILL_STYLES``.

    Attributes:
        color: base fill colour.
        hover, pressed: how much hover lightens and pressing darkens it.
        fill: ``(lighten_top, darken_bottom)`` of the vertical fill gradient.
        border: ``(top_alpha, bottom_alpha)`` of the white inner hairline.
        shadow: ``(opacity, blur, dy, spread)`` of the dark drop shadow.
        glow: ``(opacity, blur, spread)`` of a coloured glow under the pill, or None.
        glow_hover: the glow while hovered (None: same as ``glow``).
        glow_follows_state: the glow takes the hover / pressed colour (else the base colour).
    """

    color: str
    hover: float
    pressed: float
    fill: tuple[float, float]
    border: tuple[float, float]
    shadow: tuple[float, float, float, float]
    glow: Optional[tuple[float, float, float]] = None
    glow_hover: Optional[tuple[float, float, float]] = None
    glow_follows_state: bool = False


PILL_STYLES = {
    # Apply: orange, dark text.
    "accent": PillStyle(ACCENT, 0.10, 0.14, (0.08, 0.03), (0.30, 0.0), (0.25, 2, 1, 0),
                        glow=(0.28, 8, -2), glow_follows_state=True),
    # Connect: orange call to action with a clearer hover glow.
    "cta": PillStyle(ACCENT, 0.16, 0.14, (0.08, 0.03), (0.32, 0.0), (0.25, 2, 1, 0),
                     glow=(0.30, 8, -1), glow_hover=(0.55, 11, -1)),
    # Disconnect: dark secondary action.
    "dark": PillStyle(BUTTON, 0.08, 0.18, (0.04, 0.0), (0.16, 0.06), (0.32, 8, 3, -2)),
}


def render_pill(w: int, h: int, state: str, style: str = "accent") -> Image.Image:
    """A pill button in ``PILL_STYLES[style]``; every style is the same quiet grey pill when disabled.

    Args:
        state: ``"normal"``, ``"hover"``, ``"pressed"`` or ``"disabled"``.
        style: ``"accent"`` (Apply), ``"cta"`` (Connect) or ``"dark"`` (Disconnect).
    """
    r = h / 2
    if state == "disabled":
        c = hex_to_rgb(ACTIVE)
        return render_shape(w, h, r, c + (200,), c + (200,), border=(WHITE, 0.06, 0.02))
    s = PILL_STYLES[style]
    base = _tint(s.color, state, s.hover, s.pressed)
    shadows = []
    if state != "pressed":
        glow = s.glow_hover if (state == "hover" and s.glow_hover) else s.glow
        if glow:
            opacity, blur, spread = glow
            glow_rgb = base if s.glow_follows_state else hex_to_rgb(s.color)
            shadows.append((glow_rgb, opacity, blur, 3, spread))
        opacity, blur, dy, spread = s.shadow
        shadows.append((SHADOW, opacity, blur, dy, spread))
    top, bottom = s.fill
    return render_shape(w, h, r, _lighten(base, top) + (255,), _darken(base, bottom) + (255,),
                        border=(WHITE,) + s.border, shadows=shadows)


def render_laser_button(size: int, r: float, color: Optional[str], state: str,
                        glow: bool) -> Image.Image:
    """The big dark rounded-square on/off button with a coloured power symbol.

    Args:
        color: ``"#RRGGBB"`` of the symbol and inner glow, or None (grey, unavailable).
        state: ``"normal"``, ``"hover"`` or ``"pressed"``.
        glow: also draw a soft coloured glow around the square (laser on).

    Returns:
        RGBA image of ``size + 2 * LASER_MARGIN`` pixels square.
    """
    margin = LASER_MARGIN
    full = (size + 2 * margin,) * 2
    img = Image.new("RGBA", full, (0, 0, 0, 0))
    box = (margin, margin, margin + size, margin + size)
    base = _tint(BUTTON, state, 0.07, 0.18)
    pressed = state == "pressed"
    if color is not None and glow:
        _shadow(img, box, r, hex_to_rgb(color), {"hover": 0.42, "pressed": 0.22}.get(state, 0.32),
                12, 2, -4)
    if not pressed:
        _shadow(img, box, r, SHADOW, 0.35, 10, 6, -4)
    shape = _mask(full, _rr(box, r))
    img.alpha_composite(_clip(_vfill(full, _lighten(base, 0.04) + (255,), base + (255,),
                                     box[1], box[3]), shape))
    c = full[0] / 2
    if color is not None:   # soft coloured light inside the square, behind the symbol
        inner = _mask(full, _ellipse((c - size * 0.36, c - size * 0.36, c + size * 0.36, c + size * 0.36)))
        inner = inner.filter(ImageFilter.GaussianBlur(size * 0.14))
        img.alpha_composite(_layer(full, hex_to_rgb(color), ImageChops.multiply(inner, shape),
                                   0.16 if not pressed else 0.10))
    g = _vgrad(full, 255 * 0.09, 255 * 0.02, box[1], box[3])
    img.alpha_composite(_layer(full, WHITE, ImageChops.multiply(g, _ring(full, box, r, 1))))
    _paste_glyph(img, "power", round(size * 0.44), color or TEXT_3, c, pressed)
    return img


# ==========================================================================
# Icons: filled glyphs drawn on a 24-unit grid (no margin)
# ==========================================================================
def _round_line(d, pts, w):
    """Polyline of width ``w`` with round joints and caps."""
    d.line(pts, fill=255, width=round(w), joint="curve")
    for x, y in (pts[0], pts[-1]):
        d.ellipse([x - w / 2, y - w / 2, x + w / 2, y + w / 2], fill=255)


def _icon_refresh(d, u):
    cx = cy = 12 * u
    rr, w = 7.8 * u, 2.4 * u
    d.arc([cx - rr, cy - rr, cx + rr, cy + rr], start=-20, end=262, fill=255, width=round(w))
    ex, ey = cx - 0.9 * u, cy - rr + w / 2
    d.polygon([(ex + 5.1 * u, ey), (ex - 0.6 * u, ey - 4.6 * u), (ex - 0.6 * u, ey + 4.6 * u)], fill=255)


def _icon_plug(d, u):
    for x in (8.0, 13.6):                                        # prongs
        d.rounded_rectangle([x * u, 2.5 * u, (x + 2.4) * u, 9 * u], radius=1.2 * u, fill=255)
    d.polygon([(p[0] * u, p[1] * u) for p in
               [(5.5, 8), (18.5, 8), (18.5, 11.5), (15, 16.5), (9, 16.5), (5.5, 11.5)]], fill=255)
    d.rounded_rectangle([5.5 * u, 8 * u, 18.5 * u, 12.5 * u], radius=1.6 * u, fill=255)
    d.rounded_rectangle([10.8 * u, 15.5 * u, 13.2 * u, 22 * u], radius=1.2 * u, fill=255)   # cable


def _icon_camera(d, u):
    d.rounded_rectangle([2 * u, 6 * u, 16 * u, 18 * u], radius=3.5 * u, fill=255)
    d.polygon([(17 * u, 10.2 * u), (22 * u, 7 * u), (22 * u, 17 * u), (17 * u, 13.8 * u)], fill=255)


def _icon_slider(d, u):
    w = 2.2 * u
    for y, kx in ((7.5, 15.5), (16.5, 8.5)):
        _round_line(d, [(3 * u, y * u), (21 * u, y * u)], w)
        k = 3.4 * u
        d.ellipse([kx * u - k, y * u - k, kx * u + k, y * u + k], fill=255)


def _icon_bolt(d, u):
    d.polygon([(p[0] * u, p[1] * u) for p in
               [(13.8, 2), (4.5, 13.6), (11.2, 13.6), (9.8, 22), (19.5, 9.6), (12.8, 9.6)]], fill=255)


def _icon_gauge(d, u):
    w = 2.4 * u
    d.arc([3 * u, 4 * u, 21 * u, 22 * u], start=150, end=30, fill=255, width=round(w))
    _round_line(d, [(12 * u, 13 * u), (16.6 * u, 8.4 * u)], w)
    k = 2.6 * u
    d.ellipse([12 * u - k, 13 * u - k, 12 * u + k, 13 * u + k], fill=255)


def _icon_power(d, u):
    """IEC 5009 power symbol."""
    X, Y, S, W = 12 * u, 13 * u, 8.6 * u, 2.4 * u
    gap = 38   # half-gap at the top, degrees
    d.arc([X - S, Y - S, X + S, Y + S], start=-90 + gap, end=270 - gap, fill=255, width=round(W))
    for ang in (-90 + gap, 270 - gap):        # round caps
        a = math.radians(ang)
        px, py = X + (S - W / 2) * math.cos(a), Y + (S - W / 2) * math.sin(a)
        d.ellipse([px - W / 2, py - W / 2, px + W / 2, py + W / 2], fill=255)
    d.rounded_rectangle([X - W / 2, 2.2 * u, X + W / 2, 12.4 * u], radius=W / 2, fill=255)


def _icon_chevron(d, u):
    _round_line(d, [(7 * u, 9.5 * u), (12 * u, 14.5 * u), (17 * u, 9.5 * u)], 2.2 * u)


ICONS: dict[str, Callable[[ImageDraw.ImageDraw, float], None]] = {
    "refresh": _icon_refresh, "plug": _icon_plug, "camera": _icon_camera,
    "slider": _icon_slider, "bolt": _icon_bolt, "gauge": _icon_gauge,
    "power": _icon_power, "chevron": _icon_chevron,
}


def render_icon(name: str, size: int, color: str) -> Image.Image:
    """A ``size`` x ``size`` RGBA glyph from ``ICONS`` in ``color``."""
    painter = ICONS[name]
    return _layer((size, size), hex_to_rgb(color),
                  _mask((size, size), lambda d, s: painter(d, s * size / 24)))
