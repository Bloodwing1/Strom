"""Update-plan §5 tests: the transactional AppImage installation.

Locks, backup preservation, atomic replacement, interrupted-transaction
recovery, concurrent attempts, paths with spaces and permission failures
are exercised on real temporary files; the process parts are injected.
"""

import json
import os
import stat
import time
from pathlib import Path

import pytest

pytest.importorskip("PySide6", reason="PySide6 is not installed (GUI extras missing)")

from strom.linux_gui import update_install  # noqa: E402
from strom.linux_gui.app_identity import (  # noqa: E402
    AppImageIdentity,
    read_elf_machine,
)


def _fake_appimage(path: Path, machine: str = "x86_64", tag: str = "old") -> Path:
    codes = {"x86_64": 62, "aarch64": 183}
    header = (
        b"\x7fELF"
        + bytes([2, 1, 1])
        + b"\x00" * 9
        + b"\x00\x00"
        + codes.get(machine, 62).to_bytes(2, "little")
    )
    path.write_bytes(header + tag.encode())
    os.chmod(path, 0o755)
    return path


def _identity(path: Path) -> AppImageIdentity:
    info = os.stat(path)
    return AppImageIdentity(
        path=path, device=info.st_dev, inode=info.st_ino,
        arch=read_elf_machine(path) or "x86_64",
    )


def _release(version: str = "0.4.0", tag: str = "v0.4.0"):
    from packaging.version import Version

    from strom.linux_gui.updates import ReleaseAsset, ReleaseInfo

    return ReleaseInfo(
        tag=tag,
        version=Version(version),
        prerelease=False,
        appimage=ReleaseAsset(name=f"Strom-{version}-x86_64.AppImage", url="https://x", size=10),
        checksums=ReleaseAsset(name="SHA256SUMS", url="https://x", size=0),
    )


# --- journal naming and ownership validation ---


def test_updater_owned_names_beside_target(tmp_path):
    target = _fake_appimage(tmp_path / "Strom-0.3.0-x86_64.AppImage")
    assert update_install.journal_path(target).name == ".Strom-0.3.0-x86_64.AppImage.journal"
    assert update_install.update_lock_path(target).name.endswith(".update-lock")


def test_is_owned_path_rejects_foreign_paths(tmp_path):
    target = _fake_appimage(tmp_path / "Strom.AppImage")
    owned = tmp_path / ".Strom.AppImage.staging-abc123"
    foreign = tmp_path / "victim.txt"
    assert update_install.is_owned_path(owned, target, update_install.STAGING_MARK)
    assert not update_install.is_owned_path(foreign, target, update_install.STAGING_MARK)
    assert not update_install.is_owned_path(
        tmp_path / "other/.Strom.AppImage.staging-x", target, update_install.STAGING_MARK
    )


def test_load_journal_absent_is_none(tmp_path):
    target = _fake_appimage(tmp_path / "Strom.AppImage")
    assert update_install.load_journal(target) is None


def test_load_journal_rejects_unreadable_or_foreign_content(tmp_path):
    target = _fake_appimage(tmp_path / "Strom.AppImage")
    path = update_install.journal_path(target)
    path.write_text("not json")
    with pytest.raises(update_install.TransactionError):
        update_install.load_journal(target)

    path.write_text(json.dumps({"wrong": 1}))
    with pytest.raises(update_install.TransactionError):
        update_install.load_journal(target)


def test_load_journal_rejects_foreign_target_records(tmp_path):
    target = _fake_appimage(tmp_path / "Strom.AppImage")
    other = _fake_appimage(tmp_path / "Other.AppImage")
    update_install.write_journal(
        target,
        {
            update_install.JOURNAL_MARKER: 1,
            "state": "staged",
            "target": {"path": str(other), "device": 1, "inode": 1, "arch": "x86_64"},
            "backup": {"path": str(other)},
            "staging": {"path": str(other)},
        },
    )
    with pytest.raises(update_install.TransactionError):
        update_install.load_journal(target)


# --- prepare / commit / rollback on real temporary AppImages ---


