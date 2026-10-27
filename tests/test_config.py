"""Settings file: round-trip and tolerance of missing or bad content."""

import json

import pytest

from laser_app.config import Settings, load_settings, save_settings


def test_round_trip(tmp_path):
    path = tmp_path / "sub" / "settings.json"
    saved = Settings(last_port="COM7", mode="camera", manual_power_mw=12.5)
    save_settings(saved, path)
    assert load_settings(path) == saved


def test_missing_file_gives_defaults(tmp_path):
    assert load_settings(tmp_path / "nope.json") == Settings()


def test_corrupt_file_gives_defaults(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{not json", encoding="utf-8")
    assert load_settings(path) == Settings()


def test_unknown_keys_are_ignored(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"last_port": "COM3", "camera_power_mw": 40, "x": 1}),
                    encoding="utf-8")
    assert load_settings(path) == Settings(last_port="COM3")


def test_bad_mode_falls_back_to_manual(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"mode": "turbo", "manual_power_mw": 7}), encoding="utf-8")
    s = load_settings(path)
    assert s.mode == "manual"
    assert s.manual_power_mw == 7.0 and isinstance(s.manual_power_mw, float)


def test_version_matches_pyproject():
    """``laser_app.__version__`` and pyproject.toml must name the same version."""
    tomllib = pytest.importorskip("tomllib")       # Python 3.11+
    from pathlib import Path

    import laser_app
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    assert data["project"]["version"] == laser_app.__version__
