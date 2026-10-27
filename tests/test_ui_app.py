"""End-to-end GUI tests: the real window driven against the simulated laser.

Needs a display (on Linux CI run under ``xvfb-run``); skipped without one.
Events are pumped with ``root.update()`` instead of ``mainloop()``.
"""

import time

import pytest
from helpers import SimFactory

tk = pytest.importorskip("tkinter")
pytest.importorskip("PIL")

from laser_app.config import Settings  # noqa: E402
from laser_app.controller import LaserController, Mode  # noqa: E402
from laser_app.hardware.ports import PortInfo  # noqa: E402
from laser_app.ui import app as app_module  # noqa: E402
from laser_app.ui import layout  # noqa: E402

PORTS = [PortInfo("COM3", "USB Serial Device (COM3)")] + \
    [PortInfo(f"COM{i}", detected=False) for i in range(1, 21) if i != 3]


class Harness:
    """A window, its controller and the simulated lasers it opened."""

    def __init__(self, settings: Settings) -> None:
        self.sim = SimFactory()
        self.ctl = LaserController(factory=self.sim, poll_interval_s=0.2)
        self.ctl.start()
        self.root = tk.Tk()
        self.app = app_module.build_app(self.root, self.ctl, settings, lambda: list(PORTS))
        self.cv = self.app.cv
        self.pump(0.2)

    @property
    def device(self):
        """The simulated laser opened last."""
        return self.sim.device

    def pump(self, secs: float = 0.3, until=None) -> bool:
        """Process Tk events for ``secs`` or until ``until()`` is true; return ``until()``."""
        end = time.monotonic() + secs
        while time.monotonic() < end:
            self.root.update()
            if until is not None and until():
                return True
            time.sleep(0.01)
        return until() if until is not None else True

    def wait(self, pred, secs: float = 5.0) -> None:
        assert self.pump(secs, pred), "condition not met in time"

    def idle(self) -> bool:
        return not self.app.status.busy

    def connect(self) -> None:
        self.app.toggle_connect()
        self.wait(lambda: self.app.status.connected and self.idle())

    # -- mouse
    def move(self, x, y) -> None:
        self.cv.event_generate("<Motion>", x=x, y=y)
        self.pump(0.05)

    def click(self, x, y) -> None:
        self.move(x, y)
        self.cv.event_generate("<ButtonPress-1>", x=x, y=y)
        self.pump(0.05)
        self.cv.event_generate("<ButtonRelease-1>", x=x, y=y)
        self.pump(0.05)

    @staticmethod
    def centre(control):
        return control.x + control.w // 2, control.y + control.h // 2

    def close(self) -> None:
        try:
            if self.root.winfo_exists():
                if self.app._job:                     # stop the event-drain loop first
                    self.root.after_cancel(self.app._job)
                self.root.destroy()
        except tk.TclError:
            pass
        self.ctl.shutdown()


@pytest.fixture
def ui(monkeypatch):
    try:
        tk.Tk().destroy()
    except tk.TclError:
        pytest.skip("no display")
    saved = []
    monkeypatch.setattr(app_module, "save_settings", saved.append)   # never touch real settings
    h = Harness(Settings(last_port="COM3", mode="manual", manual_power_mw=5.0))
    h.saved = saved
    yield h
    h.close()


def test_window_is_fixed_size(ui):
    ui.pump(0.3)
    assert (ui.root.winfo_width(), ui.root.winfo_height()) == (layout.WIDTH, layout.HEIGHT)
    assert ui.root.resizable() == (False, False)


def test_connection_card_states(ui):
    app = ui.app
    assert (app.conn_btn.text, app.conn_btn.style, app.conn_btn.enabled) == ("Connect", "cta", True)
    assert app.conn_status.label.text == "Not connected"
    assert not app.laser_btn.enabled and not app.apply_btn.enabled
    ui.connect()
    assert (app.conn_btn.text, app.conn_btn.style) == ("Disconnect", "dark")
    assert app.conn_status.label.text == "Connected"
    assert app.conn_sub.text == "Connected · COM3"
    assert app.conn_pane.selected and app.port_dd.selected and not app.port_dd.enabled
    app.toggle_connect()
    ui.wait(lambda: not app.status.connected and ui.idle())
    assert app.conn_btn.text == "Connect" and not ui.device.emitting


def test_manual_power_and_laser(ui):
    app = ui.app
    ui.connect()
    app.power.var.set("12")
    app.apply_manual()
    ui.wait(lambda: app.status.setpoint_mw == 12.0)
    app.toggle_laser()
    ui.wait(lambda: app.status.emitting)
    assert app.laser_sub.text == "Laser on" and ui.device.emitting
    assert app.stat_power.label.text == "12.0 mW"
    app.toggle_laser()
    ui.wait(lambda: not app.status.emitting)
    assert app.laser_sub.text == "Laser off"


