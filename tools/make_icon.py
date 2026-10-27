"""Render the app icon (resources/laser_control.*) with Pillow.

Run from the project folder: ``python tools/make_icon.py``

Design: the app's dark slate tile with a warm glow at the top. In the middle
is an orange laser beam with a bright spot where it lands, ringed like a
focused spot. Colours come from ``src/laser_app/ui/theme.py`` so the icon matches
the window.
"""

import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from laser_app.ui.render import hex_to_rgb  # noqa: E402
from laser_app.ui.theme import ACCENT, BG_BOTTOM, BG_TOP, GLOW  # noqa: E402

OUT = ROOT / "resources"
S = 1024
SS = 2                      # supersampling factor
CORE = (255, 236, 205)      # near-white centre of the spot


def _solid(size: int, rgb, alpha: Image.Image) -> Image.Image:
    """``rgb`` everywhere, with ``alpha`` as the alpha channel."""
    img = Image.new("RGBA", (size, size), tuple(rgb) + (255,))
    img.putalpha(alpha)
    return img


def _scaled(mask: Image.Image, k: float) -> Image.Image:
    """``mask`` with every value multiplied by ``k`` (0..1)."""
    return mask.point(lambda v: int(v * k))


def render(size: int = S) -> Image.Image:
    """Draw the icon at ``size`` x ``size`` pixels (supersampled, then downscaled)."""
    n = size * SS
    u = n / 1024                                           # 1 design unit at 1024 px

    # Rounded tile on Apple's icon grid (824 px body on a 1024 canvas).
    m, rad = 100 * u, 185 * u
    tile_mask = Image.new("L", (n, n), 0)
    ImageDraw.Draw(tile_mask).rounded_rectangle([m, m, n - m, n - m], radius=rad, fill=255)

    # Drop shadow under the tile.
    shadow = Image.new("L", (n, n), 0)
    ImageDraw.Draw(shadow).rounded_rectangle([m, m + 18 * u, n - m, n - m + 18 * u], radius=rad, fill=110)
    img = _solid(n, (0, 0, 0), shadow.filter(ImageFilter.GaussianBlur(22 * u)))

    # Tile: slate gradient plus the app's warm glow at the top.
    grad = Image.linear_gradient("L").resize((n, n))
    tile = Image.composite(Image.new("RGB", (n, n), hex_to_rgb(BG_BOTTOM)),
                           Image.new("RGB", (n, n), hex_to_rgb(BG_TOP)), grad).convert("RGBA")
    glow = Image.new("L", (n, n), 0)
    ImageDraw.Draw(glow).ellipse([n * 0.12, -n * 0.30, n * 0.88, n * 0.38], fill=150)
    tile.alpha_composite(_solid(n, hex_to_rgb(GLOW), glow.filter(ImageFilter.GaussianBlur(110 * u))))
    tile.putalpha(tile_mask)
    img.alpha_composite(tile)

    # Light hairline around the tile edge.
    inner = Image.new("L", (n, n), 0)
    w = max(2, int(3 * u))
    ImageDraw.Draw(inner).rounded_rectangle([m + w, m + w, n - m - w, n - m - w], radius=rad - w, fill=255)
    rim = ImageChops.subtract(tile_mask, inner)
    top_fade = Image.linear_gradient("L").rotate(180).resize((n, n))   # bright at the top
    img.alpha_composite(_solid(n, (255, 255, 255), ImageChops.multiply(_scaled(rim, 0.28), top_fade)))

    # Everything below is clipped to the tile.
    art = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    accent = hex_to_rgb(ACCENT)
    cx, cy = n * 0.585, n * 0.585                          # where the beam lands
    sx, sy = m + 40 * u, m + 40 * u                        # beam source (top left)

    # Beam: wide soft glow, then a crisp tapered core.
    beam_glow = Image.new("L", (n, n), 0)
    ImageDraw.Draw(beam_glow).line([sx, sy, cx, cy], fill=200, width=int(46 * u))
    art.alpha_composite(_solid(n, accent, beam_glow.filter(ImageFilter.GaussianBlur(26 * u))))
    beam = Image.new("L", (n, n), 0)
    bd = ImageDraw.Draw(beam)
    steps = 60
    for i in range(steps):                                 # taper: thin at the source
        t0, t1 = i / steps, (i + 1) / steps
        bw = (8 + 18 * t1) * u
        bd.line([sx + (cx - sx) * t0, sy + (cy - sy) * t0, sx + (cx - sx) * t1, sy + (cy - sy) * t1],
                fill=int(110 + 145 * t1), width=max(1, int(bw)))
    art.alpha_composite(_solid(n, accent, beam))

    # Spot: halo, two thin rings, bright core.
    halo = Image.new("L", (n, n), 0)
    r = 150 * u
    ImageDraw.Draw(halo).ellipse([cx - r, cy - r, cx + r, cy + r], fill=170)
    art.alpha_composite(_solid(n, accent, halo.filter(ImageFilter.GaussianBlur(70 * u))))
    for rr, a, rw in ((205 * u, 0.30, 7 * u), (140 * u, 0.62, 9 * u)):
        ring = Image.new("L", (n, n), 0)
        ImageDraw.Draw(ring).ellipse([cx - rr, cy - rr, cx + rr, cy + rr], outline=int(255 * a),
                                     width=int(rw))
        art.alpha_composite(_solid(n, accent, ring))
    dot = Image.new("L", (n, n), 0)
    r = 72 * u
    ImageDraw.Draw(dot).ellipse([cx - r, cy - r, cx + r, cy + r], fill=255)
    art.alpha_composite(_solid(n, accent, dot))
    core = Image.new("L", (n, n), 0)
    r = 40 * u
    ImageDraw.Draw(core).ellipse([cx - r, cy - r, cx + r, cy + r], fill=255)
    art.alpha_composite(_solid(n, CORE, core.filter(ImageFilter.GaussianBlur(9 * u))))

    art.putalpha(ImageChops.multiply(art.getchannel("A"), tile_mask))
    img.alpha_composite(art)
    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    """Write the .icns, .ico and PNG icons into ``resources/``."""
    OUT.mkdir(exist_ok=True)
    big = render(1024)
    big.save(OUT / "laser_control.icns")                                 # macOS
    big.save(OUT / "laser_control.ico", sizes=[(x, x) for x in (16, 24, 32, 48, 64, 128, 256)])
    for x in (16, 32, 64, 128, 256, 512, 1024):                        # Linux / misc
        # Small sizes are rendered directly so thin lines stay crisp.
        (render(x) if x <= 64 else big.resize((x, x), Image.LANCZOS)).save(OUT / f"laser_control-{x}.png")
    print("icons written to", OUT)


if __name__ == "__main__":
    main()
