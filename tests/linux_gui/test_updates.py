"""Update-plan §1–§3 tests: install identity, release selection, network.

No test contacts GitHub, a real release, or any credential: the network
service is injected with a local fake HTTP server and an URL policy that
accepts it, and the selection functions are exercised with fixtures.
"""

import hashlib
import json
import os
import stat
from pathlib import Path

import pytest

pytest.importorskip("PySide6", reason="PySide6 is not installed (GUI extras missing)")
pytest.importorskip("pytestqt", reason="pytest-qt is not installed (gui-dev extra missing)")

from packaging.version import Version  # noqa: E402
from PySide6.QtCore import QCoreApplication  # noqa: E402

from strom.linux_gui import app_identity  # noqa: E402
from strom.linux_gui import update_install  # noqa: E402
from strom.linux_gui import updates  # noqa: E402
from strom.linux_gui.update_service import (  # noqa: E402
    PreparedUpdate,
    UpdateState,
    ServiceConfig,
    UpdateService,
    UrlPolicy,
    _checksum_for,
)


# --- §1: version and installation identity ---


def test_runtime_version_reads_package_metadata():
    version = app_identity.runtime_version()
    assert version is not None
    assert app_identity.runtime_version() == version


def test_runtime_version_missing_package_is_none(monkeypatch):
    def missing(name):
        raise app_identity.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(app_identity.metadata, "version", missing)
    assert app_identity.runtime_version() is None


def test_runtime_version_invalid_metadata_is_none(monkeypatch):
    monkeypatch.setattr(app_identity.metadata, "version", lambda name: "not-a-version")
    assert app_identity.runtime_version() is None


def _fake_appimage(tmp_path: Path, machine: str = "x86_64") -> Path:
    codes = {"x86_64": 62, "aarch64": 183}
    path = tmp_path / "Strom-0.3.0-x86_64.AppImage"
    # e_ident is 16 bytes (magic + class + data + version + osabi +
    # abiversion + 7 padding); then e_type (2) at 16 and e_machine (2) at 18.
    header = (
        b"\x7fELF"
        + bytes([2, 1, 1])
        + b"\x00" * 9
        + b"\x00\x00"
        + codes.get(machine, 62).to_bytes(2, "little")
    )
    path.write_bytes(header + b"\x00" * 64)
    return path


def test_install_status_source_install_is_check_only():
    status = app_identity.install_status(frozen=False)
    assert status.can_install is False
    assert "Python source" in status.reason
    assert status.identity is None


def test_install_status_extracted_appdir_is_check_only():
    status = app_identity.install_status(frozen=True, environ={}, version=Version("1.0"))
    assert status.can_install is False
    assert status.version == Version("1.0")


def test_install_status_appimage_is_installable(tmp_path, monkeypatch):
    path = _fake_appimage(tmp_path)
    monkeypatch.setenv("APPIMAGE", str(path))
    status = app_identity.install_status(frozen=True, version=Version("1.0"))
    assert status.can_install is True
    assert status.reason == ""
    assert status.identity is not None
    assert status.identity.arch == "x86_64"


def test_install_status_rejects_symlink_target(tmp_path, monkeypatch):
    real = _fake_appimage(tmp_path)
    link = tmp_path / "linked.AppImage"
    link.symlink_to(real)
    monkeypatch.setenv("APPIMAGE", str(link))
    status = app_identity.install_status(frozen=True, version=Version("1.0"))
    assert status.can_install is False
    assert "symbolic link" in status.reason


def test_install_status_rejects_missing_or_non_elf(tmp_path, monkeypatch):
    monkeypatch.setenv("APPIMAGE", str(tmp_path / "missing.AppImage"))
    status = app_identity.install_status(frozen=True, version=Version("1.0"))
    assert status.can_install is False

    plain = tmp_path / "plain.txt"
    plain.write_text("not an AppImage")
    monkeypatch.setenv("APPIMAGE", str(plain))
    assert app_identity.install_status(frozen=True, version=Version("1.0")).can_install is False


def test_install_status_rejects_unwritable_target(tmp_path, monkeypatch):
    path = _fake_appimage(tmp_path)
    monkeypatch.setenv("APPIMAGE", str(path))
    monkeypatch.setattr(app_identity.os, "access", lambda *_args, **_kw: False)
    status = app_identity.install_status(frozen=True, version=Version("1.0"))
    assert status.can_install is False
    assert "writable" in status.reason


def test_install_status_rejects_unsupported_arch(tmp_path, monkeypatch):
    path = _fake_appimage(tmp_path, machine="aarch64")
    monkeypatch.setenv("APPIMAGE", str(path))
    status = app_identity.install_status(frozen=True, version=Version("1.0"))
    assert status.can_install is False
    assert "architecture" in status.reason


def test_identity_matches_tracks_replacement_and_deletion(tmp_path):
    path = _fake_appimage(tmp_path)
    identity = app_identity.validate_appimage(path)
    assert identity is not None and identity.identity_matches()
    # Create the replacement while the old inode still exists; unlinking
    # first allows some filesystems to recycle that inode immediately.
    replacement = tmp_path / "replacement.AppImage"
    replacement.write_bytes(b"\x7fELF" + b"\x00" * 64)
    os.replace(replacement, path)
    assert identity.identity_matches() is False
    path.unlink()
    assert identity.identity_matches() is False


