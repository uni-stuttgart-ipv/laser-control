# Development

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
laser-control --simulate
```

`pip install -e ".[dev]"` installs the app in editable mode together with the
test, lint and Briefcase tools. All metadata and dependencies live in
`pyproject.toml`; `requirements*.txt` only point to it. The simulator (`--simulate`) offers one port, `SIM`, backed by
`hardware/simulator.py`: a simulated laser that speaks the real protocol.

## Tests and lint

```bash
pytest                                 # about 100 tests, ~10 s
python -m pyflakes src tests tools     # lint
```

Test settings live in `pyproject.toml` (`[tool.pytest.ini_options]`).

| Test file | What it covers | Needs |
|---|---|---|
| `test_controller.py` | Controller against the simulator: safety, queueing, modes, errors | – |
| `test_laser.py` | The serial driver and procedures against the simulated device: handshake, strict replies, refusals, power checks, verified off | – |
| `test_serial.py` | Driver and controller over a real serial port (the simulated device on a pseudo-terminal, `serial_pty.py`) | Linux or macOS |
| `test_ui_app.py` | The whole window driven with the simulated laser: connect, modes, power errors, mouse, port menu, settings | A display; skipped without one |
| `test_ui_render.py` | Theme, layout and Pillow rendering, including WCAG contrast of every text colour | – |
| `test_ui_text.py` | Power formatting/parsing and ellipsizing | – |
| `test_ports.py` | Port list and labels, Windows and macOS filtering | – |
| `test_config.py` | Saving and loading settings | – |
| `test_collect_tk.py` | The Briefcase Tkinter helper (Windows and macOS layouts) and its runtime loader | – |

On a Linux machine without a desktop, run the GUI tests with
`xvfb-run -a pytest`. GitHub Actions runs the whole suite this way on every
push (`.github/workflows/tests.yml`).

## Tools

| Command | What it does |
|---|---|
| `python tools/screenshots.py` | Regenerates `docs/screenshots/overview.png` from the simulated app |
| `python tools/make_icon.py` | Regenerates the app icon in `resources/` |
| `python tools/collect_tk.py` | Copies Tkinter for Briefcase builds (see [building.md](building.md)) |

## Conventions

- Never talk to the laser from the UI thread. Add a controller method that
  queues a job, and report results with events.
- Protocol details belong in `hardware/laser.py` (one method per command);
  safety rules and sequences in `hardware/operations.py`. Keep the simulator
  (`hardware/simulator.py`) in step with any protocol change.
- Keep laser-off paths verified, and add a test for every new safety rule.
- Colours go in `ui/theme.py`, positions in `ui/layout.py`; widgets and
  rendering code should not hard-code either.
- Every module, class and public function has a docstring that says what it
  does and why; comments explain the non-obvious.
- Update `CHANGELOG.md` for user-visible changes.
