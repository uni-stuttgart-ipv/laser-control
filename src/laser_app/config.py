"""Small JSON settings file and log folder in the usual per-user locations.

Settings (``settings.json``):

* Windows: ``%APPDATA%\\LaserControl``
* macOS:   ``~/Library/Application Support/LaserControl``
* Linux:   ``$XDG_CONFIG_HOME/LaserControl`` (default ``~/.config/LaserControl``)

Logs: ``<settings folder>/logs`` on Windows and Linux,
``~/Library/Logs/LaserControl`` on macOS.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)
APP_NAME = "LaserControl"


def config_dir() -> Path:
    """Per-user folder holding ``settings.json`` (see the module docstring)."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / APP_NAME


def log_dir() -> Path:
    """Per-user folder for the rotating log file."""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Logs" / APP_NAME
    return config_dir() / "logs"


@dataclass
class Settings:
    """Values remembered between runs."""

    last_port: Optional[str] = None
    mode: str = "manual"            # "manual" | "camera"
    manual_power_mw: float = 5.0    # default manual power
    # Camera mode always uses controller.CAMERA_POWER_MW (50 mW), so it is not stored.


def load_settings(path: Optional[Path] = None) -> Settings:
    """Load settings from ``path`` (default: ``config_dir()/settings.json``).

    A missing or unreadable file gives the defaults; unknown keys are ignored
    and an unknown mode falls back to ``"manual"``. Never raises.
    """
    path = path or config_dir() / "settings.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        known = {f.name for f in fields(Settings)}
        s = Settings(**{k: v for k, v in data.items() if k in known})
        if s.mode not in ("manual", "camera"):
            s.mode = "manual"
        s.manual_power_mw = float(s.manual_power_mw)
        return s
    except FileNotFoundError:
        return Settings()
    except Exception:
        log.warning("Settings file %s is unreadable; using defaults.", path)
        return Settings()


def save_settings(settings: Settings, path: Optional[Path] = None) -> None:
    """Write ``settings`` atomically (temp file + rename). Errors are logged, not raised."""
    path = path or config_dir() / "settings.json"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(settings), indent=2), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        log.exception("Could not save settings to %s", path)
