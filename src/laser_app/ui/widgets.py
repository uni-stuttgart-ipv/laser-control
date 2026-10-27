"""Canvas widgets: the clickable controls and text items the window is built from.

Tk widgets cannot be translucent, so the window is ONE ``tk.Canvas`` and each
control is a plain Python object that owns some canvas items and a hit area.
The ``App`` binds the mouse on the canvas once and forwards events to the
control under the pointer (``hover`` / ``press`` / ``release`` → ``click``).

Every control image is pre-rendered by ``render.py`` for each state and cached
by ``Images``, so a state change only swaps the image of a canvas item.

Class overview::

    Control                       hit area, state flags, command, image swapping
    ├── IconButton                header buttons (refresh, plug)
    ├── PillButton                Apply; base of ConnectButton
    │   └── ConnectButton         Connect / Disconnect / Connecting…
    ├── LaserButton               the big on/off button
    ├── PowerField                the editable power value (a real tk.Entry)
    └── Tile                      a tile (or part of one) with a wash, value and caption
        ├── PortPicker            port name; click opens a tk.Menu
        ├── CardPane              wash only (the connection card's right half)
        └── ModeTile              Camera / Manual
    CText, StatusLine, StatItem   non-clickable text items
"""

from __future__ import annotations

import tkinter as tk
from typing import TYPE_CHECKING, Callable, Optional

from PIL import Image, ImageTk

from .layout import CAPTION_DY, CARD_R, FIELD_R, GLYPH, GLYPH_D, MODE_ICONS, VALUE_DY
from .render import (render_dot, render_icon, render_icon_button, render_laser_button,
                     render_pill, render_ring, render_wash)
from .text import ellipsize, fmt_mw, parse_mw
from .theme import (ACCENT, ACTIVE, BAR_ACTIVE, BUTTON, ERROR, LASER_MARGIN, OFF, ON,
                    ON_ACCENT, TEXT, TEXT_2, TEXT_3, TEXT_ON_SELECTED, WASH, M)

if TYPE_CHECKING:                       # imported for type hints only (avoids a cycle)
    from ..controller import Mode
    from .app import App

Command = Callable[[], None]


# ==========================================================================
# Shared building blocks
# ==========================================================================
class Images:
    """Cache of Tk images keyed by their rendering parameters."""

    def __init__(self, master: tk.Misc) -> None:
        self.master = master
        self._cache: dict[tuple, ImageTk.PhotoImage] = {}

    def get(self, key: tuple, make: Callable[[], Image.Image]) -> ImageTk.PhotoImage:
        """Return the cached image for ``key``, rendering it with ``make()`` the first time."""
        img = self._cache.get(key)
        if img is None:
            img = self._cache[key] = ImageTk.PhotoImage(make(), master=self.master)
        return img

    def icon(self, name: str, size: int, color: str) -> ImageTk.PhotoImage:
        """A cached glyph from ``render.ICONS``."""
        return self.get(("icon", name, size, color), lambda: render_icon(name, size, color))


class CText:
    """A canvas text item that only reconfigures when its text or colour changed."""

    def __init__(self, cv: tk.Canvas, x, y, text: str = "", font=None, fill: str = TEXT,
                 anchor: str = "w", tags=()) -> None:
        self.cv = cv
        self.id = cv.create_text(x, y, text=text, font=font, fill=fill, anchor=anchor, tags=tags)
        self._state = (text, fill)

    @property
    def text(self) -> str:
        """The text currently shown."""
        return self._state[0]

    @property
    def fill(self) -> str:
        """The current text colour."""
        return self._state[1]

    def set(self, text: str, fill: Optional[str] = None) -> None:
        """Show ``text`` (in ``fill``, or the current colour if None)."""
        fill = self.fill if fill is None else fill
        if (text, fill) != self._state:
            self._state = (text, fill)
            self.cv.itemconfigure(self.id, text=text, fill=fill)

    def move_to(self, x, y) -> None:
        """Move the item's anchor point to (x, y)."""
        self.cv.coords(self.id, x, y)


