"""Pillow-rendered artwork: soft (neumorphic) shapes, the power dial and icons.

Tk's canvas cannot draw blurred shadows, gradients or anti-aliased curves, so
every visual with depth is drawn here as an RGBA image and placed on the
canvas with ``create_image``. Images are drawn at twice the device size and
downsampled for smooth edges, then cached: the whole UI needs a few dozen.

Coordinates passed in are *logical* pixels; :class:`Art` scales them.
"""

from __future__ import annotations

import math
from collections import OrderedDict
from dataclasses import dataclass

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps, ImageTk

from laser_control.ui import theme as T

SS = 2
"""Supersampling factor."""

DIAL_CACHE_SIZE = 96
"""Dial images are keyed per 0.1 mW; keep only the most recent ones (each is ~0.1-0.4 MB)."""

# style -> (shadow offset, blur), logical px. Light comes from the top left.
_STYLES = {
    "raise": (6, 14),
    "raise_sm": (3, 7),
    "press": (3, 7),
    "press_sm": (2, 5),
    "flat": (0, 0),
}


@dataclass(frozen=True)
class Sprite:
    """A cached image plus how far its shadow extends past the shape.

    Place it with ``create_image(x - pad, y - pad, anchor="nw")`` where
    ``(x, y)`` is the shape's top-left corner in device pixels.
    """

    photo: ImageTk.PhotoImage
    pad: int


@dataclass(frozen=True)
class Glow:
    """An outer glow: colour, offset and blur in logical px."""

    color: str
    dx: float = 0
    dy: float = 0
    blur: float = 14


@dataclass(frozen=True)
class Ring:
    """A solid outline drawn just outside the shape."""

    color: str
    width: float


