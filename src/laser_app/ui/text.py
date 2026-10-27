"""Fonts and small text helpers (formatting, parsing, fitting text into a width)."""

from __future__ import annotations

import math
import tkinter.font as tkfont
from typing import Optional, Protocol

SANS_CANDIDATES = ["Inter", "SF Pro Text", "Segoe UI", "Helvetica Neue", "Helvetica", "DejaVu Sans"]
DISPLAY_CANDIDATES = ["Inter Display", "SF Pro Display", "Segoe UI Variable Display"]
MEDIUM_CANDIDATES = ["Inter Medium", "Inter SemiBold", "SF Pro Text Medium", "Segoe UI Semibold"]


class Measurer(Protocol):
    """Anything with ``measure(text) -> pixels`` (a ``tkfont.Font``; tests use a fake)."""

    def measure(self, text: str) -> int: ...


def pick_family(candidates: list[str]) -> str:
    """The first installed font family of ``candidates`` (else ``"TkDefaultFont"``). Needs a Tk root."""
    available = {f.lower(): f for f in tkfont.families()}
    for c in candidates:
        if c.lower() in available:
            return available[c.lower()]
    return "TkDefaultFont"


def pick_medium(sans: str, size: int) -> tkfont.Font:
    """A real medium/semibold face if one is installed, else ``sans`` in bold.

    Tk only knows normal and bold, but Windows (and fontconfig) expose medium
    weights as separate families. Tk silently substitutes a fallback for a
    missing family, so a candidate only counts if Tk resolved it to that family
    AND it measures differently from the regular face (it really is another weight).
    """
    probe = "Laser Control Apply"      # words actually set in this font
    regular = tkfont.Font(family=sans, size=size).measure(probe)
    for cand in MEDIUM_CANDIDATES:
        f = tkfont.Font(family=cand, size=size)
        if f.actual("family").lower().split()[0] == cand.split()[0].lower() \
                and f.measure(probe) != regular:
            return f
    return tkfont.Font(family=sans, size=size, weight="bold")


class Fonts:
    """The app's fonts. Negative sizes are pixels, so metrics match on every platform."""

    def __init__(self) -> None:
        sans = pick_family(SANS_CANDIDATES)
        display = pick_family(DISPLAY_CANDIDATES + SANS_CANDIDATES)
        self.title = pick_medium(sans, -18)                    # window title
        self.h = pick_medium(sans, -16)                        # panel heading
        self.btn = pick_medium(sans, -14)                      # button labels
        self.value = tkfont.Font(family=display, size=-26)     # tile values
        self.value_small = tkfont.Font(family=display, size=-20)   # long port names
        self.unit = tkfont.Font(family=sans, size=-14)
        self.body = tkfont.Font(family=sans, size=-14)
        self.small = tkfont.Font(family=sans, size=-13)
        self.tiny = tkfont.Font(family=sans, size=-12)


def fmt_mw(v: float) -> str:
    """Format a power for the field: 35 -> '35.0', 12.25 -> '12.25' (1 to 2 decimals)."""
    s = f"{v:.2f}".rstrip("0")
    return s + "0" if s.endswith(".") else s


def parse_mw(text: str) -> Optional[float]:
    """Parse the power field; None if it is not a finite number. Accepts a decimal comma."""
    try:
        v = float(text.strip().replace(",", "."))
    except ValueError:
        return None
    return v if math.isfinite(v) else None


def ellipsize(text: str, font: Measurer, avail: int) -> str:
    """Shorten ``text`` with a trailing '…' so it fits in ``avail`` pixels of ``font``."""
    if avail <= 1 or font.measure(text) <= avail:
        return text
    while text and font.measure(text + "…") > avail:
        text = text[:-1]
    return text + "…"
