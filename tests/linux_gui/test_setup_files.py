"""Unit tests for the setup-file writer (no Qt required).

The tapologin.env writer stores the plug address and the derived
configuration captured by a successful Test. The finished content is
verified against python-dotenv's own parser before it touches disk; these
tests pin that never-write-corrupt-files guarantee and the status reading.
"""

import os

import pytest

from strom.linux_gui.setup_files import (
    PRICE_FILE,
    TAPO_FILE,
    WEATHER_FILE,
    SetupError,
    _parse_env_content,
    read_setup_status,
    read_tapo_credentials,
    save_api_key,
    save_tapo_credentials,
)

PLUG_CONFIG = '{"host": "192.168.1.9", "credentials_hash": "abc"}'


@pytest.fixture(autouse=True)
def clean_credential_environment(monkeypatch):
    for name in ("EMAIL", "PASSWORD", "DEVICEIP", "PLUG_CONFIG"):
        monkeypatch.delenv(name, raising=False)


def test_plug_config_roundtrips_verbatim(tmp_path):
    path = save_tapo_credentials(
        tmp_path, "192.168.1.42", plug_config=PLUG_CONFIG
    )

    assert _parse_env_content(path.read_text()) == {
        "DEVICEIP": "192.168.1.42",
        "PLUG_CONFIG": PLUG_CONFIG,
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
        return {"DEVICEIP": "different value"}

    monkeypatch.setattr(
        "strom.linux_gui.setup_files._parse_env_content", failed_parse
    )
    with pytest.raises(SetupError, match="cannot store"):
        save_tapo_credentials(tmp_path, "192.168.1.42", plug_config=PLUG_CONFIG)
    if existing:
        assert path.read_text() == "previous contents\n"
    else:
        assert not path.exists()


def test_bad_ip_rejected(tmp_path):
    with pytest.raises(SetupError, match="does not look like an IP address"):
        save_tapo_credentials(tmp_path, "not-an-ip")


def test_files_are_private(tmp_path):
    key_path = save_api_key(tmp_path, WEATHER_FILE, "k", "weather key")
    tapo_path = save_tapo_credentials(tmp_path, "192.168.1.42")

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


def test_read_tapo_credentials_roundtrips_without_touching_env(tmp_path):
    save_tapo_credentials(tmp_path, "192.168.1.7", plug_config=PLUG_CONFIG)

    stored = read_tapo_credentials(tmp_path)
    assert stored is not None
    assert stored.device_ip == "192.168.1.7"
    assert stored.plug_config == PLUG_CONFIG
    assert stored.email == ""
    assert stored.password == ""
    assert "DEVICEIP" not in os.environ


def test_read_tapo_credentials_returns_partial_records(tmp_path):
    (tmp_path / TAPO_FILE).write_text('DEVICEIP="192.168.1.1"\n')
    stored = read_tapo_credentials(tmp_path)
    assert stored is not None
    assert stored.device_ip == "192.168.1.1"
    assert stored.email == ""
    assert read_tapo_credentials(tmp_path / "missing") is None


def test_derived_config_is_stored(tmp_path):
    save_tapo_credentials(tmp_path, "192.168.1.9", plug_config=PLUG_CONFIG)

    stored = read_tapo_credentials(tmp_path)
    assert stored is not None
    assert stored.plug_config == PLUG_CONFIG
    assert stored.email == ""
    assert stored.password == ""
    status = read_setup_status(tmp_path)
    assert status.tapo_saved
    assert status.tapo_verified
    assert status.tapo_ip_saved


def test_ip_only_is_saved_but_not_verified(tmp_path):
    save_tapo_credentials(tmp_path, "192.168.1.9")

    status = read_setup_status(tmp_path)
    assert status.tapo_ip_saved
    assert not status.tapo_saved
    assert not status.tapo_verified
