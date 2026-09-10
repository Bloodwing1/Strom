"""Connection policy tests for plugs: stored proof, account, then blank."""

from __future__ import annotations

import kasa

from strom.plug import PlugCredentials, connect_plug


async def test_stored_config_wins_and_host_follows_the_endpoint(monkeypatch):
    calls: dict = {}

    async def fake_connect(config):
        calls["host"] = config.host
        calls["hash"] = config.credentials_hash
        return "device"

    def fake_from_dict(data):
        return kasa.DeviceConfig(
            host=data["host"], credentials_hash=data.get("credentials_hash")
        )

    monkeypatch.setattr(kasa.Device, "connect", fake_connect)
    monkeypatch.setattr(kasa.DeviceConfig, "from_dict", staticmethod(fake_from_dict))

    result = await connect_plug(
        PlugCredentials(
            device_ip="10.0.0.9",
            plug_config='{"host": "10.0.0.1", "credentials_hash": "abc"}',
        )
    )

    assert result == "device"
    assert calls == {"host": "10.0.0.9", "hash": "abc"}


async def test_account_credentials_are_used_when_nothing_is_stored(monkeypatch):
    calls: dict = {}

    async def fake_discover(host, **kwargs):
        calls["host"] = host
        calls["kwargs"] = kwargs
        return "device"

    monkeypatch.setattr(kasa.Discover, "discover_single", fake_discover)

    result = await connect_plug(
        PlugCredentials(device_ip="10.0.0.9", email="e@x.com", password="pw")
    )

    assert result == "device"
    assert calls == {
        "host": "10.0.0.9",
        "kwargs": {"username": "e@x.com", "password": "pw"},
    }


async def test_no_credentials_tries_blank(monkeypatch):
    calls: dict = {}

    async def fake_discover(host, **kwargs):
        calls["host"] = host
        calls["kwargs"] = kwargs
        return "device"

    monkeypatch.setattr(kasa.Discover, "discover_single", fake_discover)

    result = await connect_plug(PlugCredentials(device_ip="10.0.0.9"))

    assert result == "device"
    assert calls == {"host": "10.0.0.9", "kwargs": {}}
