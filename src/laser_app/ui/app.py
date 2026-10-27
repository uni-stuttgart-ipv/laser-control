"""The Laser Control window: ``App`` builds the canvas and renders it from the controller.

Threading rule: the GUI never talks to the laser. It calls the non-blocking
methods of ``LaserController`` and drains ``controller.events`` every
``POLL_MS`` with ``root.after``, so every Tk call happens on the Tk thread.

Rendering: ``render()`` is the single place that turns the latest ``Status``
into widget states. It is cheap when nothing changed, because every widget
only touches the canvas when its own state differs.

See ``layout.py`` for the window layout and ``widgets.py`` for the controls.
"""

from __future__ import annotations

import logging
import queue
import tkinter as tk
from tkinter import messagebox
from typing import Callable, Optional

from PIL import ImageTk

from ..config import Settings, save_settings
from ..controller import (POWER_REJECTED, LaserController, MessageEvent, Mode, Status,
                          StatusEvent, is_number)
from ..hardware.ports import PortInfo
from .layout import (APPLY_H, APPLY_W, BAR_ITEM_W, BAR_Y0, BAR_Y1, CAPTION_DY, CONN_BTN_DY,
                     CONN_BTN_H, CONN_BTN_W, CONN_CARD, CONN_STATUS_DY, CONN_Y0, CX, FIELD,
                     GLOW_CENTER, GLOW_RADIUS, GLYPH, GLYPH_D, HEAD_Y0, HEIGHT, ICON_BTN,
                     ICON_BTN_R, LASER_BTN, LASER_BTN_R, LASER_CY, LASER_SUB_Y, LASER_TITLE_Y,
                     MODE_CARDS, MODE_ICONS, MODES, MSG_Y, POWER_Y0, SCENE_DIVIDERS, SUBTITLE_Y,
                     TITLE_Y, WIDTH, X0, X1, scene_cards, scene_flats)
from .render import render_background, render_scene
from .text import Fonts, ellipsize
from .theme import (ACCENT, BG_BOTTOM, BUTTON, ERROR, LEVEL_COLORS, OFF_TEXT, ON, TEXT, TEXT_2,
                    TEXT_3, TEXT_ON_SELECTED)
from .widgets import (CardPane, Control, ConnectButton, CText, IconButton, Images, LaserButton,
                      ModeTile, PillButton, PortPicker, PowerField, StatItem, StatusLine)

log = logging.getLogger(__name__)

POLL_MS = 50                              # how often controller events are drained


