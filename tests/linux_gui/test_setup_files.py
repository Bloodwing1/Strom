"""Unit tests for the setup-file encoder (no Qt required).

The tapologin.env encoder works around python-dotenv's quoted-value
scanner, which consumes a backslash before the closing quote and runs
onto the next line (upstream issue #661). These tests pin the encoding
rules and the never-write-corrupt-files guarantee.
"""

import os

import pytest

from dotenv import load_dotenv

from strom.linux_gui.setup_files import (
    PRICE_FILE,
    TAPO_FILE,
    WEATHER_FILE,
    SetupError,
    _env_line,
    _parse_env_content,
    _unquoted_env_value,
    read_setup_status,
    read_tapo_credentials,
    save_api_key,
    save_tapo_credentials,
)

TRICKY_PASSWORDS = [
    'pa ss #wo"rd\\',  # quote, spaces, hash, trailing backslash
    "trailing\\",
    "\\",
    "\\\\\\\\",
    'quo"te',
    "has#hash",
    "has #comment-start",
    "mid dle spaces",
    "unïcodé✓",
    "C:\\Users\\bob",
    "plain",
]


@pytest.fixture(autouse=True)
def clean_credential_environment(monkeypatch):
    for name in ("EMAIL", "PASSWORD", "DEVICEIP", "PLUG_CONFIG"):
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize("password", TRICKY_PASSWORDS)
def test_tapo_passwords_roundtrip_verbatim(tmp_path, password):
    path = save_tapo_credentials(tmp_path, "u@x.com", password, "192.168.1.42")

    parsed = _parse_env_content(path.read_text())
    assert parsed == {
        "EMAIL": "u@x.com",
        "PASSWORD": password,
        "DEVICEIP": "192.168.1.42",
    }


@pytest.mark.parametrize("password", TRICKY_PASSWORDS)
def test_tapo_passwords_load_via_load_dotenv(tmp_path, monkeypatch, password):
    path = save_tapo_credentials(tmp_path, "u@x.com", password, "192.168.1.42")

    load_dotenv(path, override=True)
    assert os.environ.pop("PASSWORD") == password
    monkeypatch.delenv("EMAIL", raising=False)
    monkeypatch.delenv("DEVICEIP", raising=False)


def test_multiple_backslash_passwords_roundtrip(tmp_path):
    path = save_tapo_credentials(tmp_path, "a@x.com\\", "pw\\", "192.168.1.42")

    assert _parse_env_content(path.read_text()) == {
        "EMAIL": "a@x.com\\",
        "PASSWORD": "pw\\",
        "DEVICEIP": "192.168.1.42",
    }


def test_multiple_quoted_backslash_endings_roundtrip(tmp_path):
    # This combination is representable by the supported dotenv parser;
    # trailing backslashes alone do not prove that encoding must fail.
    email, password = '"x@x.com\\', "a #b\\"
    path = save_tapo_credentials(tmp_path, email, password, "192.168.1.42")
    assert _parse_env_content(path.read_text()) == {
        "EMAIL": email,
        "PASSWORD": password,
        "DEVICEIP": "192.168.1.42",
    }


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("parser_raises", [False, True])
def test_failed_roundtrip_never_writes_credentials(
    tmp_path, monkeypatch, existing, parser_raises
):
    path = tmp_path / TAPO_FILE
    if existing:
        path.write_text("previous contents\n")

    def failed_parse(content):
        if parser_raises:
            raise ValueError("unparseable .env line")
        return {"PASSWORD": "different value"}

    monkeypatch.setattr(
        "strom.linux_gui.setup_files._parse_env_content", failed_parse
    )
    with pytest.raises(SetupError, match="cannot store"):
        save_tapo_credentials(tmp_path, '"x@x.com\\', "a #b\\", "192.168.1.42")
    if existing:
        assert path.read_text() == "previous contents\n"
    else:
        assert not path.exists()


def test_files_are_private(tmp_path):
    key_path = save_api_key(tmp_path, WEATHER_FILE, "k", "weather key")
    tapo_path = save_tapo_credentials(tmp_path, "u@x.com", "p", "192.168.1.42")

    assert key_path.stat().st_mode & 0o777 == 0o600
    assert tapo_path.stat().st_mode & 0o777 == 0o600


def test_overwriting_tightens_permissions_of_existing_file(tmp_path):
    path = tmp_path / WEATHER_FILE
    path.write_text("old\n")
    path.chmod(0o644)

    save_api_key(tmp_path, WEATHER_FILE, "new", "weather key")

    assert path.stat().st_mode & 0o777 == 0o600
    assert path.read_text() == "new\n"


