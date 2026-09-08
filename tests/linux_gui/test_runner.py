"""Runner lifecycle tests with fake child processes (plan §3, task 2).

Fake children are small standalone scripts under ``fake_children/``; they
never import real device code. The launch specification is injectable, so the
tests never run the real CLI.
"""

import codecs
import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("PySide6", reason="PySide6 is not installed (GUI extras missing)")
pytest.importorskip("pytestqt", reason="pytest-qt is not installed (gui-dev extra missing)")

from PySide6.QtCore import QProcess  # noqa: E402

from strom.linux_gui.runner import LaunchSpec, RunnerState, make_launch_spec  # noqa: E402

FAKE_CHILDREN = Path(__file__).parent / "fake_children"
TERMINAL_STATES = (RunnerState.Completed, RunnerState.Failed, RunnerState.FailedToStart)


def fake_spec(name: str, config_dir: Path | None = None) -> LaunchSpec:
    """Launch a fake child the same way the runner launches any program."""
    return LaunchSpec(
        program=sys.executable,
        arguments=("-u", str(FAKE_CHILDREN / name)),
        config_dir=config_dir or Path("/tmp/strom-fake-config"),
    )


class Recorder:
    """Records runner signals for assertions."""

    def __init__(self, runner):
        self.states = []
        self.output = []
        runner.stateChanged.connect(self.states.append)
        runner.outputText.connect(self.output.append)

    def terminal_transitions(self) -> int:
        return sum(1 for state in self.states if state in TERMINAL_STATES)


def wait_state(qtbot, runner, state: RunnerState) -> None:
    qtbot.waitUntil(lambda: runner.state is state, timeout=10000)


def test_success_lifecycle(qtbot):
    from strom.linux_gui.runner import CycleRunner

    runner = CycleRunner()
    rec = Recorder(runner)

    assert runner.start(fake_spec("slow.py")) is True
    assert runner.state is RunnerState.Starting  # synchronous, before the loop
    wait_state(qtbot, runner, RunnerState.Running)
    wait_state(qtbot, runner, RunnerState.Completed)

    assert rec.states == [RunnerState.Starting, RunnerState.Running, RunnerState.Completed]
    assert runner.detail is None
    assert rec.output == ["started\n", "done\n"]
    assert runner.state is RunnerState.Completed
    assert runner.is_active() is False


def test_nonzero_exit_fails_and_recovers(qtbot):
    from strom.linux_gui.runner import CycleRunner

    runner = CycleRunner()
    Recorder(runner)

    runner.start(fake_spec("fail.py"))
    wait_state(qtbot, runner, RunnerState.Failed)
    assert "exit code 3" in (runner.detail or "")

    # Controls recover after failure: a new run starts and completes.
    assert runner.start(fake_spec("success.py")) is True
    wait_state(qtbot, runner, RunnerState.Completed)


def test_crash_fails(qtbot):
    from strom.linux_gui.runner import CycleRunner

    runner = CycleRunner()
    Recorder(runner)

    runner.start(fake_spec("crash.py"))
    wait_state(qtbot, runner, RunnerState.Failed)
    assert "crashed" in (runner.detail or "")


def test_failed_to_start(qtbot):
    from strom.linux_gui.runner import CycleRunner

    runner = CycleRunner()
    rec = Recorder(runner)

    bad = LaunchSpec(
        program="/nonexistent/program-for-tests",
        arguments=("-u", "x"),
        config_dir=Path("/tmp/strom-fake-config"),
    )
    runner.start(bad)
    wait_state(qtbot, runner, RunnerState.FailedToStart)
    # Actionable launch error, produced without relying on finished.
    assert runner.detail
    assert rec.terminal_transitions() == 1

    # The form is reusable afterwards.
    assert runner.start(fake_spec("success.py")) is True
    wait_state(qtbot, runner, RunnerState.Completed)


def test_terminal_once_when_error_and_finish_overlap(qtbot):
    from strom.linux_gui.runner import CycleRunner

    runner = CycleRunner()
    rec = Recorder(runner)

    runner.start(fake_spec("slow.py"))
    wait_state(qtbot, runner, RunnerState.Running)
    process = runner._process
    assert process is not None

    # Simulate an error arriving while the process is still running: it is
    # recorded, not terminal. The finish signal then decides the outcome.
    process.errorOccurred.emit(QProcess.ProcessError.Crashed)
    assert runner.state is RunnerState.Running
    wait_state(qtbot, runner, RunnerState.Completed)
    assert rec.terminal_transitions() == 1

    # A late duplicate error for a process that is no longer current (stale
    # callback) changes nothing.
    stale = QProcess(runner)
    try:
        runner._on_error(stale, QProcess.ProcessError.Crashed)
        assert rec.terminal_transitions() == 1
        assert runner.state is RunnerState.Completed
    finally:
        stale.deleteLater()


def test_double_start_refused(qtbot):
    from strom.linux_gui.runner import CycleRunner

    runner = CycleRunner()
    Recorder(runner)

    assert runner.start(fake_spec("slow.py")) is True
    wait_state(qtbot, runner, RunnerState.Running)
    first = runner._process

    # Second Run (double-click or programmatic) spawns nothing new.
    assert runner.start(fake_spec("success.py")) is False
    assert runner._process is first
    assert runner.state is RunnerState.Running

    wait_state(qtbot, runner, RunnerState.Completed)


