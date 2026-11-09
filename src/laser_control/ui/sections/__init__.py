"""The window's sections, drawn top to bottom by ``MainWindow.render()``.

::

    ┌──────────────────────────────┐
    │ header       title + status  │
    │ port_row     COM3 ▾  Connect │
    │ mode_bar     Camera | Manual │
    │ power_card   dial, − +       │  (manual mode only)
    │ laser_card   Off        (⏻)  │
    │ message      hint or banner  │
    │ readouts     mW | mA | mode  │
    └──────────────────────────────┘

Every section file has one function, ``draw(win, y)``: it draws its part with
its top edge at ``y`` and returns the ``y`` where the next section starts.
Sections only *read* ``win.state``; clicks call the window's action methods.
"""
