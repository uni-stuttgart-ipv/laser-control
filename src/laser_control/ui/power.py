"""Everything about *changing* the power in manual mode, and *when* it is sent.

The value itself is ``win.state.power`` (see :mod:`state`, which explains why
it lives there). This file decides how the user changes it and when the new
value goes to the laser.

The seven ways to change the power
----------------------------------
1. Drag the dial                    -> sent 0.5 s after you let go
2. Click − or +                     -> 0.1 mW per click, sent 0.5 s after the last click
3. Shift + click − or +             -> the same, 1 mW per click
4. Up / Down arrow keys             -> 0.1 mW, sent 0.5 s after the last key press
5. Shift + Up / Down                -> 1 mW
6. Mouse wheel over the dial        -> 0.1 mW per notch, sent 0.5 s after the last notch
7. Click the reading, type, Enter   -> sent at once

Why wait 0.5 s
--------------
Clicking + five times should send *one* command (the final value), not five.
Every change restarts a 0.5 s timer (:meth:`PowerInput.schedule_send`), and
only when it runs out is the power sent. Tk's ``after()`` runs the timer on the
window's own thread, so there is nothing to lock.
"""

from __future__ import annotations

import math
import tkinter as tk
from typing import TYPE_CHECKING

from laser_control.controller import MAX_POWER_MW
from laser_control.ui import theme as T

if TYPE_CHECKING:  # only for type hints; avoids a circular import at runtime
    from laser_control.ui.window import MainWindow

SEND_DELAY_MS = 500   # wait after the last change before sending the power
READING_RADIUS = 45   # clicking within this distance of the dial's centre opens the text field
DIAL_A0, DIAL_SWEEP = 135.0, 270.0   # the dial's arc starts at 135° (bottom left) and sweeps 270°


def dial_value(dx: float, dy: float, max_mw: float) -> float:
    """Turn a pointer position into a power, from its offset to the dial's centre.

    The dial sweeps 270° clockwise from 135° (bottom left). Pointer angles in
    the 90° gap at the bottom snap to the nearer end.
    """
    angle = math.degrees(math.atan2(dy, dx))
    t = (angle - DIAL_A0) % 360
    if t > DIAL_SWEEP:
        t = 0.0 if t > DIAL_SWEEP + (360 - DIAL_SWEEP) / 2 else DIAL_SWEEP
    return t / DIAL_SWEEP * max_mw


class PowerInput:
    """Turns mouse, keyboard and typed input into a new dial value, and sends it.

    Args:
        win: The main window; this uses ``win.state`` for the value, and
            ``win.ctl`` to send it.
    """

    def __init__(self, win: MainWindow):
        self.win = win
        self.dragging = False                    # the mouse is turning the dial
        self.editor: tk.Entry | None = None      # the text field, while open
        self.dial_center = (0.0, 0.0)            # logical px; set by sections/power_card.py when drawing
        self._send_job: str | None = None        # the pending after() timer, if any

    # ---- changing the value ----

    def set_value(self, value: float) -> None:
        """Move the dial to ``value``, kept within the limits. This alone sends nothing."""
        if not math.isfinite(value):   # "nan" or "inf" typed into the text field
            return
        value = self.win.state.clamp(value)
        if value != self.win.state.power:
            self.win.state.power = value
            self.win.render()

    def nudge(self, delta: float) -> None:
        """Step the power by ``delta`` mW (−/+, arrows, wheel), then send after the pause."""
        if self.win.state.power_editable and self.editor is None:
            self.set_value(self.win.state.power + delta)
            self.schedule_send()

    # ---- sending ----

    def schedule_send(self) -> None:
        """Send the power SEND_DELAY_MS after the last change, so a burst of changes sends once."""
        if self._send_job is not None:
            self.win.root.after_cancel(self._send_job)   # a newer change restarts the wait
        self._send_job = self.win.root.after(SEND_DELAY_MS, self.send)

    def send(self) -> None:
        """Send the dial's power to the laser, unless the laser already has it."""
        self._send_job = None
        state = self.win.state
        if state.power_editable and state.power != state.setpoint:
            self.win.ctl.set_power(state.power)

    # ---- the dial (mouse events come from buttons.py) ----

    def press_dial(self, x: int, y: int) -> None:
        """Mouse down on the dial: the centre opens the text field, the ring starts a drag."""
        if not self.win.state.power_editable:
            return
        cx, cy = self.dial_center
        px = self.win.art.px
        if math.hypot(x - px(cx), y - px(cy)) < px(READING_RADIUS):
            self.open_editor()
            return
        self.dragging = True
        self.drag_dial(x, y)

    def drag_dial(self, x: int, y: int) -> None:
        """Move the dial to follow the pointer."""
        if not self.win.state.power_editable:   # e.g. the connection dropped mid-drag
            self.dragging = False
            return
        cx, cy = self.dial_center
        px = self.win.art.px
        self.set_value(dial_value(x - px(cx), y - px(cy), MAX_POWER_MW))

    def release_dial(self) -> None:
        """Mouse up after a drag: send after the pause."""
        self.dragging = False
        self.schedule_send()

    # ---- the text field over the reading ----

    def open_editor(self) -> None:
        """Replace the dial's reading with a text field. Enter sends, Esc cancels."""
        if self.editor is not None:
            return
        win = self.win
        entry = tk.Entry(win.canvas, font=win.fonts.reading, justify="center", bd=0, relief="flat",
                         bg=T.BASE, fg=T.TEXT, insertbackground=T.AMBER_2, highlightthickness=0,
                         width=5)
        entry.insert(0, f"{win.state.power:.1f}")
        entry.select_range(0, "end")
        entry.bind("<Return>", self.commit_editor)
        entry.bind("<Escape>", lambda e: self.close_editor())  # Esc cancels typing; it is the only use of Esc
        entry.bind("<FocusOut>", lambda e: self.close_editor())
        self.editor = entry
        win.render()            # power_card.py places the field where the reading was
        entry.focus_set()

    def commit_editor(self, _event=None) -> str:
        """Enter in the text field: read the number and send it at once.

        Returns:
            ``"break"``, so Tk does not also pass the Enter key to the window.
        """
        text = self.editor.get().strip().replace(",", ".") if self.editor else ""  # "12,5" works too
        self.close_editor()
        try:
            value = float(text)
        except ValueError:
            self.win.state.message = ("warning", f"“{text}” is not a power in mW.")
            self.win.render()
            return "break"
        self.set_value(value)
        self.send()
        return "break"

    def close_editor(self) -> None:
        """Remove the text field, if open, and show the reading again."""
        if self.editor is not None:
            editor, self.editor = self.editor, None
            editor.destroy()
            self.win.render()

    def drop_editor_if_locked(self) -> None:
        """Remove the text field without a redraw when the power can no longer change.

        Called at the start of every redraw: if the connection dropped or the
        mode changed while typing, the field must not stay on screen.
        """
        if self.editor is not None and not self.win.state.power_editable:
            editor, self.editor = self.editor, None
            editor.destroy()
