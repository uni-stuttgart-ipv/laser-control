"""The port row: which serial port to use, and the Connect / Disconnect button.

::

    ┌──────────────────────────┐ ┌────────────┐
    │ ⏚  COM3 ▾            (↻) │ │  Connect   │
    └──────────────────────────┘ └────────────┘
     port field (sunk in)         pill button

While disconnected, the port name opens a dropdown and ↻ re-reads the ports.
While connected or connecting, the port is fixed and "19200 baud" is shown
instead.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from laser_control.ui import paint
from laser_control.ui import theme as T
from laser_control.ui.art import Glow
from laser_control.ui.paint import CONTENT_W, GAP, PAD_X

if TYPE_CHECKING:
    from laser_control.ui.window import MainWindow

ROW_H = 44           # height of the port field and the pill
FIELD_W = 232        # width of the port field
PILL_W = 112         # width of the Connect button; it fills the rest of the row after a 12 px gap
REFRESH = 34         # the round ↻ button
INSET = (ROW_H - REFRESH) / 2   # ↻ sits this far inside the field, top and right: 5
ICON_X = 24          # centre of the plug icon, from the field's left edge
NAME_X = 42          # start of the port name, after the plug icon
BAUD_RIGHT = 16      # "19200 baud" ends this far inside the field's right edge
CHEVRON_W = 24       # the ▾ after the name, with its gap

# Room for the port name (logical px). A long name is cut to fit, see fit_port_name.
NAME_ROOM = FIELD_W - NAME_X - CHEVRON_W - (REFRESH + INSET)   # disconnected: end before the ▾ and ↻
NAME_ROOM_FIXED = FIELD_W - NAME_X - BAUD_RIGHT                # connected: no ▾ or ↻, so more room


def fit_port_name(win: MainWindow, name: str, room: float) -> str:
    """Cut characters off the front of ``name`` until it fits in ``room`` px; "…" marks the cut.

    The end is kept because it tells ports apart (…usbserial-A1B2, …usbserial-C3D4).
    Only the drawn text is shortened: state.port keeps the full name for connecting,
    and the dropdown lists the full names.
    """
    if paint.text_width(win, name, win.fonts.port) <= room:
        return name
    while name and paint.text_width(win, "…" + name, win.fonts.port) > room:
        name = name[1:]
    return "…" + name


def draw(win: MainWindow, y: float) -> float:
    """Draw the port row at ``y``; returns where the next section starts."""
    s, f, a = win.state, win.fonts, win.art
    mid = y + ROW_H / 2   # everything in the row is centred on this line
    win.port_menu_at = (PAD_X + 30, y + ROW_H + 2)   # the dropdown opens just below the port name

    # The port field, sunk into the surface, with a plug icon
    paint.image(win, PAD_X, y, a.soft(FIELD_W, ROW_H, ROW_H / 2, "press"))
    paint.icon(win, PAD_X + ICON_X, mid, a.icon("plug", 17, T.TEXT_3))

    name_x = PAD_X + NAME_X
    if not s.connected and not s.connecting:
        name = fit_port_name(win, s.port or "No port", NAME_ROOM)
        # The name is a button that opens the dropdown; its text turns amber on hover
        tag = win.buttons.add("port", True, win.show_port_menu, fg_text={"normal": T.TEXT, "hover": T.AMBER_2})
        w = paint.text_width(win, name, f.port)
        paint.hit_area(win, name_x - 4, mid - 10, w + 30, 20, (tag,))   # covers the name and the ▾
        paint.text(win, name_x, mid, name, f.port, T.TEXT, anchor="w", tags=(tag, f"{tag}.fgt"))
        paint.icon(win, name_x + w + 11, mid + 1, a.icon("chev", 15, T.TEXT_3), tags=(tag,))

        # The round ↻ button at the field's right end
        kx = PAD_X + FIELD_W - INSET - REFRESH
        raised, sunk = a.soft(REFRESH, REFRESH, REFRESH / 2, "raise_sm"), a.soft(REFRESH, REFRESH, REFRESH / 2, "press_sm")
        rtag = win.buttons.add("refresh", True, win.refresh_ports, bg={"normal": raised, "press": sunk},
                               fg={"normal": a.icon("refresh", 15, T.TEXT_2), "hover": a.icon("refresh", 15, T.AMBER_2)})
        paint.image(win, kx, y + INSET, raised, tags=(rtag, f"{rtag}.bg"))
        paint.icon(win, kx + REFRESH / 2, mid, a.icon("refresh", 15, T.TEXT_2), tags=(rtag, f"{rtag}.fg"))
    else:
        # Fixed port; the baud rate on the right, unless a long port name needs the room
        name = fit_port_name(win, s.port or "No port", NAME_ROOM_FIXED)
        paint.text(win, name_x, mid, name, f.port, T.TEXT, anchor="w")
        room = FIELD_W - NAME_X - BAUD_RIGHT - paint.text_width(win, name, f.port)
        if room > paint.text_width(win, "19200 baud", f.small) + 10:
            paint.text(win, PAD_X + FIELD_W - BAUD_RIGHT, mid, "19200 baud", f.small, T.TEXT_3, anchor="e")

    _draw_connect_button(win, y, mid)
    return y + ROW_H + GAP


def _draw_connect_button(win: MainWindow, y: float, mid: float) -> None:
    """The pill: amber "Connect", grey "Disconnect", or a spinner with "Wait" while connecting."""
    s, f, a = win.state, win.fonts, win.art
    x = PAD_X + CONTENT_W - PILL_W   # right-aligned with the cards below
    label = "Disconnect" if s.connected else "Wait" if s.connecting else "Connect"
    amber = label == "Connect"
    r = ROW_H / 2
    if amber:
        normal = a.soft(PILL_W, ROW_H, r, "raise_sm", gradient=(T.AMBER_1, T.AMBER_2), glow=Glow(T.AMBER_GLOW, 4, 6, 14))
        disabled = a.soft(PILL_W, ROW_H, r, "raise_sm", gradient=(T.AMBER_DISABLED_1, T.AMBER_DISABLED_2))
        pressed = a.soft(PILL_W, ROW_H, r, "flat", gradient=(T.AMBER_2, T.AMBER_1))
        ink = T.AMBER_INK
    else:
        normal = a.soft(PILL_W, ROW_H, r, "raise")
        disabled = a.soft(PILL_W, ROW_H, r, "raise_sm")
        pressed = a.soft(PILL_W, ROW_H, r, "press")
        ink = T.TEXT
    enabled = s.can_connect
    tag = win.buttons.add("connect", enabled, win.connect_clicked, bg={"normal": normal, "press": pressed})
    paint.image(win, x, y, normal if enabled else disabled, tags=(tag, f"{tag}.bg"))
    if s.connecting:
        paint.spinner(win, x + 26, mid, 7, T.AMBER_2)
        paint.text(win, x + 42, mid, label, f.button, T.TEXT_3, anchor="w", tags=(tag,))
    else:
        color = ink if enabled else (T.TEXT_OFF if not amber else T.AMBER_INK)
        paint.text(win, x + PILL_W / 2, mid, label, f.button, color, anchor="center", tags=(tag,))
