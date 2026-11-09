"""Manual Control mode: continuously output at a power set in the GUI."""
import coherent_cube as cc


def apply(laser, power):
    """Apply the manual control mode to the laser."""
    laser.operation_mode = cc.OperationMode.CW
    laser.analog_control = cc.AnalogControl.Internal
    laser.power = power


def set_power(laser, power):
    """Set the power of the laser in mW while in manual control mode."""
    laser.power = power