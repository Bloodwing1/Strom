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
* ``tapologin.env`` is written with a per-value encoding chosen so that
  python-dotenv's parser reads every value back verbatim; the finished
  content is verified against python-dotenv's own parser before anything
  touches disk, so passwords with spaces, quotes, ``#``, or backslashes
  are stored correctly or not at all.
* Status checks read file *presence*/emptiness only in this module; callers
  that need values go through the backend's own loader at run time.
"""

from __future__ import annotations

import io
import ipaddress
import os
import re
from dataclasses import dataclass
from pathlib import Path

from dotenv.parser import parse_stream

# File names come from strom.config; restate them here so the GUI keeps its
# no-import-side-effects rule and stays testable without loading real config.
WEATHER_FILE = "weather_api_key.txt"
PRICE_FILE = "price_api_key.txt"
TAPO_FILE = "tapologin.env"
HOUSE_FILE = "house_config.json"

# Status-check environment fallbacks mirror the CLI precedence: an exported
# variable overrides the files, so setup is "done" when either source exists.
ENV_WEATHER_KEY = "WEATHER_API_KEY"
ENV_PRICE_KEY = "PRICE_API_KEY"
TAPO_ENV_KEYS = ("EMAIL", "PASSWORD", "DEVICEIP")


class SetupError(Exception):
    """A setup save failed validation; the message is user-facing."""


@dataclass(frozen=True)
class SetupStatus:
    """What the GUI shows as done/missing for the selected directory."""

    directory_exists: bool
    weather_key_saved: bool
    price_key_saved: bool
    tapo_saved: bool
    house_config_present: bool


def _non_blank(value: str, what: str) -> str:
    """Trim copy-paste artifacts; blank or multi-line input is rejected."""
    cleaned = value.strip()
    if not cleaned:
        raise SetupError(f"The {what} is empty; paste it and try again.")
    if "\n" in value or "\r" in value:
        raise SetupError(
            f"The {what} must be a single line; re-copy it without line breaks."
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


def _unquoted_env_value(value: str) -> str | None:
    """Encode ``value`` without quotes, or None when that is lossy.

    python-dotenv reads unquoted values verbatim with no escape decoding —
    which makes this the only lossless representation for values ending
    with a backslash (both quoted styles would swallow the closing quote).
    But the unquoted branch also strips trailing whitespace, drops a
    leading `` ``/#``-style comment, and never sees whitespace after
    ``=``, so it is only usable when none of that applies.
    """
    if value != value.rstrip() or value[0].isspace():
        return None
    if value[:1] in ("'", '"'):
        return None
    if re.search(r"\s#", value):
        return None
    return value


def _env_line(key: str, value: str) -> str:
    """Encode one key/value line, preferring the double-quoted form.

    The quoted form is lossless except for values ending with a backslash:
    python-dotenv's quoted scanner treats a backslash before the closing
    quote as an escaped quote and continues onto the next line (the same
    parser flaw behind upstream issue #661). Those values fall back to the
    unquoted form; a value that neither form can represent is rejected by
    the round-trip check instead of being written corrupted.
    """
    if value.endswith("\\"):
        unquoted = _unquoted_env_value(value)
        if unquoted is not None:
            return f"{key}={unquoted}\n"
    return f"{key}={_quote_env_value(value)}\n"


def _render_tapo_env(email: str, password: str, device_ip: str) -> str:
    """Render the file content and prove it round-trips before writing.

    Whatever encoding the lines use, the finished content is parsed back
    with python-dotenv's own parser — the exact code path the CLI's
    ``load_dotenv`` uses — and compared value by value. A quoted value
    ending with a backslash can still swallow its closing quote and run
    onto the next line; as the *last* line the parser's backtracking
    recovers it, so that order is tried as a fallback. If no order parses
    back correctly, nothing is written and a clear error is shown instead
    of silently corrupting credentials.
    """
    entries = [("EMAIL", email), ("PASSWORD", password), ("DEVICEIP", device_ip)]

    def render(order: list[tuple[str, str]]) -> str:
        return "".join(_env_line(key, value) for key, value in order)

    def roundtrips(order: list[tuple[str, str]]) -> bool:
        try:
            return _parse_env_content(render(order)) == dict(order)
        except ValueError:
            return False

    if roundtrips(entries):
        return render(entries)

    # Quoted values ending with a backslash are only recoverable on the
    # last line; stable-sort them there.
    reordered = sorted(entries, key=lambda item: item[1].endswith("\\"))
    if reordered != entries and roundtrips(reordered):
        return render(reordered)

    raise SetupError(
        "Strom cannot store these plug details safely in tapologin.env "
        "(python-dotenv cannot read back this combination of characters). "
        "Please change the password, or set EMAIL, PASSWORD, and DEVICEIP "
        "as environment variables instead."
    )


def save_tapo_credentials(
    config_dir: Path, email: str, password: str, device_ip: str
) -> Path:
    """Save the plug account to ``tapologin.env`` with verified quoting."""
    cleaned_email = _non_blank(email, "plug account email")
    cleaned_password = _non_blank(password, "plug account password")
    cleaned_ip = _non_blank(device_ip, "plug IP address")
    try:
        ipaddress.ip_address(cleaned_ip)
    except ValueError:
        raise SetupError(
            f"'{cleaned_ip}' does not look like an IP address. "
            "The Tapo app shows it under the plug's device information."
        ) from None
    content = _render_tapo_env(cleaned_email, cleaned_password, cleaned_ip)
    config_dir.mkdir(parents=True, exist_ok=True)
    path = config_dir / TAPO_FILE
    _write_secret_file(path, content)
    return path


def _file_has_content(path: Path) -> bool:
    try:
        return path.is_file() and bool(path.read_text(encoding="utf-8").strip())
    except (OSError, UnicodeDecodeError):
        return False


def _env_credentials_complete() -> bool:
    return all(os.getenv(name, "").strip() for name in TAPO_ENV_KEYS)


def read_setup_status(config_dir: Path) -> SetupStatus:
    """Check what setup is complete for ``config_dir`` without loading it.

    Files are read only to test for emptiness; no secret value is returned
    or logged. Environment overrides count as satisfied, matching the CLI's
    documented precedence.
    """
    return SetupStatus(
        directory_exists=config_dir.is_dir(),
        weather_key_saved=bool(os.getenv(ENV_WEATHER_KEY, "").strip())
        or _file_has_content(config_dir / WEATHER_FILE),
        price_key_saved=bool(os.getenv(ENV_PRICE_KEY, "").strip())
        or _file_has_content(config_dir / PRICE_FILE),
        tapo_saved=_env_credentials_complete() or _env_file_credentials(config_dir),
        house_config_present=(config_dir / HOUSE_FILE).is_file(),
    )


def _env_file_credentials(config_dir: Path) -> bool:
    """Parse ``tapologin.env`` for the three keys without mutating os.environ."""
    path = config_dir / TAPO_FILE
    if not path.is_file():
        return False
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return False
    found: set[str] = set()
    for line in lines:
        key, sep, value = line.partition("=")
        if sep and key.strip() in TAPO_ENV_KEYS and value.strip():
            found.add(key.strip())
    return found == set(TAPO_ENV_KEYS)
