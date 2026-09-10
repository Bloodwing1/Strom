"""Transactional AppImage update installation (update plan §5).

This module owns the filesystem work of replacing the running AppImage:
revalidation, a recoverable backup, the atomic replacement, the transaction
journal, and recovery of interrupted transactions. The coordinator
(``update_service.UpdateCoordinator``) sequences the steps off the GUI thread
and holds the locks; the heating child process is never killed, detached or
waited on synchronously here — that remains the runner's exclusive business.

The transaction journal records installation metadata only (paths, sizes,
hashes, version, pid), never credentials, and its content is never
interpreted as executable commands: recorded paths are acted upon only when
they match the exact updater-owned naming conventions beside the target.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import stat
import uuid
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QSaveFile

from strom.linux_gui.app_identity import AppImageIdentity, read_elf_machine
from strom.linux_gui.updates import ReleaseInfo

JOURNAL_MARKER = "strom-update-journal"
JOURNAL_VERSION = 1
JOURNAL_STATES = ("staged", "replaced", "acknowledged")
STAGING_MARK = "staging-"
BACKUP_MARK = "backup-"
DISK_MARGIN_BYTES = 2 * 1024 * 1024
KEEP_BACKUPS = 2


class InstallRefused(RuntimeError):
    """Installation cannot proceed; the original AppImage is untouched."""


class TransactionError(RuntimeError):
    """A durable step failed; the transaction cannot continue safely."""


class FileLock:
    """A cooperating advisory lock (flock) beside the target AppImage.

    Supported cycle entry points hold it in shared mode while a cycle is
    starting or running; the installer needs exclusivity, so a running
    cycle makes installation impossible and it is refused instead. Locks
    die with the owning process, so a crash can never strand one.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._fd: int | None = None

    @property
    def path(self) -> Path:
        return self._path

    def is_held(self) -> bool:
        return self._fd is not None

    def acquire(self, *, exclusive: bool) -> bool:
        """Lock from scratch, non-blocking; False when someone else holds it."""
        if self._fd is not None:
            raise TransactionError("this lock is already held by this process")
        try:
            fd = os.open(self._path, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o600)
        except OSError as exc:
            raise TransactionError(f"could not open the lock file: {exc}") from exc
        try:
            mode = (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB
            fcntl.flock(fd, mode)
        except OSError:
            os.close(fd)
            return False
        self._fd = fd
        return True

    def release(self) -> None:
        if self._fd is None:
            return
        try:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
        finally:
            os.close(self._fd)
            self._fd = None


def prefixed(target: Path, mark: str) -> str:
    return f".{target.name}.{mark}"


def journal_path(target: Path) -> Path:
    return target.with_name(prefixed(target, "journal"))


def update_lock_path(target: Path) -> Path:
    return target.with_name(prefixed(target, "update-lock"))


def is_owned_path(path: Path, target: Path, mark: str) -> bool:
    """True when ``path`` is an updater-owned artifact of this target.

    Journal content is untrusted, so a recorded path is only used when it
    matches the updater-owned naming convention beside the target; cleanup
    can then never be steered at an arbitrary file.
    """
    prefix = prefixed(target, mark)
    if path.parent != target.parent or not path.name.startswith(prefix):
        return False
    suffix = path.name[len(prefix):]
    return bool(suffix) and "/" not in suffix and suffix not in (".", "..")


def file_sha256(path: Path, *, chunk: int = 1024 * 1024) -> str:
    """Incremental SHA-256 of a file, read in bounded chunks."""
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        while piece := handle.read(chunk):
            hasher.update(piece)
    return hasher.hexdigest()


def fsync_directory(path: Path) -> None:
    """Flush a directory's metadata so a rename survives a crash."""
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_journal(target: Path, payload: dict[str, object]) -> None:
    """Write the journal atomically; a crash never leaves a partial file."""
    save = QSaveFile(str(journal_path(target)))
    if not save.open(QSaveFile.OpenModeFlag.WriteOnly):
        raise TransactionError(
            f"could not open the update journal: {save.errorString()}"
        )
    try:
        save.write(json.dumps(payload, indent=1).encode("utf-8"))
        if not save.commit():
            raise TransactionError(
                f"could not write the update journal: {save.errorString()}"
            )
    finally:
        del save


def load_journal(target: Path) -> dict[str, object] | None:
    """Read and validate the journal; None when absent.

    Raises TransactionError for a journal that exists but is unreadable or
    fails ownership validation, so recovery never trusts unknown content.
    The staging record is required only for a "staged" transaction; after
    the replacement the staging file was consumed and no longer exists.
    """
    path = journal_path(target)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise TransactionError(f"the update journal is unreadable: {exc}") from exc
    if not isinstance(payload, dict) or payload.get(JOURNAL_MARKER) != JOURNAL_VERSION:
        raise TransactionError("the update journal is not a Strom update journal")
    state = payload.get("state")
    if state not in JOURNAL_STATES:
        raise TransactionError("the update journal has an unknown state")
    recorded = payload.get("target")
    if not isinstance(recorded, dict) or recorded.get("path") != str(target):
        raise TransactionError("the update journal describes a different target")
    try:
        info = os.stat(target)
    except OSError as exc:
        raise TransactionError(f"the recorded AppImage is unreadable: {exc}") from exc
    if recorded.get("device") != info.st_dev or recorded.get("inode") != info.st_ino:
        raise TransactionError(
            "the update journal does not describe the current AppImage file"
        )
    backup = payload.get("backup")
    if not isinstance(backup, dict) or not isinstance(backup.get("path"), str):
        raise TransactionError("the update journal has no usable backup record")
    if not is_owned_path(Path(str(backup["path"])), target, BACKUP_MARK):
        raise TransactionError("the update journal backup path is not updater-owned")
    if state == "staged":
        staging = payload.get("staging")
        if not isinstance(staging, dict) or not isinstance(staging.get("path"), str):
            raise TransactionError("the update journal has no usable staging record")
        if not is_owned_path(Path(str(staging["path"])), target, STAGING_MARK):
            raise TransactionError(
                "the update journal staging path is not updater-owned"
            )
    return payload


def _target_record(target: AppImageIdentity) -> dict[str, object]:
    return {
        "path": str(target.path),
        "device": target.device,
        "inode": target.inode,
        "arch": target.arch,
    }


@dataclass(frozen=True)
class Transaction:
    """Everything the coordinator needs between the durable steps."""

    target: AppImageIdentity
    release: ReleaseInfo
    staging: Path
    backup: Path


def prepare_transaction(
    target: AppImageIdentity,
    release: ReleaseInfo,
    staging: Path,
    staging_size: int,
    staging_sha256: str,
) -> Transaction:
    """Steps 2–3: revalidate, preserve one backup, journal "staged".

    Raises InstallRefused before anything is touched when the target has
    changed; TransactionError when the durable preparation itself fails.
    """
    if not target.identity_matches():
        raise InstallRefused(
            "The AppImage at the recorded location has changed; refusing to "
            "replace it."
        )
    if staging.stat().st_size != staging_size:
        raise TransactionError("the downloaded update changed since verification")
    if file_sha256(staging) != staging_sha256:
        raise TransactionError("the downloaded update no longer matches its checksum")
    usage = shutil.disk_usage(target.path.parent)
    if usage.free < staging_size + DISK_MARGIN_BYTES:
        raise TransactionError("not enough free disk space to install the update")
    backup = target.path.with_name(prefixed(target.path, BACKUP_MARK) + uuid.uuid4().hex)
    try:
        os.link(target.path, backup)
    except OSError:
        # A hard link preserves the old inode with no copy; fall back to a
        # real copy when the filesystem refuses links.
        shutil.copyfile(target.path, backup)
        os.chmod(backup, stat.S_IMODE(os.stat(target.path).st_mode))
    try:
        write_journal(
            target.path,
            {
                JOURNAL_MARKER: JOURNAL_VERSION,
                "state": "staged",
                "target": _target_record(target),
                "backup": {"path": str(backup)},
                "staging": {
                    "path": str(staging),
                    "size": staging_size,
                    "sha256": staging_sha256,
                },
                "release": {"version": str(release.version), "tag": release.tag},
                "pid": os.getpid(),
            },
        )
    except TransactionError:
        # The journal never recorded the backup, so recovery cannot know
        # about it; remove it here instead of leaking an orphan.
        try:
            backup.unlink()
        except OSError:
            pass
        raise
    return Transaction(target=target, release=release, staging=staging, backup=backup)


def commit_replacement(target: AppImageIdentity, staging: Path, backup: Path) -> None:
    """Step 5: atomically replace the original and journal "replaced".

    The staging file already sits beside the target (one filesystem); the
    old inode is never truncated or written in place — the backup link
    keeps the previous version recoverable. The journal records the
    identity of the file that is now at the target path (re-read here), so
    the replacement instance's own recovery validation succeeds.
    """
    with staging.open("rb") as handle:
        os.fsync(handle.fileno())
    os.replace(staging, target.path)
    # The replacement must be launchable immediately, as an AppImage is.
    os.chmod(target.path, 0o755)
    fsync_directory(target.path.parent)
    fresh = _fresh_identity(target.path)
    write_journal(
        target.path,
        {
            JOURNAL_MARKER: JOURNAL_VERSION,
            "state": "replaced",
            "target": fresh,
            "backup": {"path": str(backup)},
            "release": {},
            "pid": os.getpid(),
        },
    )


def mark_acknowledged(target: AppImageIdentity, backup: Path) -> None:
    """Journal "acknowledged" after the replacement instance confirmed start."""
    write_journal(
        target.path,
        {
            JOURNAL_MARKER: JOURNAL_VERSION,
            "state": "acknowledged",
            "target": _fresh_identity(target.path),
            "backup": {"path": str(backup)},
            "release": {},
            "pid": os.getpid(),
        },
    )


def _fresh_identity(path: Path) -> dict[str, object]:
    info = os.stat(path)
    return {
        "path": str(path),
        "device": info.st_dev,
        "inode": info.st_ino,
        "arch": read_elf_machine(path),
    }


def restore_previous(target: AppImageIdentity, backup: Path) -> None:
    """Put the recorded previous version back (failed-restart recovery)."""
    if not backup.is_file():
        raise TransactionError(
            f"the backup of the previous version is missing: {backup}"
        )
    os.replace(backup, target.path)
    fsync_directory(target.path.parent)


def clear_journal(target: AppImageIdentity | None) -> None:
    if target is None:
        return
    try:
        journal_path(target.path).unlink()
    except FileNotFoundError:
        pass


def discard_transaction(
    target: AppImageIdentity | None,
    staging: Path | None,
    backup: Path | None,
) -> None:
    """Rollback before any replacement: discard staging and backup."""
    for path in (staging, backup):
        if path is None:
            continue
        try:
            path.unlink()
        except FileNotFoundError:
            pass
    clear_journal(target)


def prune_backups(target: AppImageIdentity, *, keep: int = KEEP_BACKUPS) -> None:
    """Delete the oldest updater-owned backups beyond ``keep``.

    Only files matching the exact updater-owned backup naming beside this
    target are candidates; unrelated files are never touched.
    """
    prefix = prefixed(target.path, BACKUP_MARK)
    try:
        candidates = [
            entry
            for entry in target.path.parent.iterdir()
            if entry.is_file() and entry.name.startswith(prefix)
        ]
    except OSError:
        return
    candidates.sort(key=lambda entry: entry.stat().st_mtime_ns, reverse=True)
    for stale in candidates[keep:]:
        try:
            stale.unlink()
        except OSError:
            pass


def prune_staging(target: AppImageIdentity) -> None:
    """Delete updater-owned staging files left by an abandoned download.

    A staging file is only useful while a transaction records it; recovery
    runs before any new download, so anything else beside the target was
    abandoned when the app closed.
    """
    prefix = prefixed(target.path, STAGING_MARK)
    try:
        candidates = [
            entry
            for entry in target.path.parent.iterdir()
            if entry.is_file() and entry.name.startswith(prefix)
        ]
    except OSError:
        return
    for stale in candidates:
        try:
            stale.unlink()
        except OSError:
            pass


def recover(target: AppImageIdentity, *, keep: int = KEEP_BACKUPS) -> str | None:
    """Startup recovery for an interrupted transaction (update plan §5).

    Returns the backup location when the new version is already in place,
    None when there was nothing to recover. Raises TransactionError when a
    journal exists but cannot be trusted; the caller then refuses further
    updates instead of guessing.
    """
    payload = load_journal(target.path)  # raises on corrupt/unowned records
    if payload is None:
        # No transaction is in flight, so any staging file is abandoned
        # (the app closed before installing the verified download).
        prune_staging(target)
        return None
    if str(payload["state"]) == "staged":
        # The replacement never happened: the original is intact at the
        # target, so staging and backup are both safe to discard.
        staging_section = payload["staging"]
        backup_section = payload["backup"]
        assert isinstance(staging_section, dict) and isinstance(backup_section, dict)
        discard_transaction(
            target,
            Path(str(staging_section["path"])),
            Path(str(backup_section["path"])),
        )
        prune_staging(target)
        return None
    # "replaced"/"acknowledged": the new version is in place and running.
    # Delete the journal, keep one recoverable backup and prune older ones
    # so backup cleanup stays bounded.
    clear_journal(target)
    prune_backups(target, keep=keep)
    prune_staging(target)
    backup_section = payload.get("backup")
    assert isinstance(backup_section, dict)
    return str(backup_section["path"])
