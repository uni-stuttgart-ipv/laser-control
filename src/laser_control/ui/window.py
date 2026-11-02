"""The main window: one Tk canvas drawn from the controller's snapshot.

Rendering model
---------------
The whole canvas is redrawn from scratch whenever the snapshot or local UI
state changes (``render()``). That keeps drawing code a straight top-to-bottom
function of state, and is cheap because every image is cached in
:class:`~laser_control.ui.art.Art`. The spinner and the emission pulse only
swap angles or images on existing items, without a redraw.

Input model
-----------
Because a redraw deletes every item, mouse handling must not depend on canvas
items surviving between press and release (a status poll redraws about once a
second). So all mouse events are bound on the canvas *widget*, never on item
tags:

* Clickable regions are registered each redraw with :meth:`MainWindow._button`
  under a tag ``btn:<name>``; the dial uses the tag ``dial``.
* On press, :meth:`MainWindow._target_at` finds the region under the pointer
  and remembers its name and bounding box.
* On release, the click fires if the pointer is still inside that box, even if
  the canvas was redrawn in between. Dial drags work the same way.
* After every redraw the hover and pressed looks are re-applied.

Layout, top to bottom: header, port row, mode bar, power card
(manual mode only), laser card, message line, readouts. All coordinates below
are logical pixels; ``Art.px`` converts to device pixels.
"""

from __future__ import annotations

import math
import tkinter as tk
from dataclasses import dataclass, field
from typing import Callable

from laser_control.controller import CAMERA_POWER_MW, REFUSED_TITLE, LaserController, controls_for
from laser_control.model import ConnState, Emission, Mode, Snapshot, UserMessage
from laser_control.ui import chrome
from laser_control.ui import theme as T
from laser_control.ui.art import Art, Glow, Ring, Sprite

# ---- layout constants (logical px) ----
PAD_X = 22
CONTENT_W = T.WIDTH - 2 * PAD_X  # 356
GAP = 15
PORT_FIELD_W = 232
PILL_W = 112
POWER_H = 176
LASER_H = 82
DIAL = 152
KEY = 58

DIAL_A0, DIAL_SWEEP = 135.0, 270.0
PULSE_FRAMES = 8
APPLIED_TOLERANCE_MW = 0.05
"""Half the dial step, so a laser that rounds its set point still reads as applied."""



@dataclass
class _Button:
    """Registration of one clickable canvas region (see ``MainWindow._button``)."""

    enabled: bool
    on_click: Callable[[], None] | None
    bg: dict[str, Sprite] = field(default_factory=dict)  # "normal" / "hover" / "press"
    fg: dict[str, Sprite] = field(default_factory=dict)
    fg_text: dict[str, str] = field(default_factory=dict)  # text colours by state


def dial_value(dx: float, dy: float, max_mw: float) -> float:
    """Map a pointer offset from the dial centre to a power.

    The dial sweeps 270° clockwise from 135° (bottom left). Pointer angles in
    the 90° gap at the bottom snap to the nearer end.
    """
    angle = math.degrees(math.atan2(dy, dx))
    t = (angle - DIAL_A0) % 360
    if t > DIAL_SWEEP:
        t = 0.0 if t > DIAL_SWEEP + (360 - DIAL_SWEEP) / 2 else DIAL_SWEEP
    return t / DIAL_SWEEP * max_mw


