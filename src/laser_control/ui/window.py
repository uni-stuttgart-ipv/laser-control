"""The main window: one Tk canvas, redrawn from :class:`State` whenever something changes.

How the UI files fit together
-----------------------------
::

    window.py   MainWindow: builds everything, reacts to the user, collects results
      ├─ state.py       State: what the screen shows (connected? laser on? power?)
      ├─ buttons.py     ButtonLayer: makes the drawn buttons clickable
      ├─ power.py       PowerInput: the 7 ways to change the power, and when it is sent
      ├─ log_view.py    LogView: the Log tab's lines, Technical, scrolling, Copy
      └─ sections/      one file per part of the window, each draws itself from State
            (they use paint.py for drawing, and art.py / theme.py for images, colours, fonts)

A user action and its result
----------------------------
1. The user clicks a button; :mod:`buttons` calls an action method here, such
   as :meth:`MainWindow.laser_clicked`.
2. The action calls the controller (``self.ctl.turn_on()``), which only queues
   the job and returns at once, so the window never freezes.
3. Every 100 ms :meth:`MainWindow._poll` collects what happened
   (``("laser", True)``), :meth:`State.apply` updates the state, and
   :meth:`MainWindow.render` redraws. The same poll collects new log lines
   for the Log tab.

Two tabs
--------
The tab bar and the header are drawn on both tabs, so the laser's state is
always in view. Below them, :meth:`MainWindow.render` draws either the laser
sections or the log card (``state.tab``).

Why redraw everything
---------------------
:meth:`MainWindow.render` deletes the whole canvas and draws it again from the
state. That keeps every section a plain top-to-bottom function of the state,
with no "update this one item" bookkeeping, and it is cheap because every
image is cached in :class:`~laser_control.ui.art.Art`. Only the spinner and the
emitting key's glow animate in place, without a redraw (:meth:`MainWindow._tick`).
"""

from __future__ import annotations

import tkinter as tk

from laser_control.controller import Controller
from laser_control.ui import chrome
from laser_control.ui import theme as T
from laser_control.ui.art import Art
from laser_control.ui.buttons import ButtonLayer
from laser_control.ui.log_view import LogView
from laser_control.ui.power import PowerInput
from laser_control.ui.sections import (header, laser_card, log_card, message, mode_bar, port_row, power_card,
                                       readouts, tab_bar)
from laser_control.ui.state import State

POLL_MS = 100       # how often the window collects results from the controller
TICK_MS = 40        # animation frame: the spinner turns every tick
PULSE_EVERY = 4     # the emitting key's glow steps every 4th tick (160 ms)
TOP = 12            # space above the tab bar