def test_prepare_and_commit_replacement(tmp_path):
    target = _fake_appimage(tmp_path / "Strom.AppImage", tag="old-version-bytes")
    identity = _identity(target)
    release = _release()
    with _FakeLock(update_install.update_lock_path(target)):
        staging = tmp_path / ".Strom.AppImage.staging-test1"
        staging.write_bytes(b"new-version-bytes")
        staging.chmod(0o644)
        transaction = update_install.prepare_transaction(
            identity, release, staging, staging.stat().st_size,
            update_install.file_sha256(staging),
        )
        assert transaction.backup.is_file()
        journal = json.loads(update_install.journal_path(target).read_text())
        assert journal["state"] == "staged"
        assert journal["backup"]["path"] == str(transaction.backup)
        # step 5: atomic replacement
        update_install.commit_replacement(identity, staging, transaction.backup)
        assert target.read_bytes() == b"new-version-bytes"
        assert not staging.exists()
        assert (target.stat().st_mode & 0o777) == 0o755
        journal = json.loads(update_install.journal_path(target).read_text())
        assert journal["state"] == "replaced"
        assert journal["target"]["inode"] == os.stat(target).st_ino
        # the backup still holds the previous version (with its ELF header)
        backup_bytes = transaction.backup.read_bytes()
        assert backup_bytes.endswith(b"old-version-bytes")
        assert backup_bytes.startswith(b"\x7fELF")


class _FakeLock:
    """Context-managed lock helper for the tests."""

    def __init__(self, path: Path) -> None:
        self._lock = update_install.FileLock(path)

    def __enter__(self):
        assert self._lock.acquire(exclusive=True)
        return self._lock

    def __exit__(self, *_args):
        self._lock.release()
        return False


def test_restore_previous_rolls_back_replacement(tmp_path):
    target = _fake_appimage(tmp_path / "Strom.AppImage", tag="old")
    identity = _identity(target)
    release = _release()
    staging = tmp_path / ".Strom.AppImage.staging-test1"
    staging.write_bytes(b"new")
    staging.chmod(0o644)
    transaction = update_install.prepare_transaction(
        identity, release, staging, staging.stat().st_size,
        update_install.file_sha256(staging),
    )
    update_install.commit_replacement(identity, staging, transaction.backup)
    assert target.read_bytes() == b"new"
    update_install.restore_previous(identity, transaction.backup)
    assert target.read_bytes().endswith(b"old")
    update_install.clear_journal(identity)


def test_rollback_before_replacement_discards_everything(tmp_path):
    target = _fake_appimage(tmp_path / "Strom.AppImage", tag="old")
    identity = _identity(target)
    release = _release()
    staging = tmp_path / ".Strom.AppImage.staging-test1"
    staging.write_bytes(b"new")
    staging.chmod(0o644)
    transaction = update_install.prepare_transaction(
        identity, release, staging, staging.stat().st_size,
        update_install.file_sha256(staging),
    )
    update_install.discard_transaction(identity, staging, transaction.backup)
    assert target.read_bytes().endswith(b"old")
    assert not staging.exists()
    assert not transaction.backup.exists()
    assert update_install.journal_path(target).exists() is False


def test_prepare_refuses_changed_target(tmp_path):
    target = _fake_appimage(tmp_path / "Strom.AppImage", tag="old")
    identity = _identity(target)
    replacement = _fake_appimage(tmp_path / "replacement.AppImage", tag="different")
    os.replace(replacement, target)
    staging = tmp_path / ".Strom.AppImage.staging-test1"
    staging.write_bytes(b"new")
    staging.chmod(0o644)
    with pytest.raises(update_install.InstallRefused):
        update_install.prepare_transaction(
            identity, _release(), staging, staging.stat().st_size,
            update_install.file_sha256(staging),
        )
    assert target.read_bytes().endswith(b"different")


