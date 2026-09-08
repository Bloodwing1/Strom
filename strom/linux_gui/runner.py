"""Process runner for the Strom GUI: one child control-cycle process at a time.

Keeps all QProcess lifecycle logic out of widget code (plan §3). The window
never touches the process directly; it binds to ``stateChanged`` /
``outputText`` and calls ``start()`` with a :class:`LaunchSpec`.

State machine::

    Idle -> Starting -> Running -> Completed | Failed | FailedToStart

Terminal handling is idempotent: ``errorOccurred`` and ``finished`` can both
arrive, and stale callbacks from a previous run are ignored.
"""

from __future__ import annotations

import codecs
import enum
import sys
from dataclasses import dataclass
from functools import partial
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, Signal

_MAX_PENDING_CHARS = 16 * 1024
_TRUNCATION_NOTICE = "[... line truncated after 16,384 characters ...]"


class RunnerState(enum.Enum):
    """Cycle states shown verbatim in the window status label."""

    Idle = "Idle"
    Starting = "Starting"
    Running = "Running"
    Completed = "Completed"
    FailedToStart = "Failed to start"
    Failed = "Failed"


@dataclass(frozen=True)
class LaunchSpec:
    """Fixed launch description for one child process.

    ``config_dir`` is injected into the child environment as
    ``STROM_CONFIG_DIR``; see :meth:`CycleRunner.start`.
    """

    program: str
    arguments: tuple[str, ...]
    config_dir: Path


def make_launch_spec(config_dir: Path, horizon: int, log_level: str) -> LaunchSpec:
    """Production launch specification: the current interpreter runs the CLI.

    Using ``sys.executable`` keeps the child in the same virtual environment
    instead of a possibly unrelated ``strom``/``python`` found on PATH. A
    frozen executable would need a different child-launch design.
    """
    return LaunchSpec(
        program=sys.executable,
        arguments=(
            "-u",
            "-m",
            "strom",
            "--config-dir",
            str(config_dir),
            "--horizon-hours",
            str(horizon),
            "--log-level",
            log_level,
        ),
        config_dir=config_dir,
    )