class Art:
    """Factory and cache for every image the window uses.

    Args:
        root: Tk root; ``PhotoImage`` objects belong to it.
        scale: Logical-to-device pixel factor (see :func:`theme.ui_scale`).
    """

    def __init__(self, root, scale: float):
        self.root = root
        self.scale = scale
        self._cache: dict[tuple, Sprite] = {}
        self._dials: OrderedDict[tuple, Sprite] = OrderedDict()

    def px(self, v: float) -> int:
        """Logical to device pixels."""
        return round(v * self.scale)

    # ---- public factories ----

    def soft(self, w: float, h: float, r: float, style: str = "raise", *, fill: str = T.BASE,
             gradient: tuple[str, str] | None = None, ring: Ring | None = None,
             glow: Glow | None = None) -> Sprite:
        """A rounded rectangle (or circle when ``r == w / 2 == h / 2``) with soft depth.

        Args:
            w, h, r: Size and corner radius, logical px.
            style: ``raise``, ``raise_sm`` (light from top-left, shadow bottom-right),
                ``press``, ``press_sm`` (inner shadows: the shape looks sunk in),
                or ``flat``.
            fill: Solid fill colour.
            gradient: ``(start, end)`` colours of a 135° gradient, replacing ``fill``.
            ring: Optional outline just outside the shape.
            glow: Optional coloured outer glow (amber pills, emission).
        """
        key = ("soft", w, h, r, style, fill, gradient, ring, glow)
        if key not in self._cache:
            self._cache[key] = self._sprite(self._draw_soft(w, h, r, style, fill, gradient, ring, glow))
        return self._cache[key]

    def icon(self, name: str, size: float, color: str, stroke: float = 1.75) -> Sprite:
        """A line icon from :data:`ICONS`, drawn on a 24-unit grid."""
        key = ("icon", name, size, color, stroke)
        if key not in self._cache:
            self._cache[key] = self._sprite((_draw_icon(name, size * self.scale, color, stroke), 0))
        return self._cache[key]

    def dial(self, value: float, max_mw: float, nom_mw: float | None, on: bool) -> Sprite:
        """The power dial: a 270° arc lit amber up to ``value``, with a knob.

        Args:
            value: Current field value, mW.
            max_mw: Full-scale value (the laser's maximum).
            nom_mw: Nominal power: a tick, and a red zone from here to max.
            on: Connected; when False the dial is drawn flat and grey.
        """
        key = (round(value, 1), max_mw, nom_mw, on)
        if key in self._dials:
            self._dials.move_to_end(key)
            return self._dials[key]
        sprite = self._sprite((self._draw_dial(value, max_mw, nom_mw, on), 0))
        self._dials[key] = sprite
        while len(self._dials) > DIAL_CACHE_SIZE:
            # Evicting deletes the Tk image. The dial on screen is always the newest
            # entry, so it is never the one evicted.
            self._dials.popitem(last=False)
        return sprite

    # ---- drawing ----

    def _sprite(self, img_pad: tuple[Image.Image, int]) -> Sprite:
        img, pad = img_pad
        return Sprite(ImageTk.PhotoImage(img, master=self.root), pad)

    def _draw_soft(self, w, h, r, style, fill, gradient, ring, glow) -> tuple[Image.Image, int]:
        k = self.scale * SS
        off, blur = _STYLES[style]
        extra = max((ring.width if ring else 0), (glow.blur + max(abs(glow.dx), abs(glow.dy)) if glow else 0))
        pad_l = math.ceil(max(off + blur, extra) + 2)
        P = math.ceil(pad_l * k)
        W, H, R = round(w * k), round(h * k), round(r * k)
        size = (W + 2 * P, H + 2 * P)

        mask = Image.new("L", size, 0)
        ImageDraw.Draw(mask).rounded_rectangle((P, P, P + W - 1, P + H - 1), radius=R, fill=255)
        out = Image.new("RGBA", size, (0, 0, 0, 0))

        if glow:
            out = Image.alpha_composite(out, _shadow(mask, glow.color, glow.dx * k, glow.dy * k, glow.blur * k / 2))
        if style in ("raise", "raise_sm"):
            out = Image.alpha_composite(out, _shadow(mask, T.SH_DARK, off * k, off * k, blur * k / 2))
            out = Image.alpha_composite(out, _shadow(mask, T.SH_LIGHT, -off * k, -off * k, blur * k / 2))
        if ring:
            grow = ring.width * k
            outer = Image.new("L", size, 0)
            ImageDraw.Draw(outer).rounded_rectangle(
                (P - grow, P - grow, P + W - 1 + grow, P + H - 1 + grow), radius=R + grow, fill=255)
            band = ImageChops.subtract(outer, mask)
            out = Image.alpha_composite(out, _colored(band, ring.color))

        body = _gradient(size, *gradient) if gradient else Image.new("RGBA", size, T.rgba(fill))
        body.putalpha(mask)
        out = Image.alpha_composite(out, body)

        if style in ("press", "press_sm"):
            out = Image.alpha_composite(out, _inner_shadow(mask, T.SH_DARK, off * k, blur * k / 2))
            out = Image.alpha_composite(out, _inner_shadow(mask, T.SH_LIGHT, -off * k, blur * k / 2))

        out = out.resize((size[0] // SS, size[1] // SS), Image.LANCZOS)
        return out, P // SS

    def _draw_dial(self, value: float, max_mw: float, nom_mw: float | None, on: bool) -> Image.Image:
        k = self.scale * SS
        D = round(152 * k)
        c, r, width = D / 2, 63 * k, 10 * k
        a0, sweep = 135.0, 270.0

        def ang(v: float) -> float:
            return a0 + sweep * max(0.0, min(1.0, v / max_mw if max_mw else 0.0))

        img = Image.new("RGBA", (D, D), (0, 0, 0, 0))
        img = Image.alpha_composite(img, _arc_layer(D, c, r, width, a0, a0 + sweep, T.AMBER_TRACK))
        if on and nom_mw is not None and nom_mw < max_mw:
            zone = _arc_layer(D, c, r, width, ang(nom_mw), a0 + sweep, T.WARN_ZONE)
            zone.putalpha(zone.getchannel("A").point(lambda a: int(a * 0.55)))
            img = Image.alpha_composite(img, zone)
        a = ang(value)
        if on and value > 0:
            arc_mask = _arc_layer(D, c, r, width, a0, a, "#FFFFFF").getchannel("A")
            lit = _gradient((D, D), T.AMBER_1, T.AMBER_2)
            glow = lit.copy()
            glow.putalpha(arc_mask.filter(ImageFilter.GaussianBlur(3 * k)).point(lambda v: int(v * 0.6)))
            lit.putalpha(arc_mask)
            img = Image.alpha_composite(img, glow)
            img = Image.alpha_composite(img, lit)
        if on and nom_mw is not None:
            t = math.radians(ang(nom_mw))
            p1 = (c + (r - 9 * k) * math.cos(t), c + (r - 9 * k) * math.sin(t))
            p2 = (c + (r + 9 * k) * math.cos(t), c + (r + 9 * k) * math.sin(t))
            d = ImageDraw.Draw(img)
            d.line([p1, p2], fill=T.TEXT_2, width=round(2 * k))
            for p in (p1, p2):
                d.ellipse((p[0] - k, p[1] - k, p[0] + k, p[1] + k), fill=T.TEXT_2)
        # knob with a soft drop shadow
        t = math.radians(a)
        kx, ky, kr = c + r * math.cos(t), c + r * math.sin(t), 10 * k
        knob = Image.new("L", (D, D), 0)
        ImageDraw.Draw(knob).ellipse((kx - kr, ky - kr, kx + kr, ky + kr), fill=255)
        img = Image.alpha_composite(img, _shadow(knob, "#9E8E778C", 1.5 * k, 2 * k, 2 * k))
        body = Image.new("RGBA", (D, D), T.rgba("#FFFDF7" if on else T.BASE))
        body.putalpha(knob)
        img = Image.alpha_composite(img, body)
        return img.resize((D // SS, D // SS), Image.LANCZOS)


# ---- helpers ----

def _colored(alpha: Image.Image, color: str) -> Image.Image:
    r, g, b, a = T.rgba(color)
    layer = Image.new("RGBA", alpha.size, (r, g, b, 0))
    layer.putalpha(alpha.point(lambda v: v * a // 255))
    return layer


def _shift(mask: Image.Image, dx: float, dy: float) -> Image.Image:
    moved = Image.new("L", mask.size, 0)
    moved.paste(mask, (round(dx), round(dy)))
    return moved


def _shadow(mask: Image.Image, color: str, dx: float, dy: float, sigma: float) -> Image.Image:
    alpha = _shift(mask, dx, dy)
    if sigma > 0:
        alpha = alpha.filter(ImageFilter.GaussianBlur(sigma))
    return _colored(alpha, color)


def _inner_shadow(mask: Image.Image, color: str, offset: float, sigma: float) -> Image.Image:
    # Shift the shape, invert it (so the edge strip it uncovered is solid),
    # blur, then keep only what falls inside the original shape.
    outside = ImageOps.invert(_shift(mask, offset, offset)).filter(ImageFilter.GaussianBlur(sigma))
    return _colored(ImageChops.multiply(outside, mask), color)


def _gradient(size: tuple[int, int], start: str, end: str) -> Image.Image:
    """135° linear gradient: ``start`` at top-left, ``end`` at bottom-right."""
    ramp = Image.linear_gradient("L")
    vertical = ramp.resize(size)
    horizontal = ramp.rotate(90).resize(size)
    t = ImageChops.add(horizontal, vertical, scale=2.0)
    return Image.composite(Image.new("RGBA", size, T.rgba(end)), Image.new("RGBA", size, T.rgba(start)), t)


def _arc_layer(D: int, c: float, r: float, width: float, start: float, end: float, color: str) -> Image.Image:
    """A thick arc with round caps (angles in degrees, clockwise from 3 o'clock)."""
    layer = Image.new("RGBA", (D, D), (0, 0, 0, 0))
    if end - start <= 0.01:
        return layer
    d = ImageDraw.Draw(layer)
    rr = r + width / 2  # Pillow draws the stroke inward from the bounding box
    d.arc((c - rr, c - rr, c + rr, c + rr), start, end, fill=color, width=round(width))
    for a in (start, end):
        t = math.radians(a)
        x, y = c + r * math.cos(t), c + r * math.sin(t)
        d.ellipse((x - width / 2, y - width / 2, x + width / 2, y + width / 2), fill=color)
    return layer


# ---- icons: simple line drawings on a 24-unit grid (like SVG icons) ----
# ("line", [(x, y), ...]) open polyline   ("poly", [...]) closed polyline
# ("circle", cx, cy, r)                    ("arc", cx, cy, r, start, end) clockwise degrees
# ("dot", x, y)                            filled dot the size of the stroke
ICONS: dict[str, list[tuple]] = {
    "refresh": [("arc", 12, 12, 8, 0, 315), ("line", [(20, 4), (20, 9), (15, 9)])],
    "plug": [("line", [(9, 3), (9, 8)]), ("line", [(15, 3), (15, 8)]),
             ("line", [(6, 11), (6, 8), (18, 8), (18, 11)]), ("arc", 12, 11, 6, 0, 180),
             ("line", [(12, 17), (12, 21)])],
    "camera": [("poly", [(4, 8), (7, 8), (9, 5), (15, 5), (17, 8), (20, 8), (20, 19), (4, 19)]),
               ("circle", 12, 13, 3.5)],
    "sliders": [("line", [(5, 4), (5, 11)]), ("line", [(5, 15), (5, 20)]), ("line", [(12, 4), (12, 6)]),
                ("line", [(12, 10), (12, 20)]), ("line", [(19, 4), (19, 13)]), ("line", [(19, 17), (19, 20)]),
                ("circle", 5, 13, 2), ("circle", 12, 8, 2), ("circle", 19, 15, 2)],
    "power": [("line", [(12, 3), (12, 11)]), ("arc", 12, 12, 8, -42.4, 222.4)],
    "warn": [("poly", [(12, 4), (2.5, 20), (21.5, 20)]), ("line", [(12, 10), (12, 14.5)]), ("dot", 12, 17.5)],
    "info": [("circle", 12, 12, 9), ("line", [(12, 11), (12, 16)]), ("dot", 12, 8)],
    "chev": [("line", [(7, 10), (12, 15), (17, 10)])],
    "check": [("line", [(5, 12.5), (9.5, 17), (19, 7.5)])],
    "minus": [("line", [(6, 12), (18, 12)])],
    "plus": [("line", [(12, 6), (12, 18)]), ("line", [(6, 12), (18, 12)])],
    "x": [("line", [(6, 6), (18, 18)]), ("line", [(18, 6), (6, 18)])],
}


def _draw_icon(name: str, size_px: float, color: str, stroke: float) -> Image.Image:
    k = 4
    S = max(1, round(size_px * k))
    u = S / 24
    w = stroke * u
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    def cap(x: float, y: float, radius: float = w / 2) -> None:
        d.ellipse((x - radius, y - radius, x + radius, y + radius), fill=color)

    for op in ICONS[name]:
        kind = op[0]
        if kind in ("line", "poly"):
            pts = [(x * u, y * u) for x, y in op[1]]
            if kind == "poly":
                pts.append(pts[0])
            d.line(pts, fill=color, width=round(w), joint="curve")
            for x, y in pts:
                cap(x, y)
        elif kind == "circle":
            _, cx, cy, r = op
            rr = r * u + w / 2
            d.ellipse((cx * u - rr, cy * u - rr, cx * u + rr, cy * u + rr), outline=color, width=round(w))
        elif kind == "arc":
            _, cx, cy, r, a1, a2 = op
            rr = r * u + w / 2
            d.arc((cx * u - rr, cy * u - rr, cx * u + rr, cy * u + rr), a1, a2, fill=color, width=round(w))
            for a in (a1, a2):
                t = math.radians(a)
                cap(cx * u + r * u * math.cos(t), cy * u + r * u * math.sin(t))
        elif kind == "dot":
            cap(op[1] * u, op[2] * u, w * 0.62)
    return img.resize((S // k, S // k), Image.LANCZOS)
