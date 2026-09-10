"""Smart-plug connection policy shared by the CLI and the GUI.

The policy prefers the strongest credential available and falls back to a
credential-less attempt, so plugs that need no TP-Link account are used
without one:

1. a stored device configuration (connection type plus the derived
   credentials hash captured after an earlier successful login);
2. the account email and password, when the user provided them;
3. no credentials at all, letting python-kasa try its built-in defaults
   and blank credentials. This succeeds for plugs never bound to the
   TP-Link cloud and for older Kasa devices.

The TP-Link account is only ever used on the local network: it is the seed
for the device's local authentication hash, never a cloud login.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class PlugCredentials:
    """Everything needed to reach one plug, in preference order.

    ``plug_config`` is the JSON device configuration captured after a
    successful login, including the derived credentials hash. ``email`` and
    ``password`` are the optional TP-Link account credentials. A plug with
    neither can still work when it accepts default or blank credentials.
    """

    device_ip: str
    email: str = ""
    password: str = ""
    plug_config: str = ""


async def connect_plug(credentials: PlugCredentials):
    """Connect to the plug and return the python-kasa device.

    The caller owns the returned device and must close it.
    """
    from kasa import Device, DeviceConfig, Discover

    if credentials.plug_config:
        config = DeviceConfig.from_dict(json.loads(credentials.plug_config))
        config = replace(config, host=credentials.device_ip)
        return await Device.connect(config=config)
    if credentials.email and credentials.password:
        return await Discover.discover_single(
            credentials.device_ip,
            username=credentials.email,
            password=credentials.password,
        )
    return await Discover.discover_single(credentials.device_ip)
