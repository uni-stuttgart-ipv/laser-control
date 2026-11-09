"""What the window knows about the laser, and how each controller result changes it.

The controller never touches the window. It reports what happened as small
``(kind, value)`` tuples, such as ``("laser", True)`` or ``("error", "...")``.
Every 100 ms the window collects them and hands each one to
:meth:`State.apply`, which is the *only* place that turns a result into
something the screen shows.

Nothing here imports Tk, so this logic is tested without opening a window
(``tests/test_state.py``). The drawing code in ``sections/`` only *reads*
these attributes.
"""

from __future__ import annotations

from laser_control.controller import MAX_POWER_MW


class State:
    """Everything the screen shows that comes from the laser, plus the dial value.

    Args:
        port: The serial port to show first, or ``""`` if there is none.
    """

    def __init__(self, port: str):
        self.port = port
        self.connecting = False
        self.connected = False
        self.laser_on = False
        self.mode = "manual"   # "camera" or "manual"; chosen before connecting, applied on connect
        self.min_power = 0.0   # the laser's minimum, read when connecting
        self.setpoint = None   # last power the laser accepted, mW; None until it has one
        self.current = None    # diode current, mA; None until it has been read
        self.message = None    # banner as (level, text), level "warning" or "error"; None for no banner
        self.tab = "laser"     # "laser" or "log": which tab is shown; the app always opens on Laser

        # The value on the dial. It lives here rather than in power.py because
        # apply("connected") must clamp it to the laser's minimum. power.py only
        # decides *when* the user changes it and when it is sent.
        self.power = 5.0

    # ---- results from the controller ----

    def apply(self, kind: str, value) -> None:
        """Update the state from one controller result.

        Args:
            kind: What happened: ``connected``, ``disconnected``, ``error``,
                ``refused``, ``laser``, ``mode``, ``power`` or ``current``.
            value: The detail that comes with it, e.g. the laser's minimum
                power for ``connected`` or the message for ``error``.
        """
        if kind == "connected":
            self.connecting = False
            self.connected = True
            self.min_power = value
            self.power = self.clamp(self.power)   # the dial may be below this laser's minimum
        elif kind == "disconnected":
            self._not_connected()
        elif kind == "error":                     # the controller has already closed the port
            self._not_connected()
            self.message = ("error", value)
        elif kind == "refused":                   # e.g. interlock open: still connected, laser still off
            self.message = ("warning", value)
        elif kind == "laser":
            self.laser_on = value
            self.message = None                   # a successful on/off clears an old refusal
        elif kind == "mode":
            self.mode = value
        elif kind == "power":
            self.setpoint = value
        elif kind == "current":
            self.current = value

    def _not_connected(self) -> None:
        """Forget everything that came from the laser."""
        self.connecting = False
        self.connected = False
        self.laser_on = False
        self.setpoint = None
        self.current = None

    # ---- questions the drawing code asks ----

    @property
    def power_editable(self) -> bool:
        """True when the dial can be changed: connected and in manual mode."""
        return self.connected and self.mode == "manual"

    @property
    def can_switch_mode(self) -> bool:
        """True when the Camera / Manual switch works: the mode only changes while the laser is off."""
        return not self.laser_on and not self.connecting

    @property
    def can_connect(self) -> bool:
        """True when the Connect / Disconnect button works."""
        return self.connected or (not self.connecting and bool(self.port))

    def clamp(self, value: float) -> float:
        """Round to the dial's 0.1 mW step, then keep between the laser's minimum and MAX_POWER_MW."""
        return min(max(round(value, 1), self.min_power), MAX_POWER_MW)