# --- §2: release selection (pure functions) ---


def _release_item(
    tag: str,
    *,
    draft: bool = False,
    with_appimage: bool = True,
    base: str = "https://github.com",
) -> dict:
    version_text = tag[1:]
    assets: list = []
    if with_appimage:
        name = f"Strom-{version_text}-x86_64.AppImage"
        assets.append(
            {
                "name": name,
                "browser_download_url": f"{base}/download/{tag}/{name}",
                "size": 1000,
            }
        )
    assets.append(
        {
            "name": "SHA256SUMS",
            "browser_download_url": f"{base}/download/{tag}/SHA256SUMS",
            "size": 80,
        }
    )
    return {
        "tag_name": tag,
        "draft": draft,
        "prerelease": "a" in version_text or "rc" in version_text,
        "assets": assets,
    }


def _selection(pages, current: str, arch: str = "x86_64"):
    releases = [item for page in pages for item in page]
    return updates.select_update(releases, Version(current), arch)


def test_alpha_to_alpha_channel_rule():
    selection = _selection([[_release_item("v0.4.0a1")]], "0.3.0a1")
    assert selection.kind is updates.SelectionKind.AVAILABLE
    assert selection.candidate is not None
    assert selection.candidate.version == Version("0.4.0a1")


def test_alpha_to_stable_channel_rule():
    selection = _selection([[_release_item("v0.3.0")]], "0.3.0a1")
    assert selection.kind is updates.SelectionKind.AVAILABLE
    assert selection.candidate.version == Version("0.3.0")


def test_stable_does_not_follow_prereleases():
    selection = _selection([[_release_item("v0.4.0a1")]], "0.3.0")
    assert selection.kind is updates.SelectionKind.UP_TO_DATE
    assert selection.candidate is None


def test_numeric_comparison_not_lexicographic():
    selection = _selection([[_release_item("v0.10.0")]], "0.9.0")
    assert selection.kind is updates.SelectionKind.AVAILABLE
    assert selection.candidate.version == Version("0.10.0")


def test_equal_and_older_tags_never_offer():
    for tag, current in (("v0.3.0", "0.3.0"), ("v0.2.9", "0.3.0")):
        selection = _selection([[_release_item(tag)]], current)
        assert selection.kind is updates.SelectionKind.UP_TO_DATE


def test_drafts_are_ignored_but_not_misread_as_current():
    selection = _selection([[_release_item("v0.4.0", draft=True)]], "0.3.0")
    assert selection.kind is updates.SelectionKind.UP_TO_DATE
    assert selection.candidate is None


def test_release_without_required_assets_is_not_installable():
    selection = _selection([[_release_item("v0.4.0", with_appimage=False)]], "0.3.0")
    assert selection.kind is updates.SelectionKind.UP_TO_DATE
    assert "no installable" in (selection.note or "")


def test_duplicate_appimage_assets_reject_the_release():
    duplicate = dict(_release_item("v0.4.0"))
    duplicate["assets"] = list(duplicate["assets"]) + [
        {
            "name": "Strom-0.4.0-x86_64.AppImage",
            "browser_download_url": "https://github.com/download/v0.4.0/x",
            "size": 1,
        }
    ]
    selection = _selection([[duplicate]], "0.3.0")
    assert selection.kind is updates.SelectionKind.UP_TO_DATE


def test_malformed_unrelated_tags_are_ignored_safely():
    pages = [[
        {"tag_name": "nightly", "draft": False, "assets": []},
        {"tag_name": "v0.not-a-version", "draft": False, "assets": []},
        {"tag_name": "v0.5.0", "draft": False, "assets": "broken"},
        _release_item("v0.4.0"),
    ]]
    selection = _selection(pages, "0.3.0")
    assert selection.kind is updates.SelectionKind.AVAILABLE
    assert selection.candidate is not None
    assert selection.candidate.version == Version("0.4.0")


def test_checksum_manifest_rejects_missing_duplicate_and_malformed():
    digest = hashlib.sha256(b"x").hexdigest()
    name = "Strom-0.4.0-x86_64.AppImage"
    assert _checksum_for(f"{digest}  {name}\n".encode(), name) == digest
    assert _checksum_for(f"{digest} *{name}\n".encode(), name) == digest
    assert _checksum_for(f"{digest}  {name}\n{digest}  {name}\n".encode(), name) is None
    assert _checksum_for(b"no entries here\n", name) is None
    assert _checksum_for(f"zz  {name}\n".encode(), name) is None


def test_asset_url_policy_requires_repository_and_scheme():
    policy = UrlPolicy(asset_prefix="/Bloodwing1/Strom/releases/download/")
    good = "https://github.com/Bloodwing1/Strom/releases/download/v0.4.0/Strom-0.4.0-x86_64.AppImage"
    asset = "Strom-0.4.0-x86_64.AppImage"
    assert policy.asset_url_allowed(good, "v0.4.0", asset)
    assert not policy.asset_url_allowed(
        good.replace("https://", "http://"), "v0.4.0", asset
    )
    assert not policy.asset_url_allowed(
        "https://evil.example/Bloodwing1/Strom/releases/download/v0.4.0/"
        + asset,
        "v0.4.0",
        asset,
    )
    assert not policy.asset_url_allowed(
        "https://github.com/Bloodwing1/Strom/releases/download/v0.4.0/other.bin",
        "v0.4.0",
        asset,
    )


