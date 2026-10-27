"""Makes the Tkinter copied in by ``tools/collect_tk.py`` usable inside a Briefcase app.

Briefcase's Python for Windows and macOS ships without Tkinter. ``collect_tk.py``
copies, from an official python.org install of the *same* Python version:

* the ``tkinter`` package          -> a sibling source folder (``tkinter/``)
* the ``_tkinter`` extension and the Tcl/Tk shared libraries -> this folder
* the Tcl/Tk script libraries      -> ``./tcl/``

Importing this package (laser_app does it before importing tkinter):

1. puts this folder on ``sys.path`` so ``import _tkinter`` finds the extension,
2. lets Windows find the Tcl/Tk DLLs next to it,
3. points ``TCL_LIBRARY`` / ``TK_LIBRARY`` at the bundled script libraries.

Generated file: edit ``tools/tkinter_runtime_template/__init__.py``, not the copy.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent


def _build_info() -> dict:
    """Contents of ``BUILD_INFO.json`` written by collect_tk.py, or {} if absent."""
    try:
        return json.loads((_HERE / "BUILD_INFO.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _check_python_version(info: dict) -> None:
    """Raise ImportError if Tkinter was collected from a different Python minor version."""
    want = tuple(info.get("python", ())[:2])
    if want and want != tuple(sys.version_info[:2]):
        raise ImportError(
            f"Bundled Tkinter was collected from Python {want[0]}.{want[1]} but this app "
            f"runs Python {sys.version_info[0]}.{sys.version_info[1]}. Re-run "
            "tools/collect_tk.py with the same Python that runs Briefcase.")


def _find_script_dir(prefix: str, marker: str, version: str | None) -> Path | None:
    """``tcl/<prefix><version>`` if present, else the newest ``tcl/<prefix>X.Y`` with ``marker``."""
    if version:
        exact = _HERE / "tcl" / f"{prefix}{version}"
        if (exact / marker).is_file():
            return exact
    hits = [p for p in (_HERE / "tcl").glob(prefix + "[0-9]*") if (p / marker).is_file()]
    return max(hits, key=lambda p: p.name) if hits else None


_INFO = _build_info()
_check_python_version(_INFO)

if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

if sys.platform == "win32" and hasattr(os, "add_dll_directory"):
    _DLL_DIR = os.add_dll_directory(str(_HERE))   # keep a reference: closing removes it

# Always use the bundled scripts: a TCL_LIBRARY left by another Tcl install on
# this computer (ActiveTcl, MSYS, ...) would otherwise break Tk with a
# "Can't find a usable init.tcl" error.
_TCL_VERSION = str(_INFO["tcl_version"]) if _INFO.get("tcl_version") else None
for _var, _prefix, _marker in (("TCL_LIBRARY", "tcl", "init.tcl"), ("TK_LIBRARY", "tk", "tk.tcl")):
    _dir = _find_script_dir(_prefix, _marker, _TCL_VERSION)
    if _dir is not None:
        os.environ[_var] = str(_dir)
