"""Laser Control: a small desktop app for driving a serial-controlled laser.

Package layout (dependencies point down only)::

    ui/          Tkinter window; talks only to the controller and the model
    controller   state machine, polling, public API for the UI (main thread)
    worker       the single thread that owns the serial port
    sequences    the laser command sequences, the only code that writes to the laser
    driver       serial protocol driver (supplied backend, kept unchanged)

``model``, ``errors``, ``config``, ``ports`` and ``sim`` are shared helpers.
"""

__version__ = "0.1.0"