# --- §3: network service against a local fake HTTP service ---


ASSET_NAME = "Strom-0.4.0-x86_64.AppImage"


def _local_service(base: str) -> UpdateService:
    config = ServiceConfig(
        releases_url=f"{base}/fixtures/releases",
        request_timeout_ms=800,
        download_timeout_ms=20_000,
        max_redirects=3,
    )
    return UpdateService(
        QCoreApplication.instance(),
        config=config,
        policy=UrlPolicy(
            download_hosts=(base.replace("http://", ""),),
            asset_prefix="/fixtures/download/",
            scheme="http",
        ),
        current=Version("0.3.0"),
        arch="x86_64",
    )


def _asset_url(base: str) -> str:
    return f"{base}/fixtures/download/v0.4.0/{ASSET_NAME}"


def _sums_url(base: str) -> str:
    return f"{base}/fixtures/download/v0.4.0/SHA256SUMS"


def _release(base: str, payload: bytes) -> updates.ReleaseInfo:
    return updates.ReleaseInfo(
        tag="v0.4.0",
        version=Version("0.4.0"),
        prerelease=False,
        appimage=updates.ReleaseAsset(
            name=ASSET_NAME, url=_asset_url(base), size=len(payload)
        ),
        checksums=updates.ReleaseAsset(
            name="SHA256SUMS", url=_sums_url(base), size=0
        ),
    )


def _release_payload(base: str, payload: bytes) -> list[dict]:
    return [
        {
            "tag_name": "v0.4.0",
            "draft": False,
            "prerelease": False,
            "assets": [
                {
                    "name": ASSET_NAME,
                    "browser_download_url": _asset_url(base),
                    "size": len(payload),
                },
                {
                    "name": "SHA256SUMS",
                    "browser_download_url": _sums_url(base),
                    "size": 0,
                },
            ],
        }
    ]


def test_check_selects_available_release(qtbot, fake_service):
    fake_service.routes = {
        "/fixtures/releases?per_page=100&page=1": (
            200,
            json.dumps(_release_payload(fake_service.base, b"payload")).encode(),
        ),
    }
    service = _local_service(fake_service.base)
    captured: list = []
    service.checkCompleted.connect(captured.append)
    with qtbot.waitSignal(service.checkCompleted, timeout=10_000):
        service.check_now()
    assert len(captured) == 1
    assert captured[0].kind is updates.SelectionKind.AVAILABLE
    assert captured[0].candidate is not None
    assert captured[0].candidate.version == Version("0.4.0")


def test_check_reports_failure_on_http_error(qtbot, fake_service):
    service = _local_service(fake_service.base)
    failures: list[str] = []
    service.checkFailed.connect(failures.append)
    with qtbot.waitSignal(service.checkFailed, timeout=10_000):
        service.check_now()
    assert len(failures) == 1
    assert "HTTP" in failures[0] or "could not be found" in failures[0]


def test_check_reports_failure_on_malformed_json(qtbot, fake_service):
    fake_service.routes = {
        "/fixtures/releases?per_page=100&page=1": (200, b"not json"),
    }
    service = _local_service(fake_service.base)
    failures: list[str] = []
    service.checkFailed.connect(failures.append)
    with qtbot.waitSignal(service.checkFailed, timeout=10_000):
        service.check_now()
    assert failures == ["GitHub returned a release list that could not be read"]


def test_check_reports_failure_on_rate_limit(qtbot, fake_service):
    fake_service.routes = {"/fixtures/releases?per_page=100&page=1": (403, b"no")}
    service = _local_service(fake_service.base)
    failures: list[str] = []
    service.checkFailed.connect(failures.append)
    with qtbot.waitSignal(service.checkFailed, timeout=10_000):
        service.check_now()
    assert "rate limit" in failures[0]


def test_download_streams_hashes_and_verifies(qtbot, fake_service, tmp_path):
    payload = b"A" * 5000
    digest = hashlib.sha256(payload).hexdigest()
    fake_service.routes = {
        f"/fixtures/download/v0.4.0/{ASSET_NAME}": (200, payload),
        "/fixtures/download/v0.4.0/SHA256SUMS": (
            200,
            f"{digest}  {ASSET_NAME}\n".encode(),
        ),
    }
    service = _local_service(fake_service.base)
    prepared: list = []
    service.downloadPrepared.connect(prepared.append)
    with qtbot.waitSignal(service.downloadPrepared, timeout=10_000):
        service.download(_release(fake_service.base, payload), tmp_path / "Strom.AppImage")
    assert len(prepared) == 1
    assert prepared[0].sha256 == digest
    assert prepared[0].staging.read_bytes() == payload
    assert stat.S_IMODE(prepared[0].staging.stat().st_mode) & 0o777 == 0o755


def test_download_emits_terminal_progress(qtbot, fake_service, tmp_path):
    payload = b"P" * 5000
    digest = hashlib.sha256(payload).hexdigest()
    fake_service.routes = {
        f"/fixtures/download/v0.4.0/{ASSET_NAME}": (200, payload),
        "/fixtures/download/v0.4.0/SHA256SUMS": (
            200,
            f"{digest}  {ASSET_NAME}\n".encode(),
        ),
    }
    service = _local_service(fake_service.base)
    progress: list[tuple[int, int]] = []
    service.downloadProgress.connect(lambda r, t: progress.append((r, t)))
    with qtbot.waitSignal(service.downloadPrepared, timeout=10_000):
        service.download(_release(fake_service.base, payload), tmp_path / "Strom.AppImage")
    assert progress
    assert progress[-1] == (len(payload), len(payload))


def test_download_fails_on_checksum_mismatch(qtbot, fake_service, tmp_path):
    payload = b"B" * 1000
    wrong = hashlib.sha256(b"not the payload").hexdigest()
    fake_service.routes = {
        f"/fixtures/download/v0.4.0/{ASSET_NAME}": (200, payload),
        "/fixtures/download/v0.4.0/SHA256SUMS": (
            200,
            f"{wrong}  {ASSET_NAME}\n".encode(),
        ),
    }
    service = _local_service(fake_service.base)
    failures: list[str] = []
    service.downloadFailed.connect(failures.append)
    with qtbot.waitSignal(service.downloadFailed, timeout=10_000):
        service.download(_release(fake_service.base, payload), tmp_path / "Strom.AppImage")
    assert "does not match its checksum" in failures[0]
    assert not list(tmp_path.iterdir())  # staging was removed


def test_download_fails_on_truncated_response(qtbot, fake_service, tmp_path):
    fake_service.routes = {
        f"/fixtures/download/v0.4.0/{ASSET_NAME}": (200, b"C" * 400),
    }
    service = _local_service(fake_service.base)
    failures: list[str] = []
    service.downloadFailed.connect(failures.append)
    with qtbot.waitSignal(service.downloadFailed, timeout=10_000):
        service.download(_release(fake_service.base, b"C" * 1000), tmp_path / "Strom.AppImage")
    assert "incomplete" in failures[0]


def test_download_rejects_response_larger_than_recorded_size(
    qtbot, fake_service, tmp_path
):
    payload = b"D" * 1000
    release = _release(fake_service.base, payload)
    oversized = updates.ReleaseInfo(
        tag=release.tag,
        version=release.version,
        prerelease=release.prerelease,
        appimage=updates.ReleaseAsset(
            name=ASSET_NAME, url=_asset_url(fake_service.base), size=100
        ),
        checksums=release.checksums,
    )
    fake_service.routes = {
        f"/fixtures/download/v0.4.0/{ASSET_NAME}": (200, payload),
    }
    service = _local_service(fake_service.base)
    failures: list[str] = []
    service.downloadFailed.connect(failures.append)
    with qtbot.waitSignal(service.downloadFailed, timeout=10_000):
        service.download(oversized, tmp_path / "Strom.AppImage")
    assert "larger than the release records" in failures[0]


def test_download_follows_supported_redirects(qtbot, fake_service, tmp_path):
    payload = b"E" * 2000
    digest = hashlib.sha256(payload).hexdigest()
    mirror_path = "/fixtures/mirror/AppImage"
    fake_service.routes = {
        mirror_path: (200, payload),
        "/fixtures/download/v0.4.0/SHA256SUMS": (
            200,
            f"{digest}  {ASSET_NAME}\n".encode(),
        ),
    }
    fake_service.redirects = {
        f"/fixtures/download/v0.4.0/{ASSET_NAME}": (
            f"{fake_service.base}{mirror_path}"
        ),
    }
    service = _local_service(fake_service.base)
    prepared: list = []
    service.downloadPrepared.connect(prepared.append)
    with qtbot.waitSignal(service.downloadPrepared, timeout=10_000):
        service.download(_release(fake_service.base, payload), tmp_path / "Strom.AppImage")
    assert prepared[0].staging.read_bytes() == payload


def test_download_refuses_redirect_outside_supported_hosts(
    qtbot, fake_service, tmp_path
):
    payload = b"F" * 2000
    fake_service.redirects = {
        f"/fixtures/download/v0.4.0/{ASSET_NAME}": "http://evil.example/payload",
    }
    service = _local_service(fake_service.base)
    failures: list[str] = []
    service.downloadFailed.connect(failures.append)
    with qtbot.waitSignal(service.downloadFailed, timeout=10_000):
        service.download(_release(fake_service.base, payload), tmp_path / "Strom.AppImage")
    assert "redirected outside the supported hosts" in failures[0]


def test_check_times_out_when_the_server_never_answers(qtbot, fake_service):
    fake_service.routes = {
        "/fixtures/slow?per_page=100&page=1": (200, b"[]"),
    }
    fake_service.delay_paths = {"/fixtures/slow?per_page=100&page=1": 1.2}
    service = _local_service(fake_service.base)
    service._config = ServiceConfig(
        releases_url=f"{fake_service.base}/fixtures/slow",
        request_timeout_ms=300,
        download_timeout_ms=20_000,
        max_redirects=3,
    )
    failures: list[str] = []
    service.checkFailed.connect(failures.append)
    with qtbot.waitSignal(service.checkFailed, timeout=10_000):
        service.check_now()
    assert "timed out" in failures[0]


