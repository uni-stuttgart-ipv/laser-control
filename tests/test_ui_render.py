"""Theme, layout and Pillow rendering of the UI: no display needed.

Includes WCAG contrast checks for every text colour on every surface it is
drawn on, so a theme change cannot silently make text unreadable.
"""

from functools import partial

import pytest

pytest.importorskip("PIL")

from laser_app.ui import layout, render, theme  # noqa: E402

CTA = partial(render.render_pill, style="cta")
DARK = partial(render.render_pill, style="dark")


def blend(a: str, b: str, t: float) -> str:
    """Colour of ``b`` at opacity ``t`` over ``a``."""
    ra, rb = render.hex_to_rgb(a), render.hex_to_rgb(b)
    return render.rgb_to_hex(x + (y - x) * t for x, y in zip(ra, rb))


def test_hex_rgb_round_trip():
    assert render.hex_to_rgb("#2563EB") == (0x25, 0x63, 0xEB)
    assert render.rgb_to_hex((0x25, 0x63, 0xEB)) == "#2563EB"
    assert render.rgb_to_hex((-5, 300, 12.6)) == "#00FF0D"     # clamped and rounded


def wcag_luminance(color: str) -> float:
    """Relative luminance of an sRGB colour (WCAG 2.x)."""
    def channel(v):
        v /= 255
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(v) for v in render.hex_to_rgb(color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    """WCAG contrast ratio of two colours (1 to 21)."""
    la, lb = sorted((wcag_luminance(a), wcag_luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def test_contrast_formula():
    assert contrast("#000000", "#FFFFFF") == pytest.approx(21.0)
    assert contrast("#777777", "#777777") == pytest.approx(1.0)


def test_theme_is_valid():
    names = ["BG_TOP", "BG_MID", "BG_BOTTOM", "GLOW", "BUTTON", "ACTIVE", "ACCENT", "ON_ACCENT",
             "TEXT", "TEXT_2", "TEXT_3", "ON", "OFF", "OFF_TEXT", "ERROR"]
    for name in names:
        value = getattr(theme, name)
        assert render.rgb_to_hex(render.hex_to_rgb(value)) == value.upper(), name
    assert set(theme.SURFACES) == {"card", "panel"}
    for tint, opacity in theme.SURFACES.values():
        render.hex_to_rgb(tint)
        assert 0 < opacity < 1
    assert 0 < theme.GLOW_PEAK <= 1
    # Dark theme: the background gets darker towards the bottom.
    assert wcag_luminance(theme.BG_TOP) > wcag_luminance(theme.BG_BOTTOM)


@pytest.fixture(scope="module")
def background():
    # No dither: the random noise would make the contrast checks flaky.
    return render.render_background(layout.WIDTH, layout.HEIGHT, layout.GLOW_CENTER,
                                    layout.GLOW_RADIUS, noise=0)


@pytest.fixture(scope="module")
def manual_scene(background):
    return render.render_scene(background, layout.scene_cards(True), layout.SCENE_DIVIDERS,
                               layout.scene_flats(True))


def test_background_and_scene(background):
    assert background.size == (layout.WIDTH, layout.HEIGHT) and background.mode == "RGB"
    for manual in (True, False):
        scene, flats = render.render_scene(background, layout.scene_cards(manual), layout.SCENE_DIVIDERS,
                                           layout.scene_flats(manual))
        assert scene.size == background.size and scene.mode == "RGB"
        assert len(flats) == (1 if manual else 0)


def test_glow_is_warm_and_centred(background):
    cx, cy = layout.GLOW_CENTER
    r, g, b = background.getpixel((round(cx), round(cy)))
    assert r > g > b                                         # amber
    assert sum(background.getpixel((cx, cy))) > sum(background.getpixel((4, layout.HEIGHT - 4)))


def test_flat_area_matches_entry_bg(manual_scene):
    scene, (color,) = manual_scene
    x0, y0, x1, y1 = layout.FIELD
    r = layout.FIELD_R
    for x, y in ((x0 + r, y0 + 2), ((x0 + x1) // 2, (y0 + y1) // 2), (x1 - r, y1 - 3)):
        assert render.rgb_to_hex(scene.getpixel((x, y))) == color


def brightest(scene, box, inset):
    """Lightest colour inside ``box`` (inset to skip the rounded corners and edges)."""
    x0, y0, x1, y1 = box
    pixels = (render.rgb_to_hex(scene.getpixel((x, y)))
              for x in range(x0 + inset, x1 - inset, 3) for y in range(y0 + 6, y1 - 6, 3))
    return max(pixels, key=wcag_luminance)


def test_text_contrast_on_tiles(manual_scene):
    scene, _ = manual_scene
    for box, r, kind in layout.scene_cards(True):
        bg = brightest(scene, box, r // 2)
        if kind == "card":
            for fg in (theme.TEXT, theme.TEXT_2, theme.ERROR):
                assert contrast(fg, bg) >= 4.5, (fg, bg, box)
            assert contrast(theme.ACCENT, bg) >= 3.0              # glyphs: non-text contrast
            if box[1] not in (layout.CONN_Y0, layout.MODE_Y0):
                continue
            # Selected tiles (connected / chosen mode) get the muted-orange wash in
            # every state; their text switches to TEXT and TEXT_ON_SELECTED.
            for state in ("normal", "hover", "pressed", "disabled"):
                color, opacity = theme.WASH[(True, state)]
                washed = blend(bg, color, opacity)
                for fg in (theme.TEXT, theme.TEXT_ON_SELECTED):
                    assert contrast(fg, washed) >= 4.5, (fg, washed, box, state)
        else:
            for fg in (theme.TEXT, theme.TEXT_2, theme.ON, theme.OFF_TEXT):
                assert contrast(fg, bg) >= 4.5, (fg, bg)


def test_text_contrast_bar_and_message(manual_scene):
    scene, _ = manual_scene
    strip = brightest(scene, (layout.X0, layout.MSG_Y - 8, layout.X1, layout.BAR_Y1), 0)
    for fg in theme.LEVEL_COLORS.values():
        assert contrast(fg, strip) >= 4.5, (fg, strip)
    color, opacity = theme.BAR_ACTIVE
    assert contrast(theme.TEXT, blend(strip, color, opacity)) >= 4.5
    assert contrast(theme.ON_ACCENT, theme.ACCENT) >= 4.5     # Apply label
    assert contrast(theme.TEXT, theme.BUTTON) >= 4.5           # menu items


@pytest.mark.parametrize("state", ["normal", "hover", "pressed", "disabled"])
def test_icon_button_and_pill(state):
    img = render.render_icon_button(layout.ICON_BTN, layout.ICON_BTN_R, "refresh", theme.TEXT, state)
    assert img.mode == "RGBA" and img.size == (layout.ICON_BTN + 2 * theme.M,) * 2
    assert img.getpixel((img.width // 2, theme.M + 3))[3] > 0
    assert img.getpixel((0, 0))[3] == 0
    pill = render.render_pill(layout.APPLY_W, layout.APPLY_H, state)
    assert pill.mode == "RGBA" and pill.size == (layout.APPLY_W + 2 * theme.M, layout.APPLY_H + 2 * theme.M)
    assert pill.getpixel((pill.width // 2, pill.height // 2))[3] > 0


@pytest.mark.parametrize("color", [None, theme.ON, theme.OFF])
@pytest.mark.parametrize("state", ["normal", "hover", "pressed"])
def test_laser_button_image(color, state):
    img = render.render_laser_button(layout.LASER_BTN, layout.LASER_BTN_R, color, state, glow=color == theme.ON)
    assert img.mode == "RGBA"
    assert img.size == (layout.LASER_BTN + 2 * theme.LASER_MARGIN,) * 2
    assert img.getpixel((img.width // 2, theme.LASER_MARGIN + 4))[3] == 255


def test_wash_and_ring():
    full = render.render_wash(200, 112, 28, theme.ACTIVE, 0.5)
    assert full.size == (200, 112) and full.mode == "RGBA"
    assert full.getpixel((100, 56))[3] == round(255 * 0.5)
    assert full.getpixel((0, 0))[3] == 0                         # rounded corner
    half = render.render_wash(408, 112, 28, "#FFFFFF", 0.05, clip=(204, 408))
    assert half.size == (204, 112)
    ring = render.render_ring(236, 50, 18, theme.ACCENT, 0.75)
    assert ring.size == (236 + 2 * theme.M, 50 + 2 * theme.M)
    assert ring.getpixel((ring.width // 2, ring.height // 2))[3] == 0   # hollow


def test_icons():
    for name in render.ICONS:
        img = render.render_icon(name, 24, theme.ACCENT)
        assert img.size == (24, 24) and img.mode == "RGBA"
        assert img.getchannel("A").getextrema()[1] > 200, name


def test_layout_fits_window():
    boxes = [box for box, _, _ in layout.scene_cards(True)]
    for x0, y0, x1, y1 in boxes:
        assert 0 <= x0 < x1 <= layout.WIDTH and 0 <= y0 < y1 <= layout.HEIGHT
    for i, a in enumerate(boxes):                                # no overlapping tiles
        for b in boxes[i + 1:]:
            assert a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1], (a, b)
    assert len(layout.scene_cards(False)) == len(boxes) - 1         # Camera: no Power tile
    assert layout.POWER_Y1 < layout.LASER_Y0 < layout.LASER_Y1 < layout.MSG_Y < layout.BAR_Y0 < layout.BAR_Y1 <= layout.HEIGHT


@pytest.mark.parametrize("state", ["normal", "hover", "pressed", "disabled"])
def test_connect_button_images(state):
    """Connect (orange) and Disconnect (dark) pills: size, opaque centre, clear corners."""
    for make in (CTA, DARK):
        img = make(layout.CONN_BTN_W, layout.CONN_BTN_H, state)
        assert img.mode == "RGBA"
        assert img.size == (layout.CONN_BTN_W + 2 * theme.M, layout.CONN_BTN_H + 2 * theme.M)
        assert img.getpixel((img.width // 2, img.height // 2))[3] > 0
        assert img.getpixel((theme.M, theme.M))[3] < 255      # rounded corner


def test_connect_button_label_contrast():
    """Labels on the Connect / Disconnect pills stay readable in every state."""
    for state in ("normal", "hover", "pressed"):
        cta = CTA(layout.CONN_BTN_W, layout.CONN_BTN_H, state)
        dark = DARK(layout.CONN_BTN_W, layout.CONN_BTN_H, state)
        mid = (cta.width // 2, cta.height // 2)
        assert contrast(theme.ON_ACCENT, render.rgb_to_hex(cta.getpixel(mid)[:3])) >= 4.5, state
        assert contrast(theme.TEXT, render.rgb_to_hex(dark.getpixel(mid)[:3])) >= 4.5, state


def test_status_dot():
    dot = render.render_dot(8, theme.ON)
    assert dot.size == (8, 8) and dot.getpixel((4, 4))[3] == 255 and dot.getpixel((0, 0))[3] < 255


def test_background_dither_is_optional():
    plain = render.render_background(40, 30, (20, 10), (20, 20), noise=0)
    dithered = render.render_background(40, 30, (20, 10), (20, 20))
    assert plain.size == dithered.size == (40, 30) and plain.mode == dithered.mode == "RGB"


def test_pill_styles():
    assert set(render.PILL_STYLES) == {"accent", "cta", "dark"}
    disabled = {s: render.render_pill(88, 38, "disabled", s).tobytes() for s in render.PILL_STYLES}
    assert len(set(disabled.values())) == 1                  # one grey look for every style
    normal = {s: render.render_pill(88, 38, "normal", s).tobytes() for s in render.PILL_STYLES}
    assert len(set(normal.values())) == 3
    assert render.render_pill(88, 38, "normal").tobytes() == normal["accent"]   # default style