def test_prepare_refuses_tampered_staging(tmp_path):
    target = _fake_appimage(tmp_path / "Strom.AppImage", tag="old")
    identity = _identity(target)
    staging = tmp_path / ".Strom.AppImage.staging-test1"
    staging.write_bytes(b"new")
    staging.chmod(0o644)
    with pytest.raises(update_install.TransactionError):
        update_install.prepare_transaction(
            identity, _release(), staging, staging.stat().st_size + 1,
            update_install.file_sha256(staging),
        )
    wrong_hash = update_install.file_sha256(staging)[:-1] + (
        "0" if update_install.file_sha256(staging)[-1] != "0" else "1"
    )
    with pytest.raises(update_install.TransactionError):
        update_install.prepare_transaction(
            identity, _release(), staging, staging.stat().st_size, wrong_hash
        )


def test_prepare_refuses_when_disk_is_full(tmp_path, monkeypatch):
    target = _fake_appimage(tmp_path / "Strom.AppImage", tag="old")
    identity = _identity(target)
    staging = tmp_path / ".Strom.AppImage.staging-test1"
    staging.write_bytes(b"new")
    staging.chmod(0o644)

    class Full:
        free = 1

    monkeypatch.setattr(update_install.shutil, "disk_usage", lambda _p: Full())
    with pytest.raises(update_install.TransactionError):
        update_install.prepare_transaction(
            identity, _release(), staging, staging.stat().st_size,
            update_install.file_sha256(staging),
        )


def test_prepare_journal_failure_removes_the_backup(tmp_path, monkeypatch):
    target = _fake_appimage(tmp_path / "Strom.AppImage", tag="old")
    identity = _identity(target)
    staging = tmp_path / ".Strom.AppImage.staging-test1"
    staging.write_bytes(b"new")
    staging.chmod(0o644)

    def fail_journal(*_args, **_kw):
        raise update_install.TransactionError("journal write failed")

    monkeypatch.setattr(update_install, "write_journal", fail_journal)
    with pytest.raises(update_install.TransactionError):
        update_install.prepare_transaction(
            identity, _release(), staging, staging.stat().st_size,
            update_install.file_sha256(staging),
        )
    assert not [p for p in tmp_path.iterdir() if ".backup-" in p.name]
    assert staging.exists()  # owned by the caller until it discards it


def test_prepare_falls_back_to_copy_when_links_fail(tmp_path, monkeypatch):
    target = _fake_appimage(tmp_path / "Strom.AppImage", tag="old")
    identity = _identity(target)
    staging = tmp_path / ".Strom.AppImage.staging-test1"
    staging.write_bytes(b"new")
    staging.chmod(0o644)

    def refuse_link(*_args, **_kw):
        raise OSError("links unsupported")

    monkeypatch.setattr(update_install.os, "link", refuse_link)
    transaction = update_install.prepare_transaction(
        identity, _release(), staging, staging.stat().st_size,
        update_install.file_sha256(staging),
    )
    assert transaction.backup.read_bytes().endswith(b"old")
    update_install.clear_journal(identity)


def test_paths_with_spaces_survive_the_transaction(tmp_path):
    folder = tmp_path / "updates dir with spaces"
    folder.mkdir()
    target = _fake_appimage(folder / "Strom 0.3.0 App.AppImage", tag="old")
    identity = _identity(target)
    staging = folder / ".Strom 0.3.0 App.AppImage.staging-abc"
    staging.write_bytes(b"new")
    staging.chmod(0o644)
    transaction = update_install.prepare_transaction(
        identity, _release(), staging, staging.stat().st_size,
        update_install.file_sha256(staging),
    )
    update_install.commit_replacement(identity, staging, transaction.backup)
    assert target.read_bytes() == b"new"
    assert transaction.backup.read_bytes().endswith(b"old")
    update_install.clear_journal(identity)


# --- locks ---


def test_update_lock_excludes_a_second_transaction(tmp_path):
    target = _fake_appimage(tmp_path / "Strom.AppImage")
    first = update_install.FileLock(update_install.update_lock_path(target))
    second = update_install.FileLock(update_install.update_lock_path(target))
    assert first.acquire(exclusive=True) is True
    try:
        assert second.acquire(exclusive=True) is False
        shared = update_install.FileLock(update_install.update_lock_path(target))
        assert shared.acquire(exclusive=False) is False
    finally:
        first.release()
    assert second.acquire(exclusive=True) is True
    second.release()