class Control:
    """Base class for a clickable thing on the canvas.

    It has a hit rectangle, ``enabled`` / ``hover`` / ``pressed`` / ``visible``
    flags and an optional ``command`` run on click. All of its canvas items
    carry ``self.tag`` so they can be hidden together. Subclasses override
    ``draw`` (and ``click`` etc. as needed).
    """

    cursor = "hand2"
    _seq = 0

    def __init__(self, ui: App, x: int, y: int, w: int, h: int,
                 command: Optional[Command] = None) -> None:
        Control._seq += 1
        self.ui, self.cv = ui, ui.cv
        self.tag = f"ctl{Control._seq}"
        self.x, self.y, self.w, self.h = x, y, w, h
        self.command = command
        self.enabled, self.hover, self.pressed, self.visible = True, False, False, True
        ui.controls.append(self)

    # -- canvas helpers
    def _image_item(self, margin: int = M, **kw) -> int:
        """A canvas image item at the control's corner minus ``margin`` (see ``render.M``)."""
        return self.cv.create_image(self.x - margin, self.y - margin, anchor="nw",
                                    tags=self.tag, **kw)

    def _show(self, item: int, key: tuple, make: Callable[[], Image.Image]) -> None:
        """Put the cached image ``key`` (rendered by ``make`` once) into canvas ``item``."""
        self.cv.itemconfigure(item, image=self.ui.images.get(key, make))

    # -- state
    def contains(self, x, y) -> bool:
        """True if canvas point (x, y) is inside this (visible) control."""
        return self.visible and self.x <= x < self.x + self.w and self.y <= y < self.y + self.h

    @property
    def state(self) -> str:
        """``"disabled"``, ``"pressed"``, ``"hover"`` or ``"normal"``."""
        if not self.enabled:
            return "disabled"
        return "pressed" if self.pressed else "hover" if self.hover else "normal"

    def set_hover(self, v: bool) -> None:
        """Pointer entered (True) or left (False); leaving also cancels a press."""
        if v != self.hover:
            self.hover = v
            if not v:
                self.pressed = False
            self.draw()

    def press(self, x, y) -> None:
        """Mouse button went down on the control."""
        if self.enabled:
            self.pressed = True
            self.draw()

    def release(self, x, y) -> None:
        """Mouse button went up; a press released inside the control is a click."""
        was, self.pressed = self.pressed, False
        self.draw()
        if was and self.enabled and self.contains(x, y):
            self.click(x, y)

    def on_motion(self, x, y) -> None:
        """Pointer moved inside the control (for controls with sub-areas)."""

    def click(self, x, y) -> None:
        """The control was clicked: run ``command`` if there is one."""
        if self.command is not None:
            self.command()

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable the control (a disabled control ignores the mouse)."""
        if enabled != self.enabled:
            self.enabled = enabled
            self.pressed = False
            self.draw()
            self.ui.update_cursor()

    def set_visible(self, v: bool) -> None:
        """Show or hide all of the control's canvas items."""
        if v != self.visible:
            self.visible = v
            self.hover = self.pressed = False
            self.cv.itemconfigure(self.tag, state="normal" if v else "hidden")
            if v:
                self.draw()

    def draw(self) -> None:
        """Bring the canvas items in line with the current state."""


# ==========================================================================
# Buttons
# ==========================================================================
class IconButton(Control):
    """Dark rounded-square button with a glyph (the header buttons).

    The glyph is drawn in ``tone`` while enabled and grey while disabled.
    """

    def __init__(self, ui: App, x: int, y: int, size: int, r: int, icon: str,
                 command: Command) -> None:
        super().__init__(ui, x, y, size, size, command)
        self.icon, self.r, self.tone = icon, r, TEXT
        self._img = self._image_item()
        self.draw()

    def set_state(self, enabled: bool, tone: str = TEXT) -> None:
        """Set whether the button can be clicked and the glyph colour while it can."""
        if tone != self.tone:
            self.tone = tone
            self.draw()
        self.set_enabled(enabled)

    def draw(self) -> None:
        """Swap in the image for the current state and glyph colour."""
        st = self.state
        col = TEXT_3 if st == "disabled" else self.tone
        self._show(self._img, ("ibtn", self.w, self.icon, col, st),
                   lambda: render_icon_button(self.w, self.r, self.icon, col, st))