def test_stale_callbacks_from_previous_or_foreign_processes_ignored(qtbot):
    from strom.linux_gui.runner import CycleRunner

    runner = CycleRunner()
    rec = Recorder(runner)

    # Complete run A.
    runner.start(fake_spec("success.py"))
    wait_state(qtbot, runner, RunnerState.Completed)

    # Run B is active; callbacks bound to a foreign process are ignored.
    runner.start(fake_spec("slow.py"))
    wait_state(qtbot, runner, RunnerState.Running)
    foreign = QProcess(runner)
    try:
        runner._on_finished(foreign, 0, QProcess.ExitStatus.NormalExit)
        runner._on_error(foreign, QProcess.ProcessError.FailedToStart)
        assert runner.state is RunnerState.Running
    finally:
        foreign.deleteLater()

    wait_state(qtbot, runner, RunnerState.Completed)
    assert rec.terminal_transitions() == 2  # one per run, never more


def test_terminal_state_handler_can_start_next_run(qtbot):
    from strom.linux_gui.runner import CycleRunner

    runner = CycleRunner()
    rec = Recorder(runner)
    restarted = False

    def restart_once(state):
        nonlocal restarted
        if state is RunnerState.Completed and not restarted:
            restarted = True
            assert runner.start(fake_spec("success.py")) is True

    runner.stateChanged.connect(restart_once)
    runner.start(fake_spec("success.py"))
    qtbot.waitUntil(lambda: rec.terminal_transitions() == 2, timeout=10000)

    assert runner.state is RunnerState.Completed
    assert runner._process is None
    assert rec.states == [
        RunnerState.Starting,
        RunnerState.Running,
        RunnerState.Completed,
        RunnerState.Starting,
        RunnerState.Running,
        RunnerState.Completed,
    ]


def test_trailing_output_without_newline_is_flushed(qtbot):
    from strom.linux_gui.runner import CycleRunner

    runner = CycleRunner()
    rec = Recorder(runner)

    runner.start(fake_spec("trailing.py"))
    wait_state(qtbot, runner, RunnerState.Completed)
    assert rec.output == ["no trailing newline"]


def test_arguments_reach_child_verbatim(qtbot):
    from strom.linux_gui.runner import CycleRunner

    runner = CycleRunner()
    rec = Recorder(runner)

    # No shell is involved: spaces and metacharacters stay one argument.
    literal = "dir with spaces & $chars; `quotes`"
    spec = LaunchSpec(
        program=sys.executable,
        arguments=("-u", str(FAKE_CHILDREN / "argv.py"), literal),
        config_dir=Path("/tmp/strom-fake-config"),
    )
    runner.start(spec)
    wait_state(qtbot, runner, RunnerState.Completed)

    argv = json.loads("".join(rec.output))
    # "-u" is an interpreter flag and never reaches the child's argv; the
    # literal arrives as exactly one argument, shell metacharacters intact.
    assert argv == [literal]


def test_make_launch_spec_shape():
    config_dir = Path("/tmp/some config")
    spec = make_launch_spec(config_dir, horizon=24, log_level="INFO")

    assert spec.program == sys.executable
    assert spec.config_dir == config_dir
    assert spec.arguments == (
        "-u",
        "-m",
        "strom",
        "--config-dir",
        str(config_dir),
        "--horizon-hours",
        "24",
        "--log-level",
        "INFO",
    )


# --- output handling (plan §3 output rules; task 3) ---


def _fresh_runner_with_decoder():
    """A runner with a decoder allocated, for direct chunk-feeding tests."""
    from strom.linux_gui.runner import CycleRunner

    runner = CycleRunner()
    runner._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    runner._pending = ""
    return runner


def test_split_multibyte_character_decodes_across_chunks():
    """One character split across two reads must decode as one character."""
    runner = _fresh_runner_with_decoder()
    rec = Recorder(runner)

    snow = "雪".encode("utf-8")
    runner._consume(b"before " + snow[:1])
    assert rec.output == []
    runner._consume(snow[1:] + b" after\n")

    assert rec.output == ["before 雪 after\n"]
    assert "\ufffd" not in "".join(rec.output)


def test_multibyte_split_child_end_to_end(qtbot):
    from strom.linux_gui.runner import CycleRunner

    runner = CycleRunner()
    rec = Recorder(runner)

    runner.start(fake_spec("split_utf8.py"))
    wait_state(qtbot, runner, RunnerState.Completed)

    assert "".join(rec.output) == "héllo 雪 ✅ end\n"
    assert all(isinstance(chunk, str) for chunk in rec.output)


def test_large_unterminated_line_capped_with_notice(qtbot):
    from strom.linux_gui.runner import CycleRunner

    runner = CycleRunner()
    rec = Recorder(runner)

    runner.start(fake_spec("big_unterminated.py"))
    wait_state(qtbot, runner, RunnerState.Completed)

    joined = "".join(rec.output)
    from strom.linux_gui.runner import _TRUNCATION_NOTICE

    # Only the bounded prefix reaches the log. The remainder is discarded
    # until a newline or process exit, with exactly one visible notice.
    assert joined.count(_TRUNCATION_NOTICE) == 1
    assert joined.count("y") == 16 * 1024
    assert len(runner._pending) <= 16 * 1024


def test_truncation_discards_until_newline_then_resumes():
    runner = _fresh_runner_with_decoder()
    rec = Recorder(runner)

    runner._consume(b"y" * (16 * 1024 + 100))
    runner._consume(b"still discarded\nnext line\n")

    joined = "".join(rec.output)
    assert joined.count("y") == 16 * 1024
    assert "still discarded" not in joined
    assert joined.endswith("next line\n")


def test_invalid_utf8_replaced_without_crash(qtbot):
    from strom.linux_gui.runner import CycleRunner

    runner = CycleRunner()
    rec = Recorder(runner)

    runner.start(fake_spec("invalid_utf8.py"))
    wait_state(qtbot, runner, RunnerState.Completed)

    # Invalid bytes become U+FFFD replacement characters; the run still
    # completes normally.
    assert "".join(rec.output) == "\ufffd\ufffdafter invalid bytes\n"
