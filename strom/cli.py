"""Command-line entry point for Strom.

The CLI is a thin wrapper: it loads configuration, builds the controller
dependencies and turns expected operational failures
(:class:`~strom.errors.StromError`) into a logged message and exit code 1.
Unexpected exceptions propagate with their traceback, so cron/systemd report
failure.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

from strom.controller import ControllerDeps, run_control_cycle
from strom.errors import StromError
from strom.optimization_utils import House

logger = logging.getLogger(__name__)


def setup_env_config():
    """Load credentials and house parameters from ./config (issue 36 reworks this)."""
    from dotenv import load_dotenv
    import json

    load_dotenv(dotenv_path="./config/tapologin.env")

    email = os.getenv("EMAIL")
    password = os.getenv("PASSWORD")
    device_ip = os.getenv("DEVICEIP")

    with open("./config/house_config.json", "r") as f:
        try:
            house_params = json.load(f)
        except json.JSONDecodeError as exc:
            raise StromError(
                "config/house_config.json is not valid JSON: " + str(exc)
            ) from exc
    house = House(**house_params)
    return email, password, device_ip, house


async def main(email, password, device_ip, house, deps=None, clock=None):
    """Run one control cycle (kept for backwards compatibility)."""
    if deps is None:
        deps = ControllerDeps(clock=clock) if clock else ControllerDeps()
    await run_control_cycle(deps, email, password, device_ip, house)


def run(argv: list[str] | None = None) -> int:
    """Composition root: configure logging, load config, run, map exit codes."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    email, password, device_ip, house = setup_env_config()
    try:
        asyncio.run(main(email, password, device_ip, house))
    except StromError as exc:
        logger.error("Strom finished with an operational failure: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(run())