class PillButton(Control):
    """A pill with a label and an optional glyph, in one of ``render.PILL_STYLES``.

    Styles: ``"accent"`` (orange, Apply), ``"cta"`` (orange call to action,
    Connect) and ``"dark"`` (secondary, Disconnect). Disabled pills are grey
    with a grey label and no glyph. Glyph and label are centred together and
    sink 1 px while pressed.
    """

    LABEL = {"accent": ON_ACCENT, "cta": ON_ACCENT, "dark": TEXT}     # label colour per style
    GLYPH = {"accent": ON_ACCENT, "cta": ON_ACCENT, "dark": TEXT_2}   # glyph colour per style
    GLYPH_SIZE, GLYPH_GAP = 16, 6

    def __init__(self, ui: App, x: int, y: int, w: int, h: int, text: str, command: Command,
                 style: str = "accent", glyph: Optional[str] = None) -> None:
        super().__init__(ui, x, y, w, h, command)
        self.text, self.style, self.glyph = text, style, glyph
        self.disabled_fg = TEXT_3          # label colour while disabled
        self._img = self._image_item()
        self._glyph = self.cv.create_image(0, 0, anchor="w", tags=self.tag)
        self._txt = CText(self.cv, 0, 0, "", ui.f.btn, anchor="w", tags=self.tag)
        self.draw()

    def draw(self) -> None:
        """Pill image, glyph and label for the current style and state."""
        st = self.state
        disabled = st == "disabled"
        style = None if disabled else self.style     # every style looks the same disabled
        self._show(self._img, ("pill", self.w, self.h, st, style),
                   lambda: render_pill(self.w, self.h, st, self.style))
        glyph = None if disabled else self.glyph
        f = self.ui.f.btn
        gw = self.GLYPH_SIZE + self.GLYPH_GAP if glyph else 0
        left = self.x + (self.w - gw - f.measure(self.text)) / 2
        cy = self.y + self.h / 2 + (1 if st == "pressed" else 0)
        if glyph:
            self.cv.itemconfigure(self._glyph, state="normal" if self.visible else "hidden",
                                  image=self.ui.images.icon(glyph, self.GLYPH_SIZE,
                                                            self.GLYPH[self.style]))
            self.cv.coords(self._glyph, round(left), round(cy))
        else:
            self.cv.itemconfigure(self._glyph, state="hidden")
        self._txt.move_to(left + gw, cy)
        self._txt.set(self.text, self.disabled_fg if disabled else self.LABEL[self.style])


class ConnectButton(PillButton):
    """The connection card's main action: orange "Connect", dark "Disconnect", grey "Connecting…"."""

    KINDS = {   # kind: (label, style, glyph)
        "connect": ("Connect", "cta", "plug"),
        "disconnect": ("Disconnect", "dark", "plug"),
        "busy": ("Connecting…", "dark", None),
    }

    def __init__(self, ui: App, x: int, y: int, w: int, h: int, command: Command) -> None:
        super().__init__(ui, x, y, w, h, "", command)
        self.kind = ""
        self.set_kind("connect", True)

    def set_kind(self, kind: str, enabled: bool) -> None:
        """Show ``"connect"``, ``"disconnect"`` or ``"busy"`` (always disabled)."""
        if kind != self.kind:
            self.kind = kind
            self.text, self.style, self.glyph = self.KINDS[kind]
            # "Connecting…" stays readable; a plain disabled button is grey.
            self.disabled_fg = TEXT_2 if kind == "busy" else TEXT_3
            self.draw()
        self.set_enabled(enabled and kind != "busy")


