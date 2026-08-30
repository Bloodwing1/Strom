"""Validated configuration loading (audit issue 36).

One loader, deterministic behavior:

* The config directory is resolved explicitly with ``pathlib`` (CLI
  argument, then ``$STROM_CONFIG_DIR``, then the first ``config/`` folder
  found walking up from the current directory). ``os.chdir`` is never
  called, so execution works from any working directory.
* A **missing** ``house_config.json`` is not an error: the documented
  defaults of :class:`strom.optimization_utils.House` are used and the
  decision is logged. A **malformed** file (bad JSON, wrong type, unknown
  keys, invalid physical values) fails fast with an actionable error.
* Required credentials (``EMAIL``, ``PASSWORD``, ``DEVICEIP`` from
  ``tapologin.env``/environment, plus both API keys) are validated at
  startup, before any network or device operation.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from .errors import ConfigurationError
from .optimization_utils import House

logger = logging.getLogger(__name__)

CONFIG_DIR_ENV_VAR = "STROM_CONFIG_DIR"
DEFAULT_CONFIG_DIRNAME = "config"

CREDENTIAL_FILE = "tapologin.env"
HOUSE_CONFIG_FILE = "house_config.json"
WEATHER_KEY_FILE = "weather_api_key.txt"
PRICE_KEY_FILE = "price_api_key.txt"

HOUSE_CONFIG_KEYS = frozenset({
    "C_air", "C_wall", "R_interior", "R_exterior", "Q_heater", "Q_cooling",
    "T_min", "T_max", "T_interior_init", "T_wall_init", "P_base", "freq",
})


@dataclass(frozen=True)
class Credentials:
    """Device and account credentials, validated at startup."""

    email: str
    password: str
    device_ip: str


@dataclass(frozen=True)
class AppConfig:
    """Fully validated application configuration."""

    config_dir: Path
    credentials: Credentials
    house: House
    weather_api_key: str
    price_api_key: str


def resolve_config_dir(explicit: str | Path | None = None) -> Path:
    """Resolve the config directory deterministically, never via chdir.

    Order: explicit argument, ``$STROM_CONFIG_DIR``, the first ancestor
    directory containing ``config/``, else ``./config``.
    """
    candidate: Path | None = None
    if explicit is not None:
        candidate = Path(explicit).expanduser().resolve()
    elif os.getenv(CONFIG_DIR_ENV_VAR):
        candidate = Path(os.environ[CONFIG_DIR_ENV_VAR]).expanduser().resolve()
    if candidate is None:
        current = Path.cwd()
        for directory in (current, *current.parents):
            if (directory / DEFAULT_CONFIG_DIRNAME).is_dir():
                candidate = (directory / DEFAULT_CONFIG_DIRNAME).resolve()
                break
        else:
            candidate = current / DEFAULT_CONFIG_DIRNAME
    if not candidate.is_dir():
        raise ConfigurationError(
            f"Config directory {candidate} does not exist; pass "
            "--config-dir, set STROM_CONFIG_DIR, or create ./config."
        )
    return candidate


def _required_env(name: str, config_dir: Path) -> str:
    value = os.getenv(name)
    if not value or not value.strip():
        raise ConfigurationError(
            f"{name} is not set; add it to {config_dir / CREDENTIAL_FILE} "
            "or export it in the environment."
        )
    return value.strip()


def load_credentials(config_dir: Path) -> Credentials:
    """Load and validate device credentials before any network operation."""
    env_file = config_dir / CREDENTIAL_FILE
    if env_file.is_file():
        # Never overrides variables already present in the environment.
        load_dotenv(env_file, override=False)
    credentials = Credentials(
        email=_required_env("EMAIL", config_dir),
        password=_required_env("PASSWORD", config_dir),
        device_ip=_required_env("DEVICEIP", config_dir),
    )
    return credentials


def load_house_params(config_dir: Path) -> dict:
    """Load house parameters; missing file means documented defaults."""
    path = config_dir / HOUSE_CONFIG_FILE
    if not path.is_file():
        logger.info(
            "No house_config.json in %s; using documented default house "
            "parameters.", config_dir,
        )
        return {}
    try:
        params = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ConfigurationError(
            f"{path} is not valid JSON (line {exc.lineno}, column "
            f"{exc.colno}): {exc.msg}"
        ) from exc
    if not isinstance(params, dict):
        raise ConfigurationError(
            f"{path} must contain a JSON object with house parameters."
        )
    unknown = sorted(set(params) - HOUSE_CONFIG_KEYS)
    if unknown:
        raise ConfigurationError(
            f"{path} contains unknown key(s) {unknown}; supported keys: "
            f"{sorted(HOUSE_CONFIG_KEYS)}."
        )
    return params


def load_api_key(config_dir: Path, env_var: str, file_name: str,
                 purpose: str) -> str:
    """Load an API key from the environment or the config directory."""
    key = os.getenv(env_var)
    if key and key.strip():
        return key.strip()
    path = config_dir / file_name
    if path.is_file():
        key = path.read_text().strip()
        if key:
            return key
    raise ConfigurationError(
        f"No {purpose} found; set {env_var} or create "
        f"{path} with the key."
    )


def load_app_config(config_dir: str | Path | None = None) -> AppConfig:
    """Resolve, validate and return the complete application configuration."""
    resolved = resolve_config_dir(config_dir)
    credentials = load_credentials(resolved)
    house = House(**load_house_params(resolved))
    weather_key = load_api_key(resolved, "WEATHER_API_KEY",
                               WEATHER_KEY_FILE, "weather API key")
    price_key = load_api_key(resolved, "PRICE_API_KEY",
                             PRICE_KEY_FILE, "electricity price API key")
    return AppConfig(
        config_dir=resolved,
        credentials=credentials,
        house=house,
        weather_api_key=weather_key,
        price_api_key=price_key,
    )
