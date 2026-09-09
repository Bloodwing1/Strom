# Strom native Linux GUI implementation plan

## Goal and decisions

Implement a small native desktop front end for the existing Strom CLI. Use **Python 3.12 and PySide6 / Qt 6 Widgets**, with ordinary system-styled controls. Do not rewrite Strom in C++, introduce a web view, or integrate asyncio into Qt's event loop.

This document is an implementation specification, not a request to implement every possible feature. Complete the numbered steps in order. Preserve the existing CLI and deterministic tests. Re-read the referenced source before editing; this plan describes the repository inspected on 2026-09-07.

Version one supports:

- Selecting an existing configuration directory.
- Choosing an optimization horizon and log level.
- Running one real control cycle through the existing CLI.
- Viewing process status and bounded, read-only logs.
- Remembering the directory, horizon, log level, and window geometry.

Explicitly defer credential editing, house parameter editing, charts, scheduling, tray behavior, auto-start, device discovery screens, manual ON/OFF controls, and executable bundles. Configuration stays in the existing files. The app must never start heating automatically on launch.

**Lifecycle decision:** v1 has no Stop or Force Quit button. Closing the window during a cycle is refused with an explanation; the window remains responsive until the child exits. This is deliberately limited because the existing controller does not provide a safe cancellation contract. Do not silently add process termination as a substitute. If a product requirement later demands cancellation or unattended operation, implement and test backend shutdown behavior first; see the safety section below.

## Repository facts the implementer must understand

| File | Relevant behavior |
| --- | --- |
| `strom/cli.py` | `run()` parses options, loads config, builds dependencies, and calls `asyncio.run(run_cycle(...))`. `StromError` maps to exit 1; unexpected exceptions propagate. |
| `strom/__main__.py` | Existing module entry point; invoke it as `python -m strom`. |
| `strom/config.py` | `load_app_config()` validates credentials, keys, and house settings. Explicit directory takes precedence over `STROM_CONFIG_DIR`, then ancestor-directory discovery. |
| `strom/api_utils.py` | Providers resolve keys separately from the `AppConfig` object, using environment variables / config discovery. Defaults are Barcelona weather and the ES electricity zone. |
| `strom/controller.py` | Discovers the real plug before fetching data, optimizes, then actuates one interval. Connection cleanup is not equivalent to turning the plug off. |
| `strom/control.py` | Executes duty-cycle segments. The watchdog is an asyncio task in the same process; it cannot protect against that process being killed. |
| `strom/optimization_utils.py` | `House` validates parameters; `house.dt_hours` determines control interval length. |
| `pyproject.toml` | Python is constrained to `>=3.12,<3.13`; setuptools currently packages only `strom`. There is no Qt dependency. |
| `.mise.toml`, `.github/workflows/strom-tests.yml` | Existing checks are flake8, mypy, deterministic pytest, a coverage floor, and clean-install CLI smoke tests. |

Do not edit the stale copies under `build/lib/strom`, generated egg-info, or `node_modules`. Node is only used for Git hooks.

The horizon is the optimization look-ahead, **not the runtime or number of cycles to execute**. The controller uses the first schedule row and executes one control interval immediately; it does not wait until that row's timestamp or repeat for the entire horizon. With default settings a cycle lasts about one hour, plus discovery/fetch/solve time. Do not describe this as a 24-hour scheduler or promise accurate percentage progress.

## 1. Add optional packaging and an entry point

Create these files:

```text
strom/linux_gui/__init__.py       # Empty; no startup side effects.
strom/linux_gui/__main__.py       # Thin module launcher.
strom/linux_gui/app.py            # Entry point and QApplication setup.
strom/linux_gui/window.py         # Widgets, form validation, settings, close behavior.
strom/linux_gui/runner.py         # QObject wrapping one QProcess and lifecycle signals.
tests/linux_gui/conftest.py       # GUI fixtures; isolate settings and environments.
tests/linux_gui/test_runner.py    # Process lifecycle and output tests.
tests/linux_gui/test_window.py    # Interaction and state tests.
```

In `pyproject.toml`:

1. Add a `gui` extra with `PySide6>=6.8,<7`. Verify resolution on the actual Linux target with Python 3.12; record the tested PySide6 version in the README rather than claiming every Qt 6 build works.
2. Add a `gui-dev` extra with `pytest-qt>=4.4,<5`.
3. Add `strom-gui = "strom.linux_gui.app:run"` under `[project.gui-scripts]`.
4. Replace the explicit `packages = ["strom"]` declaration with setuptools package discovery restricted to `strom` and `strom.*`. Do not package `tests` or `build`.
5. Keep Qt optional: importing `strom` and running `strom --help` must work without PySide6 installed. Import PySide6 inside the GUI entry point or GUI-only modules. The entry point should give a short installation hint if PySide6 itself is missing; do not disguise unrelated import errors as a missing dependency.