class LaserButton(Control):
    """Big dark rounded-square on/off button with the power symbol (IEC 5009).

    Green while the laser is ON (with a soft glow), red while it is OFF, grey
    when unavailable. Clicking runs ``command`` (the App decides what it means).
    """

    def __init__(self, ui: App, cx: int, cy: int, size: int, r: int, command: Command) -> None:
        super().__init__(ui, cx - size // 2, cy - size // 2, size, size, command)
        self.r = r
        self.on = False
        self._img = self._image_item(LASER_MARGIN)
        self.draw()

    def contains(self, x, y) -> bool:
        """True inside the rounded square (corners excluded)."""
        if not super().contains(x, y):
            return False
        r = self.r
        dx = max(self.x + r - x, x - (self.x + self.w - r), 0)
        dy = max(self.y + r - y, y - (self.y + self.h - r), 0)
        return dx * dx + dy * dy <= (r + 1) ** 2

    def set_state(self, on: bool, enabled: bool) -> None:
        """Set the laser state shown (on = green, off = red) and whether it can be clicked."""
        if on != self.on:
            self.on = on
            self.draw()
        self.set_enabled(enabled)

    def draw(self) -> None:
        """Swap in the image for the current colour and state."""
        color = None if not self.enabled else ON if self.on else OFF
        st = "normal" if not self.enabled else self.state
        glow = self.on and self.enabled
        self._show(self._img, ("laser", self.w, color, st, glow),
                   lambda: render_laser_button(self.w, self.r, color, st, glow))


# ==========================================================================
# Power field
# ==========================================================================
class PowerField(Control):
    """The big editable power value: a ``tk.Entry`` plus a grey 'mW', on a flat tile area.

    The value and unit stay centred in the area as the text changes. A faint
    ring on hover, an orange ring while focused, a red ring on error.

    Args:
        bg: the flat area's colour (``render_scene`` returns it); the Entry uses it.
    """

    cursor = "xterm"
    RINGS = {"hover": ("#FFFFFF", 0.14, 1.5), "focus": (ACCENT, 0.75, 2), "error": (ERROR, 0.85, 2)}
    UNIT_GAP = 6

    def __init__(self, ui: App, box: tuple[int, int, int, int], bg: str) -> None:
        x0, y0, x1, y1 = box
        super().__init__(ui, x0, y0, x1 - x0, y1 - y0)
        self.font = ui.f.value
        self.var = tk.StringVar(master=ui.root)
        self.entry = tk.Entry(self.cv, textvariable=self.var, font=self.font, justify="right",
                              bd=0, relief="flat", highlightthickness=0, bg=bg, fg=TEXT,
                              insertbackground=ACCENT, insertwidth=2,
                              selectbackground=ACCENT, selectforeground=ON_ACCENT,
                              disabledbackground=bg, disabledforeground=TEXT_2)
        self._ring = self._image_item()
        self._win = self.cv.create_window(x0, (y0 + y1) / 2, window=self.entry, anchor="w",
                                          tags=self.tag)
        self._suffix = CText(self.cv, x1, (y0 + y1) / 2 + 3, "mW", ui.f.unit, fill=TEXT_2,
                             tags=self.tag)
        self._error = self._focus = False
        self.entry.bind("<FocusIn>", lambda e: self._set_focus(True), add="+")
        self.entry.bind("<FocusOut>", lambda e: self._set_focus(False), add="+")
        self.var.trace_add("write", lambda *_: self._layout())
        self._layout()
        self.draw()

    def _layout(self) -> None:
        """Size the Entry to its text and centre 'value mW' in the area."""
        unit_w = self.ui.f.unit.measure("mW")
        text_w = self.font.measure(self.var.get() or "0") + 4      # + room for the caret
        text_w = min(text_w, self.w - 24 - self.UNIT_GAP - unit_w)
        left = self.x + (self.w - text_w - self.UNIT_GAP - unit_w) / 2
        cy = self.y + self.h / 2
        self.cv.coords(self._win, left, cy)
        self.cv.itemconfigure(self._win, width=text_w)
        self._suffix.move_to(left + text_w + self.UNIT_GAP, cy + 3)

    def get(self) -> Optional[float]:
        """The entered power in mW, or None if the text is not a number."""
        return parse_mw(self.var.get())

    def set_value(self, v: float) -> None:
        """Put ``v`` (mW) into the field."""
        self.var.set(fmt_mw(v))

    def has_focus(self) -> bool:
        """True while the Entry has keyboard focus."""
        try:
            return self.cv.focus_get() is self.entry
        except (KeyError, tk.TclError):
            return False

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable the field (and its Entry)."""
        if enabled != self.enabled:
            self.entry.configure(state="normal" if enabled else "disabled")
        super().set_enabled(enabled)

    def set_error(self, error: bool) -> None:
        """Show or clear the red error ring."""
        if error != self._error:
            self._error = error
            self.draw()

    def _set_focus(self, focus: bool) -> None:
        self._focus = focus
        self.draw()

    def press(self, x, y) -> None:
        """A click anywhere on the area focuses the Entry, caret at the end."""
        if self.enabled:
            self.entry.focus_set()
            self.entry.icursor("end")

    def release(self, x, y) -> None:
        """No click action: the Entry handles the rest."""

    def draw(self) -> None:
        """Ring for the current state (disabled > error > focus > hover > none)."""
        if not self.enabled:
            st = None
        elif self._error:
            st = "error"
        elif self._focus:
            st = "focus"
        else:
            st = "hover" if self.hover else None
        if st is None:
            self.cv.itemconfigure(self._ring, image="")
        else:
            color, opacity, width = self.RINGS[st]
            self._show(self._ring, ("ring", self.w, self.h, st),
                       lambda: render_ring(self.w, self.h, FIELD_R, color, opacity, width))


# ==========================================================================
# Tiles
# ==========================================================================
class Tile(Control):
    """A clickable tile (or one part of a split tile) with a big value and a caption.

    Hover lightens the tile and pressing flashes it orange; a selected tile is
    muted orange. Each look is a translucent wash shaped like the whole tile,
    clipped to this control's columns, laid over the base image (see
    ``theme.WASH``).

    Args:
        card: bounds ``(x0, y0, x1, y1)`` of the whole tile in the base image.
        part: ``(x0, x1)`` columns of the tile this control covers, relative to
            the tile (None: all of it).
        caption: the small grey text under the value.
    """

    def __init__(self, ui: App, card: tuple[int, int, int, int],
                 part: Optional[tuple[int, int]], caption: str,
                 command: Optional[Command] = None) -> None:
        cx0, cy0, cx1, cy1 = card
        self.card_w, self.card_h = cx1 - cx0, cy1 - cy0
        self.part = part or (0, self.card_w)
        super().__init__(ui, cx0 + self.part[0], cy0, self.part[1] - self.part[0], self.card_h,
                         command)
        self.selected = False
        mid = self.x + self.w / 2
        self._wash = self.cv.create_image(self.x, self.y, anchor="nw", state="hidden")
        self.value = CText(self.cv, mid, cy0 + VALUE_DY, "", ui.f.value, anchor="center", tags=self.tag)
        self.caption = CText(self.cv, mid, cy0 + CAPTION_DY, caption, ui.f.body, fill=TEXT_2,
                             anchor="center", tags=self.tag)

    def _glyph_item(self) -> int:
        """A canvas image item for the tile's corner glyph."""
        return self.cv.create_image(self.x - self.part[0] + GLYPH_D, self.y + GLYPH_D,
                                    anchor="nw", tags=self.tag)

    def draw(self) -> None:
        """Show the wash for the current state (if any), then the content."""
        wash = WASH.get((self.selected, self.state))
        if wash is None or not self.visible:
            self.cv.itemconfigure(self._wash, state="hidden")
        else:
            color, opacity = wash
            clip = None if self.part == (0, self.card_w) else self.part
            img = self.ui.images.get(("wash", self.card_w, self.card_h, clip, color, opacity),
                                     lambda: render_wash(self.card_w, self.card_h, CARD_R,
                                                         color, opacity, clip))
            self.cv.itemconfigure(self._wash, image=img, state="normal")
        self.draw_content()
        if self.selected:
            # Grey text loses contrast on the orange wash: lift it.
            if self.value.fill in (TEXT_2, TEXT_3):
                self.value.set(self.value.text, TEXT)
            self.caption.set(self.caption.text, TEXT_ON_SELECTED)
        else:
            self.caption.set(self.caption.text, TEXT_2)

    def set_selected(self, selected: bool) -> None:
        """Show the tile as selected (muted orange) or not."""
        if selected != self.selected:
            self.selected = selected
            self.draw()

    def draw_content(self) -> None:
        """Recolour the value and caption (subclasses)."""


