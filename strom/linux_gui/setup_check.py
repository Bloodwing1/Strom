"""Off-thread credential checks for the setup pane.

Each check performs the same kind of operation a real run does, so the
setup screen can tell the user whether a key actually works instead of just
whether a file exists. Checks run in daemon threads and report through Qt
signals, so the window never blocks on the network. Error text is scrubbed
of the credential before it reaches the UI.
"""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import Callable

import pandas as pd
from PySide6.QtCore import QObject, Signal, SignalInstance

from strom.api_utils import get_price_series, get_weather_data
from strom.errors import DeviceError, StromError
from strom.plug import PlugCredentials, connect_plug

#: Stable message the GUI translates when a plug wants the account.
PLUG_NEEDS_CREDENTIALS = (
    "This plug asks for the TP-Link account. Enter the email and password, "
    "then test again."
)


def check_weather_key(api_key: str, city: str) -> None:
    """One weather request; raises when the key is rejected or unreachable."""
    get_weather_data(city=city, api_key=api_key, max_attempts=1,
                     sleep=lambda _seconds: None)


def check_price_key(api_key: str) -> None:
    """One published-prices query for yesterday and today."""
    now = pd.Timestamp.now(tz="UTC").floor("h")
    get_price_series(api_key=api_key, start=now - pd.Timedelta(hours=24),
                     end=now, max_attempts=1, sleep=lambda _seconds: None)


async def _probe_plug(credentials: PlugCredentials) -> str | None:
    """Connect with the standard policy and capture the derived proof."""
    from kasa.exceptions import AuthenticationError

    try:
        device = await connect_plug(credentials)
    except AuthenticationError:
        raise DeviceError(PLUG_NEEDS_CREDENTIALS) from None
    if device is None:
        raise ConnectionError("no smart plug answered at that address")
    try:
        # Even a credential-less success stores the connection type, so the
        # plug stays verified and reconnects directly. The derived hash is
        # included when the account was needed.
        credentials_hash = device.credentials_hash
        config = device.config.to_dict_control_credentials(
            credentials_hash=credentials_hash
        )
        return json.dumps(config)
    finally:
        await device.async_close()


def check_plug_credentials(credentials: PlugCredentials) -> str | None:
    """One LAN connection; returns the derived device config when available."""
    return asyncio.run(_probe_plug(credentials))


class SetupChecker(QObject):
    """Runs credential checks and reports their outcome on the GUI thread."""

    weatherChecked = Signal(bool, str)
    priceChecked = Signal(bool, str)
    plugChecked = Signal(bool, str, str)

    def check_weather(self, api_key: str, city: str) -> None:
        self._spawn(
            lambda: check_weather_key(api_key, city),
            lambda ok, message, _result: _safe_emit(
                self.weatherChecked, ok, message
            ),
            api_key,
        )

    def check_price(self, api_key: str) -> None:
        self._spawn(
            lambda: check_price_key(api_key),
            lambda ok, message, _result: _safe_emit(
                self.priceChecked, ok, message
            ),
            api_key,
        )

    def check_plug(self, credentials: PlugCredentials) -> None:
        self._spawn(
            lambda: check_plug_credentials(credentials),
            self._emit_plug,
            credentials.password,
        )

    def _spawn(
        self,
        work: Callable[[], object],
        emit: Callable[[bool, str, object], None],
        secret: str,
    ) -> None:
        def run() -> None:
            try:
                result = work()
            except StromError as exc:
                emit(False, _scrub(str(exc), secret), None)
            except Exception as exc:  # noqa: BLE001 - shown as a short reason
                emit(False, _scrub(f"{type(exc).__name__}: {exc}", secret), None)
            else:
                emit(True, "", result)

        threading.Thread(target=run, daemon=True).start()

    def _emit_plug(self, ok: bool, message: str, result: object) -> None:
        plug_config = result if isinstance(result, str) else ""
        try:
            self.plugChecked.emit(ok, message, plug_config)
        except RuntimeError:
            # The window was destroyed while the check was in flight.
            pass


def _safe_emit(signal: SignalInstance, ok: bool, message: str) -> None:
    try:
        signal.emit(ok, message)
    except RuntimeError:
        # The window was destroyed while the check was in flight.
        pass


def _scrub(message: str, *secrets: str) -> str:
    for secret in secrets:
        if secret:
            message = message.replace(secret, "***")
    return message
