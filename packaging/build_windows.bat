@echo off
rem Build Laser Control on a Windows PC: tests, one-folder exe, then the installer if Inno Setup is present.
rem Run from the repo root in a normal Command Prompt. Needs Python 3.13 x64 from python.org.
setlocal
cd /d "%~dp0.."

if not exist .venv (
    py -3.13 -m venv .venv || goto :error
)
call .venv\Scripts\activate.bat || goto :error
python -m pip install -q -U pip || goto :error
pip install -q -c packaging\constraints.txt -e ".[dev,build]" || goto :error
for /f %%v in ('python -c "import laser_control; print(laser_control.__version__)"') do set VERSION=%%v

pytest -q || goto :error
pyinstaller --noconfirm --clean packaging\LaserControl.spec || goto :error
rem start /wait: a windowed exe would otherwise return before it finishes
start "" /wait dist\LaserControl\LaserControl.exe --smoke-test || goto :error
echo Built dist\LaserControl\LaserControl.exe (version %VERSION%, smoke test passed)

set ISCC="C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if exist %ISCC% (
    %ISCC% /DAppVersion=%VERSION% packaging\installer.iss || goto :error
    echo Built packaging\Output\LaserControl-Setup-%VERSION%.exe
) else (
    echo Inno Setup not found: skipping the installer. Zip dist\LaserControl instead.
)
exit /b 0

:error
echo Build failed.
exit /b 1