class PortPicker(Tile):
    """Left half of the connection card: the selected port; a click opens a ``tk.Menu``.

    Items are ``(key, label)`` pairs: the tile shows the key, the menu the labels.
    """

    def __init__(self, ui: App, card: tuple[int, int, int, int], part: tuple[int, int]) -> None:
        super().__init__(ui, card, part, "port")
        self.items: list[tuple[str, str]] = []
        self.key: Optional[str] = None
        self._open_now = False
        # One menu for the control's lifetime, refilled on every open. Creating
        # a new Menu per open would leak one widget per click, and destroying it
        # right after tk_popup is unsafe on X11, where tk_popup returns while
        # the menu is still posted.
        self._menu = tk.Menu(self.cv, tearoff=0, bg=BUTTON, fg=TEXT, activebackground=ACTIVE,
                             activeforeground=TEXT, bd=0, relief="flat", font=ui.f.body,
                             activeborderwidth=6)
        self._chev = self.cv.create_image(0, self.y + CAPTION_DY, anchor="w", tags=self.tag)
        self.draw()

    def set_items(self, items: list[tuple[str, str]], prefer: Optional[str] = None) -> None:
        """Replace the items; select ``prefer`` if present, else keep the key or take the first."""
        self.items = list(items)
        keys = [k for k, _ in self.items]
        if prefer in keys:
            self.key = prefer
        elif self.key not in keys:
            self.key = keys[0] if keys else None
        self.draw()

    @property
    def label(self) -> Optional[str]:
        """Label of the selected item, or None."""
        return next((lbl for k, lbl in self.items if k == self.key), None)

    def click(self, x, y) -> None:
        """Open the menu."""
        self.open_menu()

    def open_menu(self) -> None:
        """Fill and post the port menu under the tile (no-op when disabled or empty)."""
        if not self.enabled or not self.items:
            return
        m = self._menu
        m.delete(0, "end")
        for k, lbl in self.items:
            m.add_command(label=("✓  " if k == self.key else "     ") + lbl,
                          command=lambda k=k: self._choose(k))
        self._open_now = True
        self.draw()
        try:   # blocks on Windows/macOS until the menu closes; returns at once on X11
            m.tk_popup(self.cv.winfo_rootx() + self.x + 12,
                       self.cv.winfo_rooty() + self.y + self.h + 6)
        finally:
            self._open_now = False
            self.draw()

    def _choose(self, k: str) -> None:
        self.key = k
        self.draw()

    @property
    def state(self) -> str:
        """As ``Control.state``, but ``"pressed"`` while the menu is open."""
        return "pressed" if (self._open_now and self.enabled) else super().state

    def draw_content(self) -> None:
        """Show the port (shrunk, then ellipsized, to fit), the caption and the chevron."""
        f = self.ui.f
        avail = self.w - 2 * 24
        if self.key is None:
            text, font = "—", f.value
        else:
            text = self.key.removeprefix("/dev/")
            font = f.value if f.value.measure(text) <= avail else f.value_small
            text = ellipsize(text, font, avail)
        self.cv.itemconfigure(self.value.id, font=font)
        self.value.set(text, TEXT if self.enabled else TEXT_2)
        cap = "port" if self.items else "no ports found"
        self.caption.set(cap)
        # Caption + chevron are centred together under the value.
        show_chev = self.enabled
        cap_w = f.body.measure(cap)
        left = self.x + self.w / 2 - (cap_w + (18 if show_chev else 0)) / 2
        self.caption.move_to(left + cap_w / 2, self.y + CAPTION_DY)
        self.cv.coords(self._chev, left + cap_w + 2, self.y + CAPTION_DY + 1)
        self.cv.itemconfigure(self._chev, image=self.ui.images.icon("chevron", 16, TEXT_2),
                              state="normal" if (show_chev and self.visible) else "hidden")


