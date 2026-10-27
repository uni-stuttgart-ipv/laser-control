# Building the app with Briefcase

Laser Control is packaged with [Briefcase](https://briefcase.beeware.org).
The settings are in `pyproject.toml`; the app is `laser_app`, shown as
**Laser Control**, with the icon from `resources/`.

## Why there is an extra Tkinter step

Briefcase's Windows builds use Python's "embeddable" package, which has no
Tkinter, and its macOS Python has Tkinter removed. `tools/collect_tk.py`
copies Tkinter from the Python you build with into `build_support/`, and
`pyproject.toml` adds that folder to the app. Run it **before**
`briefcase create`. If it is skipped, `create` stops with
"Application source 'build_support/tk-macos/tkinter' does not exist".

## Requirements

- Python **3.11+** from **python.org**. Use the same Python to run
  `collect_tk.py` and Briefcase.
  - Windows installer: keep "tcl/tk and IDLE" ticked.
  - macOS: install the Xcode command line tools with `xcode-select --install`.
- Build the Windows app on Windows and the macOS app on a Mac.

## macOS

In the project folder:

```bash
python3 -m venv .venv-build
source .venv-build/bin/activate
pip install -e ".[dev]"              # includes Briefcase
rm -rf build && python tools/collect_tk.py && briefcase create && briefcase build && briefcase run
```

The `&&` stops the chain at the first failure, so a half-made app is never
built or run.

Then package it:

| Who will use it | Command | Result |
|---|---|---|
| Your own / the lab's Macs | `briefcase package --adhoc-sign` | `.dmg` in `dist/` |
| Other people | `briefcase package` (needs an Apple Developer ID) | signed `.dmg` in `dist/` |

An ad-hoc signed app warns "unidentified developer" on first launch: right-click
the app, choose **Open**, then **Open** again.

## Windows

In the project folder:

```bat
py -3.12 -m venv .venv-build
.venv-build\Scripts\activate
pip install -e ".[dev]"
python tools\collect_tk.py
briefcase create
briefcase build
briefcase run
briefcase package
```

`briefcase package` makes an `.msi` installer in `dist\`.

## After changes

| Change | Run |
|---|---|
| Code changed | `briefcase update`, then `briefcase build` and `briefcase run` |
| `requires` in `pyproject.toml` changed | `briefcase update -r` |
| Icon changed (`python tools/make_icon.py`) | `briefcase update --update-resources` |
| Python upgraded to a new minor version (3.12 → 3.13) | `rm -rf build`, `python tools/collect_tk.py`, `briefcase create` |

## Troubleshooting

| Problem | Fix |
|---|---|
| `create` says `build_support/tk-…/tkinter` does not exist | Run `python tools/collect_tk.py` first (see above). |
| `collect_tk.py` prints `ERROR: …` | Use a python.org Python. The error lists the Tcl/Tk libraries it found. |
| The app says "Bundled Tkinter was collected from Python X.Y…" | `collect_tk.py` and Briefcase ran with different Pythons. Use one Python for both, then `rm -rf build` and run the chain again. |
| `ModuleNotFoundError: No module named 'serial'` in the built app | A previous `create` failed half-way. `rm -rf build` and run the chain again. |
| The app shows "a required component (Tkinter or Pillow) is missing" | Same as above: rebuild from a clean `build/`. |

`build/`, `dist/`, `logs/` and `build_support/` are generated and ignored by git.
