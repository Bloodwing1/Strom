"""Asynchronous update check and download, plus the update lifecycle.

The :class:`UpdateService` performs network work with
:class:`QNetworkAccessManager` and owns no widgets: it checks the fixed
repository's published releases (no credentials), streams the AppImage into
a staging file beside the target while hashing it incrementally, and
verifies size and checksum before the file becomes executable. Tests inject
the transport, endpoints and URL policy and use a local fake HTTP service —
they never contact GitHub.

The :class:`UpdateCoordinator` owns the explicit update states (kept
separate from :class:`~strom.linux_gui.runner.RunnerState`) and the
cycle/update interlock; verified staging files are handed to the
transaction in :mod:`strom.linux_gui.update_install`. Update states:
Idle, Checking, Available, Downloading, Verifying, Installing, Restarting,
Failed.

The repository is fixed to Bloodwing1/Strom; release text is untrusted and
never used for repository, command or destination values. HTTPS with
normal certificate validation is used throughout; TLS verification is never
disabled and no credentials are ever sent.
"""

from __future__ import annotations

import enum
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from packaging.version import Version

from PySide6.QtCore import (
    QObject,
    QProcess,
    QProcessEnvironment,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtNetwork import (
    QLocalServer,
    QLocalSocket,
    QNetworkAccessManager,
    QNetworkReply,
    QNetworkRequest,
)

from strom.linux_gui import update_install
from strom.linux_gui import updates as release_selection
from strom.linux_gui.app_identity import (
    EXTRACT_AND_RUN_ENV,
    EXTRACT_AND_RUN_SWITCH,
    AppImageIdentity,
    InstallStatus,
)
from strom.entry_switches import FROZEN_SELF_TEST_SWITCH
from strom.linux_gui.updates import (
    API_RELEASES_URL,
    DOWNLOAD_HOSTS,
    DOWNLOAD_PATH_PREFIX,
    ReleaseInfo,
    Selection,
)

#: Environment variable carrying the restart handshake to the new instance.
ACK_ENV = "STROM_UPDATE_ACK"

#: Marks a candidate launched by a launcher that does not kill it. Older
#: launchers (through 0.3.2) destroyed the QProcess that started the
#: candidate, and Qt's destructor kills the still-running child; a
#: candidate without this mark restarts itself detached before the kill.
SAFE_LAUNCH_ENV = "STROM_UPDATE_SAFE_LAUNCH"

#: Marks a candidate that is already the detached copy (no further handoff).
_HANDOFF_ENV = "STROM_UPDATE_HANDOFF"
_HANDOFF_GRACE_MS = 2_000

ACK_TIMEOUT_MS = 30_000
SELF_TEST_TIMEOUT_MS = 300_000
_TERMINATE_GRACE_MS = 5_000
_SELF_TEST_TAIL_CHARS = 4000

_CANDIDATE_RETRY_MS = 250
REQUEST_TIMEOUT_MS = 30_000
DOWNLOAD_TIMEOUT_MS = 900_000  # 15 minutes total, documented in the README
METADATA_MAX_BYTES = 16 * 1024 * 1024
MAX_DOWNLOAD_BYTES = 1024 * 1024 * 1024  # 1 GiB documented maximum
MAX_REDIRECTS = 5
PROGRESS_STEP_BYTES = 256 * 1024

#: AppImage/AppDir loader variables that must not leak into the replacement.
_RESTART_ENV_STRIP = (
    "APPIMAGE",
    "APPDIR",
    "ARGV0",
    "OWD",
    "LD_LIBRARY_PATH",
    "PYTHONHOME",
    "PYTHONPATH",
    "GI_TYPELIB_PATH",
    "GIO_MODULE_DIR",
    "GDK_PIXBUF_MODULE_FILE",
    "QT_PLUGIN_PATH",
    EXTRACT_AND_RUN_ENV,
)

_STABLE_URL_MESSAGE = (
    "Update checks use GitHub's public API for Bloodwing1/Strom; the "
    "repository, download destination and commands are never taken from "
    "release text."
)


class UpdateState(enum.Enum):
    """Explicit update lifecycle states, separate from RunnerState (§4)."""

    Idle = "Idle"
    Checking = "Checking"
    Available = "Available"
    Downloading = "Downloading"
    Verifying = "Verifying"
    Installing = "Installing"
    Restarting = "Restarting"
    Failed = "Failed"


@dataclass(frozen=True)
class ServiceConfig:
    """Fixed network endpoints and bounds for one update service."""

    releases_url: str = API_RELEASES_URL
    page_size: int = release_selection.RELEASES_PER_PAGE
    max_pages: int = release_selection.MAX_RELEASE_PAGES
    request_timeout_ms: int = REQUEST_TIMEOUT_MS
    download_timeout_ms: int = DOWNLOAD_TIMEOUT_MS
    metadata_max_bytes: int = METADATA_MAX_BYTES
    max_download_bytes: int = MAX_DOWNLOAD_BYTES
    max_redirects: int = MAX_REDIRECTS


class UrlPolicy:
    """HTTPS-only validation of release asset and redirect URLs.

    The scheme is a constructor parameter so the production default stays
    ``https`` while a local fake HTTP service can be injected in tests.
    """

    def __init__(
        self,
        *,
        download_hosts: tuple[str, ...] = DOWNLOAD_HOSTS,
        asset_prefix: str = DOWNLOAD_PATH_PREFIX,
        scheme: str = "https",
    ) -> None:
        self._hosts = frozenset(download_hosts)
        self._prefix = asset_prefix
        self._scheme = scheme

    def asset_url_allowed(self, url: str, tag: str, asset_name: str) -> bool:
        """True when the asset URL belongs to this repository's release."""
        parsed = urlparse(url)
        return (
            parsed.scheme == self._scheme
            and parsed.netloc in self._hosts
            and parsed.path.startswith(self._prefix + tag + "/")
            and os.path.basename(parsed.path) == asset_name
        )

    def redirect_url_allowed(self, url: str) -> bool:
        """True for HTTPS redirects to a supported GitHub download host."""
        parsed = urlparse(url)
        return parsed.scheme == self._scheme and parsed.netloc in self._hosts


@dataclass(frozen=True)
class PreparedUpdate:
    """A downloaded, checksum-verified, executable staging file."""

    release: ReleaseInfo
    staging: Path
    size: int
    sha256: str


@dataclass(frozen=True)
class UpdaterHooks:
    """Window-owned callbacks the coordinator may call during updates."""

    is_cycle_active: Callable[[], bool]
    set_run_block: Callable[[bool], None]
    save_preferences: Callable[[], None]
    request_close: Callable[[], None]


class _Phase(enum.Enum):
    """Which durable installation step the coordinator is running."""

    PREPARE = "prepare"
    SELFTEST = "selftest"
    COMMIT = "commit"
    LAUNCH = "launch"


class _PhaseSignals(QObject):
    """Cross-thread completion signals for one off-GUI-thread phase."""

    done = Signal(object)
    failed = Signal(str)


def _checksum_for(payload: bytes, asset_name: str) -> str | None:
    """The manifest hash for ``asset_name``; None when absent or ambiguous.

    The manifest is untrusted plain text: entries are ``<hex>  <name>``.
    Missing, duplicate, conflicting or malformed entries are rejected
    instead of guessed at.
    """
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        return None
    entries: list[str] = []
    for line in text.splitlines():
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        digest, remainder = parts
        name = remainder.strip().lstrip("*")
        if name == asset_name:
            entries.append(digest)
    if len(entries) != 1:
        return None
    digest = entries[0].lower()
    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        return None
    return digest


def _cleaned_restart_environment() -> QProcessEnvironment:
    """Child environment for the replacement launch (update plan §5, step 6).

    Inherited PyInstaller/AppImage loader variables are removed so the new
    instance binds to its own bundle, not the old one; everything else is
    preserved.
    """
    env = QProcessEnvironment.systemEnvironment()
    for name in _RESTART_ENV_STRIP:
        env.remove(name)
    return env


class UpdateService(QObject):
    """One network operation at a time; no widgets, no filesystem writes."""

    stateChanged = Signal(object)
    checkCompleted = Signal(object)
    checkFailed = Signal(str)
    downloadProgress = Signal(int, int)
    downloadPrepared = Signal(object)
    downloadFailed = Signal(str)
    cancelled = Signal()

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        config: ServiceConfig | None = None,
        policy: UrlPolicy | None = None,
        manager: QNetworkAccessManager | None = None,
        current: Version | None = None,
        arch: str | None = None,
    ) -> None:
        super().__init__(parent)
        self._config = config or ServiceConfig()
        self._policy = policy or UrlPolicy()
        self._manager = manager or QNetworkAccessManager(self)
        self._current: Version | None = current
        self._arch = arch
        self._reply: QNetworkReply | None = None
        self._token = 0
        self._role = ""
        self._state = UpdateState.Idle
        self._pages: list[list[Mapping[str, object]]] = []
        self._metadata = bytearray()
        self._release: ReleaseInfo | None = None
        self._staging_path: Path | None = None
        self._staging_fd: int | None = None
        self._hasher: "hashlib._Hash | None" = None
        self._expected_size = 0
        self._received = 0
        self._last_progress = 0
        self._redirects_left = 0
        self._watchdog = QTimer(self)
        self._watchdog.setSingleShot(True)
        self._watchdog.timeout.connect(self._on_timeout)

    # --- queries ---

    def is_busy(self) -> bool:
        return self._reply is not None

    @property
    def received(self) -> int:
        """Bytes received so far in the current download."""
        return self._received

    @property
    def total(self) -> int:
        """Bytes expected for the current download (0 when not downloading)."""
        return self._expected_size

    # --- operations ---

    def check_now(self) -> bool:
        """Start one paginated release check; False when already busy."""
        if self._reply is not None:
            return False
        self._pages = []
        self._metadata.clear()
        self._token += 1
        self._set_state(UpdateState.Checking)
        self._request_page(1)
        return True

    def download(self, release: ReleaseInfo, target: Path) -> bool:
        """Stream a release into an owned staging file beside the target AppImage."""
        if self._reply is not None:
            return False
        if release.appimage is None or release.checksums is None:
            self._set_state(UpdateState.Idle)
            self.downloadFailed.emit(_STABLE_URL_MESSAGE)
            return False
        if not self._policy.asset_url_allowed(
            release.appimage.url, release.tag, release.appimage_name
        ) or not self._policy.asset_url_allowed(
            release.checksums.url, release.tag, release.checksums.name
        ):
            self._set_state(UpdateState.Idle)
            self.downloadFailed.emit(_STABLE_URL_MESSAGE)
            return False
        self._release = release
        self._token += 1
        self._expected_size = release.appimage.size
        self._received = 0
        self._last_progress = 0
        self._hasher = hashlib.sha256()
        try:
            fd, raw = tempfile.mkstemp(
                prefix=update_install.prefixed(
                    target, update_install.STAGING_MARK
                ),
                dir=target.parent,
            )
        except OSError as exc:
            self._set_state(UpdateState.Idle)
            self.downloadFailed.emit(f"could not create the staging file: {exc}")
            return False
        self._staging_fd = fd
        self._staging_path = Path(raw)
        self._set_state(UpdateState.Downloading)
        self._watchdog.start(self._config.download_timeout_ms)
        self._role = "asset"
        self._start(release.appimage.url)
        return True

    def cancel(self) -> bool:
        """Stop the current operation and clean up; True when one was running."""
        if self._reply is None:
            return False
        self._token += 1
        self._watchdog.stop()
        self._finish_reply()
        self._discard_staging()
        self._set_state(UpdateState.Idle)
        self.cancelled.emit()
        return True

    # --- internals ---

    def _set_state(self, state: UpdateState) -> None:
        if state is self._state:
            return
        self._state = state
        self.stateChanged.emit(state)

    def _request_page(self, number: int) -> None:
        self._role = "check"
        url = (
            f"{self._config.releases_url}"
            f"?per_page={self._config.page_size}&page={number}"
        )
        self._start(url)

    def _start(self, url: str, *, redirect: bool = False) -> None:
        if not redirect:
            self._metadata.clear()
            self._redirects_left = self._config.max_redirects
        request = QNetworkRequest(QUrl(url))
        request.setTransferTimeout(self._config.request_timeout_ms)
        request.setAttribute(
            QNetworkRequest.Attribute.RedirectPolicyAttribute,
            QNetworkRequest.RedirectPolicy.ManualRedirectPolicy,
        )
        request.setHeader(QNetworkRequest.KnownHeaders.UserAgentHeader, "strom-update")
        reply = self._manager.get(request)
        self._reply = reply
        token = self._token
        reply.finished.connect(lambda: self._on_finished(token, reply))
        reply.readyRead.connect(lambda: self._on_ready_read(token, reply))

    def _current_reply(self, token: int, reply: QNetworkReply) -> QNetworkReply | None:
        if token != self._token or self._reply is not reply:
            return None  # stale callback from a cancelled/superseded operation
        return reply

    def _on_ready_read(self, token: int, reply: QNetworkReply) -> None:
        if self._current_reply(token, reply) is None:
            return
        data = bytes(reply.readAll().data())
        if not data:
            return
        if self._role in ("check", "sums"):
            self._metadata.extend(data)
            if len(self._metadata) > self._config.metadata_max_bytes:
                self._fail("the release metadata is too large to read")
            return
        # asset: stream to the staging file, hashing incrementally, and
        # enforce the release-recorded and documented size bounds.
        assert self._hasher is not None and self._staging_fd is not None
        self._received += len(data)
        if self._expected_size and self._received > self._expected_size:
            self._fail("the downloaded AppImage is larger than the release records")
            return
        if self._received > self._config.max_download_bytes:
            self._fail("the downloaded AppImage exceeds the documented size limit")
            return
        self._hasher.update(data)
        try:
            os.write(self._staging_fd, data)
        except OSError as exc:
            self._fail(f"could not write the staging file: {exc}")
            return
        if (
            self._received == self._expected_size
            or self._received - self._last_progress >= PROGRESS_STEP_BYTES
        ):
            self._last_progress = self._received
            self.downloadProgress.emit(self._received, self._expected_size)

    def _on_finished(self, token: int, reply: QNetworkReply) -> None:
        if self._current_reply(token, reply) is None:
            return
        assert reply is not None
        # Disconnect before deferring deletion: a queued deferred-delete
        # event must never reference an object whose signals still fire.
        for signal in (reply.finished, reply.readyRead):
            try:
                signal.disconnect()
            except RuntimeError:
                pass
        self._reply = None
        redirect = reply.attribute(QNetworkRequest.Attribute.RedirectionTargetAttribute)
        if isinstance(redirect, QUrl):
            self._follow_redirect(reply, redirect)
            return
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        if reply.error() != QNetworkReply.NetworkError.NoError:
            self._fail(self._describe_error(reply, status))
            return
        if not isinstance(status, int) or status != 200:
            self._fail(self._describe_error(reply, status))
            return
        if self._role == "check":
            self._finish_check(bytes(self._metadata))
        elif self._role == "asset":
            self._finish_asset()
        elif self._role == "sums":
            self._finish_sums(bytes(self._metadata))

    def _follow_redirect(self, reply: QNetworkReply, target: QUrl) -> None:
        resolved = reply.url().resolved(target).toString()
        if self._redirects_left <= 0 or not self._policy.redirect_url_allowed(resolved):
            self._fail("the release server redirected outside the supported hosts")
            return
        self._redirects_left -= 1
        self._start(resolved, redirect=True)

    @staticmethod
    def _describe_error(reply: QNetworkReply, status: object) -> str:
        if reply.error() == QNetworkReply.NetworkError.OperationCanceledError:
            return "the update operation was cancelled"
        if reply.error() == QNetworkReply.NetworkError.TimeoutError:
            return "the update operation timed out"
        if status == 403:
            return "GitHub's rate limit for update checks was reached; try later"
        if status == 404:
            return "the release list could not be found on GitHub"
        text = reply.errorString() or "the update operation failed"
        if isinstance(status, int):
            text = f"{text} (HTTP {status})"
        return text

    def _finish_check(self, payload: bytes) -> None:
        try:
            parsed = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            self._fail("GitHub returned a release list that could not be read")
            return
        if not isinstance(parsed, list):
            self._fail("GitHub returned an unexpected release-list format")
            return
        self._pages.append(parsed)
        complete = len(parsed) < self._config.page_size
        capped = len(self._pages) >= self._config.max_pages
        if complete or capped:
            if self._current is None:
                self._fail("the installed version could not be read")
                return
            selection = release_selection.select_update(
                self._pages, self._current, self._arch
            )
            self._set_state(UpdateState.Idle)
            self.checkCompleted.emit(selection)
        else:
            self._token += 1
            self._request_page(len(self._pages) + 1)

    def _finish_asset(self) -> None:
        assert self._staging_fd is not None and self._hasher is not None
        os.close(self._staging_fd)
        self._staging_fd = None
        if self._expected_size and self._received != self._expected_size:
            self._fail("the download is incomplete (truncated response)")
            return
        # The checksum manifest is fetched next; only after comparing the
        # checksum and byte count does the staging file become executable.
        release = self._release
        if release is None or release.checksums is None:
            self._fail("the release metadata no longer contains this AppImage")
            return
        self._token += 1
        self._set_state(UpdateState.Verifying)
        self._role = "sums"
        self._start(release.checksums.url)

    def _finish_sums(self, payload: bytes) -> None:
        assert self._release is not None and self._staging_path is not None
        expected = _checksum_for(payload, self._release.appimage_name)
        if expected is None:
            self._fail("the checksum manifest does not describe this AppImage")
            return
        assert self._hasher is not None
        actual = self._hasher.hexdigest()
        if actual != expected:
            self._fail("the downloaded AppImage does not match its checksum")
            return
        staging = self._staging_path
        try:
            os.chmod(staging, 0o755)
        except OSError as exc:
            self._fail(f"could not prepare the downloaded update: {exc}")
            return
        self._staging_path = None
        self._hasher = None
        prepared = PreparedUpdate(
            release=self._release,
            staging=staging,
            size=self._expected_size,
            sha256=actual,
        )
        self._set_state(UpdateState.Idle)
        self.downloadPrepared.emit(prepared)

    def _on_timeout(self) -> None:
        self._fail("the operation timed out")

    def _finish_reply(self) -> None:
        """Abort and release the current reply; reset per-operation buffers."""
        reply, self._reply = self._reply, None
        if reply is not None:
            for signal in (reply.finished, reply.readyRead):
                try:
                    signal.disconnect()
                except RuntimeError:
                    pass
            try:
                reply.abort()
            except RuntimeError:
                pass
            reply.deleteLater()
        if self._staging_fd is not None:
            try:
                os.close(self._staging_fd)
            except OSError:
                pass
            self._staging_fd = None
        self._role = ""
        self._metadata.clear()
        self._pages = []

    def _fail(self, message: str) -> None:
        checking = self._role == "check"
        self._token += 1
        self._watchdog.stop()
        self._finish_reply()
        self._discard_staging()
        self._set_state(UpdateState.Idle)
        if checking:
            self.checkFailed.emit(message)
        else:
            self.downloadFailed.emit(message)

    def _discard_staging(self) -> None:
        """Remove the staging file of a failed or cancelled download."""
        if self._staging_path is None:
            return
        try:
            self._staging_path.unlink()
        except FileNotFoundError:
            pass
        self._staging_path = None
        self._hasher = None


