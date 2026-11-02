"""Windows 11 title-bar colouring (no-op on other platforms).

While the laser emits, the caption turns amber with dark text and the window
border turns amber, so the state is visible even from the taskbar preview.
Uses ``DwmSetWindowAttribute``; requires Windows 11 build 22000 or later and
silently does nothing on older systems.
"""

from __future__ import annotations

import ctypes
import logging
import sys

logger = logging.getLogger(__name__)

_DWMWA_USE_IMMERSIVE_DARK_MODE = 20
_DWMWA_BORDER_COLOR = 34
_DWMWA_CAPTION_COLOR = 35
_DWMWA_TEXT_COLOR = 36
_DEFAULT = 0xFFFFFFFF


def _colorref(hex_color: str) -> int:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return r | (g << 8) | (b << 16)


def _set(hwnd: int, attribute: int, value: int) -> None:
    v = ctypes.c_uint(value)
    ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(v), ctypes.sizeof(v))


def set_caption(root, caption: str | None, text: str | None, border: str | None) -> None:
    """Colour the native title bar and border.

    Args:
        root: The Tk root window.
        caption: Caption background (``#RRGGBB``) or ``None`` for the system default.
        text: Caption text colour or ``None``.
        border: Window border colour or ``None``.
    """
    if sys.platform != "win32":
        return
    try:
        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        _set(hwnd, _DWMWA_CAPTION_COLOR, _colorref(caption) if caption else _DEFAULT)
        _set(hwnd, _DWMWA_TEXT_COLOR, _colorref(text) if text else _DEFAULT)
        _set(hwnd, _DWMWA_BORDER_COLOR, _colorref(border) if border else _DEFAULT)
    except Exception as exc:  # older Windows: attributes unsupported
        logger.debug("title bar colouring unavailable: %r", exc)


def enable_dpi_awareness() -> None:
    """Make the process system-DPI aware so text is not blurry at 125-150 %.

    System-aware (1), not per-monitor (2): Tk 8.6 does not handle
    ``WM_DPICHANGED``, so per-monitor awareness would leave the window wrongly
    sized after moving it to a monitor with different scaling. With (1),
    Windows scales the window bitmap on such a move instead.

    Must run before the first Tk window is created.
    """
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass
