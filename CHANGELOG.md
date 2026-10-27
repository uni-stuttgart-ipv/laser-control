# Changelog

All notable changes to Laser Control. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[semantic versioning](https://semver.org/).

## [0.1.0] - 2026-10-27

First release.

### Added

- Tkinter desktop app for the lab laser: connection card with port menu and
  Connect / Disconnect button, Camera and Manual modes, power field, on/off
  button and readback bar, in a dark tile theme.
- Manual mode: CW output at any power within the laser's own limits (no app-side limits).
- Camera mode: pulsed, externally modulated output at a fixed 50 mW.
- Fail-safe controller: verified laser-off on connect, mode change,
  disconnect, close and communication errors; safety jobs jump the queue.
- Standard `pyproject.toml` metadata (authors, license, dependencies) used by pip and Briefcase; `laser-control` command.
- Built-in serial driver for the laser's protocol, with strict replies and a
  simulated device that speaks the same protocol.
- `--simulate` mode with a simulated laser; settings and rotating logs.
- Briefcase packaging for macOS and Windows, including bundled Tkinter
  (`tools/collect_tk.py`) and the app icon.
- Test suite (driver, controller, real serial I/O on a pseudo-terminal, GUI
  end-to-end, rendering and contrast, ports, settings, build helper) and
  GitHub Actions CI.