`python -m strom.linux_gui` and `strom-gui` must call the same `run() -> int`. Create exactly one `QApplication`, set stable organization/application names before constructing `QSettings`, build/show the window, and return `app.exec()`. Do not create a QApplication at import time.

## 2. Build a single simple window

Use `QMainWindow` with a central `QWidget`, `QVBoxLayout`, and a `QFormLayout`. Aim for about 760 × 520 initially, but use layouts and allow resizing.

Place these controls in order:

1. **Configuration directory:** `QLineEdit` and **Browse…** button using `QFileDialog.getExistingDirectory`. A cancelled dialog preserves the old value.
2. Short help text listing `tapologin.env`, `weather_api_key.txt`, `price_api_key.txt`, and optional `house_config.json`. Explain that exported credentials/keys override files, matching Strom's existing behavior.
3. **Optimization horizon (hours):** `QSpinBox`, default 24, range 1–48. This is a GUI usability bound, not a new CLI restriction or promise of provider coverage.
4. **Log level:** `QComboBox` containing INFO, WARNING, ERROR; default INFO. Omit DEBUG from v1 because verbose third-party logs can expose credentials or request URLs.
5. Explanation: “Runs one control interval and may switch your heater on. Default interval: one hour. Keep this window open until the cycle finishes.” Also disclose that this version uses the backend's Barcelona / ES defaults; do not invent editable location fields that are not wired through.
6. **Run one cycle** button. Clicking it opens a confirmation stating that this operates the real smart plug; Cancel is the default. This is a product interaction for physical actuation, not an implementation-time approval requirement.
7. Status label: Idle, Starting, Running, Completed, Failed to start, or Failed. Busy `QProgressBar` while starting/running; no fake percentage.
8. Read-only `QPlainTextEdit` log area and **Clear log** button. Set `maximumBlockCount` to 2000; cap pending partial output as well.

Before opening the run confirmation, trim and resolve the selected path with `Path.expanduser().resolve()`, and check it is a directory. Leave complete configuration validation to the child CLI; duplicating the backend validators creates drift. Do not call `load_app_config()` in the GUI process: dotenv mutates the environment and can retain credentials from a previously selected directory.

Persist only non-secret UI preferences with `QSettings`. Validate restored types/ranges and tolerate missing/deleted directories or malformed settings. Prefer saved path, then `STROM_CONFIG_DIR`, then the current directory's `config` as an initial suggestion; a suggestion is not proof of validity. Restore geometry defensively so an old monitor arrangement cannot make the window inaccessible.

## 3. Implement the process runner

Keep lifecycle logic in `runner.py`, separate from widgets. Give the `QProcess` a QObject parent and keep a strong instance reference. Create one new process per run, connect signals exactly once, and clean it up after terminal handling.

Launch with a program and an argument list, never a shell command:

```python
program = sys.executable
arguments = [
    "-u", "-m", "strom",
    "--config-dir", str(absolute_config_dir),
    "--horizon-hours", str(horizon),
    "--log-level", log_level,
]
```

Using the current interpreter ensures the child uses the same virtual environment. Do not invoke a possibly unrelated `strom` or `python` found on PATH. This design assumes a regular Python installation; a future frozen executable needs a different child-launch design.

**Mandatory config routing fix in the launcher:** construct `QProcessEnvironment.systemEnvironment()` and override `STROM_CONFIG_DIR` with the selected absolute path for each child. Pass `--config-dir` as above too. The explicit CLI option currently does not flow into provider key discovery, so omitting this environment override can validate one directory and fetch with another. Preserve other inherited environment entries, including the documented credential overrides. Never mutate the parent `os.environ`, dump the child environment, or put credentials in arguments. Do not change working directories to make config discovery work.

Use merged output channels for one ordered log stream and consume `readyReadStandardOutput`. Use an incremental UTF-8 decoder with replacement for invalid sequences: one signal can contain half a multibyte character or many lines. Buffer incomplete lines and flush decoder/tail at exit. Bound even an unterminated line (for example at 16 KiB), append a truncation notice, and avoid unbounded buffers. Treat output as plain text, never HTML. Do not write raw logs to disk automatically or offer an export in v1. Existing logs are not a formal secret-free protocol; audit emitted errors before claiming redaction, and never print `AppConfig`, credentials, or environment contents in new code.

State transitions:

| Event | Action |
| --- | --- |
| Run accepted in Idle/Completed/Failed | Enter Starting synchronously, disable run and form inputs, then start child. |
| `started` | Enter Running. |
| `errorOccurred(FailedToStart)` | Show actionable launch error, finalize as Failed to start, re-enable form. Do not rely on `finished` arriving. |
| Other process error | Record it; keep ownership until the process is actually no longer running. |
| `finished(0, NormalExit)` | Drain final output, finalize Completed, re-enable form. |
| Nonzero exit or CrashExit | Drain output, finalize Failed with exit details, re-enable form. |

Make terminal handling idempotent because error and finished signals can both arrive. Ignore stale callbacks from previous runs. Guard programmatic double-start as well as double-clicks. Release old process references only after it is stopped; `deleteLater()` is appropriate once no further lifecycle work is needed.

“Completed” means the child exited successfully. It is **not** proof of current plug state, current room temperature, achieved savings, or ongoing heating control. Do not parse log strings into authoritative device telemetry.

## 4. Enforce lifecycle and document backend hazards

In `closeEvent`, if the runner is Starting or Running, call `event.ignore()` and explain that a cycle is active and the window must stay open. Do not call `waitForFinished()`, kill the child, accept the close and destroy QProcess, or start it detached. All app-owned exit actions must follow the same rule. When inactive, save settings and accept close normally.

This restriction does not protect against desktop logout, power failure, crashes, or an external kill. Document the limitation in the README and avoid “safe shutdown” claims. Two existing details make it especially important:

- `execute_plan()` has no guaranteed OFF command in a cancellation cleanup block, and `managed_plug()` closes the connection rather than turning the heater off.
- A 100% duty cycle can contain only an ON segment. Stopping the watchdog at normal completion does not establish OFF. Do not label the plug OFF merely because the child exited.

Do not expand this GUI task into an untested controller rewrite. If a Stop button becomes required, treat it as a separate prerequisite: cooperative cancellation; bounded best-effort OFF followed by state verification; cleanup on exceptions/cancellation; graceful signal handling; clear reporting when OFF cannot be confirmed; tests for ON-only schedules, failed OFF, repeated cancellation, and shutdown during discovery/fetch/solve. Synchronous provider/solver work currently blocks the child's asyncio loop, so adding a signal handler alone cannot guarantee prompt shutdown. `QProcess.terminate()` sends SIGTERM on Unix; `kill()` is not a heater shutdown mechanism.

Another limitation: the GUI prevents concurrent runs only within its own window. Do not claim exclusion against another GUI process, cron, or a CLI invocation. Document that users must not run competing controllers for the same plug. Global device locking is separate backend work if later required.

## 5. Qt gotchas and implementation rules

- **Never block the GUI thread.** No `asyncio.run`, solver calls, network calls, `subprocess.run`, `time.sleep`, `QProcess.execute`, or `waitForStarted/Finished` in UI handlers. QProcess signals drive updates. Do not use repeated `processEvents()` as a workaround.
- **Use only one Qt binding.** No PyQt imports or Qt 5 snippets. Prefer explicit Qt 6 enums such as `QProcess.ProcessState.NotRunning`.
- **QObject lifetimes matter.** Parent processes/timers to a living QObject and retain references. A local-only process can be destroyed while running. Do not access widgets after they have been deleted.
- **Signal arguments matter.** `clicked` may supply a boolean. Use explicitly compatible slots, and avoid loop lambdas capturing the final loop value. Do not reconnect the same signals every time Run is clicked.
- **No thread machinery is needed here.** If later adding worker threads, only the GUI thread may touch widgets; communicate through signals and stop workers before destruction. Never terminate a QThread to cancel hardware work.
- **Keep native appearance.** Use platform palette, fonts, standard spacing and size policies. Avoid a global stylesheet, hard-coded colors, fixed coordinates, icon-only essential controls, or forcing Fusion style.
- **Handle scale and accessibility.** Qt 6 handles high-DPI scaling; do not copy obsolete Qt 5 high-DPI setup. Test 100% and 200%, long paths, light/dark palettes, keyboard tab order, label buddies, visible focus, and a small window. Essential status must be textual, not color-only.
- **No launch-directory assumptions.** Desktop launchers usually do not start in the repository. Resolve config paths explicitly; use installed modules rather than repository-relative paths.
- **Linux plugins are runtime dependencies.** A PySide6 wheel does not eliminate all Linux shared-library requirements. An “xcb plugin found but could not load” error often means missing dependencies or mixed Qt installations, not a missing Python import. Consult Qt's Linux requirements for the selected distribution; do not guess a universal apt package list.
- **Wayland and X11 both need testing.** Do not globally force `QT_QPA_PLATFORM=xcb` or overwrite plugin paths. Use `QT_DEBUG_PLUGINS=1` for a targeted diagnostic run. Clear accidental cross-environment Qt plugin settings when diagnosing, rather than hard-coding workstation paths into the app.
- **Headless tests are limited.** `QT_QPA_PLATFORM=offscreen` can test widget logic but does not verify native dialogs, desktop themes, platform plugins, scaling, or Wayland behavior.