def test_cancel_stops_the_download_and_removes_staging(
    qtbot, fake_service, tmp_path
):
    payload = b"G" * 2000
    fake_service.routes = {
        f"/fixtures/download/v0.4.0/{ASSET_NAME}": (200, payload),
    }
    fake_service.slow_paths = {f"/fixtures/download/v0.4.0/{ASSET_NAME}"}
    service = _local_service(fake_service.base)
    service._config = ServiceConfig(
        releases_url=f"{fake_service.base}/fixtures/releases",
        request_timeout_ms=800,
        download_timeout_ms=60_000,
        max_redirects=3,
    )
    cancelled: list = []
    service.cancelled.connect(lambda: cancelled.append(1))
    assert service.download(_release(fake_service.base, payload), tmp_path / "Strom.AppImage") is True
    qtbot.waitUntil(lambda: service.received > 0, timeout=10_000)
    with qtbot.waitSignal(service.cancelled, timeout=10_000):
        service.cancel()
    assert len(cancelled) == 1
    assert service.is_busy() is False


# --- coordinator: the full install transaction with fake children ---


def test_handshake_socket_path_fits_the_kernel_limit(monkeypatch, tmp_path):
    """The handshake socket must stay inside the AF_UNIX path limit.

    macOS spends most of the 104-byte budget on its per-user temp directory,
    which made ``QLocalServer.listen`` fail with a name error and turned a
    healthy update into a refusal; a deep TMPDIR is the same hazard on Linux.
    """
    from strom.linux_gui import update_service

    deep_dir = tmp_path / ("deep/" * 40)
    deep_dir.mkdir(parents=True)
    monkeypatch.setattr(update_service.tempfile, "tempdir", str(deep_dir))

    first = update_service._handshake_socket_path()
    second = update_service._handshake_socket_path()

    assert len(first.encode()) <= update_service.SOCKET_PATH_LIMIT
    assert len(second.encode()) <= update_service.SOCKET_PATH_LIMIT
    assert str(os.getpid()) in first or "strom-ack-" in first
    assert first != second


FAKE_CANDIDATE = """#!/usr/bin/env python3
import json
import os
import socket
import sys
import time

if "--strom-self-test" in sys.argv:
    print("selftest ok")
    sys.exit(0)

name, _, token = os.environ["STROM_UPDATE_ACK"].partition(":")
client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
for _ in range(200):
    try:
        client.connect(name)
        break
    except OSError:
        time.sleep(0.05)
else:
    sys.exit(3)
client.sendall(json.dumps({
    "token": token,
    "pid": os.getpid(),
    "heating_disabled": True,
}).encode())
time.sleep(0.4)
sys.exit(0)
"""

CRASHING_CANDIDATE = """#!/usr/bin/env python3
import sys
if "--strom-self-test" in sys.argv:
    print("selftest ok")
    sys.exit(0)
sys.stderr.write("boom\\n")
sys.exit(5)
"""

SPLIT_ACK_CANDIDATE = """#!/usr/bin/env python3
import json
import os
import socket
import sys
import time

if "--strom-self-test" in sys.argv:
    print("selftest ok")
    sys.exit(0)

name, _, token = os.environ["STROM_UPDATE_ACK"].partition(":")
client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
for _ in range(200):
    try:
        client.connect(name)
        break
    except OSError:
        time.sleep(0.05)
else:
    sys.exit(3)
payload = json.dumps({
    "token": token,
    "pid": os.getpid(),
    "heating_disabled": True,
}).encode()
client.sendall(payload[:7])
time.sleep(0.2)
client.sendall(payload[7:])
time.sleep(0.4)
sys.exit(0)
"""

FAILING_SELFTEST = """#!/usr/bin/env python3
import sys
print("selftest failed")
sys.exit(1)
"""


def _coordinator(qtbot, tmp_path, target: Path, candidate: str):
    from strom.linux_gui.app_identity import AppImageIdentity
    from strom.linux_gui.update_service import (
        UpdateCoordinator,
        UpdaterHooks,
    )

    info = os.stat(target)
    identity = AppImageIdentity(
        path=target, device=info.st_dev, inode=info.st_ino, arch="x86_64"
    )
    status = app_identity.InstallStatus(
        can_install=True, reason="", version=Version("0.3.0"), identity=identity
    )
    blocks: list = []
    saved: list = []
    closed: list = []
    hooks = UpdaterHooks(
        is_cycle_active=lambda: False,
        set_run_block=lambda b: blocks.append(b),
        save_preferences=lambda: saved.append(1),
        request_close=lambda: closed.append(1),
    )
    service = UpdateService(
        QCoreApplication.instance(),
        config=ServiceConfig(releases_url="http://127.0.0.1:1/releases"),
        current=Version("0.3.0"),
        arch="x86_64",
    )
    coordinator = UpdateCoordinator(
        QCoreApplication.instance(),
        service,
        hooks=hooks,
        status=status,
    )
    coordinator._target = identity
    coordinator._status = status
    return coordinator, blocks, saved, closed


