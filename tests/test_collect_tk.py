"""tools/collect_tk.py (Windows and macOS layouts, simulated) and the tkinter_runtime template."""

import importlib.util
import json
import os
import sys
from pathlib import Path

import collect_tk   # tools/ is on pythonpath (pytest.ini)
import pytest


def make_fake_windows_python(prefix: Path) -> Path:
    """Lay out a minimal python.org-style Windows install; return its _tkinter.pyd path."""
    dlls = prefix / "DLLs"
    dlls.mkdir(parents=True)
    for name in ("_tkinter.pyd", "tcl86t.dll", "tk86t.dll", "zlib1.dll", "_ssl.pyd"):
        (dlls / name).write_bytes(b"binary")
    (prefix / "tcl" / "tcl8.6").mkdir(parents=True)
    (prefix / "tcl" / "tcl8.6" / "init.tcl").write_text("# init")
    (prefix / "tcl" / "tk8.6").mkdir(parents=True)
    (prefix / "tcl" / "tk8.6" / "tk.tcl").write_text("# tk")
    (prefix / "tcl" / "tcl8").mkdir()
    return dlls / "_tkinter.pyd"


def test_collect_windows_layout(tmp_path, monkeypatch):
    prefix = tmp_path / "Python312"
    ext = make_fake_windows_python(prefix)
    monkeypatch.setattr(collect_tk, "_find_tkinter_extension", lambda: ext)
    runtime = tmp_path / "out" / "tkinter_runtime"
    runtime.mkdir(parents=True)
    copied = collect_tk.collect_windows(runtime, prefix)
    assert set(copied) == {"_tkinter.pyd", "tcl86t.dll", "tk86t.dll", "zlib1.dll"}
    assert not (runtime / "_ssl.pyd").exists()
    assert (runtime / "tcl" / "tcl8.6" / "init.tcl").is_file()
    assert (runtime / "tcl" / "tk8.6" / "tk.tcl").is_file()


def test_collect_windows_fails_without_tcl(tmp_path, monkeypatch):
    prefix = tmp_path / "Python312"
    ext = make_fake_windows_python(prefix)
    (prefix / "DLLs" / "tcl86t.dll").unlink()
    monkeypatch.setattr(collect_tk, "_find_tkinter_extension", lambda: ext)
    runtime = tmp_path / "rt"
    runtime.mkdir()
    with pytest.raises(collect_tk.CollectError):
        collect_tk.collect_windows(runtime, prefix)