class App:
    """Builds the window and renders it from the controller's latest ``Status``.

    Args:
        root: the Tk root to build into.
        controller: a started ``LaserController``.
        settings: loaded settings (updated and saved on close).
        list_ports: returns the serial ports to offer.
    """

    def __init__(self, root: tk.Tk, controller: LaserController, settings: Settings,
                 list_ports: Callable[[], list[PortInfo]]) -> None:
        self.root, self.controller, self.settings = root, controller, settings
        self.list_ports = list_ports
        self.f = Fonts()
        self.status: Status = controller.status
        try:
            self.selected_mode = Mode(settings.mode)   # mode chosen while disconnected
        except ValueError:
            self.selected_mode = Mode.MANUAL
        # A mode change / connect we sent but the worker has not finished yet;
        # the mode tiles show it until the request is over (see
        # _track_pending). The controller only reports busy once the worker
        # picks the job up, so "not busy" alone does not mean "done".
        self._pending_mode: Optional[Mode] = None
        self._pending_saw_busy = False
        # Last setpoint pushed into the field, so polls don't overwrite user edits.
        self._seen_setpoint: Optional[float] = None
        self._power_error: Optional[str] = None
        self._job: Optional[str] = None

        root.title("Laser Control")
        root.configure(bg=BG_BOTTOM)
        root.resizable(False, False)
        root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.images = Images(root)
        self.controls: list[Control] = []
        self._hover_ctl: Optional[Control] = None
        self._press_ctl: Optional[Control] = None
        self._pointer: Optional[tuple[int, int]] = None
        self._cursor = ""
        self._manual_shown = True

        self._build()
        self.power.set_value(settings.manual_power_mw)
        self.refresh_ports(prefer=settings.last_port, announce=False)
        self.set_message("Select a port and connect.")
        self.render()
        root.geometry(f"{WIDTH}x{HEIGHT}")

        # Clicking anywhere outside the power field ends editing (so status can update it).
        root.bind_all("<ButtonPress-1>", self._blur_fields, add="+")
        self._job = root.after(POLL_MS, self._drain)

    # ------------------------------------------------------------------ layout
    def _build(self) -> None:
        cv = self.cv = tk.Canvas(self.root, width=WIDTH, height=HEIGHT, bg=BG_BOTTOM, bd=0,
                                 highlightthickness=0, takefocus=0)
        cv.pack(fill="both", expand=True)

        # Both bases share one background so switching mode does not change
        # its (random) noise.
        background = render_background(WIDTH, HEIGHT, GLOW_CENTER, GLOW_RADIUS)
        self._bases = {}
        field_bg = BUTTON
        for manual in (True, False):
            img, flats = render_scene(background, scene_cards(manual), SCENE_DIVIDERS,
                                      scene_flats(manual))
            self._bases[manual] = ImageTk.PhotoImage(img, master=self.root)
            if flats:
                field_bg = flats[0]
        self._base = cv.create_image(0, 0, anchor="nw", image=self._bases[True])
        f = self.f

        # Header: refresh | title + connection state | connect
        CText(cv, CX, TITLE_Y, "Laser Control", f.title, anchor="center")
        self.conn_sub = CText(cv, CX, SUBTITLE_Y, "", f.body, fill=TEXT_2, anchor="center")
        self.refresh_btn = IconButton(self, X0, HEAD_Y0, ICON_BTN, ICON_BTN_R, "refresh",
                                      self.refresh_ports)
        self.connect_btn = IconButton(self, X1 - ICON_BTN, HEAD_Y0, ICON_BTN, ICON_BTN_R, "plug",
                                      self.toggle_connect)

        # Connection card: port | Connect / Disconnect + status (muted orange while connected)
        half = CX - X0
        self._tile_glyph(CONN_CARD, "plug")
        self.port_dd = PortPicker(self, CONN_CARD, (0, half))
        self.conn_pane = CardPane(self, CONN_CARD, (half, X1 - X0))
        self.conn_btn = ConnectButton(self, CX + (X1 - CX - CONN_BTN_W) // 2, CONN_Y0 + CONN_BTN_DY,
                                      CONN_BTN_W, CONN_BTN_H, self.toggle_connect)
        self.conn_status = StatusLine(self, (CX + X1) / 2, CONN_Y0 + CONN_STATUS_DY)

        # Control mode: two tiles
        self.mode_tiles = {m: ModeTile(self, MODE_CARDS[m], m, self.on_mode) for m in MODES}

        # Manual only: the Power tile. Camera shows nothing else.
        self._tile_glyph((X0, POWER_Y0), "bolt", tags="manual")
        self.power = PowerField(self, FIELD, field_bg)
        self.hint_lbl = CText(cv, (FIELD[0] + FIELD[2]) / 2, POWER_Y0 + CAPTION_DY, "", f.body,
                              fill=TEXT_2, anchor="center", tags="manual")
        self.apply_btn = PillButton(self, X1 - 20 - APPLY_W, (FIELD[1] + FIELD[3]) // 2 - APPLY_H // 2,
                                    APPLY_W, APPLY_H, "Apply", self.apply_manual)
        for key in ("<Return>", "<KP_Enter>"):
            self.power.entry.bind(key, lambda e: self.apply_manual())
        self.power.var.trace_add("write", lambda *_: self._show_power_error(None))

        # Laser panel
        CText(cv, CX, LASER_TITLE_Y, "Laser", f.h, anchor="center")
        self.laser_sub = CText(cv, CX, LASER_SUB_Y, "", f.body, fill=TEXT_2, anchor="center")
        self.laser_btn = LaserButton(self, CX, LASER_CY, LASER_BTN, LASER_BTN_R, self.toggle_laser)

        # Latest message and the readback bar
        self.msg_lbl = CText(cv, CX, MSG_Y, "", f.tiny, fill=TEXT_2, anchor="center")
        step = (X1 - X0) / 3
        self.stat_power, self.stat_current, self.stat_mode = (
            StatItem(self, round(X0 + step * (i + 0.5)), BAR_Y0, BAR_ITEM_W, BAR_Y1 - BAR_Y0, icon)
            for i, icon in enumerate(("bolt", "gauge", "slider")))

        cv.bind("<Motion>", self._on_motion)
        cv.bind("<Leave>", self._on_leave)
        cv.bind("<ButtonPress-1>", self._on_press)
        cv.bind("<ButtonRelease-1>", self._on_release)

    def _tile_glyph(self, corner: tuple[int, ...], icon: str, tags: str = "") -> None:
        """The small orange glyph in a tile's top-left corner (``corner`` starts with x0, y0)."""
        self.cv.create_image(corner[0] + GLYPH_D, corner[1] + GLYPH_D, anchor="nw", tags=tags,
                             image=self.images.icon(icon, GLYPH, ACCENT))

    def manual_visible(self) -> bool:
        """True while the Manual Power tile (field and Apply) is shown.

        Not used by the app itself; the GUI tests and the screenshot tool call it.
        """
        return self._manual_shown

    def _show_manual(self, show: bool) -> None:
        if show == self._manual_shown:
            return
        self._manual_shown = show
        self.cv.itemconfigure(self._base, image=self._bases[show])
        self.cv.itemconfigure("manual", state="normal" if show else "hidden")
        self.power.set_visible(show)
        self.apply_btn.set_visible(show)
        if not show and self.power.has_focus():
            self.root.focus_set()
        self.update_cursor()

    # ------------------------------------------------------------------ pointer
    def _hit(self, x, y) -> Optional[Control]:
        for c in reversed(self.controls):      # topmost (last created) first
            if c.contains(x, y):
                return c
        return None

    def _on_motion(self, e: tk.Event) -> None:
        """Canvas <Motion>: move hover to the control under the pointer."""
        self._pointer = (e.x, e.y)
        c = self._hit(e.x, e.y)
        if c is not self._hover_ctl:
            if self._hover_ctl is not None:
                self._hover_ctl.set_hover(False)
            self._hover_ctl = c
            if c is not None:
                c.set_hover(True)
                if c is self._press_ctl and c.enabled:   # dragged back in while held
                    c.press(e.x, e.y)
        if c is not None:
            c.on_motion(e.x, e.y)
        self.update_cursor()

    def _on_leave(self, _e: tk.Event) -> None:
        """Canvas <Leave>: clear hover."""
        self._pointer = None
        if self._hover_ctl is not None:
            self._hover_ctl.set_hover(False)
            self._hover_ctl = None
        self.update_cursor()

    def _on_press(self, e: tk.Event) -> None:
        """Canvas <ButtonPress-1>: press the control under the pointer."""
        c = self._hit(e.x, e.y)
        self._press_ctl = c
        if c is not None and c.enabled:
            c.press(e.x, e.y)

    def _on_release(self, e: tk.Event) -> None:
        """Canvas <ButtonRelease-1>: release the pressed control (it decides if it was a click)."""
        c, self._press_ctl = self._press_ctl, None
        if c is not None:
            c.release(e.x, e.y)
        # The click may have changed what is under the pointer; refresh hover,
        # unless the button was released outside the window.
        if str(self.cv) in str(self.root.winfo_containing(e.x_root, e.y_root) or ""):
            self._on_motion(e)

    def update_cursor(self) -> None:
        """Show the cursor of the enabled control under the pointer (default elsewhere)."""
        c = self._hit(*self._pointer) if self._pointer else None
        cursor = c.cursor if (c is not None and c.enabled) else ""
        if cursor != self._cursor:
            self._cursor = cursor
            self.cv.configure(cursor=cursor)

    # ------------------------------------------------------------------ events
    def _drain(self) -> None:
        """Apply every queued controller event, then re-render once. Reschedules itself."""
        try:
            latest: Optional[Status] = None
            while True:
                try:
                    ev = self.controller.events.get_nowait()
                except queue.Empty:
                    break
                if isinstance(ev, StatusEvent):
                    latest = ev.status
                    self._track_pending(ev.status)
                elif isinstance(ev, MessageEvent):
                    self.set_message(ev.text, ev.level)
                    if ev.level == "error" and self._pending_mode is not None \
                            and not self._pending_saw_busy:
                        # Rejected before the worker started it (e.g. "Not
                        # connected."): no busy -> not busy will follow.
                        self._pending_mode = None
                    if ev.code == POWER_REJECTED:
                        self._show_power_error("Refused by the laser")
            if latest is not None:
                self.status = latest
                self.render()
        except Exception:
            # Never let one bad render stop the event loop: the UI must keep
            # showing the real laser state.
            log.exception("Error while updating the window")
        finally:
            self._job = self.root.after(POLL_MS, self._drain)

    def _track_pending(self, st: Status) -> None:
        """Drop the pending mode once its request is over (or can no longer run)."""
        if self._pending_mode is None:
            return
        if st.busy:
            self._pending_saw_busy = True
        elif self._pending_saw_busy or not st.connected:
            # busy -> not busy: the job finished, failed or was rejected; follow
            # the status. Disconnected and idle: nothing can apply it any more.
            self._pending_mode = None

    def _set_pending(self, mode: Mode) -> None:
        self._pending_mode, self._pending_saw_busy = mode, False

    def set_message(self, text: str, level: str = "info") -> None:
        """Show a one-line message above the bar; ``level`` is info, warning or error."""
        self.msg_lbl.set(ellipsize(text, self.f.tiny, X1 - X0), LEVEL_COLORS.get(level, TEXT_2))

    def _blur_fields(self, e: tk.Event) -> None:
        """Global <ButtonPress-1>: a click outside the power field takes its focus away."""
        # e.widget is a str for clicks on a tk.Menu's internal clone.
        if isinstance(e.widget, (str, tk.Entry)):
            return
        if e.widget is self.cv and self.power.contains(e.x, e.y):
            return
        try:
            self.root.focus_set()
        except tk.TclError:
            pass

    def _show_power_error(self, text: Optional[str]) -> None:
        self._power_error = text
        self.power.set_error(bool(text))
        self._render_hint()

    def _render_hint(self) -> None:
        if self._power_error:
            self.hint_lbl.set(self._power_error, ERROR)
        else:
            self.hint_lbl.set("power" if self.status.connected else "Connect to set", TEXT_2)

    # ------------------------------------------------------------------ actions
    def refresh_ports(self, prefer: Optional[str] = None, announce: bool = True) -> None:
        """Re-list the serial ports into the port menu.

        Args:
            prefer: port to select if present (else the current one is kept).
            announce: report the number of ports found in the message line.
        """
        previous = self.port_dd.key
        try:
            ports = self.list_ports()
        except Exception as exc:   # pragma: no cover - OS specific
            ports = []
            self.set_message(f"Could not list serial ports: {exc}", "error")
            announce = False
        self.port_dd.set_items([(p.device, p.label) for p in ports], prefer=prefer)
        if previous and ports and self.port_dd.key != previous and prefer is None:
            self.set_message(f"{previous} is gone; selected {self.port_dd.key}. "
                             "Check the port before connecting.", "warning")
            announce = False
        if announce:
            n = len(ports)
            self.set_message(f"Found {n} serial port{'s' if n != 1 else ''}." if n
                             else "No serial ports found.", "info" if n else "warning")
        self.render()

    def toggle_connect(self) -> None:
        """Connect to the selected port in the shown mode, or disconnect."""
        st = self.status
        if st.connected:
            self._pending_mode = None      # disconnect cancels any queued mode change
            self.controller.disconnect()
            return
        if st.busy or self.port_dd.key is None:
            return
        manual = self.power.get()
        if manual is None:
            manual = self.settings.manual_power_mw
        self._set_pending(self.selected_mode)
        self.controller.connect(self.port_dd.key, self.selected_mode, manual)

    def toggle_laser(self) -> None:
        """Turn the laser on or off (ignored while disconnected or busy)."""
        st = self.status
        if not st.connected or st.busy:
            return
        if st.emitting:
            self._pending_mode = None      # turn_off cancels any queued mode change
            self.controller.turn_off()
        else:
            self.controller.turn_on()

    def on_mode(self, mode: Mode) -> None:
        """A mode tile asked for ``mode``: remember it, or ask the controller."""
        st = self.status
        if st.busy or mode is self.shown_mode():
            return
        self._show_power_error(None)
        if not st.connected:               # just choose the mode used on connect
            self.selected_mode = mode
        else:
            self._set_pending(mode)
            self.controller.set_mode(mode)
        self.render()

    def apply_manual(self) -> None:
        """Send the power in the field (Apply button or Enter)."""
        if not self.apply_btn.enabled:
            return
        v = self.power.get()
        if not is_number(v):               # the only check: no power limits in the app
            self._show_power_error("Enter a number")
            return
        self._show_power_error(None)
        self.controller.apply_power(v)

    # ------------------------------------------------------------------ render
    def shown_mode(self) -> Mode:
        """The mode the tiles show: a pending request wins over the status."""
        st = self.status
        if not st.connected and not st.busy:
            return self.selected_mode
        if self._pending_mode is not None:
            return self._pending_mode
        return st.mode if st.connected else self.selected_mode

    def render(self) -> None:
        """Bring every control in line with ``self.status``. Cheap when nothing changed."""
        st = self.status
        conn, busy = st.connected, st.busy
        connecting = busy and not conn

        # Header and connection tile
        if st.limits:
            self.conn_sub.set(f"Connected · {st.port}")
        elif connecting:
            self.conn_sub.set("Connecting…")
        else:
            self.conn_sub.set("Not connected")
        has_ports = bool(self.port_dd.items)
        can_toggle = conn or (not connecting and has_ports)
        self.connect_btn.set_state(can_toggle, ACCENT if conn else TEXT)
        # The whole connection tile turns muted orange while connected.
        self.conn_pane.set_selected(conn)
        self.port_dd.set_selected(conn)
        self.conn_btn.set_kind("disconnect" if conn else "busy" if connecting else "connect",
                               can_toggle)
        if conn:
            self.conn_status.set("Connected", ON, TEXT_ON_SELECTED)
        else:
            self.conn_status.set("Not connected", TEXT_3, TEXT_2)
        self.port_dd.set_enabled(not conn and not busy and has_ports)
        self.refresh_btn.set_state(not conn and not busy)

        # Control mode tiles; the Power tile only in Manual.
        if conn and not busy:
            self.selected_mode = st.mode
        mode = self.shown_mode()
        for m, tile in self.mode_tiles.items():
            tile.set(m is mode, enabled=not busy)
        if mode is not Mode.MANUAL and self._manual_shown:
            self._show_power_error(None)
        self._show_manual(mode is Mode.MANUAL)
        enabled = conn and not busy
        self.power.set_enabled(enabled)
        self.apply_btn.set_enabled(enabled)
        self._render_hint()
        if st.mode is Mode.MANUAL and st.setpoint_mw is not None \
                and st.setpoint_mw != self._seen_setpoint and not self.power.has_focus():
            self._seen_setpoint = st.setpoint_mw
            self.power.set_value(st.setpoint_mw)

        # Laser panel
        if not conn:
            self.laser_sub.set("Not connected", TEXT_2)
        elif st.emitting:
            self.laser_sub.set("Laser on", ON)
        else:
            self.laser_sub.set("Laser off", OFF_TEXT)
        self.laser_btn.set_state(on=st.emitting, enabled=conn and not busy)

        # Readback bar
        p = f"{st.setpoint_mw:.1f}" if conn and st.setpoint_mw is not None else "—"
        i = f"{st.current_ma:.1f}" if conn and st.current_ma is not None else "—"
        self.stat_power.set(f"{p} mW", conn)
        self.stat_current.set(f"{i} mA", conn)
        self.stat_mode.set(mode.value, conn, MODE_ICONS[mode])

    # ------------------------------------------------------------------ close
    def collect_settings(self) -> Settings:
        """Update ``self.settings`` from the window (port, mode, manual power) and return it."""
        s = self.settings
        s.last_port = self.status.port or self.port_dd.key or s.last_port
        s.mode = self.shown_mode().value
        # The field if it holds a number, else the last manual setpoint seen.
        for manual in (self.power.get(), self._seen_setpoint):
            if is_number(manual):
                s.manual_power_mw = manual
                break
        return s

    def on_close(self) -> None:
        """Window close: confirm if the laser is on, save settings, destroy the window.

        The caller shuts the controller down after ``mainloop`` returns.
        """
        if self.status.emitting:
            if not messagebox.askokcancel("Laser is on", "Turn the laser off and quit?",
                                          parent=self.root):
                return
            self.controller.turn_off()   # first in line; shutdown() turns it off again
        save_settings(self.collect_settings())
        if self._job:
            self.root.after_cancel(self._job)
            self._job = None
        self.root.destroy()


# ==========================================================================
# Entry points
# ==========================================================================
def build_app(root: tk.Tk, controller: LaserController, settings: Settings,
              list_ports: Callable[[], list[PortInfo]]) -> App:
    """Build the UI into ``root`` without entering mainloop.

    Used by ``run_app`` and by screenshot / test-harness scripts.
    """
    return App(root, controller, settings, list_ports)


def run_app(controller: LaserController, settings: Settings,
            list_ports: Callable[[], list[PortInfo]]) -> None:
    """Build the window, run mainloop, return when the window closes."""
    root = tk.Tk()
    build_app(root, controller, settings, list_ports)
    root.mainloop()