class CycleRunner(QObject):
    """Runs at most one child process; one new ``QProcess`` per run.

    Signals are connected exactly once per run, on the freshly created
    process. Handlers ignore any process that is not the current one, which
    both ignores stale callbacks from previous runs and makes terminal
    handling idempotent when error and finish signals overlap.
    """

    stateChanged = Signal(object)
    outputText = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._process: QProcess | None = None
        self._state = RunnerState.Idle
        self._detail: str | None = None
        self._decoder: codecs.IncrementalDecoder | None = None
        self._pending = ""
        self._discarding_line = False

    @property
    def state(self) -> RunnerState:
        return self._state

    @property
    def detail(self) -> str | None:
        """Human-readable detail for the current/last failure, or None."""
        return self._detail

    def is_active(self) -> bool:
        return self._state in (RunnerState.Starting, RunnerState.Running)

    def start(self, spec: LaunchSpec) -> bool:
        """Start one child process; return False without side effects if busy.

        Guards programmatic double-start as well as double-clicks.
        """
        if self.is_active():
            return False

        process = QProcess(self)
        process.setProgram(spec.program)
        process.setArguments(list(spec.arguments))
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)

        # Mandatory config routing fix: the explicit --config-dir option does
        # not flow into provider key discovery, so the child must also see the
        # selected directory as STROM_CONFIG_DIR. Other inherited environment
        # entries, including documented credential overrides, are preserved.
        # The parent os.environ is never mutated and credentials are never
        # placed in arguments.
        env = QProcessEnvironment.systemEnvironment()
        env.insert("STROM_CONFIG_DIR", str(spec.config_dir))
        process.setProcessEnvironment(env)

        process.started.connect(partial(self._on_started, process))
        process.finished.connect(partial(self._on_finished, process))
        process.errorOccurred.connect(partial(self._on_error, process))
        process.readyReadStandardOutput.connect(partial(self._on_ready_read, process))

        self._process = process
        self._detail = None
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self._pending = ""
        self._discarding_line = False
        # Enter Starting synchronously so the window can disable the form
        # before returning to the event loop.
        self._set_state(RunnerState.Starting)
        process.start()
        return True

    # --- signal handlers (all ignore non-current processes) ---

    def _on_started(self, process: QProcess) -> None:
        if self._process is not process:
            return
        self._set_state(RunnerState.Running)

    def _on_error(self, process: QProcess, error: QProcess.ProcessError) -> None:
        if self._process is not process:
            return
        if error == QProcess.ProcessError.FailedToStart:
            # Do not rely on finished arriving for this case.
            self._detail = process.errorString() or "process failed to start"
            self._finalize(process, RunnerState.FailedToStart)
        else:
            # Record it; the process may still be running. The terminal state
            # is decided by finished (or a later FailedToStart, which cannot
            # happen after a successful start).
            self._detail = f"process error: {error.name}"

    def _on_finished(
        self, process: QProcess, exit_code: int, exit_status: QProcess.ExitStatus
    ) -> None:
        if self._process is not process:
            return
        # Drain anything still buffered before deciding the terminal state so
        # the log is complete when the status label updates.
        self._consume(process.readAllStandardOutput().data())
        self._flush_output()
        if exit_status == QProcess.ExitStatus.NormalExit and exit_code == 0:
            self._detail = None
            self._finalize(process, RunnerState.Completed)
        else:
            parts = []
            if exit_status != QProcess.ExitStatus.NormalExit:
                parts.append("process crashed")
            if exit_code != 0:
                parts.append(f"exit code {exit_code}")
            if self._detail is not None:
                parts.append(self._detail)
            self._detail = "; ".join(parts) or "process failed"
            self._finalize(process, RunnerState.Failed)

    def _on_ready_read(self, process: QProcess) -> None:
        if self._process is not process:
            return
        self._consume(process.readAllStandardOutput().data())

    # --- output handling ---

    def _consume(self, data: bytes | bytearray | memoryview) -> None:
        """Decode a chunk incrementally and emit bounded plain-text lines."""
        if self._decoder is None:
            return
        self._consume_text(self._decoder.decode(data))

    def _consume_text(self, text: str) -> None:
        """Emit complete lines, retaining at most one bounded partial line."""
        remaining = self._pending + text
        self._pending = ""

        while remaining:
            if self._discarding_line:
                newline = remaining.find("\n")
                if newline < 0:
                    return
                self._discarding_line = False
                remaining = remaining[newline + 1:]
                continue

            newline = remaining.find("\n")
            if newline >= 0:
                line = remaining[:newline]
                remaining = remaining[newline + 1:]
                if len(line) > _MAX_PENDING_CHARS:
                    self.outputText.emit(
                        line[:_MAX_PENDING_CHARS] + _TRUNCATION_NOTICE + "\n"
                    )
                else:
                    self.outputText.emit(line + "\n")
                continue

            if len(remaining) > _MAX_PENDING_CHARS:
                self.outputText.emit(
                    remaining[:_MAX_PENDING_CHARS] + _TRUNCATION_NOTICE + "\n"
                )
                self._discarding_line = True
            else:
                self._pending = remaining
            return

    def _flush_output(self) -> None:
        """Flush the decoder and any bounded partial line at process exit."""
        if self._decoder is not None:
            tail = self._decoder.decode(b"", True)
            self._decoder = None
            self._consume_text(tail)
        if not self._discarding_line and self._pending:
            self.outputText.emit(self._pending)
        self._pending = ""
        self._discarding_line = False

    # --- state transitions and cleanup ---

    def _set_state(self, state: RunnerState) -> None:
        if state is self._state:
            return
        self._state = state
        self.stateChanged.emit(state)

    def _finalize(self, process: QProcess, state: RunnerState) -> None:
        """Clean up the current process and emit one terminal transition."""
        if self._process is not process:
            return
        # The process is stopped by the time this runs (or never started).
        # Clear ownership before emitting: same-thread Qt slots run
        # synchronously and may start the next run from stateChanged.
        process.deleteLater()
        self._process = None
        self._decoder = None
        self._pending = ""
        self._discarding_line = False
        self._set_state(state)