def test_api_key_trims_pasted_whitespace(tmp_path):
    path = save_api_key(tmp_path, PRICE_FILE, "  token  ", "price key")

    assert path.read_text() == "token\n"


def test_multiline_api_key_is_rejected(tmp_path):
    with pytest.raises(SetupError, match="single line"):
        save_api_key(tmp_path, PRICE_FILE, "token\nmore", "price key")


# --- encoding decisions ---


def test_unquoted_encoding_only_for_safe_values():
    assert _unquoted_env_value("abc\\") == "abc\\"
    assert _unquoted_env_value("C:\\Users\\bob") == "C:\\Users\\bob"
    assert _unquoted_env_value("trail \\") == "trail \\"
    # Lossy under the unquoted parser rules: no encoding offered.
    assert _unquoted_env_value(" lead\\") is None
    assert _unquoted_env_value("trail \\ ") is None
    assert _unquoted_env_value('a #b\\') is None
    assert _unquoted_env_value('"quoted\\') is None


def test_env_line_uses_quotes_except_for_backslash_endings():
    assert _env_line("PASSWORD", 'quo"te') == 'PASSWORD="quo\\"te"\n'
    assert _env_line("PASSWORD", "abc\\") == "PASSWORD=abc\\\n"


def test_parse_env_content_rejects_broken_lines():
    with pytest.raises(ValueError):
        _parse_env_content("this is not an assignment\n")


# --- status reading ---


def test_read_setup_status_reflects_files_and_env(tmp_path, monkeypatch):
    status = read_setup_status(tmp_path)
    assert not status.weather_key_saved
    assert not status.tapo_saved

    # Environment overrides satisfy the check without any files.
    monkeypatch.setenv("WEATHER_API_KEY", "env-key")
    status = read_setup_status(tmp_path)
    assert status.weather_key_saved

    # A file with only whitespace does not count as saved.
    (tmp_path / WEATHER_FILE).write_text("  \n")
    monkeypatch.delenv("WEATHER_API_KEY")
    assert not read_setup_status(tmp_path).weather_key_saved

    # tapologin.env counts only when all three keys are present and non-empty.
    (tmp_path / TAPO_FILE).write_text('EMAIL="e@x.com"\nPASSWORD="p"\n')
    assert not read_setup_status(tmp_path).tapo_saved
    (tmp_path / TAPO_FILE).write_text(
        'EMAIL="e@x.com"\nPASSWORD="p"\nDEVICEIP="192.168.1.1"\n'
    )
    assert read_setup_status(tmp_path).tapo_saved
    assert (tmp_path / PRICE_FILE).name == PRICE_FILE


def test_read_tapo_credentials_roundtrips_without_touching_env(tmp_path, monkeypatch):
    monkeypatch.delenv("EMAIL", raising=False)
    monkeypatch.delenv("PASSWORD", raising=False)
    monkeypatch.delenv("DEVICEIP", raising=False)
    save_tapo_credentials(tmp_path, "user@example.com", 'pa ss "word', "192.168.1.7")

    stored = read_tapo_credentials(tmp_path)
    assert stored is not None
    assert stored.email == "user@example.com"
    assert stored.password == 'pa ss "word'
    assert stored.device_ip == "192.168.1.7"
    assert stored.plug_config == ""
    assert "EMAIL" not in os.environ


def test_read_tapo_credentials_returns_partial_records(tmp_path):
    (tmp_path / TAPO_FILE).write_text('DEVICEIP="192.168.1.1"\n')
    stored = read_tapo_credentials(tmp_path)
    assert stored is not None
    assert stored.device_ip == "192.168.1.1"
    assert stored.email == ""
    assert read_tapo_credentials(tmp_path / "missing") is None


def test_derived_config_is_stored_instead_of_the_password(tmp_path):
    plug_config = '{"host": "192.168.1.9", "credentials_hash": "abc"}'
    save_tapo_credentials(
        tmp_path, "", "", "192.168.1.9", plug_config=plug_config
    )

    stored = read_tapo_credentials(tmp_path)
    assert stored is not None
    assert stored.plug_config == plug_config
    assert stored.email == ""
    assert stored.password == ""
    status = read_setup_status(tmp_path)
    assert status.tapo_saved
    assert status.tapo_verified
    assert status.tapo_ip_saved


def test_ip_only_is_saved_but_not_verified(tmp_path):
    save_tapo_credentials(tmp_path, "", "", "192.168.1.9")

    status = read_setup_status(tmp_path)
    assert status.tapo_ip_saved
    assert not status.tapo_saved
    assert not status.tapo_verified


def test_half_account_details_rejected(tmp_path):
    with pytest.raises(SetupError, match="both"):
        save_tapo_credentials(tmp_path, "user@example.com", "", "192.168.1.9")