def test_locks_die_with_the_owning_process(tmp_path):
    """A killed holder releases the lock (flock semantics)."""
    target = _fake_appimage(tmp_path / "Strom.AppImage")
    path = update_install.update_lock_path(target)
    probe = (
        "import fcntl, os, sys, time\n"
        f"fd = os.open({str(path)!r}, os.O_RDWR | os.O_CREAT, 0o600)\n"
        "fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
        "print('held', flush=True)\n"
        "time.sleep(30)\n"
    )
    import subprocess
    import sys as _sys

    child = subprocess.Popen(
        [_sys.executable, "-c", probe], stdout=subprocess.PIPE, text=True
    )
    try:
        assert child.stdout is not None
        assert child.stdout.readline().strip() == "held"
        lock = update_install.FileLock(path)
        assert lock.acquire(exclusive=True) is False
        child.kill()
        child.wait(timeout=10)
        deadline = 50
        while deadline and lock.acquire(exclusive=True) is False:
            deadline -= 1
            time.sleep(0.05)
        assert lock.is_held()
        lock.release()
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=10)


# --- startup recovery of interrupted transactions ---


def test_recover_staged_transaction_discards_staging(tmp_path):
    target = _fake_appimage(tmp_path / "Strom.AppImage", tag="old")
    identity = _identity(target)
    staging = tmp_path / ".Strom.AppImage.staging-abc"
    staging.write_bytes(b"new")
    backup = tmp_path / ".Strom.AppImage.backup-abc"
    backup.write_bytes(b"old")
    update_install.write_journal(
        target,
        {
            update_install.JOURNAL_MARKER: 1,
            "state": "staged",
            "target": {"path": str(target), "device": os.stat(target).st_dev,
                       "inode": os.stat(target).st_ino, "arch": "x86_64"},
            "backup": {"path": str(backup)},
            "staging": {"path": str(staging)},
            "pid": os.getpid(),
        },
    )
    assert update_install.recover(identity) is None
    assert not staging.exists()
    assert not backup.exists()
    assert update_install.journal_path(target).exists() is False
    assert target.read_bytes().endswith(b"old")


def test_recover_replaced_transaction_keeps_one_backup(tmp_path):
    target = _fake_appimage(tmp_path / "Strom.AppImage", tag="old")
    identity = _identity(target)
    backup = tmp_path / ".Strom.AppImage.backup-abc"
    backup.write_bytes(b"old")
    update_install.write_journal(
        target,
        {
            update_install.JOURNAL_MARKER: 1,
            "state": "replaced",
            "target": {"path": str(target), "device": os.stat(target).st_dev,
                       "inode": os.stat(target).st_ino, "arch": "x86_64"},
            "backup": {"path": str(backup)},
            "staging": {"path": str(target)},
            "pid": os.getpid(),
        },
    )
    note = update_install.recover(identity)
    assert note == str(backup)
    assert backup.read_bytes() == b"old"
    assert update_install.journal_path(target).exists() is False


def test_recover_prunes_old_backups_bounded(tmp_path):
    target = _fake_appimage(tmp_path / "Strom.AppImage", tag="old")
    identity = _identity(target)
    for index in range(4):
        backup = tmp_path / f".Strom.AppImage.backup-{index:08x}"
        backup.write_bytes(f"old{index}".encode())
    update_install.write_journal(
        target,
        {
            update_install.JOURNAL_MARKER: 1,
            "state": "replaced",
            "target": {"path": str(target), "device": os.stat(target).st_dev,
                       "inode": os.stat(target).st_ino, "arch": "x86_64"},
            "backup": {"path": str(tmp_path / ".Strom.AppImage.backup-00000003")},
            "staging": {"path": str(target)},
            "pid": os.getpid(),
        },
    )
    update_install.recover(identity, keep=2)
    remaining = sorted(
        p.name for p in tmp_path.iterdir() if ".backup-" in p.name
    )
    assert len(remaining) == 2


def test_recover_prunes_abandoned_staging_files(tmp_path):
    target = _fake_appimage(tmp_path / "Strom.AppImage", tag="old")
    identity = _identity(target)
    orphan = tmp_path / ".Strom.AppImage.staging-orphan"
    orphan.write_bytes(b"leftover download")
    unrelated = tmp_path / "important.txt"
    unrelated.write_text("keep")
    assert update_install.recover(identity) is None
    assert not orphan.exists()
    assert unrelated.read_text() == "keep"