class AckServer(QObject):
    """Private local IPC endpoint for the restart handshake (§5, step 7).

    One server per update attempt with a per-attempt token; the candidate
    must report its own pid and that heating is still disabled. Process
    creation alone is never treated as a successful start.
    """

    acked = Signal(int)  # candidate pid

    def __init__(self, parent: QObject, name: str, token: str) -> None:
        super().__init__(parent)
        self._token = token
        self._buffers: dict[QLocalSocket, bytearray] = {}
        self._server = QLocalServer(self)
        QLocalServer.removeServer(name)  # stale sockets from crashed attempts
        if not self._server.listen(name):
            raise update_install.TransactionError(
                f"could not open the restart handshake: {self._server.errorString()}"
            )
        self._server.newConnection.connect(self._accept)

    def close(self) -> None:
        self._server.close()

    def _accept(self) -> None:
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            if socket is None:
                return
            socket.readyRead.connect(lambda s=socket: self._read(s))
            if socket.bytesAvailable():
                self._read(socket)

    def _read(self, socket: QLocalSocket) -> None:
        """Accumulate a stream payload; a split write is not an error.

        Local sockets are byte streams: a payload may arrive in pieces, and
        a second callback may fire after a successful ack. Both are handled
        by buffering per socket and stopping once the payload is consumed;
        the handshake timeout decides failure for anything malformed.
        """
        buffer = self._buffers.setdefault(socket, bytearray())
        buffer.extend(socket.readAll().data())
        if not buffer:
            return
        try:
            payload = json.loads(bytes(buffer).decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return  # partial (or malformed) until the timeout
        self._buffers.pop(socket, None)
        pid = payload.get("pid") if isinstance(payload, dict) else None
        if (
            isinstance(payload, dict)
            and payload.get("token") == self._token
            and payload.get("heating_disabled") is True
            and isinstance(pid, int)
            and pid > 0
        ):
            socket.disconnectFromServer()
            self.acked.emit(int(pid))
        else:
            socket.abort()


class UpdateCoordinator(QObject):
    """Owns the update lifecycle states and the cycle/update interlock (§4).

    Checking may run during a heating cycle. The **Update and restart**
    action refuses while ``is_cycle_active()`` is true — the guard lives in
    this action handler and is repeated immediately before the replacement
    is committed, regardless of any widget's enabled state. Accepting an
    installation blocks new heating runs until the update fails or the
    restart happens, and closing during the short installation
    transaction is refused.

    The heating child is never killed, detached or waited on
    synchronously; that remains the cycle runner's exclusive business. The
    replacement is launched detached and proven by the ack handshake: it
    reports its own pid and that heating is still disabled before this
    window releases the lifecycle lock, and a handshake that never lands
    rolls back to the previous version.
    """

    stateChanged = Signal(object)
    messageChanged = Signal(str)
    downloadProgress = Signal(int, int)
    updateNotice = Signal(object)
    installFinished = Signal(bool, str)

    def __init__(
        self,
        parent: QObject,
        service: UpdateService,
        *,
        hooks: UpdaterHooks,
        status: InstallStatus,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._hooks = hooks
        self._status = status
        self._target: AppImageIdentity | None = status.identity
        self._lock: update_install.FileLock | None = None
        if status.can_install and self._target is not None:
            self._lock = update_install.FileLock(
                update_install.update_lock_path(self._target.path)
            )
        self._state = UpdateState.Idle
        self._message = ""
        self._message_template = ""
        self._message_context: dict[str, str] = {}
        self._message_note: str | None = None
        self._selection: Selection | None = None
        self._prepared: PreparedUpdate | None = None
        self._transaction: update_install.Transaction | None = None
        self._phase: _Phase | None = None
        self._settled = False
        self._manual_check = False
        self._phase_failed_restore = True
        self._restore_after_stop: tuple[bool, str] | None = None
        self._acked = False
        self._ack_token = ""
        self._ack_server: AckServer | None = None
        self._child: QProcess | None = None
        self._candidate_socket: QLocalSocket | None = None
        self._selftest_tail = ""
        self._extract_mode = os.environ.get(EXTRACT_AND_RUN_ENV) == "1"
        self._updates_refused: str | None = None
        self._phase_signals = _PhaseSignals(self)
        self._phase_signals.done.connect(self._on_phase_done)
        self._phase_signals.failed.connect(self._on_phase_failed)
        self._ack_timer = QTimer(self)
        self._ack_timer.setSingleShot(True)
        self._ack_timer.timeout.connect(self._on_ack_timeout)
        self._selftest_timer = QTimer(self)
        self._selftest_timer.setSingleShot(True)
        self._selftest_timer.timeout.connect(self._on_selftest_timeout)
        self._retry_timer = QTimer(self)
        self._retry_timer.setSingleShot(True)
        self._retry_timer.timeout.connect(self._retry_candidate_recovery)
        service.checkCompleted.connect(self._on_check_completed)
        service.checkFailed.connect(self._on_check_failed)
        service.downloadPrepared.connect(self._on_prepared)
        service.downloadFailed.connect(self._on_download_failed)
        service.cancelled.connect(self._on_cancelled)
        service.downloadProgress.connect(self.downloadProgress)

    @property
    def state(self) -> UpdateState:
        return self._state

    @property
    def message(self) -> str:
        return self._message

    @property
    def status(self) -> InstallStatus:
        return self._status

    @property
    def selection(self) -> Selection | None:
        return self._selection

    def run_blocked(self) -> bool:
        """True while an accepted update forbids starting heating runs."""
        return self._phase is not None or self._state in (
            UpdateState.Installing,
            UpdateState.Restarting,
        )

    def is_cycle_active(self) -> bool:
        """True while a heating cycle is starting or running."""
        return self._hooks.is_cycle_active()

    def swap_service(self, service: UpdateService) -> None:
        """Point the coordinator at another service (used by tests)."""
        old, self._service = self._service, service
        for signal, handler in (
            (old.checkCompleted, self._on_check_completed),
            (old.checkFailed, self._on_check_failed),
            (old.downloadPrepared, self._on_prepared),
            (old.downloadFailed, self._on_download_failed),
            (old.cancelled, self._on_cancelled),
            (old.downloadProgress, self.downloadProgress),
        ):
            try:
                signal.disconnect(handler)
            except (RuntimeError, TypeError):
                pass
        service.checkCompleted.connect(self._on_check_completed)
        service.checkFailed.connect(self._on_check_failed)
        service.downloadPrepared.connect(self._on_prepared)
        service.downloadFailed.connect(self._on_download_failed)
        service.cancelled.connect(self._on_cancelled)
        service.downloadProgress.connect(self.downloadProgress)

    def download_received(self) -> int:
        """Bytes received so far in the current download."""
        return self._service.received

    def download_total(self) -> int:
        """Total bytes expected for the current download."""
        return self._service.total
    # --- startup, checks, and the install action ---

    def recover_startup(self) -> None:
        """Recover an interrupted transaction. Safe to call on every start."""
        self._recover_startup()

    def run_startup_checks(self, delay_ms: int = 2500) -> None:
        """Recover an interrupted transaction, then check once, silently."""
        self._recover_startup()
        QTimer.singleShot(max(delay_ms, 0), lambda: self.check(manual=False))

    def check(self, manual: bool) -> bool:
        """Run one release check; manual failures are explained in ``message``."""
        if self._phase is not None or self._state in (
            UpdateState.Downloading,
            UpdateState.Verifying,
            UpdateState.Installing,
            UpdateState.Restarting,
        ):
            if manual:
                self._set_message("An update is already running.")
            return False
        if self._service.is_busy():
            if manual:
                self._set_message("An update check is already running.")
            return False
        self._manual_check = manual
        if not self._service.check_now():
            return False
        self._set_state(UpdateState.Checking)
        self._set_message("Checking for updates…")
        return True

    def accept_install(self, release: ReleaseInfo) -> bool:
        """The explicit user consent: download, verify, install, restart."""
        if self._phase is not None or self._state in (
            UpdateState.Downloading,
            UpdateState.Verifying,
            UpdateState.Installing,
            UpdateState.Restarting,
        ):
            self._set_message("An update is already running.")
            return False
        if self._updates_refused is not None:
            self._set_message(self._updates_refused)
            return False
        if not self._status.can_install or self._target is None:
            self._set_message(self._status.reason or _STABLE_URL_MESSAGE)
            return False
        if self._hooks.is_cycle_active():
            self._set_message(
                "Installation is unavailable while a cycle runs; try again "
                "after it finishes."
            )
            return False
        self._hooks.set_run_block(True)
        if self._prepared is not None and self._prepared.release == release:
            self._begin_install()
            return True
        self._set_state(UpdateState.Downloading)
        self._set_message("Downloading the update…")
        if not self._service.download(release, self._target.path):
            # downloadFailed already ran the failure path synchronously.
            return False
        return True

    def request_close(self) -> str | None:
        """Close-refusal reason from the update side, or None when safe.

        Closing during a download cancels it and removes the staging file;
        during the short installation transaction it is refused.
        """
        if self._state is UpdateState.Installing:
            return (
                "An update is being installed; the window must stay open "
                "until it finishes."
            )
        if self._state is UpdateState.Downloading:
            self._service.cancel()
        return None

    def begin_candidate_handshake(self, ack_name: str, ack_token: str) -> None:
        """New-instance side: keep heating disabled until the handoff lands."""
        self._ack_token = ack_token
        self._acked = False
        self._hooks.set_run_block(True)
        socket = QLocalSocket(self)
        self._candidate_socket = socket
        socket.connected.connect(lambda: self._send_candidate_ack(socket))
        socket.errorOccurred.connect(lambda _error: self._retry_candidate_recovery())
        socket.connectToServer(ack_name)
        QTimer.singleShot(ACK_TIMEOUT_MS, self._candidate_watchdog)

    # --- internal state helpers ---

    def _set_state(self, state: UpdateState) -> None:
        if state is self._state:
            return
        self._state = state
        self.stateChanged.emit(state)

    def _set_message(
        self,
        template: str,
        *,
        note: str | None = None,
        **context: str,
    ) -> None:
        self._message_template = template
        self._message_context = context
        self._message_note = note
        message = template.format(**context) if context else template
        if note:
            message = f"{message}\n{note}"
        self._message = message
        self.messageChanged.emit(message)

    def translated_message(self, translate: Callable[[str], str]) -> str:
        """Translate the current message template, then interpolate values.

        Interpolating before translation would make the template
        unreachable; the dialog uses this to show the user's language.
        """
        text = translate(self._message_template)
        if self._message_context:
            text = text.format(**self._message_context)
        if self._message_note:
            text = f"{text}\n{translate(self._message_note)}"
        return text

    def _running_child(self) -> QProcess | None:
        child = self._child
        if child is not None and child.state() != QProcess.ProcessState.NotRunning:
            return child
        return None

    def _recover_startup(self) -> None:
        target, lock = self._target, self._lock
        if target is None or lock is None:
            return
        try:
            held = lock.acquire(exclusive=True)
        except update_install.TransactionError as exc:
            self._updates_refused = str(exc)
            self._set_message(str(exc))
            return
        if not held:
            # Another window owns the transaction and its recovery.
            return
        try:
            update_install.recover(target)
        except update_install.TransactionError as exc:
            self._updates_refused = str(exc)
            self._set_message(str(exc))
            return
        finally:
            lock.release()

    def _on_check_completed(self, selection: Selection) -> None:
        self._selection = selection
        if selection.candidate is not None:
            self._set_state(UpdateState.Available)
            template, context = self._available_message(selection)
            self._set_message(template, note=selection.note, **context)
            if not self._manual_check:
                self.updateNotice.emit(selection)
            return
        self._set_state(UpdateState.Idle)
        self._set_message(
            selection.note or "You are already on the newest available Strom version."
        )

    def _on_check_failed(self, message: str) -> None:
        self._set_state(UpdateState.Failed)
        self._set_message("Checking for updates failed: {reason}", reason=message)

    def _on_prepared(self, prepared: PreparedUpdate) -> None:
        self._prepared = prepared
        if self._state is UpdateState.Downloading:
            self._begin_install()

    def _on_download_failed(self, message: str) -> None:
        self._settle_failed(restore=False, detail=f"download failed: {message}")

    def _on_cancelled(self) -> None:
        if self._state in (UpdateState.Downloading, UpdateState.Verifying):
            self._set_state(UpdateState.Idle)
            self._hooks.set_run_block(False)
            self._set_message("Update download cancelled.")

    def _available_message(self, selection: Selection) -> tuple[str, dict[str, str]]:
        assert selection.candidate is not None
        template = "Strom {available} is available; you are running {current}."
        return template, {
            "available": str(selection.candidate.version),
            "current": str(self._status.version),
        }

    # --- installation transaction (§5) ---

    def _begin_install(self) -> None:
        prepared, target, lock = self._prepared, self._target, self._lock
        if prepared is None or target is None or lock is None:
            return
        if self._hooks.is_cycle_active():
            self._settle_failed(
                restore=False,
                detail="a heating cycle is running; the update was not installed",
            )
            return
        try:
            held = lock.acquire(exclusive=True)
        except update_install.TransactionError as exc:
            self._settle_failed(restore=False, detail=str(exc))
            return
        if not held:
            self._settle_failed(
                restore=False,
                detail=(
                    "another Strom window is running an update or a cycle; "
                    "close it and try again"
                ),
            )
            return
        self._settled = False
        self._acked = False
        self._restore_after_stop = None
        self._transaction = None
        self._phase = _Phase.PREPARE
        self._phase_failed_restore = False
        self._set_state(UpdateState.Installing)
        self._set_message("Preparing the update…")

        def prepare() -> update_install.Transaction:
            return update_install.prepare_transaction(
                target, prepared.release, prepared.staging, prepared.size,
                prepared.sha256,
            )

        self._run_phase(prepare)

    def _run_phase(self, fn: Callable[[], object]) -> None:
        signals = self._phase_signals

        def run() -> None:
            try:
                result = fn()
            except Exception as exc:  # noqa: BLE001 - surfaced to the user
                signals.failed.emit(f"{exc}")
            else:
                signals.done.emit(result)

        threading.Thread(target=run, daemon=True).start()

    def _on_phase_done(self, result: object) -> None:
        if self._phase is _Phase.PREPARE:
            if not isinstance(result, update_install.Transaction):
                self._settle_failed(restore=False, detail="nothing prepared")
                return
            self._transaction = result
            self._phase = _Phase.SELFTEST
            self._run_selftest()
        elif self._phase is _Phase.COMMIT:
            self._launch_candidate()

    def _on_phase_failed(self, message: str) -> None:
        self._settle_failed(restore=self._phase_failed_restore, detail=message)

    def _run_selftest(self) -> None:
        transaction = self._transaction
        prepared = self._prepared
        if not isinstance(transaction, update_install.Transaction) or prepared is None:
            self._settle_failed(restore=False, detail="nothing to verify")
            return
        self._set_message("Verifying the downloaded update (offline self-test)…")
        self._selftest_timer.start(SELF_TEST_TIMEOUT_MS)
        self._selftest_tail = ""
        self._start_child(
            program=str(prepared.staging), arguments=self._selftest_arguments()
        )

    def _selftest_arguments(self) -> list[str]:
        arguments: list[str] = []
        if self._extract_mode:
            arguments.append(EXTRACT_AND_RUN_SWITCH)
        arguments.append(FROZEN_SELF_TEST_SWITCH)
        return arguments

    def _launch_candidate(self) -> None:
        target = self._target
        if target is None or self._prepared is None:
            self._settle_failed(restore=False, detail="nothing to start")
            return
        self._phase = _Phase.LAUNCH
        name = (
            f"{tempfile.gettempdir()}/strom-update-ack-"
            f"{os.getpid()}-{uuid.uuid4().hex}"
        )
        self._ack_token = uuid.uuid4().hex
        try:
            server = AckServer(self, name, self._ack_token)
        except update_install.TransactionError as exc:
            self._settle_failed(restore=True, detail=str(exc))
            return
        self._ack_server = server
        server.acked.connect(self._on_candidate_ack)
        arguments: list[str] = []
        if self._extract_mode:
            arguments.append(EXTRACT_AND_RUN_SWITCH)
        environment = _cleaned_restart_environment()
        environment.insert(ACK_ENV, f"{name}:{self._ack_token}")
        environment.insert(SAFE_LAUNCH_ENV, "1")
        self._ack_timer.start(ACK_TIMEOUT_MS)
        self._set_message("Starting the updated Strom…")
        if not self._start_detached(
            program=str(target.path), arguments=arguments, environment=environment
        ):
            self._settle_failed(
                restore=True,
                detail="the updated Strom could not be started",
            )

    @staticmethod
    def _start_detached(
        program: str,
        arguments: list[str],
        environment: QProcessEnvironment,
    ) -> bool:
        """Start the replacement outside this process tree.

        A tracked QProcess kills its still-running child when it is
        destroyed (Qt's destructor), which is exactly what must not
        happen here: this window is about to close while the replacement
        keeps running. ``startDetached`` is Qt's supported way to do that,
        and the ack handshake still proves the candidate came up.
        """
        process = QProcess()
        process.setProgram(program)
        process.setArguments(arguments)
        process.setProcessEnvironment(environment)
        return bool(process.startDetached())

    def _start_child(
        self,
        program: str,
        arguments: list[str],
        environment: QProcessEnvironment | None = None,
    ) -> None:
        process = QProcess(self)
        process.setProgram(program)
        process.setArguments(arguments)
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        if environment is not None:
            process.setProcessEnvironment(environment)
        process.finished.connect(self._on_child_finished)
        process.errorOccurred.connect(
            lambda _error: None  # finished decides the terminal path
        )
        process.readyReadStandardOutput.connect(
            lambda: self._consume_child_output(process)
        )
        self._child = process
        process.start()

    def _consume_child_output(self, process: QProcess) -> None:
        text = bytes(process.readAllStandardOutput().data()).decode("utf-8", "replace")
        self._selftest_tail = (self._selftest_tail + text)[
            -_SELF_TEST_TAIL_CHARS:
        ]

    def _on_child_finished(self, exit_code: int, status: object) -> None:
        del status
        pending, self._restore_after_stop = self._restore_after_stop, None
        if pending is not None:
            self._finish_failed(pending[0], pending[1])
            return
        if self._phase is _Phase.SELFTEST:
            self._on_selftest_finished(exit_code)

    def _on_selftest_finished(self, exit_code: int) -> None:
        if exit_code != 0:
            self._settle_failed(
                restore=False,
                detail=(
                    "the downloaded update failed its offline self-test; "
                    f"your current Strom is unchanged.\n{self._selftest_tail.strip()}"
                ),
            )
            return
        transaction = self._transaction
        prepared = self._prepared
        if not isinstance(transaction, update_install.Transaction) or prepared is None:
            self._settle_failed(restore=False, detail="nothing verified")
            return
        self._selftest_timer.stop()
        self._phase = _Phase.COMMIT
        self._phase_failed_restore = True
        self._set_message("Replacing the AppImage…")
        self._run_phase(
            lambda: update_install.commit_replacement(
                transaction.target, prepared.staging, transaction.backup
            )
        )

    def _on_selftest_timeout(self) -> None:
        self._settle_failed(
            restore=False, detail="the offline self-test took too long"
        )

    def _on_ack_timeout(self) -> None:
        if self._acked:
            return
        self._settle_failed(
            restore=True,
            detail="the updated Strom did not report a successful start in time.",
        )

    def _on_candidate_ack(self, pid: int) -> None:
        del pid
        if self._acked or self._settled:
            return
        self._acked = True
        self._settled = True
        self._phase = None
        self._ack_timer.stop()
        transaction = self._transaction
        if isinstance(transaction, update_install.Transaction):
            try:
                update_install.mark_acknowledged(
                    transaction.target, transaction.backup
                )
            except update_install.TransactionError as exc:
                # The new version is in place and running; the journal
                # bookkeeping failed, so further updates are refused.
                self._updates_refused = str(exc)
        server, self._ack_server = self._ack_server, None
        if server is not None:
            server.close()
        child, self._child = self._child, None
        if child is not None:
            child.deleteLater()
        lock, self._lock = self._lock, None
        if lock is not None:
            try:
                lock.release()
            except update_install.TransactionError:
                pass
        self._hooks.save_preferences()
        self._set_state(UpdateState.Restarting)
        self._set_message(
            "The updated Strom is running; this window can now be closed."
        )
        self.installFinished.emit(True, self._message)
        self._hooks.request_close()

    # --- candidate-side handoff completion (§5, step 7) ---

    def _send_candidate_ack(self, socket: QLocalSocket) -> None:
        payload = json.dumps(
            {
                "token": self._ack_token,
                "pid": os.getpid(),
                "heating_disabled": True,
            }
        )
        socket.write(payload.encode("utf-8"))
        socket.flush()
        self._retry_candidate_recovery()
        self._handoff_from_old_launcher()

    def _handoff_from_old_launcher(self) -> None:
        """Relaunch detached when an older launcher will kill this process.

        Launchers through 0.3.2 tracked the candidate with a QProcess and
        destroyed it right after the ack; Qt's destructor then kills the
        still-running child, so the user sees the old window close and no
        new one. A launcher that starts candidates detached marks the
        environment; without that mark, start an independent copy and let
        the old launcher's kill land on this process instead. The detached
        copy reads the same configuration and needs no handshake because
        the ack has already been delivered.
        """
        if SAFE_LAUNCH_ENV in os.environ or _HANDOFF_ENV in os.environ:
            return
        if not self._relaunch_detached():
            return
        QTimer.singleShot(_HANDOFF_GRACE_MS, lambda: os._exit(0))

    @staticmethod
    def _relaunch_detached() -> bool:
        """Start an independent copy of the running AppImage; False on failure."""
        image = os.environ.get("APPIMAGE")
        if not image or not Path(image).is_file():
            return False
        arguments = [image]
        if (
            os.environ.get(EXTRACT_AND_RUN_ENV) == "1"
            or EXTRACT_AND_RUN_SWITCH in sys.argv
        ):
            arguments.append(EXTRACT_AND_RUN_SWITCH)
        environment = {
            name: value
            for name, value in os.environ.items()
            if name not in _RESTART_ENV_STRIP and name != ACK_ENV
        }
        environment[_HANDOFF_ENV] = "1"
        try:
            subprocess.Popen(
                arguments,
                env=environment,
                start_new_session=True,
                close_fds=True,
            )
        except OSError:
            return False
        return True

    def _candidate_watchdog(self) -> None:
        if not self._acked:
            self._retry_candidate_recovery()

    def _retry_candidate_recovery(self) -> None:
        """Take over an interrupted transaction, then enable heating."""
        lock = self._lock
        if lock is None:
            self._finish_candidate_recovery()
            return
        if lock.is_held():
            self._finish_candidate_recovery()
            return
        try:
            if lock.acquire(exclusive=True):
                self._finish_candidate_recovery()
                return
        except update_install.TransactionError as exc:
            self._updates_refused = str(exc)
            self._set_message(str(exc))
            return
        self._retry_timer.start(_CANDIDATE_RETRY_MS)

    def _finish_candidate_recovery(self) -> None:
        target, lock = self._target, self._lock
        try:
            if target is not None:
                update_install.recover(target)
        except update_install.TransactionError as exc:
            self._updates_refused = str(exc)
            self._set_message(str(exc))
        finally:
            if lock is not None and lock.is_held():
                try:
                    lock.release()
                except update_install.TransactionError:
                    pass
        self._retry_timer.stop()
        self._hooks.set_run_block(False)
        version = self._status.version
        if version is None:
            self._set_message("Strom was updated.")
        else:
            self._set_message("Strom was updated to {version}.", version=str(version))

    # --- failure settlement (§5, step 8) ---

    def _settle_failed(self, restore: bool, detail: str) -> None:
        if self._settled:
            return
        self._settled = True
        self._ack_timer.stop()
        self._selftest_timer.stop()
        running = self._running_child()
        if running is not None:
            # The only process ever stopped here is the offline self-test.
            # The replacement itself is launched detached and is proven by
            # the ack handshake instead.
            self._restore_after_stop = (restore, detail)
            running.terminate()
            QTimer.singleShot(_TERMINATE_GRACE_MS, self._kill_running_child)
            return
        self._finish_failed(restore, detail)

    def _kill_running_child(self) -> None:
        running = self._running_child()
        if running is not None:
            running.kill()

    def _finish_failed(self, restore: bool, detail: str) -> None:
        self._settled = True
        self._phase = None
        self._ack_timer.stop()
        self._selftest_timer.stop()
        self._retry_timer.stop()
        server, self._ack_server = self._ack_server, None
        if server is not None:
            server.close()
        lock, self._lock = self._lock, None
        if lock is not None:
            try:
                lock.release()
            except update_install.TransactionError:
                pass
        self._hooks.set_run_block(False)
        self._set_state(UpdateState.Failed)
        template, context = self._compose_failure_message(restore, detail)
        self._set_message(template, **context)
        self.installFinished.emit(False, self._message)

    def _compose_failure_message(
        self, restore: bool, detail: str
    ) -> tuple[str, dict[str, str]]:
        target, transaction = self._target, self._transaction
        if restore and target is not None and isinstance(
            transaction, update_install.Transaction
        ):
            try:
                update_install.restore_previous(target, transaction.backup)
                update_install.clear_journal(target)
            except update_install.TransactionError as exc:
                self._updates_refused = str(exc)
                return (
                    "The update could not be restored automatically; your "
                    "previous version is preserved at: {backup}\n"
                    "{detail}\n{error}",
                    {
                        "backup": str(transaction.backup),
                        "detail": detail,
                        "error": str(exc),
                    },
                )
            return (
                "The updated Strom could not be started; your previous "
                "version was restored. {detail}",
                {"detail": detail},
            )
        prepared = self._prepared
        if prepared is not None:
            try:
                update_install.discard_transaction(target, prepared.staging, None)
            except update_install.TransactionError:
                pass
            self._prepared = None
        return ("The update was not installed. {detail}", {"detail": detail})
