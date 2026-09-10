"""Composition root and command-line interface (audit issue 36).

This is the single supported entry point: it resolves and validates the
configuration, builds the controller dependencies and maps expected
operational failures (:class:`~strom.errors.StromError`) to exit code 1.
Unexpected exceptions propagate with their traceback so process managers
report the failure.

Run via ``strom`` (console script), ``python -m strom`` or the legacy
``python main.py`` shim.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from strom.config import AppConfig, load_app_config
from strom.controller import ControlReport, ControllerDeps, run_control_cycle
from strom.control import SystemClock
from strom.errors import ConfigurationError, StromError
from strom.plug import PlugCredentials

logger = logging.getLogger(__name__)


def build_controller_deps(config: AppConfig,
                          horizon_hours: int, city: str = "Barcelona, ES") -> ControllerDeps:
    """Wire production dependencies from validated configuration."""
    from strom.data_utils import get_temp_price_df

    def fetch_data():
        return get_temp_price_df(
            horizon_hours=horizon_hours,
            city=city,
            weather_api_key=config.weather_api_key,
            price_api_key=config.price_api_key,
        )

    return ControllerDeps(
        fetch_data=fetch_data,
        clock=SystemClock(),
        interval_seconds=config.house.dt_hours * 3600.0,
        horizon_hours=horizon_hours,
    )


async def run_cycle(config: AppConfig, deps: ControllerDeps) -> ControlReport:
    return await run_control_cycle(
        deps,
        PlugCredentials(
            device_ip=config.credentials.device_ip,
            email=config.credentials.email,
            password=config.credentials.password,
            plug_config=config.credentials.plug_config,
        ),
        config.house,
    )


def write_report(path: str, report: ControlReport) -> None:
    """Write the machine-readable run summary; never fail the run for it."""
    payload = {
        "on_seconds": report.on_seconds,
        "interval_seconds": report.interval_seconds,
        "estimated_cost_eur": report.estimated_cost_eur,
    }
    try:
        Path(path).write_text(json.dumps(payload), encoding="utf-8")
    except OSError as exc:
        logger.warning("Could not write the run report to %s: %s", path, exc)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="strom",
        description="Optimize hourly heating against weather forecasts and "
                    "day-ahead electricity prices.",
    )
    parser.add_argument(
        "--config-dir", default=None,
        help="Directory holding tapologin.env, house_config.json and the "
             "API key files (default: $STROM_CONFIG_DIR, then ./config).",
    )
    parser.add_argument(
        "--horizon-hours", type=int, default=24,
        help="How many whole-hour intervals ahead to optimize (default 24, minimum 2).",
    )
    parser.add_argument(
        "--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity (default INFO).",
    )
    parser.add_argument("--city", default="Barcelona, ES",
                        help="Weather location, including country code (default: Barcelona, ES).")
    parser.add_argument(
        "--report-file", default=None,
        help="Write a JSON run summary (on-time and estimated cost) to this path.",
    )
    return parser


def run(argv: list[str] | None = None) -> int:
    """Composition root: parse args, validate config, run, map exit codes."""
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        if args.horizon_hours < 2:
            raise ConfigurationError(
                f"--horizon-hours must be >= 2, got {args.horizon_hours}: the "
                "optimizer needs at least two intervals."
            )
        config = load_app_config(args.config_dir)
        deps = build_controller_deps(config, args.horizon_hours, args.city)
        report = asyncio.run(run_cycle(config, deps))
        if args.report_file and report is not None:
            write_report(args.report_file, report)
    except StromError as exc:
        logger.error("Strom finished with an operational failure: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(run())
