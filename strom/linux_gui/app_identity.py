"""Runtime version lookup and AppImage installation identity (update plan §1).

``pyproject.toml`` is the single build-time version source. Installed Python
builds report their package metadata and the frozen AppImage bundle ships
that same metadata (``copy_metadata`` in ``packaging/appimage/strom.spec``);
this module never reads a repository pyproject file at runtime and never
invents a fallback version literal. An unavailable or invalid version
disables in-place installation with a clear user-facing reason instead of
silently becoming version zero.

Installation capability requires a frozen build plus a *validated* original
AppImage path: ``APPIMAGE`` is only a candidate path, never proof of
ownership. The candidate must be an absolute existing regular file (symlinks
are rejected), a supported architecture (the ELF machine of the file itself,
not the file name), and both the file and its directory must be writable.
``sys.executable`` inside a frozen bundle is the inner executable, so the
external ``APPIMAGE`` path is the only thing the updater may replace.
"""

from __future__ import annotations

import os
import stat
import sys
from typing import Literal
from collections.abc import Mapping
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path

from packaging.version import InvalidVersion, Version

APPIMAGE_ENV = "APPIMAGE"
EXTRACT_AND_RUN_ENV = "APPIMAGE_EXTRACT_AND_RUN"
EXTRACT_AND_RUN_SWITCH = "--appimage-extract-and-run"

#: Assets and artifacts of the updater carry this architecture token.
SUPPORTED_ARCH = "x86_64"

_ELF_MAGIC = b"\x7fELF"
_ELF_MACHINE_CODES = {"x86_64": 62, "aarch64": 183}

SOURCE_INSTALL_REASON = (
    "This Strom runs from Python source or pip, not from an AppImage, so it "
    "cannot replace itself in place. Download the new version from the "
    "release page instead."
)
VERSION_UNAVAILABLE_REASON = (
    "The installed Strom version could not be read, so in-place updating is "
    "disabled. Download the new release from the release page."
)
EXTRACTED_DIR_REASON = (
    "Strom is running from an extracted AppDir without a verifiable original "
    "AppImage, so in-place updating is unavailable. Download the new release "
    "from the release page instead."
)
MISSING_APPIMAGE_REASON = (
    "The original AppImage file is missing, so in-place updating is "
    "unavailable. Download the new release from the release page."
)
SYMLINK_REASON = (
    "The AppImage is a symbolic link, which the updater does not replace. "
    "Download the new release from the release page or update the link "
    "target by hand."
)
ARCH_REASON = (
    "This Strom AppImage has an architecture the updater does not support. "
    "Download the matching release from the release page."
)
WRITE_REASON = (
    "The AppImage location is not writable, so in-place updating is "
    "unavailable. Move Strom to a writable folder or update it from the "
    "release page."
)


def runtime_version(dist_name: str = "strom") -> Version | None:
    """The installed package version, or None when missing or invalid.

    Package metadata ships with every distribution form, so a frozen bundle
    reports its version exactly like a pip install. There is deliberately no
    version-zero fallback: None means "unknown" and callers disable
    installation.
    """
    try:
        raw = metadata.version(dist_name)
    except metadata.PackageNotFoundError:
        return None
    try:
        return Version(raw)
    except InvalidVersion:
        return None


def read_elf_machine(path: Path) -> str | None:
    """The ELF machine token of a file (``x86_64``/``aarch64``), or None.

    The token is read from the header itself — not from the file name — so
    the check reflects what the file actually is.
    """
    try:
        with path.open("rb") as handle:
            header = handle.read(20)
    except OSError:
        return None
    if len(header) < 20 or not header.startswith(_ELF_MAGIC):
        return None
    if header[5] == 1:
        order: Literal["little", "big"] = "little"
    elif header[5] == 2:
        order = "big"
    else:
        return None
    code = int.from_bytes(header[18:20], order)
    for token, known in _ELF_MACHINE_CODES.items():
        if code == known:
            return token
    return None


@dataclass(frozen=True)
class AppImageIdentity:
    """A validated original AppImage plus its on-disk file identity."""

    path: Path
    device: int
    inode: int
    arch: str

    def identity_matches(self) -> bool:
        """True while the file at :attr:`path` is still the recorded one."""
        try:
            info = os.stat(self.path)
        except OSError:
            return False
        return (
            stat.S_ISREG(info.st_mode)
            and info.st_dev == self.device
            and info.st_ino == self.inode
        )


def validate_appimage(path: Path) -> AppImageIdentity | None:
    """Validate a candidate AppImage path; None when unusable for updates."""
    try:
        if not path.is_absolute() or path.is_symlink() or not path.is_file():
            return None
        info = os.stat(path)
    except OSError:
        return None
    if not stat.S_ISREG(info.st_mode):
        return None
    arch = read_elf_machine(path)
    if arch is None:
        return None
    return AppImageIdentity(
        path=path, device=info.st_dev, inode=info.st_ino, arch=arch
    )


@dataclass(frozen=True)
class InstallStatus:
    """Structured install capability plus the user-facing reason when absent.

    ``reason`` is a stable English sentence (translated by the GUI); when
    installation is possible it is empty.
    """

    can_install: bool
    reason: str
    version: Version | None
    identity: AppImageIdentity | None


def _frozen() -> bool:
    """True inside a PyInstaller bundle (AppImage or extracted AppDir)."""
    return bool(getattr(sys, "frozen", False))


def install_status(
    *,
    environ: Mapping[str, str] | None = None,
    frozen: bool | None = None,
    version: Version | None = None,
) -> InstallStatus:
    """Classify this runtime for the updater (source / extracted / installable)."""
    environ = os.environ if environ is None else environ
    version = runtime_version() if version is None else version
    if frozen is None:
        frozen = _frozen()
    if not frozen:
        return InstallStatus(
            can_install=False, reason=SOURCE_INSTALL_REASON, version=version,
            identity=None,
        )
    if version is None:
        return InstallStatus(
            can_install=False, reason=VERSION_UNAVAILABLE_REASON, version=None,
            identity=None,
        )
    raw = environ.get(APPIMAGE_ENV) if environ is not None else None
    if not raw:
        return InstallStatus(
            can_install=False, reason=EXTRACTED_DIR_REASON, version=version,
            identity=None,
        )
    identity = validate_appimage(Path(raw))
    if identity is None:
        try:
            candidate = Path(raw)
            linked = candidate.is_symlink()
        except OSError:
            linked = False
        reason = SYMLINK_REASON if linked else MISSING_APPIMAGE_REASON
        return InstallStatus(
            can_install=False, reason=reason, version=version, identity=None,
        )
    if identity.arch != SUPPORTED_ARCH:
        return InstallStatus(
            can_install=False, reason=ARCH_REASON, version=version,
            identity=identity,
        )
    try:
        writable = os.access(identity.path, os.W_OK) and os.access(
            identity.path.parent, os.W_OK
        )
    except OSError:
        writable = False
    if not writable:
        return InstallStatus(
            can_install=False, reason=WRITE_REASON, version=version,
            identity=identity,
        )
    return InstallStatus(
        can_install=True, reason="", version=version, identity=identity
    )