def test_install_transaction_replaces_and_restarts(
    qtbot, fake_service, tmp_path, monkeypatch
):
    target = tmp_path / "Strom.AppImage"
    target.write_bytes(b"#!/usr/bin/env python3\nprint('old')\n")
    os.chmod(target, 0o755)
    staging = tmp_path / ".Strom.AppImage.staging-abc"
    staging.write_bytes(FAKE_CANDIDATE.encode())
    os.chmod(staging, 0o755)
    release = _release(fake_service.base, b"x")
    coordinator, blocks, saved, closed = _coordinator(qtbot, tmp_path, target, FAKE_CANDIDATE)
    coordinator._prepared = PreparedUpdate(
        release=release, staging=staging, size=staging.stat().st_size,
        sha256=update_install.file_sha256(staging),
    )
    with qtbot.waitSignal(coordinator.installFinished, timeout=30_000):
        assert coordinator.accept_install(release) is True
    assert coordinator.state is UpdateState.Restarting
    assert blocks == [True]
    assert saved == [1] and closed == [1]
    # The replacement actually happened, keeping the backup recoverable.
    assert target.read_bytes() == FAKE_CANDIDATE.encode()
    assert (target.stat().st_mode & 0o777) == 0o755
    assert update_install.journal_path(target).exists()
    journal = json.loads(update_install.journal_path(target).read_text())
    assert journal["state"] == "acknowledged"
    backups = [p for p in tmp_path.iterdir() if ".backup-" in p.name]
    assert len(backups) == 1 and backups[0].read_bytes().startswith(b"#!/usr/bin/env python3\nprint('old')")


def test_ack_handshake_accepts_a_split_payload(qtbot, fake_service, tmp_path):
    target = tmp_path / "Strom.AppImage"
    target.write_bytes(b"#!/usr/bin/env python3\nprint('old')\n")
    os.chmod(target, 0o755)
    staging = tmp_path / ".Strom.AppImage.staging-abc"
    staging.write_bytes(SPLIT_ACK_CANDIDATE.encode())
    os.chmod(staging, 0o755)
    release = _release(fake_service.base, b"x")
    coordinator, blocks, saved, closed = _coordinator(
        qtbot, tmp_path, target, SPLIT_ACK_CANDIDATE
    )
    coordinator._prepared = PreparedUpdate(
        release=release, staging=staging, size=staging.stat().st_size,
        sha256=update_install.file_sha256(staging),
    )
    with qtbot.waitSignal(coordinator.installFinished, timeout=30_000) as finished:
        assert coordinator.accept_install(release) is True
    assert finished.args[0] is True
    assert coordinator.state is UpdateState.Restarting
    assert blocks == [True]
    assert saved == [1] and closed == [1]


def test_selftest_failure_rolls_back_and_reopens_controls(
    qtbot, fake_service, tmp_path
):
    target = tmp_path / "Strom.AppImage"
    target.write_bytes(b"old")
    os.chmod(target, 0o644)
    staging = tmp_path / ".Strom.AppImage.staging-abc"
    staging.write_bytes(FAILING_SELFTEST.encode())
    os.chmod(staging, 0o755)
    release = _release(fake_service.base, b"x")
    coordinator, blocks, saved, closed = _coordinator(qtbot, tmp_path, target, FAILING_SELFTEST)
    coordinator._prepared = PreparedUpdate(
        release=release, staging=staging, size=staging.stat().st_size,
        sha256=update_install.file_sha256(staging),
    )
    with qtbot.waitSignal(coordinator.installFinished, timeout=30_000):
        assert coordinator.accept_install(release) is True
    assert coordinator.state is UpdateState.Failed
    assert "self-test" in coordinator.message
    assert blocks == [True, False]  # blocked during, released after failure
    assert target.read_bytes() == b"old"  # untouched
    assert not update_install.journal_path(target).exists()
    assert saved == []


def test_candidate_exit_without_ack_restores_previous_version(
    qtbot, fake_service, tmp_path, monkeypatch
):
    from strom.linux_gui import update_service as update_service_module

    monkeypatch.setattr(update_service_module, "ACK_TIMEOUT_MS", 300)
    target = tmp_path / "Strom.AppImage"
    target.write_bytes(b"old")
    os.chmod(target, 0o644)
    staging = tmp_path / ".Strom.AppImage.staging-abc"
    staging.write_bytes(CRASHING_CANDIDATE.encode())
    os.chmod(staging, 0o755)
    release = _release(fake_service.base, b"x")
    coordinator, blocks, saved, closed = _coordinator(qtbot, tmp_path, target, CRASHING_CANDIDATE)
    coordinator._prepared = PreparedUpdate(
        release=release, staging=staging, size=staging.stat().st_size,
        sha256=update_install.file_sha256(staging),
    )
    with qtbot.waitSignal(coordinator.installFinished, timeout=10_000):
        assert coordinator.accept_install(release) is True
    assert coordinator.state is UpdateState.Failed
    assert "restored" in coordinator.message
    assert target.read_bytes() == b"old"
    assert blocks == [True, False]
    assert saved == []


def test_detached_launch_keeps_the_replacement_alive(qtbot, tmp_path):
    """Qt kills a tracked QProcess's child; the replacement must be detached."""
    import subprocess

    from PySide6.QtCore import QProcessEnvironment

    from strom.linux_gui.update_service import UpdateCoordinator

    script = tmp_path / "candidate.sh"
    marker = tmp_path / "started.txt"
    script.write_text(
        f'#!/bin/sh\nprintf "%s" "$STROM_TEST_MARK" > {marker}\nsleep 10\n'
    )
    os.chmod(script, 0o755)
    environment = QProcessEnvironment.systemEnvironment()
    environment.insert("STROM_TEST_MARK", "1")

    assert UpdateCoordinator._start_detached(str(script), [], environment) is True

    qtbot.waitUntil(marker.exists, timeout=5000)
    assert marker.read_text() == "1"
    running = subprocess.run(
        ["pgrep", "-f", str(script)], capture_output=True, text=True
    ).stdout
    assert running
    subprocess.run(["pkill", "-f", str(script)])


