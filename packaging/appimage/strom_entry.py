"""Packaged entry point for a frozen Strom bundle (AppImage AppRun target).

One bundled executable with an internal command dispatcher. Internal switches
are handled before any QApplication creation and are stripped before the
remaining arguments reach the product CLI; they never appear on normal
product screens::

    <bundle>                          -> normal Qt GUI (strom.linux_gui.app)
    <bundle> --strom-cli <CLI args>   -> strom.cli.run(<CLI args>)
    <bundle> --strom-self-test        -> offline packaging verification

A frozen ``sys.executable`` is this application, not a Python interpreter,
so frozen child launches pass ``--strom-cli`` instead of ``-u -m strom``
(see ``strom.linux_gui.runner.make_launch_spec``); forwarding ``-m strom``
to this executable would open a second GUI instead of running a cycle.
"""

from __future__ import annotations

import sys

from strom.entry_switches import FROZEN_CLI_SWITCH, FROZEN_SELF_TEST_SWITCH


def _unbuffer_output() -> None:
    """Make child output flush promptly without ``python -u``.

    A frozen executable is not a Python interpreter, so ``-u`` cannot be
    passed. Line buffering on the text streams is the supported mechanism;
    it is exercised by tests instead of relying on an environment flag.
    """
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(line_buffering=True)


def _run_cli(cli_arguments: list[str]) -> int:
    """Run the product CLI; keep Qt and the GUI package out of this branch.

    Importing ``strom.cli`` only means a control-cycle child can never
    construct a QApplication, however wrong its arguments are.
    """
    _unbuffer_output()
    from strom.cli import run

    return run(cli_arguments)


def _run_gui() -> int:
    from strom.linux_gui.app import run

    return run()


def _run_self_test() -> int:
    from strom.linux_gui.selftest import run_self_test

    return run_self_test()


def main(argv: list[str] | None = None) -> int:
    """Dispatch one invocation; the plain form is the GUI, as installed."""
    arguments = sys.argv[1:] if argv is None else list(argv)
    if arguments and arguments[0] == FROZEN_SELF_TEST_SWITCH:
        return _run_self_test()
    if arguments and arguments[0] == FROZEN_CLI_SWITCH:
        # Remove the internal switch before handing arguments to the CLI.
        return _run_cli(arguments[1:])
    return _run_gui()


if __name__ == "__main__":
    sys.exit(main())