class MainWindow:
    """Builds the window, reacts to the user, and shows what the laser reports.

    Args:
        root: The Tk root window.
        controller: The controller; the window only calls its public methods.
    """

    def __init__(self, root: tk.Tk, controller: Controller):
        self.root = root
        self.ctl = controller
        self.scale = T.ui_scale(root)            # logical -> device pixels (see paint.py)
        self.art = Art(root, self.scale)         # makes and caches every image
        self.fonts = T.make_fonts(root, self.scale)

        found = controller.get_ports()
        self.state = State(found[0] if found else "")

        # ---- drawing and animation ----
        self.height = 0                          # current canvas height, device px
        self.spin = 0                            # spinner angle, degrees
        self.pulse_frame = 0                     # frame of the emitting key's glow
        self.port_menu_at = (0.0, 0.0)           # where the port dropdown opens; set by port_row.py
        self._ticks = 0
        self._emitting_shown: bool | None = None # title-bar colour last applied
        self._menu: tk.Menu | None = None

        root.configure(bg=T.BASE)
        root.resizable(False, False)
        self.canvas = tk.Canvas(root, width=self.art.px(T.WIDTH), height=10, bg=T.BASE,
                                highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self.buttons = ButtonLayer(self)         # binds the mouse
        self.power_input = PowerInput(self)
        self.log_view = LogView(self)            # starts collecting log lines
        self._bind_keys()

        self.render()
        self._tick()
        self._poll()

    # ================================================================ results from the controller

    def _poll(self) -> None:
        """Every POLL_MS: collect what the controller did, and redraw if anything happened."""
        results = self.ctl.get_results()
        for kind, value in results:
            self.state.apply(kind, value)
        new_lines = self.log_view.take_new()
        if results or (new_lines and self.state.tab == "log"):   # log lines only matter on the Log tab
            self.render()
        self.root.after(POLL_MS, self._poll)

    # ================================================================ keyboard

    def _bind_keys(self) -> None:
        """Every keyboard shortcut of the app, in one place.

        Esc has no shortcut here on purpose: it only cancels typing in the
        power field (power.py). The laser is turned off with the key,
        Disconnect, or by closing the window.
        """
        self.root.bind_all("<Up>", lambda e: self.on_arrow(0.1, -1))
        self.root.bind_all("<Down>", lambda e: self.on_arrow(-0.1, 1))
        self.root.bind_all("<Shift-Up>", lambda e: self.on_arrow(1.0, -10))
        self.root.bind_all("<Shift-Down>", lambda e: self.on_arrow(-1.0, 10))

    def on_arrow(self, power_step: float, log_rows: int) -> None:
        """↑/↓ change the power on the Laser tab, and scroll the log on the Log tab.

        So the power can never change while it is out of sight.
        """
        if self.state.tab == "log":
            self.log_view.scroll(log_rows)
        else:
            self.power_input.nudge(power_step)

    # ================================================================ actions (called by the buttons)

    def connect_clicked(self) -> None:
        """Connect / Disconnect button."""
        s = self.state
        if s.connected:
            self.ctl.disconnect()
            return
        s.message = None
        s.connecting = True
        self.ctl.connect(s.port, s.mode, s.power)
        self.render()

    def mode_clicked(self, mode: str) -> None:
        """Camera or Manual. Before connecting it is only remembered; it is applied on connect."""
        s = self.state
        if mode == s.mode and not s.connected:
            return
        if s.message and s.message[0] == "warning":
            s.message = None
        self.power_input.close_editor()
        s.mode = mode
        if s.connected:
            self.ctl.use_mode(mode, s.power)
        self.render()

    def tab_clicked(self, tab: str) -> None:
        """Laser or Log, in the tab bar."""
        self.power_input.close_editor()   # the power field belongs to the Laser tab
        self.state.tab = tab
        self.render()

    def laser_clicked(self) -> None:
        """The round key: on when off, off when on."""
        if self.state.laser_on:
            self.ctl.turn_off()
        else:
            self.ctl.turn_on()

    def dismiss(self) -> None:
        """The ✕ on a banner."""
        self.state.message = None
        self.render()

    def show_port_menu(self) -> None:
        """Open the dropdown of serial ports under the port name."""
        if self._menu is not None:
            self._menu.destroy()
        self._menu = menu = tk.Menu(self.root, tearoff=0)
        self._port_var = tk.StringVar(self.root, value=self.state.port)  # kept on self, or Python would delete it
        found = self.ctl.get_ports()
        if not found:
            menu.add_command(label="No serial ports found", state="disabled")
        for name in found:
            menu.add_radiobutton(label=name, value=name, variable=self._port_var,
                                 command=lambda n=name: self.port_chosen(n))
        x, y = self.port_menu_at
        menu.tk_popup(self.canvas.winfo_rootx() + self.art.px(x), self.canvas.winfo_rooty() + self.art.px(y))

    def port_chosen(self, name: str) -> None:
        """A port was picked in the dropdown."""
        self.state.message = None
        self.state.port = name
        self.render()

    def refresh_ports(self) -> None:
        """The ↻ button: read the ports again; pick the first if the chosen one is gone."""
        found = self.ctl.get_ports()
        if self.state.port not in found:
            self.state.port = found[0] if found else ""
        self.render()

    # ================================================================ drawing

    def render(self) -> None:
        """Redraw the whole window from the state, section by section, top to bottom."""
        self.power_input.drop_editor_if_locked()
        self.canvas.delete("all")
        self.buttons.clear()

        y = tab_bar.draw(self, TOP)
        y = header.draw(self, y)
        if self.state.tab == "log":
            y = log_card.draw(self, y)
        else:
            y = port_row.draw(self, y)
            y = mode_bar.draw(self, y)
            if self.state.mode == "manual":
                y = power_card.draw(self, y)
            y = laser_card.draw(self, y)
            y = message.draw(self, y)
            y = readouts.draw(self, y)

        if self.state.laser_on:  # an amber border around the whole window while emitting
            p = self.art.px
            self.canvas.create_rectangle(p(1), p(1), p(T.WIDTH) - p(1), p(y) - p(1), outline=T.EMIT, width=p(2))
        self._resize(y)
        self._update_title()
        self.buttons.restore()

    def _resize(self, height: float) -> None:
        """Fit the window to the content; it is taller in manual mode (the power card) and on the Log tab."""
        h = self.art.px(height)
        if h != self.height:
            self.height = h
            self.canvas.configure(height=h)
            self.root.geometry(f"{self.art.px(T.WIDTH)}x{h}")

    def _update_title(self) -> None:
        """Window title, and on Windows 11 an amber title bar while emitting (see chrome.py)."""
        emitting = self.state.laser_on
        self.root.title("Emitting – Laser Control" if emitting else "Laser Control")
        if emitting != self._emitting_shown:   # only call Windows when it changes
            self._emitting_shown = emitting
            if emitting:
                chrome.set_caption(self.root, T.TITLEBAR_EMIT, T.EMIT_INK, T.EMIT)
            else:
                chrome.set_caption(self.root, None, None, None)

    # ================================================================ animation

    def _tick(self) -> None:
        """Every TICK_MS: turn the spinner; every PULSE_EVERY ticks, step the emitting key's glow.

        Both only change existing canvas items, without a redraw. The glow
        pauses while the key is held down, so its pressed look stays.
        """
        self.spin = (self.spin - 12) % 360
        self._ticks += 1
        if self.canvas.find_withtag("spinner"):
            self.canvas.itemconfigure("spinner", start=self.spin)
        if self._ticks % PULSE_EVERY == 0 and self.state.laser_on and self.buttons.pressed is None:
            self.pulse_frame = (self.pulse_frame + 1) % laser_card.PULSE_FRAMES
            sprite = laser_card.pulse_sprite(self, self.pulse_frame)
            self.canvas.itemconfigure("key.bg", image=sprite.photo)
            if "btn:key" in self.buttons.registered:   # so a hover / un-press restores the current frame
                self.buttons.registered["btn:key"].bg["normal"] = sprite
        self.root.after(TICK_MS, self._tick)
