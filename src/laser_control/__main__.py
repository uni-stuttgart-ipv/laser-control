"""Start the app: python -m laser_control"""
import tkinter as tk
from pathlib import Path

from laser_control import log
from laser_control.controller import Controller
from laser_control.ui import MainWindow, chrome

ICON = Path(__file__).parent / "assets" / "laser_control-64.png"


def main():
    """Open the window and run until it is closed."""
    log.start()                     # every laser command and reply goes to log.LOG_FILE
    chrome.enable_dpi_awareness()   # sharp text on high-DPI Windows screens
    root = tk.Tk()
    root.iconphoto(True, tk.PhotoImage(file=ICON))
    controller = Controller()
    MainWindow(root, controller)

    def close():
        controller.shut_down()      # safety: the laser turns off when the window closes
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", close)
    root.mainloop()


if __name__ == "__main__":
    main()