"""Configuration and entry point tests (audit issue 36).

Everything uses temporary config directories; developer-local files and
the real environment never influence results.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from strom.config import (
    load_app_config,
    load_credentials,
    load_house_params,
    resolve_config_dir,
)
from strom.errors import ConfigurationError

from .conftest import make_config_dir


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    for var in ("EMAIL", "PASSWORD", "DEVICEIP", "STROM_CONFIG_DIR",
                "WEATHER_API_KEY", "PRICE_API_KEY"):
        monkeypatch.delenv(var, raising=False)


class TestResolveConfigDir:
    def test_explicit_directory(self, tmp_path):
        config = make_config_dir(tmp_path)
        assert resolve_config_dir(config) == config.resolve()

    def test_explicit_missing_directory_raises(self, tmp_path):
        with pytest.raises(ConfigurationError, match="does not exist"):
            resolve_config_dir(tmp_path / "nowhere")

    def test_env_variable(self, tmp_path, monkeypatch):
        config = make_config_dir(tmp_path)
        monkeypatch.setenv("STROM_CONFIG_DIR", str(config))
        assert resolve_config_dir() == config.resolve()

    def test_walks_up_from_cwd(self, tmp_path, monkeypatch):
        config = make_config_dir(tmp_path)
        nested = tmp_path / "a" / "b"
        nested.mkdir(parents=True)
        monkeypatch.chdir(nested)
        assert resolve_config_dir() == config.resolve()

    def test_missing_directory_names_candidate(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with pytest.raises(ConfigurationError, match="config"):
            resolve_config_dir()


class TestCredentials:
    def test_valid_credentials(self, tmp_path):
        config = make_config_dir(tmp_path)
        creds = load_credentials(config)
        assert creds.email == "user@example.com"
        assert creds.password == "secret-pass"
        assert creds.device_ip == "192.168.1.42"

    def test_missing_email_raises(self, tmp_path):
        config = make_config_dir(tmp_path)
        (config / "tapologin.env").write_text("PASSWORD=p\nDEVICEIP=1.2.3.4\n")
        with pytest.raises(ConfigurationError, match="EMAIL"):
            load_credentials(config)

    def test_missing_device_ip_raises(self, tmp_path, monkeypatch):
        config = tmp_path / "config"
        config.mkdir()
        (config / "tapologin.env").write_text("EMAIL=user@example.com\nPASSWORD=p\n")
        monkeypatch.setenv("EMAIL", "user@example.com")
        monkeypatch.setenv("PASSWORD", "p")
        with pytest.raises(ConfigurationError, match="DEVICEIP"):
            load_credentials(config)

    def test_environment_takes_precedence(self, tmp_path, monkeypatch):
        config = make_config_dir(tmp_path)
        monkeypatch.setenv("DEVICEIP", "10.0.0.1")
        creds = load_credentials(config)
        assert creds.device_ip == "10.0.0.1"


class TestHouseParams:
    def test_missing_file_means_documented_defaults(self, tmp_path):
        assert load_house_params(tmp_path) == {}

    def test_malformed_json_raises_with_position(self, tmp_path):
        path = tmp_path / "house_config.json"
        path.write_text("{not json")
        with pytest.raises(ConfigurationError, match="line 1"):
            load_house_params(tmp_path)

    def test_non_object_raises(self, tmp_path):
        (tmp_path / "house_config.json").write_text("[1, 2]")
        with pytest.raises(ConfigurationError, match="JSON object"):
            load_house_params(tmp_path)

    def test_unknown_keys_raise(self, tmp_path):
        (tmp_path / "house_config.json").write_text('{"C_airr": 1.0}')
        with pytest.raises(ConfigurationError, match="C_airr"):
            load_house_params(tmp_path)

    def test_invalid_physical_values_raise(self, tmp_path):
        config = make_config_dir(tmp_path)
        (config / "house_config.json").write_text('{"C_air": 0}')
        with pytest.raises(ConfigurationError, match="C_air"):
            load_app_config(str(config))


class TestAppConfig:
    def test_full_load_from_temporary_dir(self, tmp_path, monkeypatch):
        config = make_config_dir(tmp_path)
        (config / "house_config.json").write_text('{"Q_heater": 1.5}')
        app = load_app_config(str(config))
        assert app.house.Q_heater == 1.5
        assert app.credentials.device_ip == "192.168.1.42"
        assert app.weather_api_key == "weather-key"
        assert app.price_api_key == "price-key"

    def test_missing_api_key_raises_before_network(self, tmp_path):
        config = tmp_path / "config"
        config.mkdir()
        (config / "tapologin.env").write_text(
            "EMAIL=e\nPASSWORD=p\nDEVICEIP=1.2.3.4\n")
        with pytest.raises(ConfigurationError, match="weather API key"):
            load_app_config(config)

    def test_credentials_validated_before_network(self, tmp_path):
        config = tmp_path / "config"
        config.mkdir()
        (config / "weather_api_key.txt").write_text("k\n")
        (config / "price_api_key.txt").write_text("k\n")
        with pytest.raises(ConfigurationError, match="EMAIL"):
            load_app_config(config)

    def test_works_from_arbitrary_cwd(self, tmp_path, monkeypatch):
        config = make_config_dir(tmp_path)
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        monkeypatch.chdir(elsewhere)
        app = load_app_config(str(config))
        assert app.credentials.device_ip == "192.168.1.42"


class TestImportSideEffectFree:
    def test_importing_modules_performs_no_io(self, tmp_path, monkeypatch):
        """Import must succeed in an empty working directory with no config,
        no environment and no developer-local files."""
        repo_root = Path(__file__).resolve().parents[1]
        env = {
            "PATH": "/usr/bin:/bin",
            "PYTHONPATH": str(repo_root),
        }
        result = subprocess.run(
            [sys.executable, "-c",
             "import strom, strom.cli, strom.config, strom.controller, "
             "strom.data_utils, strom.api_utils, strom.optimization_utils"],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, result.stderr
