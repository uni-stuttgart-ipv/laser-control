"""Tkinter user interface.

The UI depends only on :mod:`laser_control.controller` and
:mod:`laser_control.model`; it never imports the driver, the worker or the
sequences, and never blocks on the laser.
"""

from laser_control.ui.window import MainWindow

__all__ = ["MainWindow"]
