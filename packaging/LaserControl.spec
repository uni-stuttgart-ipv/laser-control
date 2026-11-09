# PyInstaller spec for Laser Control: a one-folder, windowed build.
#
# Build on the target OS (PyInstaller cannot cross-compile), from the repo root:
#     pyinstaller --noconfirm --clean packaging/LaserControl.spec
# Output: dist/LaserControl/LaserControl(.exe) plus dist/LaserControl/_internal/
#
# One-folder (not one-file) starts faster and trips antivirus heuristics less,
# because nothing is unpacked to %TEMP% on every launch.

from PyInstaller.utils.hooks import collect_data_files

ROOT = SPECPATH + "/.."

a = Analysis(
    [ROOT + "/packaging/run_laser_control.py"],
    pathex=[ROOT + "/src"],
    datas=collect_data_files("laser_control", includes=["assets/*.ico", "assets/*.png"]),  # window icons only (no .DS_Store)
    hiddenimports=["serial.tools.list_ports_windows"],    # imported conditionally by pyserial on Windows
    excludes=["pytest"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="LaserControl",
    console=False,                                         # windowed: no console window
    icon=ROOT + "/src/laser_control/assets/laser_control.ico",
)
coll = COLLECT(exe, a.binaries, a.datas, name="LaserControl")