def test_camera_mode_and_back(ui):
    app = ui.app
    ui.connect()
    app.power.var.set("12")
    app.apply_manual()
    ui.wait(lambda: app.status.setpoint_mw == 12.0)
    app.toggle_laser()
    ui.wait(lambda: app.status.emitting)
    # Camera while on: laser goes off, the Power tile disappears, 50 mW is used.
    app.on_mode(Mode.CAMERA)
    ui.wait(lambda: app.status.mode is Mode.CAMERA and ui.idle())
    assert not app.status.emitting and not app.manual_visible()
    assert not app.power.entry.winfo_ismapped()
    assert ui.device.state["CAL"] == 50.0 and ui.device.setpoint == 50.0
    # Back to Manual: the field returns and the last manual power is restored.
    app.on_mode(Mode.MANUAL)
    ui.wait(lambda: app.status.mode is Mode.MANUAL and ui.idle())
    ui.pump(0.3)
    assert ui.device.setpoint == 12.0 and app.manual_visible() and app.power.entry.winfo_ismapped()
    assert (ui.root.winfo_width(), ui.root.winfo_height()) == (layout.WIDTH, layout.HEIGHT)


def test_power_input_errors(ui):
    app = ui.app
    ui.connect()
    # No app-side limit: 0.2 mW (below the laser minimum) is sent.
    app.power.var.set("0.2")
    app.apply_manual()
    ui.wait(lambda: app.status.setpoint_mw == 0.2)
    # Not a number: inline error, nothing sent.
    n = len(ui.device.received)
    app.power.var.set("abc")
    app.apply_manual()
    assert app._power_error == "Enter a number" and app.hint_lbl.text == "Enter a number"
    # Above the laser maximum: refused before sending; shown inline, link kept.
    app.power.var.set("70")
    app.apply_manual()
    ui.wait(lambda: app._power_error == "Refused by the laser")
    assert app.status.connected and not any(c.startswith("P=") for c in ui.device.received[n:])
    # Typing clears the error.
    app.power.var.set("7")
    assert app._power_error is None


def test_mouse_interaction(ui):
    app, cv = ui.app, ui.cv
    x, y = ui.centre(app.conn_btn)
    ui.move(x, y)
    assert app.conn_btn.hover and cv.cget("cursor") == "hand2"
    cv.event_generate("<ButtonPress-1>", x=x, y=y)
    ui.pump(0.05)
    assert app.conn_btn.state == "pressed"
    cv.event_generate("<ButtonRelease-1>", x=x, y=y)
    ui.wait(lambda: app.status.connected and ui.idle())
    # The laser button only reacts inside its rounded square.
    ui.move(layout.CX, layout.LASER_CY)
    assert app.laser_btn.hover
    ui.move(app.laser_btn.x + 1, app.laser_btn.y + 1)          # rounded corner
    assert not app.laser_btn.hover
    ui.click(layout.CX, layout.LASER_CY)
    ui.wait(lambda: app.status.emitting)
    # Enter in the field applies the power.
    app.power.entry.focus_force()
    app.power.var.set("7.5")
    ui.pump(0.05)
    app.power.entry.event_generate("<Return>")
    ui.wait(lambda: app.status.setpoint_mw == 7.5)
    # Clicking a mode tile switches mode.
    ui.click(*ui.centre(app.mode_tiles[Mode.CAMERA]))
    ui.wait(lambda: app.status.mode is Mode.CAMERA and ui.idle())
    # Hidden and disabled controls ignore the pointer.
    assert not app.apply_btn.contains(*ui.centre(app.apply_btn))
    ui.move(*ui.centre(app.port_dd))
    assert cv.cget("cursor") == ""


def test_port_menu(ui):
    picker = ui.app.port_dd
    assert picker.key == "COM3" and len(picker.items) == 20       # COM3, then COM1-COM20 minus COM3
    assert picker.label == "COM3 – USB Serial Device"
    picker.open_menu()                       # returns at once on X11; the menu stays posted
    menu = picker._menu
    assert menu.index("end") == 19
    assert menu.entrycget(0, "label").startswith("✓")
    menu.invoke(1)                           # choose COM1
    menu.unpost()
    assert picker.key == "COM1"


def test_close_saves_settings(ui):
    app = ui.app
    ui.connect()
    app.power.var.set("12")
    app.apply_manual()
    ui.wait(lambda: app.status.setpoint_mw == 12.0)
    app.on_close()
    (settings,) = ui.saved
    assert settings.manual_power_mw == 12.0 and settings.mode == "manual"
    assert settings.last_port == "COM3"
