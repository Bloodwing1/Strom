"""Release selection for the in-app updater (update plan §2).

Immutable data and pure functions only: no widgets, no Qt, no network, no
filesystem writes. The repository is fixed to ``Bloodwing1/Strom``; release
text is treated as untrusted data and never used for repository, command or
destination values.

Channel rule (proposed product default, documented in tests and UI help):
stable installations follow stable releases only; prerelease installations
also follow newer prereleases. Downgrades are never offered. A release
missing or duplicating its required assets cannot be installed but is still
counted when finding the newest published version. Pagination uses a
defined cap; when the cap prevents a complete result the outcome says so
instead of claiming the app is current.
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
MAX_RELEASE_PAGES = 5
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
    INCOMPLETE = "incomplete"


@dataclass(frozen=True)
class Selection:
    """The result of comparing published releases with the running version.

    ``kind`` is INCOMPLETE when the pagination cap may have hidden newer
    releases — that is never reported as an up-to-date result — and carries
    an installable candidate whenever one was found.
    """

    kind: SelectionKind
    candidate: ReleaseInfo | None = None
    newest_seen: Version | None = None
    note: str | None = None


def is_newer(candidate: Version, current: Version) -> bool:
    """Channel rule: strictly newer, and prereleases only follow prereleases."""
    if candidate <= current:
        return False
    if candidate.is_prerelease and not current.is_prerelease:
        return False
    return True


def select_update(
    pages: Sequence[Sequence[Mapping[str, object]]],
    current: Version,
    arch: str | None,
) -> Selection:
    """Pick the update offer from already-fetched release pages.

    Pure function: the caller fetches pages and passes them in. A hit must
    be strictly newer under the channel rule; equal or older tags never
    produce an offer, and a pagination cap that leaves the list incomplete
    is reported instead of being read as "up to date".
    """
    parsed = [
        release
        for page in pages
        for item in page
        if isinstance(item, Mapping)
        for release in (parse_release(item, arch),)
        if release is not None
    ]
    newest_seen = max((entry.version for entry in parsed), default=None)
    incomplete = (
        bool(pages)
        and len(pages) >= MAX_RELEASE_PAGES
        and len(pages[-1]) >= RELEASES_PER_PAGE
    )
    candidates = [
        entry for entry in parsed if entry.is_installable and is_newer(entry.version, current)
    ]
    best = max(
        candidates,
        key=lambda entry: (entry.version, not entry.prerelease),
        default=None,
    )
    if best is not None:
        return Selection(
            kind=SelectionKind.INCOMPLETE if incomplete else SelectionKind.AVAILABLE,
            candidate=best,
            newest_seen=newest_seen,
            note=(
                "The release list was too long to check completely; newer "
                "releases may exist."
            )
            if incomplete
            else None,
        )
    note = None
    if incomplete:
        note = (
            "The release list was too long to check completely, so this "
            "cannot prove the app is current."
        )
    elif newest_seen is not None and newest_seen > current:
        note = (
            f"A newer release ({newest_seen}) was found, but it has no "
            "installable AppImage asset for this architecture."
        )
    return Selection(
        kind=SelectionKind.INCOMPLETE if incomplete else SelectionKind.UP_TO_DATE,
        candidate=None,
        newest_seen=newest_seen,
        note=note,
    )
