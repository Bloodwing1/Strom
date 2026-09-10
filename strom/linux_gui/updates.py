"""Release selection for the in-app updater (update plan §2).

Immutable data and pure functions only: no widgets, no Qt, no network, no
filesystem writes. The repository is fixed to ``Bloodwing1/Strom``; release
text is treated as untrusted data and never used for repository, command or
destination values.

Channel rule (proposed product default, documented in tests and UI help):
stable installations follow stable releases only; prerelease installations
also follow newer prereleases. Downgrades are never offered. A release
missing or duplicating its required assets cannot be installed but is still
counted when finding the newest published version.
"""

from __future__ import annotations

import enum
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from packaging.version import InvalidVersion, Version

REPOSITORY_OWNER = "Bloodwing1"
REPOSITORY_NAME = "Strom"
RELEASES_PAGE_URL = f"https://github.com/{REPOSITORY_OWNER}/{REPOSITORY_NAME}/releases"
DOWNLOAD_PATH_PREFIX = (
    f"/{REPOSITORY_OWNER}/{REPOSITORY_NAME}/releases/download/"
)
API_RELEASES_URL = (
    f"https://api.github.com/repos/{REPOSITORY_OWNER}/{REPOSITORY_NAME}/releases"
)
DOWNLOAD_HOSTS = (
    "github.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
)
RELEASES_PER_PAGE = 100
CHECKSUMS_ASSET_NAME = "SHA256SUMS"


@dataclass(frozen=True)
class ReleaseAsset:
    """One downloadable release file, exactly as enumerated by the API."""

    name: str
    url: str
    size: int


@dataclass(frozen=True)
class ReleaseInfo:
    """One published release parsed from the API.

    ``appimage``/``checksums`` are the exactly-one required assets, or None
    when that release is missing or ambiguous — such a release is counted
    (so a newer one is never misread as "up to date") but cannot be
    installed.
    """

    tag: str
    version: Version
    prerelease: bool
    appimage: ReleaseAsset | None
    checksums: ReleaseAsset | None

    @property
    def is_installable(self) -> bool:
        return self.appimage is not None and self.checksums is not None

    @property
    def appimage_name(self) -> str:
        assert self.appimage is not None
        return self.appimage.name


def appimage_asset_name(version: Version, arch: str | None) -> str | None:
    """The asset name the release workflow produces, or None without an arch."""
    if not arch:
        return None
    return f"Strom-{version}-{arch}.AppImage"


def parse_release(item: Mapping[str, object], arch: str | None) -> ReleaseInfo | None:
    """Parse one API release object.

    Drafts, non-``v`` or malformed tags and releases with malformed asset
    objects yield None and are skipped safely, never misread as "up to
    date". Missing or duplicated required assets mark the release
    uninstallable instead.
    """
    try:
        if item.get("draft"):
            return None
        tag = item.get("tag_name")
        if not isinstance(tag, str) or not tag.startswith("v"):
            return None
        version = Version(tag[1:])
    except (AttributeError, InvalidVersion, TypeError):
        return None
    assets = item.get("assets")
    if not isinstance(assets, list):
        return None
    wanted = appimage_asset_name(version, arch)
    return ReleaseInfo(
        tag=tag,
        version=version,
        prerelease=bool(item.get("prerelease")) or version.is_prerelease,
        appimage=_sole_asset(assets, wanted),
        checksums=_sole_asset(assets, CHECKSUMS_ASSET_NAME),
    )


def _sole_asset(
    assets: list[object], wanted_name: str | None
) -> ReleaseAsset | None:
    """Exactly one asset named ``wanted_name`` with usable download data.

    Missing, duplicated, or unusable (no URL or size) entries mean the
    release cannot be installed.
    """
    if wanted_name is None:
        return None
    matches = []
    for entry in assets:
        if not isinstance(entry, Mapping):
            continue
        if entry.get("name") != wanted_name:
            continue
        matches.append(_asset(entry))
    if len(matches) != 1:
        return None
    return matches[0]


def _asset(entry: Mapping[str, object]) -> ReleaseAsset | None:
    try:
        url = entry["browser_download_url"]
        size = entry["size"]
    except KeyError:
        return None
    name = entry.get("name")
    if (
        not isinstance(url, str)
        or not url
        or not isinstance(size, int)
        or not isinstance(name, str)
    ):
        return None
    return ReleaseAsset(name=name, url=url, size=size)


class SelectionKind(enum.Enum):
    """Structured outcomes of a release selection."""

    UP_TO_DATE = "up to date"
    AVAILABLE = "available"


@dataclass(frozen=True)
class Selection:
    """The result of comparing published releases with the running version.

    ``kind`` is UP_TO_DATE when no installable candidate is strictly newer,
    and ``note`` explains a newer release that had no usable asset.
    """

    kind: SelectionKind
    candidate: ReleaseInfo | None = None
    note: str | None = None


def is_newer(candidate: Version, current: Version) -> bool:
    """Channel rule: strictly newer, and prereleases only follow prereleases."""
    if candidate <= current:
        return False
    if candidate.is_prerelease and not current.is_prerelease:
        return False
    return True


def select_update(
    releases: Sequence[Mapping[str, object]],
    current: Version,
    arch: str | None,
) -> Selection:
    """Pick the update offer from an already-fetched release list.

    Pure function: the caller fetches the releases and passes them in. A hit
    must be strictly newer under the channel rule; equal or older tags never
    produce an offer.
    """
    parsed = [
        release
        for item in releases
        if isinstance(item, Mapping)
        for release in (parse_release(item, arch),)
        if release is not None
    ]
    candidates = [
        entry for entry in parsed if entry.is_installable and is_newer(entry.version, current)
    ]
    best = max(
        candidates,
        key=lambda entry: (entry.version, not entry.prerelease),
        default=None,
    )
    if best is not None:
        return Selection(kind=SelectionKind.AVAILABLE, candidate=best)
    newest_seen = max((entry.version for entry in parsed), default=None)
    note = None
    if newest_seen is not None and newest_seen > current:
        note = (
            f"A newer release ({newest_seen}) was found, but it has no "
            "installable AppImage asset for this architecture."
        )
    return Selection(kind=SelectionKind.UP_TO_DATE, candidate=None, note=note)
