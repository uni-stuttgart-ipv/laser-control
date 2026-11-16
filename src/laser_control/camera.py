"""Camera mode: the camera's analog signal drives the laser.

calibrate(power) takes the laser's output at that moment to be `power`, so the
laser must be emitting `power` when it runs. apply() therefore first runs the
laser continuously at `power` for WARM_UP_S, then switches to pulsed, external
control and calibrates against that output. Calibrating with the laser off
leaves camera mode almost dark (measured on the lab laser: 0.06 mW instead of
about 21 mW).
"""
import time

import coherent_cube as cc

from laser_control import manual

WARM_UP_S = 1   # seconds of continuous output at full power before calibrating


def apply(laser, power):
    """Apply the camera mode to the laser. The laser is on afterwards, in pulse mode."""
    manual.apply(laser, power)     # continuous at `power`, exactly like manual mode
    laser.on()
    time.sleep(WARM_UP_S)

    laser.analog_control_mode = cc.AnalogControlMode.Current
    laser.analog_control = cc.AnalogControl.External
    laser.operation_mode = cc.OperationMode.Pulsed
    laser.power = power
    laser.calibrate(power)
