"""Design tokens (colours, window width) and font selection.

Colour meanings: amber is anything you control and, at full glow (``EMIT*``),
the laser emitting; red (``WARN``/``ERR``) is only for warnings and errors;
green only for "connected" / "applied". Six-digit values are opaque Tk
colours; eight-digit values carry alpha and are only used when drawing with
Pillow.
"""

from __future__ import annotations

import sys
import tkinter as tk
import tkinter.font as tkfont
from dataclasses import dataclass

# ---- surface ----
BASE = "#EEECE8"
DIVIDER = "#DDD8D0"
SH_DARK = "#BDB5A973"
SH_LIGHT = "#FFFFFFE6"

# ---- text ----
TEXT = "#3B3732"
TEXT_2 = "#77706A"
TEXT_3 = "#A59E95"
TEXT_OFF = "#C9C3BA"

# ---- accent ----
AMBER_1 = "#FFD866"
AMBER_2 = "#F6A623"
AMBER_NUM = "#EE9A12"
AMBER_INK = "#4A2E05"
AMBER_GLOW = "#F6A62359"
AMBER_TRACK = "#E4DFD8"
AMBER_DISABLED_1 = "#F6E1AE"
AMBER_DISABLED_2 = "#F1CB8A"

# ---- status (red is for warnings and errors only) ----
OK = "#3E9E6B"
WARN = "#D2483A"
WARN_BG = "#FADFDA"
WARN_ZONE = "#EE9C92"
ERR = "#C23B2E"
ERR_BG = "#F8D9D4"

# ---- emission: the app's amber at full glow, used only while the laser is on ----
EMIT = "#F29A12"
EMIT_GLOW = "#F6A62373"
EMIT_RING = "#F6A62340"
EMIT_TEXT = "#A66300"
EMIT_INK = "#3A2606"
EMIT_WASH = "#FBE3B4"
TITLEBAR_EMIT = "#F5B238"

WIDTH = 400
"""Window width in logical pixels."""


def rgba(hex_color: str) -> tuple[int, int, int, int]:
    """Convert ``#RRGGBB`` or ``#RRGGBBAA`` to an RGBA tuple."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    a = int(h[6:8], 16) if len(h) == 8 else 255
    return r, g, b, a


def ui_scale(root: tk.Tk) -> float:
    """Logical-to-device pixel factor.

    On Windows the process is DPI aware, so Tk works in device pixels and we
    scale by ``dpi / 96``. On macOS Tk already works in points.
    """
    if sys.platform != "win32":
        return 1.0
    return max(1.0, root.winfo_fpixels("1i") / 96.0)


@dataclass(frozen=True)
class Fonts:
    """Tk fonts for every text role in the spec, already scaled."""

    title: tkfont.Font
    reading: tkfont.Font
    state: tkfont.Font
    port: tkfont.Font
    readout: tkfont.Font
    button: tkfont.Font
    mode: tkfont.Font
    label: tkfont.Font
    body: tkfont.Font
    small: tkfont.Font
    tiny: tkfont.Font


_DISPLAY_LIGHT = ("Segoe UI Variable Display Light", "Segoe UI Light", "Helvetica Neue Light", "Helvetica Neue")
_DISPLAY = ("Segoe UI Variable Display", "Segoe UI", "Helvetica Neue")
_DISPLAY_SEMI = ("Segoe UI Variable Display Semibold", "Segoe UI Semibold", "Helvetica Neue")
_TEXT = ("Segoe UI Variable Text", "Segoe UI", "Helvetica Neue")
_TEXT_SEMI = ("Segoe UI Variable Text Semibold", "Segoe UI Semibold", "Helvetica Neue")


def _pick(root: tk.Tk, candidates: tuple[str, ...]) -> str:
    available = {f.lower() for f in tkfont.families(root)}
    for name in candidates:
        if name.lower() in available:
            return name
    return "TkDefaultFont"


def make_fonts(root: tk.Tk, scale: float) -> Fonts:
    """Create fonts, falling back to whatever the OS has.

    Negative sizes are pixels, so the layout is the same on every system.
    """
    light, disp, semi = _pick(root, _DISPLAY_LIGHT), _pick(root, _DISPLAY), _pick(root, _DISPLAY_SEMI)
    text, text_semi = _pick(root, _TEXT), _pick(root, _TEXT_SEMI)
    bold_if_fallback = "bold" if "semibold" not in text_semi.lower() else "normal"

    def f(family: str, px: float, weight: str = "normal") -> tkfont.Font:
        return tkfont.Font(root=root, family=family, size=-round(px * scale), weight=weight)

    return Fonts(
        title=f(light, 25),
        reading=f(light, 27),
        state=f(light, 26),
        port=f(semi, 17, "bold" if "semibold" not in semi.lower() else "normal"),
        readout=f(disp, 17),
        button=f(text_semi, 14, bold_if_fallback),
        mode=f(text, 14),
        label=f(text_semi, 13, bold_if_fallback),
        body=f(text, 12.5),
        small=f(text, 12),
        tiny=f(text, 11),
    )
