"""Collect Tkinter so Briefcase can bundle it (Windows and macOS).

Briefcase builds Windows apps on Python's "embeddable" package and macOS apps
on a re-bundled python.org framework; both have Tkinter removed. This script
copies Tkinter from the Python running it into ``build_support/``, where
``pyproject.toml`` lists it as extra app sources:

    build_support/tk-<windows|macos>/
        tkinter/                    the stdlib tkinter package
        tkinter_runtime/            _tkinter extension + Tcl/Tk libraries + tcl/ scripts
                                    + __init__.py (from tools/tkinter_runtime_template)

Run it ONCE per build machine, with the SAME Python that runs Briefcase
(ideally a python.org install), before ``briefcase create``:

    python tools/collect_tk.py

Re-run it after upgrading Python to a new minor version (3.12 -> 3.13).
"""

from __future__ import annotations

import argparse
import json
import platform
import re
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = Path(__file__).resolve().parent / "tkinter_runtime_template" / "__init__.py"
SYSTEM_LIB_PREFIXES = ("/usr/lib/", "/System/")


class CollectError(RuntimeError):
    """Tkinter could not be collected from this Python (message says why)."""


# ---------------------------------------------------------------------------- helpers
def _copytree(src: Path, dst: Path) -> None:
    """Copy a tree, skipping bytecode caches and test folders."""
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "test", "tests"))


def _find_tkinter_package() -> Path:
    """Folder of the stdlib ``tkinter`` package of this Python."""
    import tkinter                       # the real one, from this Python
    pkg = Path(tkinter.__file__).resolve().parent
    if not (pkg / "__init__.py").is_file():
        raise CollectError(f"Unexpected tkinter location: {pkg}")
    return pkg


def _find_tkinter_extension() -> Path:
    """Path of this Python's ``_tkinter`` extension module (raises ``CollectError`` if none)."""
    try:
        import _tkinter
    except ImportError as exc:
        raise CollectError(f"This Python has no working Tkinter ({exc}). Use a python.org "
                           "install (Windows: tick 'tcl/tk and IDLE'; macOS: the "
                           "python.org installer).") from exc
    path = getattr(_tkinter, "__file__", None)
    if not path:
        raise CollectError("_tkinter is built into this Python; cannot copy it. "
                           "Use a python.org install.")
    return Path(path).resolve()


# ---------------------------------------------------------------------------- Windows
def collect_windows(runtime: Path, prefix: Path) -> list[str]:
    """Copy ``_tkinter.pyd``, the Tcl/Tk DLLs and ``<prefix>/tcl`` into ``runtime``.

    Returns the names of the copied binaries.
    """
    ext = _find_tkinter_extension()
    dll_dir = ext.parent
    shutil.copy2(ext, runtime / ext.name)
    copied = [ext.name]
    # Tcl/Tk DLLs sit next to _tkinter.pyd in <prefix>\DLLs (tcl86t.dll, tk86t.dll,
    # or tcl90.dll / tcl9tk90.dll for Tcl/Tk 9, plus zlib1.dll on some versions).
    for pattern in ("tcl*.dll", "tk*.dll", "zlib*.dll", "libtommath*.dll"):
        for dll in dll_dir.glob(pattern):
            shutil.copy2(dll, runtime / dll.name)
            copied.append(dll.name)
    if not any(n.lower().startswith("tcl") for n in copied):
        raise CollectError(f"No Tcl DLL found next to {ext}")
    tcl_src = prefix / "tcl"
    if not tcl_src.is_dir():
        raise CollectError(f"Tcl script folder not found: {tcl_src}")
    _copytree(tcl_src, runtime / "tcl")
    return copied


