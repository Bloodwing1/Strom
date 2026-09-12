"""Save-and-check helpers for the GUI setup pane.

The setup pane lets non-technical users paste their credentials and API keys
instead of creating files by hand. Everything a user pastes here is written
to the same files the CLI already reads (plan §2), so the GUI stays a thin
front end over the existing configuration:

* ``weather_api_key.txt`` — OpenWeatherMap API key.
* ``price_api_key.txt`` — ENTSO-E Transparency Platform token.
* ``tapologin.env`` — ``EMAIL``/``PASSWORD``/``DEVICEIP`` for the smart plug.

Security rules for this module:

* Secrets are only ever written into the user-chosen config directory, never
  into ``QSettings`` or logs.
* Written files are forced to mode 0600 so other users on the machine cannot
  read them.
* ``tapologin.env`` values are quoted so that python-dotenv's parser reads
  them back verbatim; the finished content is verified against
  python-dotenv's own parser before anything touches disk, so the file is
  stored correctly or not at all.
* Status checks read file *presence*/emptiness only in this module; callers
  that need values go through the backend's own loader at run time.
"""

from __future__ import annotations

import io
import ipaddress
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv.parser import parse_stream

# File names come from strom.config; restate them here so the GUI keeps its
# no-import-side-effects rule and stays testable without loading real config.
WEATHER_FILE = "weather_api_key.txt"
PRICE_FILE = "price_api_key.txt"
TAPO_FILE = "tapologin.env"

# Status-check environment fallbacks mirror the CLI precedence: an exported
# variable overrides the files, so setup is "done" when either source exists.
ENV_WEATHER_KEY = "WEATHER_API_KEY"
ENV_PRICE_KEY = "PRICE_API_KEY"
TAPO_ENV_KEYS = ("EMAIL", "PASSWORD", "DEVICEIP")
PLUG_CONFIG_KEY = "PLUG_CONFIG"


