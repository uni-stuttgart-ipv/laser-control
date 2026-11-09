"""Camera mode: the camera's analog signal drives the laser."""
import coherent_cube as cc


def apply(laser, power):
    """Apply the camera mode to the laser."""
    laser.analog_control_mode = cc.AnalogControlMode.Current
    laser.analog_control = cc.AnalogControl.External
    laser.operation_mode = cc.OperationMode.Pulsed
    laser.power = power
    laser.calibrate(power)
