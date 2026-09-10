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

import inspect
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

from .errors import ConfigurationError
from .optimization_utils import House

logger = logging.getLogger(__name__)

CONFIG_DIR_ENV_VAR = "STROM_CONFIG_DIR"
DEFAULT_CONFIG_DIRNAME = "config"

CREDENTIAL_FILE = "tapologin.env"
HOUSE_CONFIG_FILE = "house_config.json"
WEATHER_KEY_FILE = "weather_api_key.txt"
PRICE_KEY_FILE = "price_api_key.txt"

#: Exactly the parameters :class:`House` accepts; kept in sync by deriving
#: them from its signature instead of restating the list here.
HOUSE_CONFIG_KEYS = frozenset(inspect.signature(House).parameters)


@dataclass(frozen=True)
class Credentials:
    """Plug endpoint plus optional proof, validated at startup.

    ``device_ip`` is required. ``plug_config`` is the derived device
    configuration captured after a successful login (preferred when
    present). ``email`` and ``password`` are the optional TP-Link account
    credentials; a plug that needs no account can leave them empty.
    """

    email: str
    password: str
    device_ip: str
    plug_config: str = ""


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


def _optional_env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def _credential_value(name: str, file_values: dict[str, str]) -> str:
    """Environment wins over the file; both are stripped."""
    return _optional_env(name) or file_values.get(name, "")


def load_credentials(config_dir: Path) -> Credentials:
    """Load and validate device credentials before any network operation.

    ``DEVICEIP`` is required. ``EMAIL`` and ``PASSWORD`` are optional but
    must be set together. ``PLUG_CONFIG`` carries the derived device
    configuration captured after a successful login; it takes precedence
    over the account credentials at connect time.

    The credential file is parsed without mutating ``os.environ``;
    exported variables take precedence over file values.
    """
    env_file = config_dir / CREDENTIAL_FILE
    raw_values = dotenv_values(env_file) if env_file.is_file() else {}
    file_values = {
        key: (value or "").strip() for key, value in raw_values.items()
    }
    email = _credential_value("EMAIL", file_values)
    password = _credential_value("PASSWORD", file_values)
    if bool(email) != bool(password):
        raise ConfigurationError(
            "EMAIL and PASSWORD must be set together (or both left empty "
            "for plugs that need no TP-Link account)."
        )
    plug_config = _credential_value("PLUG_CONFIG", file_values)
    if plug_config:
        try:
            parsed = json.loads(plug_config)
        except json.JSONDecodeError as exc:
            raise ConfigurationError(
                f"PLUG_CONFIG is not valid JSON: {exc.msg}."
            ) from exc
        if not isinstance(parsed, dict):
            raise ConfigurationError(
                "PLUG_CONFIG must be a JSON object."
            )
    device_ip = _credential_value("DEVICEIP", file_values)
    if not device_ip:
        raise ConfigurationError(
            f"DEVICEIP is not set; add it to {env_file} or export it in "
            "the environment."
        )
    return Credentials(
        email=email,
        password=password,
        device_ip=device_ip,
        plug_config=plug_config,
    )


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


def load_api_key(config_dir: Path | None, env_var: str, file_name: str,
                 purpose: str) -> str:
    """Load an API key from the environment or the config directory.

    ``config_dir=None`` resolves the directory lazily, so an exported key
    works even when no config directory exists.
    """
    key = os.getenv(env_var)
    if key and key.strip():
        return key.strip()
    path = (config_dir or resolve_config_dir()) / file_name
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
