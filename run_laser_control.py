"""Run Laser Control from a source checkout, without installing anything.

    python run_laser_control.py [--simulate] [--log-level DEBUG]

Same as ``python -m laser_app`` with ``src`` on the module path.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from laser_app.__main__ import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