class CardPane(Tile):
    """A wash-only part of a tile that is never hit: shows the selected wash behind other controls."""

    def __init__(self, ui: App, card: tuple[int, int, int, int], part: Optional[tuple[int, int]]) -> None:
        super().__init__(ui, card, part, "")
        self.draw()

    def contains(self, x, y) -> bool:
        """Never under the pointer: the controls on top of it take the clicks."""
        return False


class ModeTile(Tile):
    """One control-mode tile. Selected: muted-orange wash, orange glyph, white value.

    Clicking only asks ``command(mode)``; the App decides and calls ``set``.
    """

    def __init__(self, ui: App, card: tuple[int, int, int, int], mode: Mode,
                 command: Callable[[Mode], None]) -> None:
        super().__init__(ui, card, None, "mode", lambda: command(mode))
        self.mode = mode
        self.value.set(mode.value.capitalize())
        self._glyph = self._glyph_item()
        self.draw()

    def set(self, selected: bool, enabled: bool) -> None:
        """Set whether this mode is the one shown and whether it can be clicked."""
        self.set_selected(selected)
        self.set_enabled(enabled)

    def draw_content(self) -> None:
        """Glyph and value colours for selected / unselected / disabled."""
        if not self.enabled:
            glyph, val = TEXT_3, (TEXT_2 if self.selected else TEXT_3)
        elif self.selected:
            glyph, val = ACCENT, TEXT
        else:
            glyph, val = TEXT_2, (TEXT if self.hover else TEXT_2)
        self.cv.itemconfigure(self._glyph, image=self.ui.images.icon(MODE_ICONS[self.mode], GLYPH, glyph))
        self.value.set(self.value.text, val)


