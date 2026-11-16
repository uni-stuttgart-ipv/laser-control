"""The only module the window talks to.

It holds the connected laser and runs every laser command on one background
thread, one at a time, so the window never freezes and commands never overlap.
The window calls the methods below, then collects what happened with
get_results().
"""
import logging
import queue
import threading
import warnings

from coherent_cube import CoherentCube

from laser_control import camera, manual, ports

log = logging.getLogger(__name__)                  # technical lines: each action, full errors
events = logging.getLogger("laser_control.events")  # plain-words lines: one per result (see _report)

MAX_POWER_MW = 50      # highest power the window allows in manual mode
CAMERA_POWER_MW = 50   # camera mode: output power and calibration power
TIMEOUT_S = 2          # how long to wait for a reply from the laser


def describe(kind, value):
    """One result in plain words, for the log: ("laser", True) -> "Laser on"."""
    if kind == "connected":
        return f"Connected. Laser range {value:g}–{MAX_POWER_MW} mW"
    if kind == "disconnected":
        return "Disconnected"
    if kind == "laser":
        return "Laser on" if value else "Laser off"
    if kind == "mode":
        return f"{value.capitalize()} mode"
    if kind == "power":
        return f"Power set to {value:.1f} mW"
    if kind == "current":
        return f"Diode current {value:.1f} mA"
    if kind == "refused":
        return value                       # the laser's own reason, e.g. "... interlock open."
    return f"Error: {value}"


class Controller:
    """Faces the window: one method per user action."""

    def __init__(self):
        self.laser = None          # the connected CoherentCube, or None
        self.laser_is_on = False
        self.min_power = 0.0       # read from the laser when connecting
        self._jobs = queue.Queue()      # commands waiting to run, in order
        self._results = queue.Queue()   # what happened, for the window
        self._thread = threading.Thread(target=self._run_jobs, daemon=True)
        self._thread.start()

    # ---- called by the window: each one only queues a job ----

    def get_ports(self):
        """Return the names of the serial ports."""
        return ports.get_serial_ports()

    def connect(self, port, mode, power):
        """Connect to the laser on `port`, then apply `mode` ("camera" or "manual")."""
        self._jobs.put((self._connect, (port, mode, power)))

    def disconnect(self):
        """Turn the laser off and close the port."""
        self._jobs.put((self._disconnect, ()))

    def turn_on(self):
        """Turn the laser on."""
        self._jobs.put((self._turn_on, ()))

    def turn_off(self):
        """Turn the laser off."""
        self._jobs.put((self._turn_off, ()))

    def use_mode(self, mode, power):
        """Switch to `mode` ("camera" or "manual"); the laser stays on or off as it was."""
        self._jobs.put((self._use_mode, (mode, power)))

    def set_power(self, power):
        """Change the power in manual mode."""
        self._jobs.put((self._set_power, (power,)))

    def get_results(self):
        """Return everything that happened since the last call, oldest first."""
        results = []
        while not self._results.empty():
            results.append(self._results.get())
        return results

    def shut_down(self):
        """Turn the laser off and close the port, then stop the thread."""
        self._jobs.put((self._disconnect, ()))
        self._jobs.put(None)            # tells the thread to stop
        self._thread.join(timeout=5)    # wait, but never hang the window forever

    # ---- the background thread ----

    def _run_jobs(self):
        """Run queued jobs one at a time until shut_down()."""
        while True:
            job = self._jobs.get()
            if job is None:
                break
            function, args = job
            log.info("%s %s", function.__name__.lstrip("_"), args)   # e.g. "connect ('COM3', 'manual', 5.0)"
            try:
                function(*args)
            except Exception as error:
                log.exception("failed, closing the port")   # the full error and where it happened
                self._close_quietly()
                self._report("error", str(error))

    def _connect(self, port, mode, power):
        self.laser = CoherentCube(port, timeout=TIMEOUT_S, write_timeout=TIMEOUT_S)
        self.laser.off()                       # start from a known state
        self.laser_is_on = False
        self.min_power = self.laser.min_power
        self._report("connected", self.min_power)
        self._use_mode(mode, power)

    def _disconnect(self):
        if self.laser is not None:
            self.laser.off()
            self.laser.close()
            self.laser = None
        self.laser_is_on = False
        self._report("disconnected", None)

    def _turn_on(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            self.laser.on()
        if caught:                              # the laser refused, e.g. interlock open
            self._report("refused", str(caught[0].message))
        else:
            self.laser_is_on = True
            self._report("laser", True)
        self._report_current()

    def _turn_off(self):
        self.laser.off()
        self.laser_is_on = False
        self._report("laser", False)
        self._report_current()

    def _use_mode(self, mode, power):
        if mode == "camera":                        # 1 s continuous at full power, calibrate, then on in pulse mode
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                camera.apply(self.laser, CAMERA_POWER_MW)
            refused = [w for w in caught if str(w.message).startswith("Can not turn laser on")]
            self.laser_is_on = not refused         # e.g. interlock open: it never turned on
            self._report("laser", self.laser_is_on)
            self._report("mode", "camera")
            self._report("power", CAMERA_POWER_MW)   # no query right after calibrate
            if refused:
                self._report("refused", str(refused[0].message))
        else:
            power = self._limit(power)
            manual.apply(self.laser, power)          # the laser stays on or off as it was
            self._report("mode", "manual")
            self._report("power", power)

    def _set_power(self, power):
        power = self._limit(power)
        manual.set_power(self.laser, power)
        self._report("power", power)
        self._report_current()

    def _limit(self, power):
        """Keep power between the laser's minimum and MAX_POWER_MW."""
        return max(self.min_power, min(power, MAX_POWER_MW))

    def _report(self, kind, value):
        """Tell the window what happened, and write the same in plain words to the log.

        Refusals are logged as warnings and errors as errors, so the Log tab
        shows them in amber and red.
        """
        level = {"refused": logging.WARNING, "error": logging.ERROR}.get(kind, logging.INFO)
        events.log(level, describe(kind, value))
        self._results.put((kind, value))

    def _report_current(self):
        self._report("current", self.laser.current)

    def _close_quietly(self):
        """After an error: try to turn off and close, ignoring further errors."""
        if self.laser is not None:
            for step in (self.laser.off, self.laser.close):
                try:
                    step()
                except Exception:
                    pass
        self.laser = None
        self.laser_is_on = False