class MainWindow:
    """Builds and updates the UI.

    Args:
        root: The Tk root window.
        controller: The app controller; the window only calls its public API.
        title_suffix: Appended to the window title (e.g. " (simulation)").
    """

    def __init__(self, root: tk.Tk, controller: LaserController, title_suffix: str = ""):
        self.root = root
        self.ctl = controller
        self.scale = T.ui_scale(root)
        self.art = Art(root, self.scale)
        self.fonts = T.make_fonts(root, self.scale)
        self.title_suffix = title_suffix

        self.snap: Snapshot = controller.snapshot
        self.power = round(controller.manual_power_mw, 1)
        """Value on the dial. Only sent to the laser by Apply."""
        self.banner: UserMessage | None = None
        self.height = 0
        self._buttons: dict[str, _Button] = {}
        self._hover: str | None = None
        self._pressed: str | None = None
        self._press_box: tuple[int, int, int, int] | None = None
        self._dragging = False
        self._spin = 0
        self._pulse = 0
        self._editor: tk.Entry | None = None
        self._emitting_shown: bool | None = None
        self._dial_center = (0.0, 0.0)
        self._port_y = 0.0
        self._menu: tk.Menu | None = None
        self._shift = False

        root.configure(bg=T.BASE)
        root.resizable(False, False)
        self.canvas = tk.Canvas(root, width=self.art.px(T.WIDTH), height=10, bg=T.BASE,
                                highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self._bind_static()
        controller.subscribe(self._on_state, self._on_message)
        self._tick()

    # ================================================================ events from the controller

    def _on_state(self, snap: Snapshot) -> None:
        previous = self.snap
        self.snap = snap
        if not self._power_editable():
            # Outside manual editing the dial always shows the applied power, so
            # an unapplied value can never be sent by a later mode change.
            self.power = self._clamp(round(self.ctl.manual_power_mw, 1))
        if snap.emission is Emission.ON and previous.emission is not Emission.ON and self.banner \
                and self.banner.title == REFUSED_TITLE:
            self.banner = None
        if snap.conn is ConnState.ERROR and snap.last_error and previous.last_error != snap.last_error:
            self.banner = snap.last_error
        self.render()

    def _on_message(self, msg: UserMessage) -> None:
        if msg.level == "info":
            return  # hints are derived from state
        self.banner = msg
        self.render()

    def show_internal_error(self) -> None:
        """Called by the app when a Tk callback raised; the details are in the log."""
        self.banner = UserMessage("error", "Internal error",
                                  "Something went wrong in the app (details are in the log). "
                                  "Esc still turns the laser off.")
        try:
            self.render()
        except Exception:
            pass

    # ================================================================ input

    def _bind_static(self) -> None:
        c = self.canvas
        c.bind("<Motion>", self._on_motion)
        c.bind("<Leave>", lambda e: self._set_hover(None))
        c.bind("<ButtonPress-1>", self._on_press)
        c.bind("<B1-Motion>", self._on_drag)
        c.bind("<ButtonRelease-1>", self._on_release)
        c.bind("<MouseWheel>", lambda e: self._on_wheel(e.x, e.y, e.delta))
        c.bind("<Button-4>", lambda e: self._on_wheel(e.x, e.y, 1))  # X11 wheel up
        c.bind("<Button-5>", lambda e: self._on_wheel(e.x, e.y, -1))  # X11 wheel down
        self.root.bind_all("<Escape>", self._on_escape)
        self.root.bind_all("<Return>", lambda e: self._apply() if self._dirty() else None)
        self.root.bind_all("<Up>", lambda e: self._nudge(0.1))
        self.root.bind_all("<Down>", lambda e: self._nudge(-0.1))
        self.root.bind_all("<Shift-Up>", lambda e: self._nudge(1.0))
        self.root.bind_all("<Shift-Down>", lambda e: self._nudge(-1.0))

    def _target_at(self, x: int, y: int) -> str | None:
        """Name of the clickable region under device point ``(x, y)``: ``btn:<name>``, ``dial`` or None."""
        for item in reversed(self.canvas.find_overlapping(x, y, x, y)):
            for tag in self.canvas.gettags(item):
                if tag == "dial" or (tag.startswith("btn:") and "." not in tag):
                    return tag
        return None

    def _on_motion(self, event) -> None:
        if not self._pressed:
            self._set_hover(self._target_at(event.x, event.y))

    def _set_hover(self, target: str | None) -> None:
        if target == self._hover:
            return
        if self._hover in self._buttons:
            self._show(self._hover, "normal")
        self._hover = target
        b = self._buttons.get(target) if target else None
        clickable = (b is not None and b.enabled) or (target == "dial" and self._power_editable())
        if b is not None and b.enabled:
            self._show(target, "hover")
        self.canvas.configure(cursor="hand2" if clickable else "")

    def _on_press(self, event) -> None:
        self._shift = bool(event.state & 0x1)  # Shift held: the ± keys step 1 mW
        target = self._target_at(event.x, event.y)
        if target == "dial":
            self._dial_press(event)
            return
        b = self._buttons.get(target) if target else None
        if b and b.enabled:
            self._pressed = target
            self._press_box = self.canvas.bbox(target)
            self._show(target, "press")

    def _on_drag(self, event) -> None:
        if self._dragging:
            self._dial_drag(event.x, event.y)

    def _on_release(self, event) -> None:
        if self._dragging:
            self._dragging = False
            return
        pressed, box = self._pressed, self._press_box
        self._pressed = self._press_box = None
        if not pressed:
            return
        inside = box is not None and box[0] <= event.x <= box[2] and box[1] <= event.y <= box[3]
        b = self._buttons.get(pressed)
        if b:
            self._show(pressed, "hover" if inside and b.enabled else "normal")
        self._hover = pressed if inside else None
        if inside and b and b.enabled and b.on_click:
            b.on_click()

    def _on_escape(self, _event=None) -> None:
        """Esc always sends off (while connected); it also closes the power editor."""
        if self._editor is not None:
            self._close_editor()
        self.ctl.laser_off()

    # ---- actions ----

    def _connect_clicked(self) -> None:
        conn = self.snap.conn
        if conn is ConnState.CONNECTED:
            self.ctl.disconnect()
        elif conn is ConnState.CONNECTING:
            self.ctl.cancel_connect()
        else:
            self.banner = None
            self.ctl.connect()

    def _mode_clicked(self, mode: Mode) -> None:
        if mode is self.snap.mode and not self.snap.connected:
            return
        if self.banner and self.banner.level == "warning":
            self.banner = None
        self._close_editor()
        self.ctl.select_mode(mode)

    def _apply(self) -> None:
        self.ctl.set_power(self.power)

    def _laser_clicked(self) -> None:
        s = self.snap
        if s.emission is Emission.OFF and not s.emission_warning:
            self.ctl.laser_on()
        else:  # on, unknown, or not confirmed off: the key always means "off"
            self.ctl.laser_off()

    def _dismiss(self) -> None:
        self.banner = None
        self.render()

    def _show_port_menu(self) -> None:
        if self._menu is not None:
            self._menu.destroy()
        self._menu = menu = tk.Menu(self.root, tearoff=0)
        self._port_var = tk.StringVar(self.root, value=self.snap.port)  # kept on self so it is not collected
        found = self.ctl.list_ports()
        if not found:
            menu.add_command(label="No serial ports found", state="disabled")
        for p in found:
            label = p.device if p.description in ("", p.device, "n/a") else f"{p.device}    {p.description}"
            menu.add_radiobutton(label=label, value=p.device, variable=self._port_var,
                                 command=lambda d=p.device: self._port_chosen(d))
        x = self.canvas.winfo_rootx() + self.art.px(PAD_X + 30)
        y = self.canvas.winfo_rooty() + self.art.px(self._port_y + 46)
        menu.tk_popup(x, y)

    def _port_chosen(self, device: str) -> None:
        self.banner = None
        self.ctl.select_port(device)

    def _refresh_ports(self) -> None:
        found = [p.device for p in self.ctl.list_ports()]
        if found and self.snap.port not in found:
            self.ctl.select_port(found[0])
        self.render()

    # ---- power dial ----

    def _power_editable(self) -> bool:
        return controls_for(self.snap).power_edit and self.snap.limits is not None

    def _dirty(self) -> bool:
        s = self.snap
        if not self._power_editable():
            return False
        return s.setpoint_mw is None or abs(s.setpoint_mw - self.power) > APPLIED_TOLERANCE_MW

    def _clamp(self, value: float) -> float:
        """Round to the dial's 0.1 mW step, then keep within the laser's limits."""
        lim = self.snap.limits
        value = round(value, 1)
        return min(max(value, lim.min_mw), lim.max_mw) if lim else value

    def _set_power(self, value: float) -> None:
        if self.snap.limits is None or not math.isfinite(value):
            return
        value = self._clamp(value)
        if value != self.power:
            self.power = value
            self.render()

    def _nudge(self, delta: float) -> None:
        if self._power_editable() and self._editor is None:
            self._set_power(self.power + delta)

    def _on_wheel(self, x: int, y: int, delta: int) -> None:
        if self._target_at(x, y) == "dial":
            self._nudge(0.1 if delta > 0 else -0.1)

    def _dial_press(self, event) -> None:
        if not self._power_editable():
            return
        cx, cy = self._dial_center
        if math.hypot(event.x - self.art.px(cx), event.y - self.art.px(cy)) < self.art.px(45):
            self._open_editor()  # the reading in the middle
            return
        self._dragging = True
        self._dial_drag(event.x, event.y)

    def _dial_drag(self, x: int, y: int) -> None:
        if not self._power_editable():
            self._dragging = False
            return
        cx, cy = self._dial_center
        self._set_power(dial_value(x - self.art.px(cx), y - self.art.px(cy), self.snap.limits.max_mw))

    def _open_editor(self) -> None:
        """Replace the dial reading with a text field. Enter applies, Esc cancels."""
        if self._editor is not None:
            return
        entry = tk.Entry(self.canvas, font=self.fonts.reading, justify="center", bd=0, relief="flat",
                         bg=T.BASE, fg=T.TEXT, insertbackground=T.AMBER_2, highlightthickness=0,
                         width=5)
        entry.insert(0, f"{self.power:.1f}")
        entry.select_range(0, "end")
        entry.bind("<Return>", self._commit_editor)
        entry.bind("<Escape>", lambda e: self._close_editor())  # falls through: Esc also turns the laser off
        entry.bind("<FocusOut>", lambda e: self._close_editor())
        self._editor = entry
        self.render()
        entry.focus_set()

    def _commit_editor(self, _e=None) -> str:
        text = self._editor.get().strip().replace(",", ".") if self._editor else ""
        self._close_editor()
        try:
            value = float(text)
            if not math.isfinite(value):
                raise ValueError(text)
        except ValueError:
            self.banner = UserMessage("warning", "Not a number", f"“{text}” is not a power in mW.")
            self.render()
            return "break"
        self._set_power(value)
        if self._dirty():
            self._apply()
        return "break"

    def _close_editor(self) -> None:
        if self._editor is not None:
            editor, self._editor = self._editor, None
            editor.destroy()
            self.render()

    # ================================================================ buttons

    def _button(self, name: str, enabled: bool, on_click: Callable[[], None] | None, *,
                bg: dict[str, Sprite] | None = None, fg: dict[str, Sprite] | None = None,
                fg_text: dict[str, str] | None = None) -> str:
        """Register a clickable region for this redraw; returns its tag (``btn:<name>``).

        Items drawn with this tag form the hit area. For hover and press
        feedback, ``bg`` and ``fg`` image sets are swapped on the items tagged
        ``<tag>.bg`` / ``<tag>.fg``, and ``fg_text`` recolours text items
        tagged ``<tag>.fgt``.
        """
        tag = f"btn:{name}"
        self._buttons[tag] = _Button(enabled, on_click, bg or {}, fg or {}, fg_text or {})
        return tag

    def _show(self, tag: str, state: str) -> None:
        b = self._buttons.get(tag)
        if not b:
            return
        c = self.canvas
        if b.bg:
            sprite = b.bg.get(state) or b.bg["normal"]
            c.itemconfigure(f"{tag}.bg", image=sprite.photo)
        if b.fg:
            sprite = b.fg.get(state) or b.fg["normal"]
            c.itemconfigure(f"{tag}.fg", image=sprite.photo)
        if b.fg_text:
            c.itemconfigure(f"{tag}.fgt", fill=b.fg_text.get(state) or b.fg_text["normal"])

    def _restore_feedback(self) -> None:
        """Re-apply the pressed / hover look after a redraw recreated the items."""
        if self._pressed in self._buttons:
            self._show(self._pressed, "press")
        elif self._hover in self._buttons and self._buttons[self._hover].enabled:
            self._show(self._hover, "hover")

    # ================================================================ drawing helpers

    def _img(self, x: float, y: float, sprite: Sprite, tags=()) -> int:
        return self.canvas.create_image(self.art.px(x) - sprite.pad, self.art.px(y) - sprite.pad,
                                        image=sprite.photo, anchor="nw", tags=tags)

    def _icon(self, cx: float, cy: float, sprite: Sprite, tags=()) -> int:
        return self.canvas.create_image(self.art.px(cx), self.art.px(cy), image=sprite.photo,
                                        anchor="center", tags=tags)

    def _text(self, x: float, y: float, text: str, font, fill: str, anchor: str = "nw", tags=(),
              width: float | None = None) -> int:
        kw = {"width": self.art.px(width)} if width else {}
        return self.canvas.create_text(self.art.px(x), self.art.px(y), text=text, font=font, fill=fill,
                                       anchor=anchor, tags=tags, **kw)

    def _hit(self, x: float, y: float, w: float, h: float, tags, fill: str = T.BASE) -> None:
        """An invisible hit area.

        Canvas shapes only receive clicks where they are filled, so the area is
        filled with the colour underneath; place it over flat parts only.
        """
        p = self.art.px
        self.canvas.create_rectangle(p(x), p(y), p(x + w), p(y + h), fill=fill, outline="", tags=tags)

    def _spinner(self, cx: float, cy: float, r: float, color: str) -> None:
        p = self.art.px
        box = (p(cx - r), p(cy - r), p(cx + r), p(cy + r))
        self.canvas.create_oval(*box, outline=T.TEXT_OFF, width=max(1, p(2)))
        self.canvas.create_arc(*box, start=self._spin, extent=90, style="arc", outline=color,
                               width=max(1, p(2.2)), tags=("spinner",))

    def _text_width(self, text: str, font) -> float:
        return font.measure(text) / self.scale

    # ================================================================ render

    def render(self) -> None:
        """Redraw everything from ``self.snap`` and local UI state."""
        s = self.snap
        ctl = controls_for(s)
        c = self.canvas
        if self._editor is not None and (s.mode is Mode.CAMERA or not self._power_editable()):
            editor, self._editor = self._editor, None  # the power card is gone or locked
            editor.destroy()
        c.delete("all")
        self._buttons.clear()

        y = 18
        self._draw_header(s, y)
        y += 48 + GAP
        self._port_y = y
        self._draw_port_row(s, ctl, y)
        y += 44 + GAP
        y = self._draw_mode(s, ctl, y)
        if s.mode is not Mode.CAMERA:
            self._draw_power(s, y)
            y += POWER_H + GAP
        self._draw_laser(s, ctl, y)
        y += LASER_H + 11
        y += self._draw_message(s, y) + GAP
        self._draw_readouts(s, y)
        y += 56 + 16

        if s.emitting:
            p = self.art.px
            c.create_rectangle(p(1), p(1), p(T.WIDTH) - p(1), p(y) - p(1), outline=T.EMIT, width=p(2))
        self._resize(y)
        self._update_title(s)
        self._restore_feedback()

    def _resize(self, height: float) -> None:
        h = self.art.px(height)
        if h != self.height:
            self.height = h
            self.canvas.configure(height=h)
            self.root.geometry(f"{self.art.px(T.WIDTH)}x{h}")

    def _update_title(self, s: Snapshot) -> None:
        emitting = s.emitting
        self.root.title(("Emitting – Laser Control" if emitting else "Laser Control") + self.title_suffix)
        if emitting != self._emitting_shown:
            self._emitting_shown = emitting
            if emitting:
                chrome.set_caption(self.root, T.TITLEBAR_EMIT, T.EMIT_INK, T.EMIT)
            else:
                chrome.set_caption(self.root, None, None, None)

    # ---- sections ----

    def _draw_header(self, s: Snapshot, y: float) -> None:
        f = self.fonts
        self._text(PAD_X, y - 2, "Laser Control", f.title, T.TEXT)
        if s.limits:
            sub = f"{s.limits.min_mw:g} to {s.limits.max_mw:g} mW, nominal {s.limits.nom_mw:g}"
        else:
            sub = "Serial laser controller"
        self._text(PAD_X, y + 30, sub, f.small, T.TEXT_3)

        right, cy = PAD_X + CONTENT_W, y + 38
        if s.emitting:
            label, color, dot, weight = "Emitting", T.EMIT_TEXT, T.EMIT, True
        elif s.emission_warning:
            label, color, dot, weight = "May still be on", T.WARN, T.WARN, True
        elif s.connected:
            label, color, dot, weight = "Connected", T.TEXT_2, T.OK, False
        elif s.conn is ConnState.CONNECTING:
            label, color, dot, weight = "Connecting", T.TEXT_3, None, False
        elif s.conn is ConnState.ERROR and s.last_error:
            label, color, dot, weight = s.last_error.title, T.ERR, T.ERR, False
        else:
            label, color, dot, weight = "Not connected", T.TEXT_3, T.TEXT_3, False
        font = f.label if weight else f.small
        self._text(right, cy, label, font, color, anchor="e")
        dx = right - self._text_width(label, font) - 10
        p = self.art.px
        if dot is None:
            self._spinner(dx, cy, 5, T.TEXT_2)
        else:
            if s.emitting:
                self.canvas.create_oval(p(dx - 6.5), p(cy - 6.5), p(dx + 6.5), p(cy + 6.5), fill=T.EMIT_WASH,
                                        outline="")
            self.canvas.create_oval(p(dx - 3.5), p(cy - 3.5), p(dx + 3.5), p(cy + 3.5), fill=dot, outline="")

    def _draw_port_row(self, s: Snapshot, ctl, y: float) -> None:
        f, a = self.fonts, self.art
        self._img(PAD_X, y, a.soft(PORT_FIELD_W, 44, 22, "press"))
        self._icon(PAD_X + 24, y + 22, a.icon("plug", 17, T.TEXT_3))

        name_x = PAD_X + 42
        if ctl.port_select:
            tag = self._button("port", True, self._show_port_menu, fg_text={"normal": T.TEXT, "hover": T.AMBER_2})
            w = self._text_width(s.port, f.port)
            self._hit(name_x - 4, y + 12, w + 30, 20, (tag,))
            self._text(name_x, y + 22, s.port, f.port, T.TEXT, anchor="w", tags=(tag, f"{tag}.fgt"))
            self._icon(name_x + w + 11, y + 23, a.icon("chev", 15, T.TEXT_3), tags=(tag,))
            kx = PAD_X + PORT_FIELD_W - 5 - 34
            rtag = self._button("refresh", True, self._refresh_ports,
                                bg={"normal": a.soft(34, 34, 17, "raise_sm"), "press": a.soft(34, 34, 17, "press_sm")},
                                fg={"normal": a.icon("refresh", 15, T.TEXT_2), "hover": a.icon("refresh", 15, T.AMBER_2)})
            self._img(kx, y + 5, a.soft(34, 34, 17, "raise_sm"), tags=(rtag, f"{rtag}.bg"))
            self._icon(kx + 17, y + 22, a.icon("refresh", 15, T.TEXT_2), tags=(rtag, f"{rtag}.fg"))
        else:
            self._text(name_x, y + 22, s.port, f.port, T.TEXT, anchor="w")
            room = PORT_FIELD_W - 42 - 16 - self._text_width(s.port, f.port)
            if room > self._text_width("19200 baud", f.small) + 10:  # long port names win over the baud label
                self._text(PAD_X + PORT_FIELD_W - 16, y + 22, "19200 baud", f.small, T.TEXT_3, anchor="e")

        x = PAD_X + PORT_FIELD_W + 12
        label = ctl.connect_label
        amber = label in ("Connect", "Retry")
        if amber:
            glow = Glow(T.AMBER_GLOW, 4, 6, 14)
            normal = a.soft(PILL_W, 44, 22, "raise_sm", gradient=(T.AMBER_1, T.AMBER_2), glow=glow)
            disabled = a.soft(PILL_W, 44, 22, "raise_sm", gradient=(T.AMBER_DISABLED_1, T.AMBER_DISABLED_2))
            pressed = a.soft(PILL_W, 44, 22, "flat", gradient=(T.AMBER_2, T.AMBER_1))
            ink = T.AMBER_INK
        else:
            normal = a.soft(PILL_W, 44, 22, "raise")
            disabled = a.soft(PILL_W, 44, 22, "raise_sm")
            pressed = a.soft(PILL_W, 44, 22, "press")
            ink = T.TEXT
        enabled = ctl.connect
        tag = self._button("connect", enabled, self._connect_clicked, bg={"normal": normal, "press": pressed})
        self._img(x, y, normal if enabled else disabled, tags=(tag, f"{tag}.bg"))
        if s.conn is ConnState.CONNECTING:  # spinner plus "Cancel"
            self._spinner(x + 26, y + 22, 7, T.AMBER_2)
            self._text(x + 42, y + 22, label, f.button, T.TEXT, anchor="w", tags=(tag,))
        else:
            color = ink if enabled else (T.TEXT_OFF if not amber else T.AMBER_INK)
            self._text(x + PILL_W / 2, y + 22, label, f.button, color, anchor="center", tags=(tag,))

    def _draw_mode(self, s: Snapshot, ctl, y: float) -> float:
        a, f = self.art, self.fonts
        self._img(PAD_X, y, a.soft(CONTENT_W, 52, 26, "raise"))
        half = (CONTENT_W - 12 - 1) / 2
        self.canvas.create_line(a.px(T.WIDTH / 2), a.px(y + 15), a.px(T.WIDTH / 2), a.px(y + 37),
                                fill=T.DIVIDER, width=max(1, a.px(1)))
        for i, (mode, icon, label) in enumerate(((Mode.CAMERA, "camera", "Camera"), (Mode.MANUAL, "sliders", "Manual"))):
            x = PAD_X + 6 + i * (half + 1)
            selected = s.mode is mode
            # Clicking the selected mode while connected re-runs its sequence
            # (for example to repeat the camera calibration).
            enabled = ctl.mode_select and (not selected or s.connected)
            tag = self._button(f"mode-{label.lower()}", enabled, lambda m=mode: self._mode_clicked(m),
                               fg_text={"normal": T.TEXT_2, "hover": T.TEXT})
            self._hit(x, y + 6, half, 40, (tag,))
            if selected:
                self._img(x, y + 6, a.soft(half, 40, 20, "press_sm"), tags=(tag,))
                icon_color, text_color = T.AMBER_2, T.TEXT
            elif ctl.mode_select:
                icon_color, text_color = T.TEXT_3, T.TEXT_2
            else:
                icon_color, text_color = T.TEXT_OFF, T.TEXT_OFF
            width = 18 + 9 + self._text_width(label, f.mode)
            left = x + half / 2 - width / 2
            self._icon(left + 9, y + 26, a.icon(icon, 18, icon_color, 1.9), tags=(tag,))
            self._text(left + 27, y + 26, label, f.mode, text_color, anchor="w", tags=(tag, f"{tag}.fgt"))

        hint_y = y + 52 + 9
        if s.applying is Mode.CAMERA:
            self._spinner(PAD_X + 10, hint_y + 8, 5, T.AMBER_2)
            self._text(PAD_X + 22, hint_y, f"Calibrating at {CAMERA_POWER_MW} mW…", f.small, T.TEXT_3)
        else:
            hint = (f"Pulsed. The camera drives power, calibrated at {CAMERA_POWER_MW} mW."
                    if s.mode is Mode.CAMERA else
                    "Mode not confirmed. Pick a mode again." if s.mode is Mode.UNKNOWN else
                    "Continuous. You set the power on the dial.")
            self._text(PAD_X + 4, hint_y, hint, f.small, T.WARN if s.mode is Mode.UNKNOWN else T.TEXT_3)
        return hint_y + 16 + GAP

    def _draw_power(self, s: Snapshot, y: float) -> None:
        a, f, p = self.art, self.fonts, self.art.px
        self._img(PAD_X, y, a.soft(CONTENT_W, POWER_H, 26, "raise"))
        on = s.connected and s.limits is not None
        editable = self._power_editable()
        lim = s.limits
        over = on and lim is not None and self.power > lim.nom_mw
        dirty = self._dirty()

        # dial
        dx, dy = PAD_X + 12, y + 12
        cx, cy = dx + DIAL / 2, dy + DIAL / 2
        self._dial_center = (cx, cy)
        max_mw = lim.max_mw if lim else 55.0
        self._img(dx, dy, a.dial(self.power, max_mw, lim.nom_mw if lim else None, on),
                  tags=("dial",) if editable else ())
        self._img(cx - 45, cy - 45, a.soft(90, 90, 45, "raise_sm"), tags=("dial",) if editable else ())
        if self._editor is not None:
            self.canvas.create_window(p(cx), p(cy - 4), window=self._editor, width=p(80), anchor="center")
        else:
            num = f"{self.power:.1f}"
            color = T.TEXT_OFF if not on else T.WARN if over else T.AMBER_NUM
            w_num, w_unit = self._text_width(num, f.reading), self._text_width("mW", f.tiny)
            left = cx - (w_num + 2 + w_unit) / 2
            tags = ("dial",) if editable else ()
            self._text(left, cy + 7, num, f.reading, color, anchor="sw", tags=tags)
            self._text(left + w_num + 2, cy + 3, "mW", f.tiny, T.TEXT_2, anchor="sw", tags=tags)
        caption = "set point" if not on else "not applied" if dirty else "applied"
        self._text(cx, cy + 12, caption, f.tiny, T.OK if on and not dirty else T.TEXT_3, anchor="n",
                   tags=("dial",) if editable else ())

        # side column
        sx, sw = dx + DIAL + 12, CONTENT_W - 12 - DIAL - 12 - 16
        if not on:
            lim_text, lim_color = "Limits load when connected.", T.TEXT_3
        elif over:
            lim_text, lim_color = f"Above nominal ({lim.nom_mw:g} mW).", T.WARN
        else:  # the range itself is already in the header
            lim_text, lim_color = "Drag the dial, or use − and +.", T.TEXT_3
        lines = 1 if self._text_width(lim_text, f.small) <= sw else 2
        total = 18 + 16 * lines + 10 + 38 + 10 + 38
        ty = y + (POWER_H - total) / 2
        self._text(sx, ty, "Power", f.label, T.TEXT)
        self._text(sx, ty + 18, lim_text, f.small, lim_color, width=sw)
        ky = ty + 18 + 16 * lines + 10
        for i, (name, delta, icon) in enumerate((("dec", -0.1, "minus"), ("inc", 0.1, "plus"))):
            at_limit = lim is not None and (self.power <= lim.min_mw if delta < 0 else self.power >= lim.max_mw)
            enabled = editable and not at_limit
            normal, pressed = a.soft(38, 38, 19, "raise_sm"), a.soft(38, 38, 19, "press_sm")
            tag = self._button(name, enabled, lambda d=delta: self._nudge(d * (10 if self._shift else 1)),
                               bg={"normal": normal, "press": pressed})
            bx = sx + i * 50
            self._img(bx, ky, normal, tags=(tag, f"{tag}.bg"))
            self._icon(bx + 19, ky + 19, a.icon(icon, 16, T.TEXT if enabled else T.TEXT_OFF, 2), tags=(tag,))
        ay = ky + 38 + 10
        if on and dirty:
            normal = a.soft(96, 38, 19, "raise_sm", gradient=(T.AMBER_1, T.AMBER_2), glow=Glow(T.AMBER_GLOW, 4, 6, 14))
            pressed = a.soft(96, 38, 19, "flat", gradient=(T.AMBER_2, T.AMBER_1))
            tag = self._button("apply", True, self._apply, bg={"normal": normal, "press": pressed})
            self._img(sx, ay, normal, tags=(tag, f"{tag}.bg"))
            self._text(sx + 48, ay + 19, "Apply", f.button, T.AMBER_INK, anchor="center", tags=(tag,))
        elif on:
            self._icon(sx + 8, ay + 19, a.icon("check", 15, T.OK, 2.25))
            self._text(sx + 21, ay + 19, "Applied", f.label, T.OK, anchor="w")
        else:
            self._img(sx, ay, a.soft(96, 38, 19, "raise_sm"))
            self._text(sx + 48, ay + 19, "Apply", f.button, T.TEXT_OFF, anchor="center")

    def _key_sprites(self) -> dict[str, Sprite]:
        a = self.art
        return {
            "idle": a.soft(KEY, KEY, KEY / 2, "raise"),
            "press": a.soft(KEY, KEY, KEY / 2, "press"),
            "disabled": a.soft(KEY, KEY, KEY / 2, "raise_sm"),
            "blocked": a.soft(KEY, KEY, KEY / 2, "raise", ring=Ring(T.WARN_ZONE, 2)),
        }

    def _pulse_sprite(self, frame: int) -> Sprite:
        """Emission key: pressed in, with an amber ring and glow that breathe.

        The glow blur stays fixed so every frame has the same padding and can be
        swapped in place without moving the item.
        """
        t = (1 - math.cos(2 * math.pi * frame / PULSE_FRAMES)) / 2  # 0..1..0
        ring = round(3 + 3 * t)
        alpha = round(0x82 - 0x3C * t)
        return self.art.soft(KEY, KEY, KEY / 2, "press", ring=Ring(T.EMIT_RING, ring),
                             glow=Glow(f"{T.EMIT_GLOW[:7]}{alpha:02X}", 0, 0, 22))

    def _draw_laser(self, s: Snapshot, ctl, y: float) -> None:
        """The laser card. Five looks, in priority order:

        * emitting: amber card, pulsing pressed-in key (press = off);
        * may still be on (``emission_warning``): red ring and text; the key
          sends off again while connected;
        * unknown (just connected): the key sends one off to start from a
          confirmed state;
        * off and connected: the key turns the laser on;
        * not connected: greyed out.
        """
        a, f = self.art, self.fonts
        emitting = s.emitting
        warning = s.emission_warning
        if emitting:
            card = a.soft(CONTENT_W, LASER_H, 26, "raise", gradient=(T.EMIT_WASH, T.BASE),
                          ring=Ring(T.EMIT, 2), glow=Glow(T.EMIT_GLOW, 0, 10, 30))
        elif warning:
            card = a.soft(CONTENT_W, LASER_H, 26, "raise", ring=Ring(T.WARN_ZONE, 2))
        else:
            card = a.soft(CONTENT_W, LASER_H, 26, "raise")
        self._img(PAD_X, y, card)

        x = PAD_X + 22
        if emitting:
            state = "Emitting"
            sub = ("Pulsed by the camera." if s.mode is Mode.CAMERA
                   else f"Continuous at {s.setpoint_mw or self.power:.1f} mW.") + " Esc turns it off."
            colors = (T.EMIT_TEXT, T.EMIT_TEXT, T.EMIT_TEXT)
        elif warning:
            state = "May still be on"
            sub = ("Off not confirmed. Press the key again." if s.connected
                   else "Off not confirmed. Check the laser.")
            colors = (T.WARN, T.WARN, T.WARN)
        elif s.connected and s.emission is Emission.UNKNOWN:
            state = "Unknown"
            sub = "Press the key once to confirm the laser is off."
            colors = (T.TEXT_3, T.TEXT, T.TEXT_3)
        elif s.connected:
            state = "Off"
            sub = ("Blocked by the open interlock." if s.on_refused else
                   "Wait for calibration." if s.applying is Mode.CAMERA else
                   "Pick a mode first." if s.mode is Mode.UNKNOWN else "Ready to turn on.")
            colors = (T.TEXT_3, T.TEXT, T.WARN if s.on_refused else T.TEXT_3)
        else:
            state = "Off"
            sub = "Waiting for the connection." if s.conn is ConnState.CONNECTING else "Connect first."
            colors = (T.TEXT_3, T.TEXT_OFF, T.TEXT_3)
        self._text(x, y + 12, "Laser", f.small, colors[0])
        self._text(x, y + 25, state, f.state, colors[1])
        self._text(x, y + 60, sub, f.small, colors[2])

        kx, ky = PAD_X + CONTENT_W - 14 - KEY, y + (LASER_H - KEY) / 2
        sprites = self._key_sprites()
        turns_on = s.emission is Emission.OFF and not warning
        if emitting:
            enabled, bg, glyph = ctl.laser_off, self._pulse_sprite(self._pulse), T.EMIT
            states = {"normal": bg}
        elif s.connected and not turns_on:  # unknown or unconfirmed: the key sends off
            enabled = ctl.laser_off
            bg = sprites["blocked"] if warning else sprites["idle"]
            glyph = T.WARN if warning else T.TEXT_2
            states = {"normal": bg, "press": sprites["press"]}
        elif s.connected:
            enabled = ctl.laser_on
            bg = sprites["blocked"] if s.on_refused else sprites["idle"] if enabled else sprites["disabled"]
            glyph = T.WARN if s.on_refused else T.TEXT_2 if enabled else T.TEXT_OFF
            states = {"normal": bg, "press": sprites["press"]}
        else:
            bg = sprites["blocked"] if warning else sprites["disabled"]
            enabled, glyph, states = False, T.WARN if warning else T.TEXT_OFF, {"normal": bg}
        hover_glyph = T.EMIT if emitting else T.AMBER_2
        tag = self._button("key", enabled, self._laser_clicked, bg=states,
                           fg={"normal": a.icon("power", 26, glyph, 2.25),
                               "hover": a.icon("power", 26, hover_glyph, 2.25)})
        self._img(kx, ky, bg, tags=(tag, f"{tag}.bg", "key.bg"))
        self._icon(kx + KEY / 2, ky + KEY / 2, a.icon("power", 26, glyph, 2.25), tags=(tag, f"{tag}.fg"))

    def _draw_message(self, s: Snapshot, y: float) -> float:
        """Draw the message line; returns its height.

        While emitting, the eye-protection line always stays; a warning or
        error banner is added below it rather than replacing it.
        """
        a, f = self.art, self.fonts
        banner = self.banner
        top = 0.0
        if s.emitting and banner and banner.level in ("warning", "error"):
            self._icon(PAD_X + 22, y + 12, a.icon("warn", 16, T.EMIT_TEXT))
            self._text(PAD_X + 37, y + 12, "Wear eye protection while the laser is on.", f.body, T.EMIT_TEXT,
                       anchor="w")
            top = 28
            y += top
        if banner and banner.level in ("warning", "error"):
            text = banner.text
            width = CONTENT_W - 37 - 34
            lines = 1 if self._text_width(text, f.body) <= width else 2
            h = 32 if lines == 1 else 48
            fill = T.WARN_BG if banner.level == "warning" else T.ERR_BG
            color = T.WARN if banner.level == "warning" else T.ERR
            self._img(PAD_X, y, a.soft(CONTENT_W, h, 16, "press_sm", fill=fill))
            self._icon(PAD_X + 23, y + h / 2, a.icon("warn", 18, color))
            self._text(PAD_X + 37, y + h / 2, text, f.body, T.TEXT, anchor="w", width=width)
            tag = self._button("dismiss", True, self._dismiss,
                               fg={"normal": a.icon("x", 15, T.TEXT_2), "hover": a.icon("x", 15, T.TEXT)})
            self._hit(PAD_X + CONTENT_W - 29, y + h / 2 - 10, 20, 20, (tag,), fill=fill)
            self._icon(PAD_X + CONTENT_W - 19, y + h / 2, a.icon("x", 15, T.TEXT_2), tags=(tag, f"{tag}.fg"))
            return top + h
        if s.emitting:
            icon, color, text = a.icon("warn", 16, T.EMIT_TEXT), T.EMIT_TEXT, "Wear eye protection while the laser is on."
        else:
            icon, color, text = a.icon("info", 15, T.TEXT_3), T.TEXT_3, self._hint(s)
        self._icon(PAD_X + 22, y + 16, icon)
        self._text(PAD_X + 37, y + 16, text, f.body, color, anchor="w", width=CONTENT_W - 40)
        return 32

    def _hint(self, s: Snapshot) -> str:
        if s.conn is ConnState.CONNECTING:
            return f"Opening {s.port}. This can take a while if the laser does not answer."
        if s.conn is ConnState.DISCONNECTING:
            return "Turning the laser off and closing the port."
        if not s.connected:
            if s.emission_warning:
                return "The laser may still be on. Check it, then reconnect to switch it off."
            return "Pick the laser’s port and connect."
        if s.emission_warning:
            return "Press the key or Esc to send off again."
        if s.emission is Emission.UNKNOWN:
            return "The app cannot tell if the laser is on. Press the key once to switch it off."
        if s.applying is Mode.CAMERA:
            return "Calibrating. The key unlocks in a moment."
        if s.applying is Mode.MANUAL:
            return "Switching to manual mode."
        if s.mode is Mode.CAMERA:
            return "The camera controls power. Turn the laser on when ready."
        if self._dirty():
            return f"Press Apply to send {self.power:.1f} mW to the laser."
        return "Set the power, then turn the laser on."

    def _draw_readouts(self, s: Snapshot, y: float) -> None:
        a, f, p = self.art, self.fonts, self.art.px
        self._img(PAD_X, y, a.soft(CONTENT_W, 56, 24, "raise"))
        on = s.connected
        cell = (CONTENT_W - 12) / 3
        sp = f"{s.setpoint_mw:.1f} mW" if on and s.setpoint_mw is not None else "— mW"
        cur = f"{s.current_ma:.1f} mA" if on and s.current_ma is not None else "— mA"
        cam = s.mode is Mode.CAMERA
        cells = ((sp, "Set point", T.TEXT), (cur, "Diode current", T.EMIT_TEXT if s.emitting else T.TEXT),
                 ("Pulsed" if cam else "CW", "Camera" if cam else "Manual", T.TEXT))
        for i, (value, label, color) in enumerate(cells):
            cx = PAD_X + 6 + cell * (i + 0.5)
            self._text(cx, y + 20, value, f.readout, color if on else T.TEXT_OFF, anchor="center")
            self._text(cx, y + 40, label, f.tiny, T.TEXT_3, anchor="center")
            if i:
                x = PAD_X + 6 + cell * i
                self.canvas.create_line(p(x), p(y + 14), p(x), p(y + 42), fill=T.DIVIDER, width=max(1, p(1)))

    # ================================================================ animation

    def _tick(self) -> None:
        """Rotate spinners every 40 ms and step the emission pulse every 160 ms."""
        self._spin = (self._spin - 12) % 360
        if self.canvas.find_withtag("spinner"):
            self.canvas.itemconfigure("spinner", start=self._spin)
        if self._spin % 48 == 0 and self.snap.emitting and self._pressed is None:
            self._pulse = (self._pulse + 1) % PULSE_FRAMES
            sprite = self._pulse_sprite(self._pulse)
            self.canvas.itemconfigure("key.bg", image=sprite.photo)
            if "btn:key" in self._buttons:
                self._buttons["btn:key"].bg["normal"] = sprite
        self.root.after(40, self._tick)