def _load_runtime(folder: Path):
    """Execute a copied tkinter_runtime/__init__.py under a throwaway module name."""
    spec = importlib.util.spec_from_file_location("tkinter_runtime_under_test", folder / "__init__.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_runtime_sets_tcl_tk_library(tmp_path, monkeypatch):
    rt = tmp_path / "tkinter_runtime"
    (rt / "tcl" / "tcl8.6").mkdir(parents=True)
    (rt / "tcl" / "tcl8.6" / "init.tcl").write_text("")
    (rt / "tcl" / "tk8.6").mkdir()
    (rt / "tcl" / "tk8.6" / "tk.tcl").write_text("")
    (rt / "tcl" / "tcl8").mkdir()                  # no init.tcl: must be ignored
    (rt / "__init__.py").write_bytes(collect_tk.TEMPLATE.read_bytes())
    (rt / "BUILD_INFO.json").write_text(json.dumps({"python": list(sys.version_info[:3])}))
    # setenv first so monkeypatch restores the real values (or absence) afterwards.
    for var in ("TCL_LIBRARY", "TK_LIBRARY"):
        monkeypatch.setenv(var, "/stale/path")
    monkeypatch.setattr(sys, "path", list(sys.path))
    _load_runtime(rt)
    # Stale values from other Tcl installs are overridden by the bundled scripts.
    assert os.environ["TCL_LIBRARY"] == str((rt / "tcl" / "tcl8.6").resolve())
    assert os.environ["TK_LIBRARY"] == str((rt / "tcl" / "tk8.6").resolve())
    assert str(rt.resolve()) in sys.path


def test_runtime_rejects_other_python_version(tmp_path, monkeypatch):
    rt = tmp_path / "tkinter_runtime"
    rt.mkdir()
    (rt / "__init__.py").write_bytes(collect_tk.TEMPLATE.read_bytes())
    (rt / "BUILD_INFO.json").write_text(json.dumps({"python": [2, 7, 18]}))
    monkeypatch.setattr(sys, "path", list(sys.path))
    with pytest.raises(ImportError, match="2.7"):
        _load_runtime(rt)


def test_runtime_prefers_recorded_tcl_version(tmp_path, monkeypatch):
    rt = tmp_path / "tkinter_runtime"
    for d, marker in (("tcl8.6", "init.tcl"), ("tcl9.0", "init.tcl"), ("tk8.6", "tk.tcl"), ("tk9.0", "tk.tcl")):
        (rt / "tcl" / d).mkdir(parents=True)
        (rt / "tcl" / d / marker).write_text("")
    (rt / "__init__.py").write_bytes(collect_tk.TEMPLATE.read_bytes())
    (rt / "BUILD_INFO.json").write_text(json.dumps({"python": list(sys.version_info[:3]),
                                                    "tcl_version": 8.6}))
    for var in ("TCL_LIBRARY", "TK_LIBRARY"):
        monkeypatch.setenv(var, "")
    monkeypatch.setattr(sys, "path", list(sys.path))
    _load_runtime(rt)
    assert os.environ["TCL_LIBRARY"].endswith("tcl8.6")
    assert os.environ["TK_LIBRARY"].endswith("tk8.6")


# ---------------------------------------------------------------------------- macOS
def _fake_mac(monkeypatch, ext: Path, deps: dict):
    """Run collect_macos without Xcode: fake otool/install_name_tool/codesign."""
    monkeypatch.setattr(collect_tk.shutil, "which", lambda tool: "/usr/bin/" + tool)
    monkeypatch.setattr(collect_tk, "_find_tkinter_extension", lambda: ext)
    monkeypatch.setattr(collect_tk, "_otool_deps",
                        lambda b: deps.get(Path(b).resolve(), deps.get(Path(b).name, [])))
    monkeypatch.setattr(collect_tk.subprocess, "run", lambda *a, **k: None)


def _write(path: Path, text: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def test_collect_macos_dylib_layout(tmp_path, monkeypatch):
    """python.org layout: lib/libtcl8.6.dylib with lib/tcl8.6 and lib/tk8.6 beside it."""
    prefix = tmp_path / "Python.framework" / "Versions" / "3.13"
    ext = _write(prefix / "lib" / "python3.13" / "lib-dynload" / "_tkinter.so")
    tcl = _write(prefix / "lib" / "libtcl8.6.dylib")
    tk = _write(prefix / "lib" / "libtk8.6.dylib")
    _write(prefix / "lib" / "tcl8.6" / "init.tcl")
    _write(prefix / "lib" / "tk8.6" / "tk.tcl")
    _fake_mac(monkeypatch, ext, {ext.resolve(): [str(tcl), str(tk), "/usr/lib/libSystem.B.dylib"]})
    runtime = tmp_path / "out" / "tkinter_runtime"
    runtime.mkdir(parents=True)
    names = collect_tk.collect_macos(runtime, prefix)
    assert set(names) == {"_tkinter.so", "libtcl8.6.dylib", "libtk8.6.dylib"}
    assert (runtime / "tcl" / "tcl8.6" / "init.tcl").is_file()
    assert (runtime / "tcl" / "tk8.6" / "tk.tcl").is_file()


def test_collect_macos_framework_layout(tmp_path, monkeypatch):
    """Tcl.framework / Tk.framework: binaries named Tcl / Tk, scripts in Resources/Scripts.

    A copied file named ``Tcl`` would clash with the ``tcl`` folder on macOS's
    case-insensitive disk ("File exists"), so the binaries must be renamed.
    """
    prefix = tmp_path / "py"
    ext = _write(prefix / "lib" / "python3.13" / "lib-dynload" / "_tkinter.so")
    fw = tmp_path / "Frameworks"
    tcl = _write(fw / "Tcl.framework" / "Versions" / "8.6" / "Tcl")
    tk = _write(fw / "Tk.framework" / "Versions" / "8.6" / "Tk")
    _write(fw / "Tcl.framework" / "Versions" / "8.6" / "Resources" / "Scripts" / "init.tcl")
    _write(fw / "Tk.framework" / "Versions" / "8.6" / "Resources" / "Scripts" / "tk.tcl")
    _fake_mac(monkeypatch, ext, {ext.resolve(): [str(tcl), str(tk)]})
    runtime = tmp_path / "out" / "tkinter_runtime"
    runtime.mkdir(parents=True)
    names = collect_tk.collect_macos(runtime, prefix)
    assert set(names) == {"_tkinter.so", "libtcl8.6.dylib", "libtk8.6.dylib"}
    assert not any(p.name.lower() in ("tcl", "tk") and p.is_file() for p in runtime.iterdir())
    assert (runtime / "tcl" / "tcl8.6" / "init.tcl").is_file()
    assert (runtime / "tcl" / "tk8.6" / "tk.tcl").is_file()