## 6. Add deterministic tests and Linux verification

Use pytest-qt's `qtbot` / signal waits, not arbitrary sleeps. GUI tests must skip cleanly before importing GUI modules if PySide6 or pytest-qt is absent. Keep the default CLI install/test workflow working; run GUI tests explicitly in a separate Linux CI job with both extras installed. Isolate QSettings in temporary storage and never read the developer's real config.

Test the runner with small fake Python children supplied through an injectable launch specification. The production launch specification remains fixed to `sys.executable -u -m strom`; do not expose arbitrary command execution in the UI. Fake children must not import real device code.

Required automated cases:

- Arguments preserve paths containing spaces and shell metacharacters literally; no shell executes them.
- Child `STROM_CONFIG_DIR` matches the selected path and changes correctly for run A then run B; parent environment remains unchanged, inherited credential overrides are preserved.
- Process startup failure, success, nonzero exit, crash, trailing output without newline, split UTF-8, and a large unterminated line.
- Repeated Run cannot spawn two children; controls recover after failure; terminal handling happens once even when error and finish overlap.
- Window remains responsive while a fake child is running; closing during Starting/Running is ignored without terminating the child; closing after completion succeeds.
- Confirmation cancellation starts nothing. Invalid directory starts nothing. Cancelling Browse preserves the path.
- Restored invalid settings do not crash; log clearing does not affect the child; log memory remains bounded.
- A wheel installed in a fresh environment includes `strom.linux_gui` and both launchers work from outside the checkout. Without GUI extras, `strom --help` still works and the GUI launcher gives the install hint.

Run existing checks and the dedicated GUI suite after implementation:

```sh
python -m pip install -e '.[dev,gui,gui-dev]'
mise run check
QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/linux_gui
```

Use the same environment for installation and checks; activate `.venv` first or invoke its Python explicitly. Add a Linux CI GUI job that installs these extras, sets `QT_QPA_PLATFORM=offscreen`, runs the GUI suite, and type-checks the added modules. Keep existing CLI-only smoke coverage and the coverage floor; do not lower gates to accommodate GUI code.

Manual acceptance on an actual Linux desktop (macOS results do not establish Linux compatibility):

1. Launch the installed app from a terminal and from outside the source directory.
2. Test X11 and Wayland where available, light/dark themes, resizing, keyboard-only operation, and 200% scaling.
3. Use a fake child during development to test a long-running cycle, close refusal, log streaming, and failure recovery without a real heater or credentials.
4. For any intentional real-device test, use a controlled setup and explicit operator action. Record what was verified; do not run live providers/devices as part of deterministic CI.

## 7. Documentation and completion criteria

Update README with `pip install '.[gui]'`, `strom-gui`, `python -m strom.linux_gui`, Python requirements, existing config-file setup, environment precedence, default location, one-cycle semantics, long-running behavior, no-stop limitation, and Linux troubleshooting. Update the current “single supported entry point” wording to explain that the GUI delegates to the unchanged CLI.

Do not add AppImage/Flatpak/deb packaging or desktop integration in this first pass. Those require separate dependency, install-path, and runtime testing. A normal installed `strom-gui` command is the v1 deliverable.

The work is complete only when the installed native window runs the existing CLI asynchronously, uses the selected config consistently, prevents duplicate runs in its window, handles failures and close behavior as specified, and passes the existing checks plus GUI tests. Report the tested Linux distribution/session and PySide6 version, and explicitly list any Linux checks that could not be run. Never equate an offscreen test with successful desktop verification.

## Official Qt references

Consult these when implementing instead of guessing APIs or translating old PyQt examples:

- [PySide6 QProcess](https://doc.qt.io/qtforpython-6/PySide6/QtCore/QProcess.html): asynchronous signals, buffers, process state, exit status, and termination semantics.
- [Qt for Linux requirements](https://doc.qt.io/qt-6/linux-requirements.html): platform plugin shared-library dependencies.
- [Qt for Python supported platforms](https://doc.qt.io/qtforpython-6/overviews/qtdoc-supported-platforms.html): supported target combinations for the selected release.

The architectural and product choices above are specific to Strom; they are not Qt requirements.
