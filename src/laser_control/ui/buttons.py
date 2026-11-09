"""The window's home-made buttons: registering them, hover / press looks, and clicks.

Why home-made
-------------
Tk's own buttons can't have soft shadows, so every button here is a set of
images and text drawn on the one canvas (see :mod:`art`). This file makes those
drawings behave like buttons.

The problem it solves
---------------------
The window redraws the whole canvas whenever anything changes (a result from
the laser can arrive at any time), and a redraw deletes every canvas item. So
a click can't be bound to a canvas item: the item might be deleted between
the mouse press and the release. Instead:

1. **While drawing**, each section calls :meth:`ButtonLayer.add` to register a
   button under a tag ``btn:<name>``, and tags every item that belongs to it
   (its hit area) with that tag.
2. **Mouse events** are bound once, on the canvas *widget*, which is never
   deleted. On press, :meth:`ButtonLayer.target_at` finds the tag under the
   pointer, and its bounding box is remembered.
3. **On release**, the click fires if the pointer is still inside that box,
   even if the canvas was redrawn in between.
4. **After each redraw**, :meth:`ButtonLayer.restore` re-applies the hover or
   pressed look, because the redraw recreated the items in their normal look.

Tags used
---------
``btn:<name>``       every item of the button: this is its clickable area
``btn:<name>.bg``    its background image, swapped for the hover / press image
``btn:<name>.fg``    its icon, swapped for the hover icon
``btn:<name>.fgt``   its text, recoloured on hover
``dial``             the power dial; presses and drags on it go to :mod:`power`
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable

from laser_control.ui.art import Sprite

if TYPE_CHECKING:  # only for type hints; avoids a circular import at runtime
    from laser_control.ui.window import MainWindow

SHIFT_MASK = 0x1  # bit in a Tk event's ``state`` that is set while Shift is held
SCROLL_STEP = 3   # log rows per wheel notch


@dataclass
class Button:
    """One registered button, valid until the next redraw.

    The ``bg`` / ``fg`` / ``fg_text`` dictionaries map a look (``"normal"``,
    ``"hover"``, ``"press"``) to the image or text colour for it. A look that
    is missing falls back to ``"normal"``.
    """

    enabled: bool
    on_click: Callable[[], None] | None
    bg: dict[str, Sprite] = field(default_factory=dict)
    fg: dict[str, Sprite] = field(default_factory=dict)
    fg_text: dict[str, str] = field(default_factory=dict)


class ButtonLayer:
    """Registers the canvas buttons for each redraw, and handles the mouse for them.

    Args:
        win: The main window; this uses its canvas, and hands dial events to
            ``win.power_input``.
    """

    def __init__(self, win: MainWindow):
        self.win = win
        self.registered: dict[str, Button] = {}    # tag -> button, rebuilt on every redraw
        self.origins: dict[str, tuple[float, float]] = {}
        """Where each ``<tag>.bg`` image's shape was placed (logical px), for swapping looks."""
        self.hover: str | None = None              # tag under the mouse
        self.pressed: str | None = None            # tag the mouse button went down on
        self.press_box: tuple[int, int, int, int] | None = None
        self.shift_held = False                    # Shift was held at the last press: −/+ step 1 mW

        c = win.canvas
        c.bind("<Motion>", self._on_motion)
        c.bind("<Leave>", lambda e: self._set_hover(None))
        c.bind("<ButtonPress-1>", self._on_press)
        c.bind("<B1-Motion>", self._on_drag)
        c.bind("<ButtonRelease-1>", self._on_release)
        c.bind("<MouseWheel>", lambda e: self._on_wheel(e.x, e.y, e.delta))  # Windows and macOS
        c.bind("<Button-4>", lambda e: self._on_wheel(e.x, e.y, 1))          # Linux wheel up
        c.bind("<Button-5>", lambda e: self._on_wheel(e.x, e.y, -1))         # Linux wheel down

    # ---- used while drawing ----

    def clear(self) -> None:
        """Forget all buttons; called at the start of every redraw."""
        self.registered.clear()
        self.origins.clear()

    def add(self, name: str, enabled: bool, on_click: Callable[[], None] | None, *,
            bg: dict[str, Sprite] | None = None, fg: dict[str, Sprite] | None = None,
            fg_text: dict[str, str] | None = None) -> str:
        """Register a button for this redraw and return its tag, ``btn:<name>``.

        Tag the items that make up the button with the returned tag; for hover
        and press looks, also tag them ``<tag>.bg`` / ``<tag>.fg`` / ``<tag>.fgt``.
        """
        tag = f"btn:{name}"
        self.registered[tag] = Button(enabled, on_click, bg or {}, fg or {}, fg_text or {})
        return tag

    def remember_origin(self, tag: str, x: float, y: float) -> None:
        """Remember where a button's background shape was placed (called by :func:`paint.image`)."""
        self.origins[tag] = (x, y)

    def restore(self) -> None:
        """Re-apply the pressed / hover look after a redraw recreated the items."""
        if self.pressed in self.registered:
            self.show(self.pressed, "press")
        elif self.hover in self.registered and self.registered[self.hover].enabled:
            self.show(self.hover, "hover")

    # ---- looks ----

    def show(self, tag: str, look: str) -> None:
        """Switch a button to a look: ``"normal"``, ``"hover"`` or ``"press"``."""
        b = self.registered.get(tag)
        if not b:
            return
        c, px = self.win.canvas, self.win.art.px
        if b.bg:
            sprite = b.bg.get(look) or b.bg["normal"]
            c.itemconfigure(f"{tag}.bg", image=sprite.photo)
            # The looks can have different shadow margins (``pad``), so place the
            # new image again, to keep the shape itself exactly where it was.
            origin = self.origins.get(f"{tag}.bg")
            if origin:
                c.coords(f"{tag}.bg", px(origin[0]) - sprite.pad, px(origin[1]) - sprite.pad)
        if b.fg:
            sprite = b.fg.get(look) or b.fg["normal"]
            c.itemconfigure(f"{tag}.fg", image=sprite.photo)
        if b.fg_text:
            c.itemconfigure(f"{tag}.fgt", fill=b.fg_text.get(look) or b.fg_text["normal"])

    # ---- the mouse ----

    def target_at(self, x: int, y: int) -> str | None:
        """What is under device point ``(x, y)``: a ``btn:<name>`` tag, ``"dial"``, or None.

        The topmost item wins. Tags with a dot (``btn:key.bg``) are looks, not
        buttons, so they are skipped.
        """
        c = self.win.canvas
        for item in reversed(c.find_overlapping(x, y, x, y)):
            for tag in c.gettags(item):
                if tag == "dial" or (tag.startswith("btn:") and "." not in tag):
                    return tag
        return None

    def _on_motion(self, event) -> None:
        if not self.pressed:   # while a button is held down, it keeps its pressed look
            self._set_hover(self.target_at(event.x, event.y))

    def _set_hover(self, target: str | None) -> None:
        if target == self.hover:
            return
        if self.hover in self.registered:
            self.show(self.hover, "normal")
        self.hover = target
        b = self.registered.get(target) if target else None
        if b is not None and b.enabled:
            self.show(target, "hover")
        clickable = (b is not None and b.enabled) or (target == "dial" and self.win.state.power_editable)
        self.win.canvas.configure(cursor="hand2" if clickable else "")

    def _on_press(self, event) -> None:
        # A click anywhere on the canvas cancels typing in the power field, like Esc. The canvas
        # never takes keyboard focus, so the field's FocusOut doesn't fire on its own; without
        # this, − / + would do nothing and the key would turn the laser on with the typed value
        # still showing. (close_editor redraws, so look up the target only after it.)
        self.win.power_input.close_editor()
        self.shift_held = bool(event.state & SHIFT_MASK)
        target = self.target_at(event.x, event.y)
        if target == "dial":
            self.win.power_input.press_dial(event.x, event.y)
            return
        b = self.registered.get(target) if target else None
        if b and b.enabled:
            self.pressed = target
            self.press_box = self.win.canvas.bbox(target)
            self.show(target, "press")

    def _on_drag(self, event) -> None:
        if self.win.power_input.dragging:
            self.win.power_input.drag_dial(event.x, event.y)

    def _on_release(self, event) -> None:
        if self.win.power_input.dragging:
            self.win.power_input.release_dial()
            return
        pressed, box = self.pressed, self.press_box
        self.pressed = self.press_box = None
        if not pressed:
            return
        inside = box is not None and box[0] <= event.x <= box[2] and box[1] <= event.y <= box[3]
        b = self.registered.get(pressed)
        if b:
            self.show(pressed, "hover" if inside and b.enabled else "normal")
        self.hover = pressed if inside else None
        if inside and b and b.enabled and b.on_click:   # released outside: no click, like a normal button
            b.on_click()

    def _on_wheel(self, x: int, y: int, delta: int) -> None:
        """The wheel scrolls the log on the Log tab, and turns the dial when over it."""
        if self.win.state.tab == "log":
            self.win.log_view.scroll(-SCROLL_STEP if delta > 0 else SCROLL_STEP)   # wheel up: older lines
        elif self.target_at(x, y) == "dial":
            self.win.power_input.close_editor()   # as for a click: cancel typing, then turn the dial
            self.win.power_input.nudge(0.1 if delta > 0 else -0.1)
