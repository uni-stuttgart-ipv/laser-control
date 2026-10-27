"""Everything that talks to (or stands in for) the laser hardware.

* ``laser``      - ``Laser``: the serial driver, one method per protocol command.
* ``operations`` - the procedures built on it: verified off, power checks, the two modes.
* ``simulator``  - a simulated laser speaking the same protocol, for ``--simulate`` and tests.
* ``ports``      - the serial port list shown in the Connection card.

Only the controller's worker thread calls into this package.
"""
