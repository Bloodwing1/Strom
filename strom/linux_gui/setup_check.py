"""Off-thread credential checks for the setup pane.

Each check performs the same kind of operation a real run does, so the
setup screen can tell the user whether a key actually works instead of just
whether a file exists. Checks run in daemon threads and report through Qt
signals, so the window never blocks on the network. Error text is scrubbed
of the credential before it reaches the UI.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable

import pandas as pd
from PySide6.QtCore import QObject, Signal, SignalInstance

from strom.api_utils import get_price_series, get_weather_data
from strom.errors import StromError


def check_weather_key(api_key: str, city: str) -> None:
    """One weather request; raises when the key is rejected or unreachable."""
    get_weather_data(city=city, api_key=api_key, max_attempts=1,
                     sleep=lambda _seconds: None)


def check_price_key(api_key: str) -> None:
    """One published-prices query for yesterday and today."""
    now = pd.Timestamp.now(tz="UTC").floor("h")
    get_price_series(api_key=api_key, start=now - pd.Timedelta(hours=24),
                     end=now, max_attempts=1, sleep=lambda _seconds: None)


async def _discover_plug(email: str, password: str, device_ip: str) -> None:
    from kasa import Discover

    plug = await Discover.discover_single(
        device_ip, username=email, password=password
    )
    if plug is None:
        raise ConnectionError("no smart plug answered at that address")
    await plug.async_close()  # type: ignore[attr-defined]


def check_plug_credentials(email: str, password: str, device_ip: str) -> None:
    """One LAN discovery; raises when the plug cannot be reached."""
    asyncio.run(_discover_plug(email, password, device_ip))


class SetupChecker(QObject):
    """Runs credential checks and reports their outcome on the GUI thread."""

    weatherChecked = Signal(bool, str)
    priceChecked = Signal(bool, str)
    plugChecked = Signal(bool, str)

    def check_weather(self, api_key: str, city: str) -> None:
        self._spawn(lambda: check_weather_key(api_key, city),
                    self._emit_weather, api_key)

    def check_price(self, api_key: str) -> None:
        self._spawn(lambda: check_price_key(api_key),
                    self._emit_price, api_key)

    def check_plug(self, email: str, password: str, device_ip: str) -> None:
        self._spawn(lambda: check_plug_credentials(email, password, device_ip),
                    self._emit_plug, password)

    def _spawn(self, work: Callable[[], None],
               emit: Callable[[bool, str], None], secret: str) -> None:
        def run() -> None:
            try:
                work()
            except StromError as exc:
                emit(False, _scrub(str(exc), secret))
            except Exception as exc:  # noqa: BLE001 - shown as a short reason
                emit(False, _scrub(f"{type(exc).__name__}: {exc}", secret))
            else:
                emit(True, "")

        threading.Thread(target=run, daemon=True).start()

    def _emit_weather(self, ok: bool, message: str) -> None:
        _safe_emit(self.weatherChecked, ok, message)

    def _emit_price(self, ok: bool, message: str) -> None:
        _safe_emit(self.priceChecked, ok, message)

    def _emit_plug(self, ok: bool, message: str) -> None:
        _safe_emit(self.plugChecked, ok, message)


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