class SetupError(Exception):
    """A setup save failed validation; the message is user-facing.

    ``code`` and ``params`` let the GUI translate the message, while
    ``message`` stays a complete English sentence for logs and tests.
    """

    def __init__(
        self,
        message: str,
        *,
        code: str = "",
        params: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.params = params or {}


@dataclass(frozen=True)
class SetupStatus:
    """What the GUI shows as done/missing for the selected directory.

    ``tapo_saved`` means the plug can be used: its IP is set plus either a
    stored derived configuration or the account credentials.
    ``tapo_verified`` means a derived configuration from a successful login
    is stored, so the account is no longer needed.
    """

    weather_key_saved: bool
    price_key_saved: bool
    tapo_saved: bool
    tapo_verified: bool = False
    tapo_ip_saved: bool = False


@dataclass(frozen=True)
class TapoCredentials:
    """Everything stored for the plug, in the same shape the CLI reads."""

    device_ip: str = ""
    email: str = ""
    password: str = ""
    plug_config: str = ""


def _non_blank(value: str, what: str) -> str:
    """Trim copy-paste artifacts; blank or multi-line input is rejected."""
    cleaned = value.strip()
    if not cleaned:
        raise SetupError(
            f"The {what} is empty; paste it and try again.", code="empty"
        )
    if "\n" in value or "\r" in value:
        raise SetupError(
            f"The {what} must be a single line; re-copy it without line breaks.",
            code="multiline",
        )
    return cleaned


def _write_secret_file(path: Path, content: str) -> None:
    """Write ``content`` to ``path`` with mode 0600, replacing any old value."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(content)
    os.chmod(path, 0o600)


def save_api_key(config_dir: Path, file_name: str, key: str, what: str) -> Path:
    """Save one API key into ``file_name`` inside ``config_dir``."""
    cleaned = _non_blank(key, what)
    config_dir.mkdir(parents=True, exist_ok=True)
    path = config_dir / file_name
    _write_secret_file(path, cleaned + "\n")
    return path


def _quote_env_value(value: str) -> str:
    """Quote one single-line value for a .env file, escape-safe.

    python-dotenv processes ``\\`` escapes inside double-quoted values, so
    escaping backslashes and double quotes round-trips every value that
    does not end with a backslash. ``set_key`` is deliberately not used:
    its single quoting corrupts such values even harder (issue #661).
    """
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _parse_env_content(content: str) -> dict[str, str]:
    """Parse .env content with the backend's own parser (pure function)."""
    parsed: dict[str, str] = {}
    for binding in parse_stream(io.StringIO(content)):
        if binding.error or binding.key is None or binding.value is None:
            raise ValueError("unparseable .env line")
        parsed[binding.key] = binding.value
    return parsed


def _render_tapo_env(entries: list[tuple[str, str]]) -> str:
    """Render the file content and prove it round-trips before writing.

    The finished content is parsed back with python-dotenv's own parser —
    the exact code path the CLI's ``load_dotenv`` uses — and compared value
    by value. A value python-dotenv cannot read back exactly is rejected
    here instead of being written corrupted.
    """
    content = "".join(
        f"{key}={_quote_env_value(value)}\n" for key, value in entries
    )
    try:
        parsed = _parse_env_content(content)
    except ValueError:
        parsed = {}
    if parsed != dict(entries):
        raise SetupError(
            "Strom cannot store these plug details safely in tapologin.env "
            "(python-dotenv cannot read back this combination of "
            "characters). Please set DEVICEIP and PLUG_CONFIG as environment "
            "variables instead.",
            code="encoding",
        )
    return content


def save_tapo_credentials(
    config_dir: Path,
    device_ip: str,
    *,
    email: str = "",
    password: str = "",
    plug_config: str = "",
) -> Path:
    """Save the plug endpoint and whatever credentials it has.

    Only the address is required. A derived configuration captured by a
    successful Test is stored beside it and replaces any account
    credentials; without one, a passed email/password pair is preserved so
    saving the address cannot erase what an older file already had.
    """
    cleaned_ip = _non_blank(device_ip, "plug IP address")
    try:
        ipaddress.ip_address(cleaned_ip)
    except ValueError:
        raise SetupError(
            f"'{cleaned_ip}' does not look like an IP address. "
            "The Tapo app shows it under the plug's device information.",
            code="bad_ip",
            params={"value": cleaned_ip},
        ) from None
    entries = [("DEVICEIP", cleaned_ip)]
    if plug_config:
        entries.append((PLUG_CONFIG_KEY, plug_config))
    else:
        if email:
            entries.append(("EMAIL", email))
        if password:
            entries.append(("PASSWORD", password))
    content = _render_tapo_env(entries)
    config_dir.mkdir(parents=True, exist_ok=True)
    path = config_dir / TAPO_FILE
    _write_secret_file(path, content)
    return path


def _file_has_content(path: Path) -> bool:
    try:
        return path.is_file() and bool(path.read_text(encoding="utf-8").strip())
    except (OSError, UnicodeDecodeError):
        return False


def _env_tapo_saved() -> bool:
    """True when exported variables fully configure the plug."""
    device_ip = os.getenv("DEVICEIP", "").strip()
    plug_config = os.getenv(PLUG_CONFIG_KEY, "").strip()
    email = os.getenv("EMAIL", "").strip()
    password = os.getenv("PASSWORD", "").strip()
    return bool(device_ip and (plug_config or (email and password)))


def read_setup_status(config_dir: Path) -> SetupStatus:
    """Check what setup is complete for ``config_dir`` without loading it.

    Files are read only to test for emptiness; no secret value is returned
    or logged. Environment overrides count as satisfied, matching the CLI's
    documented precedence.
    """
    stored = read_tapo_credentials(config_dir)
    file_saved = bool(
        stored
        and stored.device_ip
        and (stored.plug_config or (stored.email and stored.password))
    )
    return SetupStatus(
        weather_key_saved=bool(os.getenv(ENV_WEATHER_KEY, "").strip())
        or _file_has_content(config_dir / WEATHER_FILE),
        price_key_saved=bool(os.getenv(ENV_PRICE_KEY, "").strip())
        or _file_has_content(config_dir / PRICE_FILE),
        tapo_saved=_env_tapo_saved() or file_saved,
        tapo_verified=bool(
            stored and stored.plug_config
        ) or bool(os.getenv(PLUG_CONFIG_KEY, "").strip()),
        tapo_ip_saved=bool(
            stored and stored.device_ip
        ) or bool(os.getenv("DEVICEIP", "").strip()),
    )


def read_tapo_credentials(config_dir: Path) -> TapoCredentials | None:
    """Read the plug settings from ``tapologin.env``.

    Parses with python-dotenv's own parser so quoted values read back
    exactly; ``os.environ`` is never touched. Returns None when the file
    is missing or unreadable, otherwise a record with empty fields for the
    keys that are not stored.
    """
    path = config_dir / TAPO_FILE
    try:
        parsed = _parse_env_content(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    return TapoCredentials(
        device_ip=parsed.get("DEVICEIP", "").strip(),
        email=parsed.get("EMAIL", "").strip(),
        password=parsed.get("PASSWORD", "").strip(),
        plug_config=parsed.get(PLUG_CONFIG_KEY, "").strip(),
    )