# ==========================================================================
# Non-clickable items
# ==========================================================================
class StatusLine:
    """A small centred status: a coloured dot and a short label."""

    DOT, GAP = 8, 7

    def __init__(self, ui: App, cx: float, cy: float) -> None:
        self.ui, self.cv, self.cx, self.cy = ui, ui.cv, cx, cy
        self._dot = self.cv.create_image(0, cy, anchor="w")
        self.label = CText(self.cv, 0, cy, "", ui.f.small, anchor="w")
        self._state: Optional[tuple[str, str, str]] = None

    def set(self, text: str, dot: str, fill: str) -> None:
        """Show ``text`` in ``fill`` after a dot in ``dot``."""
        if (text, dot, fill) == self._state:
            return
        self._state = (text, dot, fill)
        total = self.DOT + self.GAP + self.ui.f.small.measure(text)
        left = self.cx - total / 2
        self.cv.coords(self._dot, round(left), self.cy + 1)
        self.cv.itemconfigure(self._dot, image=self.ui.images.get(
            ("dot", self.DOT, dot), lambda: render_dot(self.DOT, dot)))
        self.label.move_to(left + self.DOT + self.GAP, self.cy)
        self.label.set(text, fill)


class StatItem:
    """One item of the readback bar: a glyph over a short label.

    While live (connected) it gets the lighter rounded backdrop and white text.
    """

    GLYPH = 22

    def __init__(self, ui: App, cx: int, y0: int, w: int, h: int, icon: str) -> None:
        self.ui, self.cv = ui, ui.cv
        self.icon = icon
        color, opacity = BAR_ACTIVE
        backdrop = ui.images.get(("wash", w, h, None, color, opacity),
                                 lambda: render_wash(w, h, 20, color, opacity))
        self._bg = self.cv.create_image(cx - w // 2, y0, anchor="nw", state="hidden", image=backdrop)
        self._glyph = self.cv.create_image(cx, y0 + 22, anchor="center")
        self.label = CText(self.cv, cx, y0 + 46, "", ui.f.small, anchor="center")
        self._state: Optional[tuple[str, str, bool]] = None

    def set(self, text: str, live: bool, icon: Optional[str] = None) -> None:
        """Show ``text`` (and optionally another glyph); ``live`` gives the active look."""
        icon = icon or self.icon
        if (text, icon, live) == self._state:
            return
        self._state, self.icon = (text, icon, live), icon
        col = TEXT if live else TEXT_2
        self.cv.itemconfigure(self._bg, state="normal" if live else "hidden")
        self.cv.itemconfigure(self._glyph, image=self.ui.images.icon(icon, self.GLYPH, col))
        self.label.set(text, col)
