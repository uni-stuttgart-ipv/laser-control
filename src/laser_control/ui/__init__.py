"""Tkinter user interface.

The window talks only to :mod:`laser_control.controller`; it never uses the
laser directly and never blocks on it.
"""

from laser_control.ui.window import MainWindow

__all__ = ["MainWindow"]
