# AppImage build and release maintenance

User-facing installation instructions live in the repository README. This
document is for maintainers: how to build locally, how to update the pinned
build inputs, and how to publish a release. The design constraints behind all
of this are in `docs/linux-qt-app/appimage-implementation-guide.md`.

## Files

| File | Purpose |
| --- | --- |
| `strom_entry.py` | Packaged entry point; internal dispatcher (`--strom-cli`, `--strom-self-test`). |
| `strom.spec` | PyInstaller spec (one-directory mode). |
| `AppRun` | AppDir launcher (quoted, `exec`, no host python). |
| `strom.desktop` | Desktop entry shipped inside the AppDir. |
| `build.sh` | The single local build command: fresh venv, freeze, AppDir, staged AppRun self-test, ELF baseline audit, pinned-tool AppImage, artifact verification. |
| `build-requirements.txt` | Deliberate build-tool pins (PyInstaller, bundled tzdata). |
| `build-constraints.txt` | Resolved pins for the whole build environment (generated, then enforced). |
| `tool-hashes.sha256` | Checked-in SHA256 of the pinned appimagetool and runtime. |
| `verify-ubuntu2204.sh` | Runs the artifact inside a clean Ubuntu 22.04 container (self-test + X11 under Xvfb). |

## Local build

One command (staging goes to `build-appimage/`, which is gitignored):

```sh
packaging/appimage/build.sh
```

Requirements: Python 3.12 (`STROM_BUILD_PYTHON` overrides), network for the
fresh build venv and the pinned tools (downloaded once into
`build-appimage/tools/` and hash-verified on every run). Optional but
recommended: `desktop-file-utils`, `libfuse2` (enables the FUSE-mount launch
check), and `podman` (enables the Ubuntu 22.04 container verification). Every
missing optional check is skipped with a clear log line rather than assumed.

The script runs, in order: fresh venv with pinned inputs → PyInstaller
freeze → AppDir assembly and validation → staged AppRun `--strom-self-test`
(before anything becomes an AppImage) → ELF audit against the glibc 2.35 /
GLIBCXX 3.4.30 / CXXABI 1.3.13 baseline → AppImage with pinned tools →
artifact self-test via FUSE (if available) and extract-and-run → Ubuntu 22.04
container check (if podman is available). Provenance (commit, versions,
hashes, artifact sha256) lands in `build-appimage/provenance.txt`.

## Updating the pinned inputs

All pin updates are deliberate edits, reviewed like any other code change:

- **Python build dependencies** (`build-constraints.txt`): after changing
  `pyproject.toml` or upgrading PyInstaller in `build-requirements.txt`, run
  `packaging/appimage/build.sh --write-constraints`, review the regenerated
  file, and commit it. Never paste a developer machine's `pip freeze`.
- **Packaging tools** (`tool-hashes.sha256`): both tools are pinned to tagged
  releases — the URLs and versions live in `build.sh`. To move to a new
  release, update both URLs, download the files, run
  `sha256sum appimagetool-x86_64.AppImage runtime-x86_64`, and replace the
  hashes in `tool-hashes.sha256`. `build.sh` re-verifies them on every run.
- **Compatibility baseline**: the defaults are Ubuntu 22.04 (glibc 2.35 /
  GLIBCXX 3.4.30 / CXXABI 1.3.13). Raising them (via `STROM_MIN_GLIBC`,
  `STROM_MIN_GLIBCXX`, `STROM_MIN_CXXABI`) is a documented decision: record
  it in the guide and the README, and re-run the full verification.

## Publishing a release

1. Set the version in `pyproject.toml` and commit.
2. Tag the exact commit: `git tag v0.3.0 && git push origin v0.3.0`.
   Prereleases use PEP 440 suffixes (`v0.3.0rc1`, `v0.3.0b1`, `v0.3.0a1`);
   the workflow marks those releases as prereleases. Anything else
   (`v1.2`, `v1.0.0.dev1`, a tag that does not match `pyproject.toml`) is
   rejected with a clear error.
3. The `AppImage` workflow then: runs the existing test gates for the tagged
   commit, builds and verifies the AppImage on a pinned runner, validates the
   tag against `pyproject.toml`, and publishes `Strom-<version>-x86_64.AppImage`
   plus `SHA256SUMS` as a draft first — published only after the uploaded
   assets are downloaded back and checksum-verified.

Rerun semantics (same tag pushed again or a rerun of the failed jobs):

- A published release with the identical artifact is a no-op.
- A published release with a **different** binary is never overwritten; the
  workflow fails loudly instead.
- An incomplete draft is resumed: its same-name assets are replaced with the
  new run's, re-verified, and then it is published.

Do not create releases by hand for versions that the workflow should ship;
the workflow is the only path that attaches the exact tested artifact. The
first public release still requires a human review of the workflow's first
real run on GitHub — locally validated workflows and GitHub-run workflows are
different things.