def test_relaunch_detached_strips_the_launcher_environment(tmp_path, monkeypatch):
    import subprocess as subprocess_module

    from strom.linux_gui import update_service as update_service_module

    image = tmp_path / "strom.AppImage"
    image.write_bytes(b"x")
    recorded: dict = {}

    class FakePopen:
        def __init__(self, args, **kwargs):
            recorded["args"] = args
            recorded["kwargs"] = kwargs

    monkeypatch.setenv("APPIMAGE", str(image))
    monkeypatch.setenv(update_service_module.ACK_ENV, "name:token")
    monkeypatch.setenv("APPDIR", "/tmp/mount")
    monkeypatch.setattr(subprocess_module, "Popen", FakePopen)

    assert update_service_module.UpdateCoordinator._relaunch_detached() is True

    assert recorded["args"] == [str(image)]
    environment = recorded["kwargs"]["env"]
    assert update_service_module.ACK_ENV not in environment
    assert "APPDIR" not in environment
    assert environment[update_service_module._HANDOFF_ENV] == "1"
    assert recorded["kwargs"]["start_new_session"] is True


def test_handoff_skipped_for_a_safe_launcher(
    qtbot, fake_service, tmp_path, monkeypatch
):
    from strom.linux_gui import update_service as update_service_module

    target = tmp_path / "Strom.AppImage"
    target.write_bytes(b"old")
    os.chmod(target, 0o644)
    coordinator, _blocks, _saved, _closed = _coordinator(
        qtbot, tmp_path, target, FAKE_CANDIDATE
    )
    calls: list = []
    monkeypatch.setenv(update_service_module.SAFE_LAUNCH_ENV, "1")
    monkeypatch.setattr(
        coordinator, "_relaunch_detached",
        lambda: calls.append("relaunch") or True,
    )

    coordinator._handoff_from_old_launcher()

    assert calls == []


def test_handoff_relaunches_for_an_old_launcher(
    qtbot, fake_service, tmp_path, monkeypatch
):
    from strom.linux_gui import update_service as update_service_module

    target = tmp_path / "Strom.AppImage"
    target.write_bytes(b"old")
    os.chmod(target, 0o644)
    coordinator, _blocks, _saved, _closed = _coordinator(
        qtbot, tmp_path, target, FAKE_CANDIDATE
    )
    monkeypatch.delenv(update_service_module.SAFE_LAUNCH_ENV, raising=False)
    monkeypatch.delenv(update_service_module._HANDOFF_ENV, raising=False)
    monkeypatch.setattr(coordinator, "_relaunch_detached", lambda: True)
    scheduled: list = []
    monkeypatch.setattr(
        update_service_module.QTimer, "singleShot",
        lambda ms, fn: scheduled.append(ms),
    )

    coordinator._handoff_from_old_launcher()

    assert scheduled == [update_service_module._HANDOFF_GRACE_MS]


def test_accepted_install_blocks_run_until_failure_or_restart(
    qtbot, fake_service, tmp_path
):
    target = tmp_path / "Strom.AppImage"
    target.write_bytes(b"old")
    os.chmod(target, 0o644)
    staging = tmp_path / ".Strom.AppImage.staging-abc"
    staging.write_bytes(FAILING_SELFTEST.encode())
    os.chmod(staging, 0o755)
    release = _release(fake_service.base, b"x")
    coordinator, blocks, _saved, _closed = _coordinator(qtbot, tmp_path, target, FAILING_SELFTEST)
    coordinator._prepared = PreparedUpdate(
        release=release, staging=staging, size=staging.stat().st_size,
        sha256=update_install.file_sha256(staging),
    )
    assert coordinator.run_blocked() is False
    with qtbot.waitSignal(coordinator.installFinished, timeout=30_000):
        coordinator.accept_install(release)
    assert blocks == [True, False]
    assert coordinator.run_blocked() is False


def test_repeated_update_clicks_start_one_transaction(
    qtbot, fake_service, tmp_path, monkeypatch
):
    target = tmp_path / "Strom.AppImage"
    target.write_bytes(b"old")
    os.chmod(target, 0o644)
    staging = tmp_path / ".Strom.AppImage.staging-abc"
    staging.write_bytes(FAILING_SELFTEST.encode())
    os.chmod(staging, 0o755)
    release = _release(fake_service.base, b"x")
    coordinator, blocks, _saved, _closed = _coordinator(qtbot, tmp_path, target, FAILING_SELFTEST)
    coordinator._prepared = PreparedUpdate(
        release=release, staging=staging, size=staging.stat().st_size,
        sha256=update_install.file_sha256(staging),
    )
    assert coordinator.accept_install(release) is True
    # A repeated explicit click cannot start a competing operation.
    assert coordinator.accept_install(release) is False
    with qtbot.waitSignal(coordinator.installFinished, timeout=30_000):
        pass
    assert update_install.journal_path(target).exists() is False


