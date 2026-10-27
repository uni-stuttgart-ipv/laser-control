"""The Tkinter user interface.

Modules, from low level to high level:

* ``theme``   - colours and image margins (design tokens).
* ``render``  - Pillow drawing of the background, tiles, buttons and icons (no Tk).
* ``layout``  - window geometry and the tile rectangles.
* ``text``    - fonts and text helpers.
* ``widgets`` - the canvas controls (buttons, tiles, power field, ...).
* ``app``     - ``App``: builds the window and renders it from the controller.

``theme`` and ``render`` need only Pillow, and ``layout`` adds the
controller (pyserial); none of them imports Tkinter, so they work without a
display (the icon tool and the render tests use them). ``App``,
``build_app`` and ``run_app`` are loaded on first use for the same reason.
"""

from __future__ import annotations

from typing import Any

__all__ = ["App", "build_app", "run_app"]


def __getattr__(name: str) -> Any:
    """Lazy access to ``App``, ``build_app`` and ``run_app`` (imports Tkinter)."""
    if name in __all__:
        from . import app
        return getattr(app, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