# ---------------------------------------------------------------------------- macOS
def _otool_deps(binary: Path) -> list[str]:
    """Install names of the libraries ``binary`` links against (``otool -L``)."""
    out = subprocess.run(["otool", "-L", str(binary)], check=True, capture_output=True,
                         text=True).stdout
    deps = []
    for line in out.splitlines()[1:]:
        m = re.match(r"\s+(\S.*?) \(compatibility", line)
        if m:
            deps.append(m.group(1))
    return deps


def _resolve_dep(dep: str, binary: Path, rpaths: list[Path]) -> Path | None:
    """Resolve an ``@loader_path`` / ``@rpath`` / absolute install name to a file, or None."""
    if dep.startswith("@loader_path/"):
        return (binary.parent / dep[len("@loader_path/"):]).resolve()
    if dep.startswith("@rpath/"):
        for rp in rpaths:
            cand = rp / dep[len("@rpath/"):]
            if cand.exists():
                return cand.resolve()
        return None
    if dep.startswith("@"):
        return None
    return Path(dep).resolve()


def _tk_framework(real: Path) -> str | None:
    """``"tcl"`` / ``"tk"`` if ``real`` is the binary inside ``Tcl.framework`` / ``Tk.framework``."""
    for part in reversed(real.parts):
        if part.endswith(".framework"):
            kind = part[: -len(".framework")].lower()
            return kind if kind in ("tcl", "tk") else None
    return None


def _local_name(real: Path) -> str:
    """File name for a copied library inside ``tkinter_runtime``.

    Framework binaries have bare names (``Tcl.framework/Versions/8.6/Tcl``). A
    file called ``Tcl`` would clash with the ``tcl`` script folder on macOS's
    case-insensitive disks, so those get a ``lib<name><version>.dylib`` name.
    """
    if _tk_framework(real) is None or real.suffix:
        return real.name
    return f"lib{real.name.lower()}{real.parent.name}.dylib"


def _script_dirs_for(real: Path) -> list[tuple[Path, str]]:
    """Tcl/Tk script folders belonging to library ``real``, as (source, folder name) pairs.

    * Plain dylibs (python.org layout): ``lib/tcl8.6``, ``lib/tk8.6`` next to the library.
    * Frameworks: ``Tcl.framework/Versions/8.6/Resources/Scripts`` -> ``tcl8.6``.
    """
    found = []
    kind = _tk_framework(real)
    if kind:
        scripts = real.parent / "Resources" / "Scripts"
        if scripts.is_dir():
            found.append((scripts, f"{kind}{real.parent.name}"))
        return found
    for sub in sorted(real.parent.iterdir()):
        if sub.is_dir() and re.fullmatch(r"(tcl|tk)\d[\d.]*", sub.name):
            found.append((sub, sub.name))
    return found


