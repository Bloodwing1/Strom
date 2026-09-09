# Linux Qt GUI: session tasks

Work through the tasks in order; later tasks depend on earlier ones. One task fits one working session. Each task names the plan sections that specify its behavior and states its own completion criterion — a task is done only when its criterion is met, not when code exists.

Plan: [plan.md](plan.md). Before writing code in any task, re-read the plan sections that task points to; the plan is the specification, this file only sequences it. Re-read the referenced source files before editing them, as the plan requires.

## Session protocol

Every task ends the same way, and the criterion of a task includes it:

- The GUI suite passes in the offscreen platform (command in plan §6).
- The pre-existing checks still pass (`mise run check`) and the coverage floor is not lowered.
- The work is committed.

Do not start a task whose dependencies are not complete. If a plan requirement turns out to be infeasible, stop and record the conflict instead of silently deviating.

## Tasks

1. **Packaging and entry points** (plan §1, items 1–5). Add the extras, the `strom-gui` script, and package discovery, and create the `strom/linux_gui` package with a minimal `run() -> int` that builds one `QApplication` and an empty placeholder window.
   Done when: an editable install with `[dev,gui,gui-dev]` succeeds on the working machine; both `python -m strom.linux_gui` and `strom-gui` open that window; `strom --help` still works with PySide6 absent; flake8 and mypy pass on the new modules.

2. **Runner process lifecycle** (plan §3, the launch and state-transition rules). Implement `runner.py` against an injectable launch specification, with no window code touching the process directly.
   Done when: every state transition in the plan's table (§3) is exercised by `tests/linux_gui/test_runner.py` using fake children — start, success, nonzero exit, failed-to-start, crash, and at least one overlapping error/finish — and terminal handling is idempotent under repeated Run.

3. **Output handling** (plan §3, output rules). Add merged-channel streaming, incremental UTF-8 decoding, incomplete-line buffering, and the size bounds to the runner.
   Done when: tests cover a trailing line without newline, a multibyte character split across reads, and a large unterminated line capped with a truncation notice; the log widget receives plain text only.

4. **Config routing** (plan §3, "Mandatory config routing fix"). Build the child environment from `systemEnvironment()` with `STROM_CONFIG_DIR` overridden per run.
   Done when: a test shows the child's `STROM_CONFIG_DIR` equals the selected path for run A and a different selected path for run B, the parent environment is unchanged afterward, and inherited credential overrides are preserved.

5. **Window and settings** (plan §2). Build the full window with the controls, texts, validation, and confirmation dialog in the listed order, and the `QSettings` persistence with defensive restore.
   Done when: every control in plan §2 exists with its stated default, range, and text; Browse-cancel preserves the path; an invalid directory blocks the run dialog; malformed or out-of-range restored settings fall back to defaults without crashing; geometry restore keeps the window reachable.

6. **Close behavior** (plan §4, first two paragraphs). Wire `closeEvent` and any app-owned exit actions to refuse closing during Starting/Running.
   Done when: qtbot tests show a refused close leaves a fake child running and the window responsive, a close after completion saves settings and accepts, and the child process outlives the refused close in every case.

7. **GUI test suite completion** (plan §6, "Required automated cases"). Add the remaining cases not covered by tasks 2–6.
   Done when: each bullet in the plan's required-cases list is either covered by an existing test or explicitly listed in this file as covered elsewhere; arguments with spaces and shell metacharacters are shown to reach the child verbatim; no test reads the developer's real `QSettings`.
   Coverage audit (plan §6 bullet → tests in `tests/linux_gui/`):
   - Arguments literal, no shell → `test_runner.py::test_arguments_reach_child_verbatim` (metacharacter argument arrives verbatim; child `ppid` equals the test process, proving no intermediate shell)
   - Per-run `STROM_CONFIG_DIR`, parent env unchanged, inherited overrides preserved → `test_config_dir_env_override_changes_per_run`, `test_inherited_overrides_preserved_and_parent_env_unchanged`, `test_config_dir_env_absent_in_child_when_parent_unset`
   - Startup failure / success / nonzero / crash / trailing output / split UTF-8 / large unterminated line → `test_failed_to_start`, `test_success_lifecycle`, `test_nonzero_exit_fails_and_recovers`, `test_crash_fails`, `test_trailing_output_without_newline_is_flushed`, `test_split_multibyte_character_decodes_across_chunks` + `test_multibyte_split_child_end_to_end`, `test_large_unterminated_line_capped_with_notice` (+ `test_truncation_discards_until_newline_then_resumes`)
   - Repeated Run, failure recovery, terminal-once → `test_double_start_refused`, `test_nonzero_exit_fails_and_recovers`, `test_terminal_once_when_error_and_finish_overlap`, `test_terminal_state_handler_can_start_next_run`, `test_stale_callbacks_from_previous_or_foreign_processes_ignored`, and window-level `test_run_button_click_while_active_starts_nothing`
   - Window responsive while child runs; close refused/accepted → `test_log_streams_incrementally_before_completion`, `test_clear_log_during_run_and_bounded_memory`, `test_close_refused_while_running_leaves_child_alive`, `test_close_refused_during_starting_leaves_child_alive`, `test_close_accepted_after_completion_saves_settings`
   - Confirmation cancel / invalid directory / Browse cancel → `test_confirmation_cancel_starts_nothing`, `test_invalid_directory_blocks_confirmation`, `test_browse_cancel_preserves_path`
   - Restored invalid settings / clear log / bounded memory → `test_malformed_settings_fall_back_to_defaults`, `test_clear_log_during_run_and_bounded_memory`
   - No test reads the developer's real `QSettings`: every window test injects a per-test temporary INI `QSettings`; runner tests construct no settings; `test_app.py` monkeypatches imports only
   - Wheel in a fresh environment → deferred to task 8 (packaging session); the no-GUI-extras CLI behavior is additionally verified there in a real fresh venv

8. **Packaging verification** (plan §1 item 5 and §6 wheel bullet). Build a wheel, install it into a fresh environment without the repo on `sys.path`, and verify both launchers from outside the checkout.
   Done when: the installed `strom-gui` and `python -m strom.linux_gui` work from a foreign directory; `strom --help` works in an environment without GUI extras and the GUI launcher prints the install hint; the tested PySide6 version is recorded for the README task.
   Result (macOS verification; Linux desktop acceptance remains task 11): wheel `strom-0.2.0-py3-none-any.whl` contains all five `strom.linux_gui` modules and no tests/build artifacts. Fresh venv with `strom[gui]` from the wheel: `strom-gui` and `python -m strom.linux_gui` both ran from `/tmp` with `strom` importing from site-packages (stayed alive, no errors). Fresh venv without GUI extras: `strom --help` exits 0; both GUI launchers print the PySide6 install hint and exit 2. **Tested PySide6 version for the README: 6.11.2** (constraint `PySide6>=6.8,<7`).

9. **CI job** (plan §6, CI paragraph). Add the Linux GUI job to `.github/workflows/strom-tests.yml`.
   Done when: the new job installs the three extras, sets `QT_QPA_PLATFORM=offscreen`, runs the GUI suite, and type-checks the GUI modules; the existing CLI-only smoke job and coverage gate are unchanged and green.
   Result: `gui` job added to `.github/workflows/strom-tests.yml` (ubuntu-latest, `QT_QPA_PLATFORM=offscreen`, `pip install -e ".[dev,gui,gui-dev]"`, `pytest tests/linux_gui`, `mypy strom/linux_gui` with PySide6 installed). Existing `test` and `smoke` jobs untouched; YAML validity, the offscreen suite, GUI mypy, and the coverage floor verified locally. CI run on the Linux runner is the remaining confirmation (push).

10. **Documentation** (plan §7). Update the README per the plan's list.
    Done when: every item in the plan §7 README list is present, the "single supported entry point" wording is revised, and the tested distribution and PySide6 version from task 8 appear in the text.
   Result: README gains a "Desktop GUI (Linux)" section covering install (`pip install '.[gui]'`), both launchers, Python/Qt requirements, config-file layout reference, environment precedence (`STROM_CONFIG_DIR` export, credential overrides), suggestion order (saved path → `STROM_CONFIG_DIR` → `./config`), one-cycle semantics with confirmation, keep-window-open long-running behavior, the explicit no-Stop limitation, and Linux troubleshooting (xcb plugin errors, no global `QT_QPA_PLATFORM` forcing, `QT_DEBUG_PLUGINS=1`, Wayland). The Usage entry-point wording now states the GUI delegates to the unchanged CLI. Text records tested PySide6 6.11.2 and states explicitly that offscreen results are not desktop verification; the tested Linux distribution/session will be added by task 11.

11. **Manual Linux verification** (plan §6, "Manual acceptance"). Perform the on-desktop checks on real Linux; this needs hardware and cannot be done in an automated session.
    Done when: the checked items and the environment (distribution, X11/Wayland session, scaling, PySide6 version) are recorded, and any check that could not be run is listed explicitly, as the plan's completion criteria require.

Tasks 5, 6, and 11 are the sessions where scope temptation is highest — the plan's lifecycle decision (§ "Lifecycle decision") forbids adding Stop, termination, or cancellation behavior; if requested, treat it as the separate backend prerequisite the plan describes, not as part of these tasks.