def test_recover_refuses_journal_describing_another_file(tmp_path):
    target = _fake_appimage(tmp_path / "Strom.AppImage", tag="old")
    identity = _identity(target)
    other = _fake_appimage(tmp_path / "Other.AppImage", tag="old")
    update_install.write_journal(
        target,
        {
            update_install.JOURNAL_MARKER: 1,
            "state": "staged",
            "target": {"path": str(other), "device": 1, "inode": 1, "arch": "x86_64"},
            "backup": {"path": str(other)},
            "staging": {"path": str(other)},
            "pid": os.getpid(),
        },
    )
    with pytest.raises(update_install.TransactionError):
        update_install.recover(identity)


def test_recover_refuses_journal_with_foreign_paths(tmp_path):
    target = _fake_appimage(tmp_path / "Strom.AppImage", tag="old")
    identity = _identity(target)
    victim = tmp_path / "keep-me.txt"
    victim.write_text("do not delete")
    update_install.write_journal(
        target,
        {
            update_install.JOURNAL_MARKER: 1,
            "state": "staged",
            "target": {"path": str(target), "device": os.stat(target).st_dev,
                       "inode": os.stat(target).st_ino, "arch": "x86_64"},
            "backup": {"path": str(victim)},
            "staging": {"path": str(victim)},
            "pid": os.getpid(),
        },
    )
    with pytest.raises(update_install.TransactionError):
        update_install.recover(identity)
    assert victim.read_text() == "do not delete"
    assert update_install.journal_path(target).exists()


def test_prune_backups_never_touches_unrelated_files(tmp_path):
    target = _fake_appimage(tmp_path / "Strom.AppImage", tag="old")
    identity = _identity(target)
    keep = tmp_path / "important.txt"
    keep.write_text("keep")
    backups = []
    for index in range(3):
        backup = tmp_path / f".Strom.AppImage.backup-{index:08x}"
        backup.write_bytes(b"old")
        backups.append(backup)
    update_install.prune_backups(identity, keep=1)
    assert keep.read_text() == "keep"
    assert not backups[0].exists()
    assert backups[-1].exists()


# --- concurrent instances ---


def test_second_instance_lock_attempt_is_refused(tmp_path):
    """The coordinator's guard: a running instance blocks installation."""
    target = _fake_appimage(tmp_path / "Strom.AppImage")
    path = update_install.update_lock_path(target)
    holder = update_install.FileLock(path)
    assert holder.acquire(exclusive=True) is True
    try:
        contender = update_install.FileLock(path)
        assert contender.acquire(exclusive=True) is False
        contender.release()
    finally:
        holder.release()


def test_transaction_survives_paths_with_unicode(tmp_path):
    folder = tmp_path / "Áéíóú"
    folder.mkdir()
    target = _fake_appimage(folder / "Strom-Ápp.AppImage", tag="old")
    identity = _identity(target)
    staging = folder / ".Strom-Ápp.AppImage.staging-x"
    staging.write_bytes(b"new")
    staging.chmod(0o644)
    transaction = update_install.prepare_transaction(
        identity, _release(), staging, staging.stat().st_size,
        update_install.file_sha256(staging),
    )
    update_install.commit_replacement(identity, staging, transaction.backup)
    assert target.read_bytes() == b"new"
    update_install.clear_journal(identity)


def test_file_permissions_are_preserved_on_replacement(tmp_path):
    target = _fake_appimage(tmp_path / "Strom.AppImage", tag="old")
    identity = _identity(target)
    staging = tmp_path / ".Strom.AppImage.staging-x"
    staging.write_bytes(b"new")
    staging.chmod(0o600)
    transaction = update_install.prepare_transaction(
        identity, _release(), staging, staging.stat().st_size,
        update_install.file_sha256(staging),
    )
    update_install.commit_replacement(identity, staging, transaction.backup)
    assert stat.S_IMODE(target.stat().st_mode) & 0o777 == 0o755
    update_install.clear_journal(identity)