def collect_macos(runtime: Path, prefix: Path) -> list[str]:
    """Copy ``_tkinter`` and its non-system libraries into ``runtime``, relink and re-sign them.

    Also copies the Tcl/Tk script folders into ``runtime/tcl``. Returns the
    names of the binaries written.
    """
    for tool in ("otool", "install_name_tool", "codesign"):
        if not shutil.which(tool):
            raise CollectError(f"'{tool}' not found. Install the Xcode command line tools: "
                               "xcode-select --install")
    ext = _find_tkinter_extension()
    rpaths = [prefix / "lib", ext.parent, ext.parent.parent]
    # Copy _tkinter and every non-system library it (transitively) needs.
    pending = [(ext, runtime / ext.name)]
    copied: dict[str, Path] = {}         # original dep string -> copied file
    scripts: dict[str, Path] = {}       # folder name in tcl/ -> source folder
    while pending:
        src, dst = pending.pop()
        shutil.copy2(src, dst)
        dst.chmod(0o755)
        for dep in _otool_deps(src):
            if dep.startswith(SYSTEM_LIB_PREFIXES) or Path(dep).name == "Python":
                continue                 # OS libraries / the Python framework itself
            if Path(dep).name in (src.name, ext.name):
                continue
            real = _resolve_dep(dep, src, rpaths)
            if real is None or not real.exists():
                if "tcl" in dep.lower() or "tk" in dep.lower():
                    raise CollectError(f"Cannot locate {dep} needed by {src.name}")
                continue
            if dep not in copied:
                target = runtime / _local_name(real)
                copied[dep] = target
                if not target.exists():
                    pending.append((real, target))
                for src_dir, name in _script_dirs_for(real):
                    scripts.setdefault(name, src_dir)
    if not any("tcl" in p.name.lower() for p in copied.values()):
        raise CollectError(f"{ext.name} does not link a Tcl library; is this a python.org Python?")

    # Point every copied binary at its siblings and give the libraries local ids.
    binaries = [runtime / ext.name] + sorted(set(copied.values()))
    for b in binaries:
        args = []
        for dep, target in copied.items():
            if dep in _otool_deps(b):
                args += ["-change", dep, f"@loader_path/{target.name}"]
        if b != runtime / ext.name:
            args += ["-id", f"@rpath/{b.name}"]
        if args:
            subprocess.run(["install_name_tool", *args, str(b)], check=True,
                           capture_output=True)
        # install_name_tool invalidates signatures; re-sign ad hoc (Briefcase re-signs later).
        subprocess.run(["codesign", "--force", "--sign", "-", str(b)], check=True,
                       capture_output=True)

    # Fallback: python.org's own lib/tcl8.6 and lib/tk8.6.
    lib = prefix / "lib"
    if lib.is_dir():
        for sub in sorted(lib.iterdir()):
            if sub.is_dir() and re.fullmatch(r"(tcl|tk)\d[\d.]*", sub.name):
                scripts.setdefault(sub.name, sub)
    tcl_out = runtime / "tcl"
    tcl_out.mkdir()
    for name, src_dir in sorted(scripts.items()):
        _copytree(src_dir, tcl_out / name)
    if not any((p / "init.tcl").exists() for p in tcl_out.glob("tcl*")):
        libs = ", ".join(str(p) for p in copied) or "none"
        raise CollectError(f"Tcl script library (init.tcl) not found. Libraries linked: {libs}")
    return [b.name for b in binaries]


# ---------------------------------------------------------------------------- main
def main(argv: list[str] | None = None) -> int:
    """Command-line entry point. Returns the exit code."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, default=None,
                        help="output folder (default: build_support/tk-<platform>)")
    args = parser.parse_args(argv)

    if sys.platform == "win32":
        plat, collect = "windows", collect_windows
    elif sys.platform == "darwin":
        plat, collect = "macos", collect_macos
    else:
        print("Only needed on Windows and macOS (Linux Briefcase builds use the system "
              "Python, which has Tkinter).")
        return 0

    out = args.out or ROOT / "build_support" / f"tk-{plat}"
    prefix = Path(sys.base_prefix)
    if out.exists():
        shutil.rmtree(out)
    runtime = out / "tkinter_runtime"
    runtime.mkdir(parents=True)

    try:
        pkg = _find_tkinter_package()
        _copytree(pkg, out / "tkinter")
        binaries = collect(runtime, prefix)
    except (CollectError, subprocess.CalledProcessError, OSError) as exc:
        shutil.rmtree(out, ignore_errors=True)
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    shutil.copy2(TEMPLATE, runtime / "__init__.py")
    info = {
        "python": list(sys.version_info[:3]),
        "platform": plat,
        "machine": platform.machine(),
        "source_prefix": str(prefix),
        "binaries": binaries,
        "tcl_version": __import__("tkinter").TclVersion,
        "soabi": sysconfig.get_config_var("SOABI"),
    }
    (runtime / "BUILD_INFO.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    print(f"Collected Tkinter (Python {sys.version.split()[0]}, Tcl/Tk {info['tcl_version']}) "
          f"into {out}")
    print("Now run:  briefcase create  (or: briefcase update -r) and build as usual.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
