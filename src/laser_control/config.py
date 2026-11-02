"""Small JSON settings file (last port, last power, timeouts).

Location:

* Windows: ``%APPDATA%\\LaserControl\\config.json``
* macOS: ``~/Library/Application Support/LaserControl/config.json``
* other: ``~/.config/laser_control/config.json``

A missing or corrupt file falls back to defaults; writes are atomic.
"""

from __future__ import annotations

import json
import logging
import math
import os
import sys
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from laser_control.model import DEFAULT_PORT

logger = logging.getLogger(__name__)

CONFIG_VERSION = 1


@dataclass
class AppConfig:
    """User settings remembered between runs.

    Attributes:
        last_port: Port of the last successful connection.
        last_power_mw: Last manual-mode power that was applied.
        timeout_s: Serial read/write timeout in seconds.
        poll_interval_ms: How often set point and current are read.
    """

    last_port: str = DEFAULT_PORT
    last_power_mw: float = 5.0
    timeout_s: float = 2.0
    poll_interval_ms: int = 1000


TIMEOUT_RANGE_S = (0.2, 30.0)
"""Serial timeout bounds. Zero would make reads non-blocking and desync the reply stream."""
POLL_RANGE_MS = (250, 60_000)


def validated(cfg: AppConfig) -> AppConfig:
    """Return ``cfg`` with every value forced into a safe range (defaults for nonsense)."""
    default = AppConfig()

    def number(value, fallback, low=None, high=None):
        try:
            value = float(value)
        except (TypeError, ValueError):
            return fallback
        if not math.isfinite(value):
            return fallback
        if low is not None:
            value = max(low, value)
        if high is not None:
            value = min(high, value)
        return value

    return AppConfig(
        last_port=cfg.last_port if isinstance(cfg.last_port, str) and cfg.last_port.strip() else default.last_port,
        last_power_mw=number(cfg.last_power_mw, default.last_power_mw, low=0.0),
        timeout_s=number(cfg.timeout_s, default.timeout_s, *TIMEOUT_RANGE_S),
        poll_interval_ms=int(number(cfg.poll_interval_ms, default.poll_interval_ms, *POLL_RANGE_MS)),
    )


def config_dir() -> Path:
    """Return the per-user settings directory for this OS."""
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "LaserControl"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "LaserControl"
    return Path.home() / ".config" / "laser_control"


def _default_path() -> Path:
    return config_dir() / "config.json"


def load_config(path: Path | None = None) -> AppConfig:
    """Load settings, ignoring unknown keys, clamping values (see :func:`validated`)
    and falling back to defaults on any error."""
    path = path or _default_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        known = {f.name for f in fields(AppConfig)}
        return validated(AppConfig(**{k: v for k, v in data.items() if k in known}))
    except FileNotFoundError:
        return AppConfig()
    except Exception as exc:
        logger.warning("ignoring unreadable config %s: %r", path, exc)
        return AppConfig()


def save_config(cfg: AppConfig, path: Path | None = None) -> None:
    """Write settings atomically (temp file, then rename)."""
    path = path or _default_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"version": CONFIG_VERSION, **asdict(cfg)}, indent=2), encoding="utf-8")
    os.replace(tmp, path)
