"""Internal switches shared by the packaged entry point and the GUI runner.

Deliberately free of Qt and GUI imports: the packaged CLI branch imports
this module on every control-cycle child launch, so it must never pull the
GUI package or PySide6 into the child (that would open a second GUI).
"""

FROZEN_CLI_SWITCH = "--strom-cli"
FROZEN_SELF_TEST_SWITCH = "--strom-self-test"