def test_check_refused_while_installation_runs(
    qtbot, fake_service, tmp_path
):
    target = tmp_path / "Strom.AppImage"
    target.write_bytes(b"old")
    os.chmod(target, 0o644)
    staging = tmp_path / ".Strom.AppImage.staging-abc"
    staging.write_bytes(FAILING_SELFTEST.encode())
    os.chmod(staging, 0o755)
    release = _release(fake_service.base, b"x")
    coordinator, blocks, _saved, _closed = _coordinator(qtbot, tmp_path, target, FAILING_SELFTEST)
    coordinator._prepared = PreparedUpdate(
        release=release, staging=staging, size=staging.stat().st_size,
        sha256=update_install.file_sha256(staging),
    )
    assert coordinator.accept_install(release) is True
    assert coordinator.state is UpdateState.Installing
    # A check during the installation must not overwrite the install state.
    assert coordinator.check(manual=True) is False
    assert coordinator.state is UpdateState.Installing
    with qtbot.waitSignal(coordinator.installFinished, timeout=30_000):
        pass
    assert blocks == [True, False]


def test_translated_message_formats_after_translation(qtbot, fake_service, tmp_path):
    target = _fake_appimage(tmp_path)
    coordinator, _blocks, _saved, _closed = _coordinator(
        qtbot, tmp_path, target, FAKE_CANDIDATE
    )
    release = _release(fake_service.base, b"x")
    note = "Updating is recommended."
    coordinator._on_check_completed(
        updates.Selection(
            kind=updates.SelectionKind.AVAILABLE, candidate=release, note=note
        )
    )
    translated = {
        "Strom {available} is available; you are running {current}.":
            "Strom {available} disponible; usas {current}.",
        note: "Se recomienda actualizar.",
    }
    assert coordinator.translated_message(translated.get) == (
        "Strom 0.4.0 disponible; usas 0.3.0.\n"
        "Se recomienda actualizar."
    )


def test_install_refused_when_another_window_holds_the_lock(
    qtbot, fake_service, tmp_path
):
    from strom.linux_gui.update_install import update_lock_path

    target = tmp_path / "Strom.AppImage"
    target.write_bytes(b"old")
    os.chmod(target, 0o644)
    staging = tmp_path / ".Strom.AppImage.staging-abc"
    staging.write_bytes(FAILING_SELFTEST.encode())
    os.chmod(staging, 0o755)
    holder = update_install.FileLock(update_lock_path(target))
    assert holder.acquire(exclusive=True)
    release = _release(fake_service.base, b"x")
    coordinator, blocks, _saved, _closed = _coordinator(qtbot, tmp_path, target, FAILING_SELFTEST)
    coordinator._prepared = PreparedUpdate(
        release=release, staging=staging, size=staging.stat().st_size,
        sha256=update_install.file_sha256(staging),
    )
    with qtbot.waitSignal(coordinator.installFinished, timeout=30_000):
        coordinator.accept_install(release)
    assert "another Strom window" in coordinator.message
    assert blocks == [True, False]
    assert target.read_bytes() == b"old"
    holder.release()


def test_check_then_download_can_recover_staged_transaction(
    qtbot, fake_service, tmp_path,
):
    target_path = _fake_appimage(tmp_path)
    original = target_path.read_bytes()
    info = target_path.stat()
    target = app_identity.AppImageIdentity(
        path=target_path, device=info.st_dev, inode=info.st_ino, arch="x86_64",
    )
    payload = b"new AppImage payload"
    digest = hashlib.sha256(payload).hexdigest()
    fake_service.routes = {
        "/fixtures/releases?per_page=100&page=1": (
            200, json.dumps(_release_payload(fake_service.base, payload)).encode(),
        ),
        f"/fixtures/download/v0.4.0/{ASSET_NAME}": (200, payload),
        "/fixtures/download/v0.4.0/SHA256SUMS": (
            200, f"{digest}  {ASSET_NAME}\n".encode(),
        ),
    }
    service = _local_service(fake_service.base)
    with qtbot.waitSignal(service.checkCompleted, timeout=3000) as checked:
        service.check_now()
    release = checked.args[0].candidate
    with qtbot.waitSignal(service.downloadPrepared, timeout=3000) as downloaded:
        service.download(release, target_path)
    prepared = downloaded.args[0]
    assert prepared.staging.read_bytes() == payload
    transaction = update_install.prepare_transaction(
        target, release, prepared.staging, prepared.size, prepared.sha256,
    )
    assert update_install.recover(target) is None
    assert target_path.read_bytes() == original
    assert not prepared.staging.exists()
    assert not transaction.backup.exists()
    assert not update_install.journal_path(target_path).exists()


@pytest.mark.parametrize("operation", ["check", "download"])
def test_supported_redirect_loop_stops_at_limit(
    qtbot, fake_service, tmp_path, monkeypatch, operation,
):
    service = _local_service(fake_service.base)
    path = (
        "/fixtures/releases?per_page=100&page=1"
        if operation == "check"
        else f"/fixtures/download/v0.4.0/{ASSET_NAME}"
    )
    fake_service.redirects = {path: fake_service.base + path}
    requests = []
    get = service._manager.get

    def record_request(request):
        requests.append(request.url().toString())
        return get(request)

    monkeypatch.setattr(service._manager, "get", record_request)
    failed = service.checkFailed if operation == "check" else service.downloadFailed
    try:
        with qtbot.waitSignal(failed, timeout=3000):
            if operation == "check":
                service.check_now()
            else:
                service.download(
                    _release(fake_service.base, b"payload"), tmp_path / "Strom.AppImage",
                )
        assert len(requests) == service._config.max_redirects + 1
        assert not service.is_busy()
        assert not list(tmp_path.iterdir())
    finally:
        service.cancel()
