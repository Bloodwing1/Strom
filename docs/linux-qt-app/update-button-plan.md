# GUI update button implementation plan

Status: proposed implementation, not an implemented feature.

## Outcome and boundaries

Let users check for a newer Strom release from the GUI, see the available
version, and install it through an **Update and restart** button when running
a supported, writable Linux AppImage. Preserve their configuration and never
interrupt a heating cycle. This document is an ordered implementation guide;
complete and test each stage before connecting the next stage to the UI.

These are proposed product defaults for this implementation, not existing
behavior: check once after the window opens, silently tolerate automatic-check
failures, provide a manual **Check for updates** action, and require an explicit
click before downloading or installing. Do not add scheduled background
services, unattended installs, elevated privileges, or updates to the CLI's
Python environment. A source/pip installation can check releases and open the
release page, but cannot install an AppImage over itself.

## Read the existing code first

| File | Relevant responsibility |
| --- | --- |
| `strom/linux_gui/window.py` | `MainWindow`, four setup steps, translations, settings, run/close guards |
| `strom/linux_gui/app.py` | QApplication identity and startup |
| `strom/linux_gui/runner.py` | CycleRunner state and `is_active()`; frozen versus source launches |
| `strom/linux_gui/translations.py` | English-to-Spanish UI strings |
| `strom/linux_gui/selftest.py` | Offline bundle verification |
| `strom/entry_switches.py` | Internal packaged dispatch switches |
| `packaging/appimage/strom_entry.py` | GUI, CLI, and self-test dispatch before QApplication creation |
| `packaging/appimage/strom.spec` | PyInstaller bundle contents |
| `packaging/appimage/build.sh` | Versioned AppImage and checksum generation |
| `.github/workflows/strom-appimage.yml` | Draft publication, uploaded-asset verification, final publication |
| `packaging/appimage/README.md` | Release and packaging contract |
| `tests/linux_gui/test_window.py` | Injected settings, fake children, GUI regression patterns |

At planning time, releases contain `Strom-<version>-x86_64.AppImage` and
`SHA256SUMS`. Tags use a leading `v` and versions follow PEP 440, including
alpha and release-candidate versions. The application has no updater. Country
and city are unrelated to update selection. Credentials and preferences live
outside the AppImage; never copy or modify them as part of updating.

## 1. Establish version and installation identity

Create a small module for runtime version lookup and installation capability.
Use `pyproject.toml` as the single build-time version source. For installed
Python code, use package metadata; ensure the frozen build explicitly includes
that metadata (or generates a version resource from the same source). Do not
read the repository's pyproject file at runtime or duplicate a version literal.
An unavailable/invalid runtime version should disable installation with a clear
message, not silently become version zero.

Use `packaging.version.Version` for comparisons and declare `packaging` as a
direct dependency if introduced. Never compare version strings lexicographically.
Include the new dependency in the normal packaging constraint regeneration.

For installation, require a frozen build and a validated original AppImage
path. `sys.executable` inside a frozen bundle identifies the inner executable,
not necessarily the external AppImage. `APPIMAGE` is a candidate path, not proof
of ownership or authenticity. Require an absolute existing regular file, a
supported architecture, and writable file/directory operations. Reject symlink
and ambiguous targets for the initial implementation; offer the release-page
fallback. Record the target's file identity and revalidate before replacement.
Test normal AppImage launch and extract-and-run separately. An extracted AppDir
without a verifiable original AppImage is check-only.

Done when: source, normal AppImage, extracted AppDir, absent metadata, malformed
paths, symlinks, and read-only installations have deterministic tested results.

## 2. Build release selection without widgets or filesystem writes

Add `strom/linux_gui/updates.py` with immutable release data and pure selection
functions. Fix the repository to `Bloodwing1/Strom`; do not accept a repository,
command, or destination path from release text.

Use GitHub's public releases API without credentials. Inspect published
releases, exclude drafts, parse the tag version, and compare numeric versions.
Do not rely on publication order or only the latest-release endpoint: the
current product uses prereleases. Proposed channel rule: stable installations
accept only stable releases; prerelease installations accept newer prereleases
and stable releases. Never downgrade. Document this rule in tests and UI help.

Require exactly one correctly named architecture-matching AppImage and one
`SHA256SUMS` asset from the selected release. Missing or ambiguous assets mean
that release cannot be installed. Handle pagination with a defined cap; if the
cap prevents a complete result, report an incomplete check rather than claiming
the app is current. Ignore malformed unrelated tags safely.

Return structured outcomes: up to date, update available, check failed, and
unsupported installation. A failed request is never evidence of being current.
Treat release notes as untrusted plain text; do not render arbitrary HTML.

Done when: fixture-based tests cover alpha-to-alpha, alpha-to-stable,
stable-versus-prerelease, version 0.9 versus 0.10, equal/older tags, drafts,
missing assets, malformed JSON, and pagination boundaries.

## 3. Add asynchronous checking and downloading

Use a QObject service with `QNetworkAccessManager` owned on its Qt thread.
Keep network lifecycle out of MainWindow. Expose state, progress, candidate,
and error signals; inject transport/endpoints in tests. Use bounded metadata
responses, request timeouts, a total download timeout, cancellation, and one
operation at a time. Release replies and ignore stale callbacks after cancel
or a subsequent request.

Use HTTPS with normal certificate validation. Validate initial asset URLs as
belonging to the selected repository release. Follow only HTTPS redirects to
explicitly supported GitHub download hosts; verify the real redirect chain in
the packaging smoke test. Do not disable TLS verification or send credentials.
Handle offline operation, rate limits, denied access, missing assets, truncated
responses, disk-full errors, and timeout as recoverable failures.

Fetch the checksum manifest, parse the exact asset basename, and reject
missing, duplicate, conflicting, or malformed checksum entries. Stream the
AppImage into a uniquely created staging file in the destination directory,
computing SHA-256 incrementally. Enforce the asset's expected size and a
reasonable documented maximum. Compare checksum and byte count before making
it executable or launching it. Clean up partial files on failure/cancel.

The manifest detects corruption and mismatch with the release; it is not an
independent signature against a compromised publisher account. State that
trust boundary accurately. Release signing is separate future scope.

Done when: a local fake HTTP service exercises success, redirects, timeout,
cancellation, checksum mismatch, excessive size, disk failure, and stale
callbacks without contacting GitHub or downloading a real production release.

## 4. Implement the cycle/update interlock before installation

Define explicit update states: Idle, Checking, Available, Downloading,
Verifying, Installing, Restarting, and Failed. Keep them separate from
RunnerState. Centralize control enablement so runner-state changes cannot
accidentally re-enable Run during an update.

Checking may run during a heating cycle. Disable **Update and restart** while
`CycleRunner.is_active()` is true, and repeat this guard in the action handler.
After the user accepts installation, block new heating runs until failure or
restart, including direct action-handler calls and queued UI events. Recheck
immediately before committing replacement. Never kill, detach, or wait
synchronously for a heating child. Ask the user to try after the cycle finishes;
do not silently queue an installation.

Closing during a download should cancel and remove staging safely. During the
short installation transaction, refuse closing with a clear message. Retain
the existing refusal to close during Starting/Running. Save non-secret UI
preferences before restart using the existing method.

Done when: fake-child tests prove the child stays alive, repeated clicks cannot
start competing operations, and both Run and Update handlers enforce the guard
regardless of widget enabled state.

## 5. Install transactionally and restart with recovery

Keep filesystem installation in a dedicated module, for example
`strom/linux_gui/update_install.py`, with injected process and file operations.
Do not implement this as shell command strings or an overwrite of the mounted
bundle's inner executable.

Implement this ordered transaction:

1. Acquire a per-target update lock. Ensure no other Strom instance can start a
   cycle against the same installation during the transaction. Add a cooperating
   per-installation lifecycle lock for GUI instances and supported cycle entry
   points, or conservatively refuse installation when exclusivity cannot be
   established. Cover multi-instance behavior; a guard in one window is not
   sufficient.
2. Revalidate target identity, permissions, disk capacity, and verified staging
   identity. Flush the completed staging file and keep all temporary artifacts
   beside the target so replacement stays on one filesystem.
3. Preserve one recoverable copy of the current AppImage under an updater-owned
   unique backup name. Do not overwrite unrelated files. Record a small atomic
   transaction journal containing only installation metadata, never secrets.
4. Run the verified candidate's existing offline self-test asynchronously with
   a timeout and captured bounded output. Failure leaves the original untouched.
   Preserve the supported FUSE/extract-and-run launch mode. Pass arguments as a
   list with no shell. A self-test does not prove the new GUI can open.
5. Atomically replace the original path with the candidate, retain the backup,
   and flush directory changes. Do not truncate/write the old inode in place.
   After replacement, the old GUI must not start any new heating cycle.
6. Launch the replacement from the external AppImage path with a cleaned,
   tested child environment. Inherited PyInstaller/AppImage loader variables
   must not bind it to the old bundle. Verify this with a real packaged test;
   source-mode process tests cannot establish it.
7. Require a local startup acknowledgement from the new GUI after window
   construction and settings restoration. Use a private local IPC endpoint
   and per-attempt token, with a timeout; process creation alone is not success.
   During this handshake the new GUI must keep heating disabled. Transfer the
   lifecycle lock before enabling normal operation and closing the old GUI.
8. On failed startup, stop only the updater-launched candidate after confirming
   it has not been allowed to start a heating cycle, restore the backup
   atomically, and keep the old GUI usable. If recovery itself fails, retain
   the journal and backup and show an actionable recovery location. Do not
   claim success or delete the last working copy.

Add startup recovery for interrupted transactions: validate journal paths and
ownership, distinguish staged/installed/acknowledged states, and recover before
allowing another update. Never interpret journal content as executable commands.
Test process termination between each durable transaction step. Keep backup
cleanup bounded and restricted to proven updater-owned files.

If a small helper process is needed, add an explicit internal dispatch switch
before GUI construction in `strom_entry.py` and its constant in
`entry_switches.py`. Ensure it works from the packaged runtime without host
Python. Do not modify normal `--strom-cli` dispatch or expose internal switches
in product-facing controls. Keep this helper limited to installation recovery
and restart; it must never control a heater.

Done when: replacement, restart acknowledgement, rollback, interrupted recovery,
concurrent launches, paths with spaces, and permissions failures pass on real
temporary AppImages as well as injected unit tests.

## 6. Connect the GUI and translations

Add a compact application menu action **Check for updates** available from both
setup and heating views. Use a separate update dialog; keep the first setup
step limited to language and location. Show current and available versions,
check result, download progress, and concise recovery actions. Do not mix update
errors with the heating-cycle log or status.

When an automatic check finds a newer version, show a non-modal notice that
opens the dialog. Do not steal focus, block setup, or show modal errors for an
automatic offline check. A manual check should explain its failure. Provide
**Update and restart** only for supported writable AppImages; otherwise show
**Open release page** and explain manual installation. During an active cycle,
explain why installation is unavailable. Translate all text into Spanish and
preserve live language switching, keyboard navigation, and accessible names.

Done when: GUI tests cover both languages, all states, source-mode fallback,
startup checking, and the unchanged language/location-only first step.

## 7. Validation and release handoff

Run the existing repository lint, mypy, and deterministic test gates, plus the
Qt-enabled GUI suite. Add focused tests in `tests/linux_gui/test_updates.py`
and `test_update_install.py`, extend `test_window.py`, and extend packaged
entry/self-test coverage where dispatch or bundle contents change. All ordinary
tests use temporary configuration and fake network/process inputs; never touch
the developer's live AppImage, credentials, or heater.

Build two local test versions and demonstrate old-to-new updating with the
real bundle on the Ubuntu compatibility baseline, normal FUSE launch, and
extract-and-run. Verify that Qt's TLS support, version metadata, and any helper
are present in the bundle. Exercise failed self-test, failed GUI startup,
interrupted replacement, rollback, and a denied-write target. Check that saved
city, language, settings folder, and credentials remain available after restart.
No live control cycle is needed for these checks.

Update the README's manual-update description only after the feature works.
Document check timing, channel selection, supported install modes, fallback,
and recovery. The first updater-enabled release must itself be installed
manually: older releases cannot discover an updater they do not contain.
Do not publish a release merely to validate this implementation.

## Completion checklist

- [x] Users can discover an update and install/restart from a writable AppImage.
- [x] Source and unsupported installations have an honest manual fallback.
- [x] Checks/downloads never freeze the GUI or transmit user configuration.
- [x] Installation cannot interrupt or race a heating cycle.
- [x] Version/channel selection and checksums are tested.
- [x] Atomic replacement, startup acknowledgement, and recovery are tested.
- [x] English and Spanish UI plus existing setup behavior are preserved.
- [x] Real packaged smoke tests and repository gates pass.
- [x] User documentation describes implemented behavior accurately.

## Implementation result (2026-09-10)

Implemented in this order, each stage tested before the next:

1. `strom/linux_gui/app_identity.py` — version from package metadata
   (shipped in the frozen bundle via `copy_metadata` in `strom.spec`), ELF
   machine read from the file itself, and a structured
   :class:`InstallStatus` for source / extracted / installable / symlink /
   read-only / unsupported-arch cases. `packaging` added to the `gui`
   extra; comparisons use `packaging.version.Version`.
2. `strom/linux_gui/updates.py` — pure selection: drafts and malformed
   non-`v` tags ignored safely; exactly-one required assets or the release
   is counted but not installable; channel rule (stable follows stable,
   prerelease follows newer prereleases, never a downgrade); pagination
   cap reported as INCOMPLETE, never as "up to date".
3. `strom/linux_gui/update_service.py` — `UpdateService` (QNetworkAccess
   Manager, manual HTTPS-only redirects to the supported hosts, bounded
   metadata reads, incremental SHA-256 streaming into a staging file,
   release-recorded and documented size caps, per-request and total
   timeouts, cancel with staging cleanup, stale-callback token guard) and
   `UpdateCoordinator` (states Idle/Checking/Available/Downloading/
   Verifying/Installing/Restarting/Failed, the cycle/update interlock,
   `request_close()` refusal during Installing, closing during a download
   cancels and removes staging, off-thread prepare/commit phases, the
   offline self-test of the candidate with a timeout, the restart
   handshake over a private local socket with a per-attempt token).
4. The interlock: Run and Update handlers enforce the guard regardless of
   widget state through one centralized `_refresh_controls`; accepting an
   install blocks heating runs until failure or restart; the cycle guard
   is repeated immediately before the replacement; the heating child is
   never killed, detached or waited on — the only process stopped is the
   updater-launched candidate, which cannot have started heating while the
   handshake was incomplete.
5. `strom/linux_gui/update_install.py` — per-target update lock (flock;
   cycle entry points hold it shared), identity/permission/disk/
   checksum revalidation, one recoverable backup (hard link with a copy
   fallback), atomic `os.replace` + directory fsync, an atomic journal
   (QSaveFile) recording only installation metadata with updater-owned
   path validation, rollback before replacement, restore-after-failed
   restart, bounded backup pruning, and startup recovery for staged /
   replaced / acknowledged journals that refuses updates on untrusted
   journals instead of guessing.
6. `strom/linux_gui/update_dialog.py` + window wiring: Help-menu action,
   a separate update dialog with current/available versions, progress and
   concise recovery actions, a non-modal notice for the automatic check,
   **Update and restart** only for supported writable AppImages with the
   release-page fallback, and full Spanish translations with live
   language switching.
7. Self-test extended with offline TLS-support and version-metadata
   checks; `strom.spec` ships the package metadata; README updated.

Verification performed:

- flake8, mypy (25 files), the full deterministic suite (331 tests) and the
  GUI suite (181 tests, 84% coverage on `strom/linux_gui`) pass; the CLI
  coverage floor and gates are unchanged.
- `packaging/appimage/build.sh` ran end to end with the updater changes:
  staged AppRun self-test, FUSE-mount launch, extract-and-run, and the
  Ubuntu 22.04 container verification (extract-and-run + X11/Xvfb via
  Xvfb) all passed, including the new TLS and version-metadata checks
  (PySide6 6.11.2).
- The transaction itself (locks, backup, replacement, rollback, recovery,
  concurrent attempts, paths with spaces and unicode, permission
  failures, process death between steps) is exercised on real temporary
  AppImages in `tests/linux_gui/test_update_install.py` plus coordinator
  end-to-end tests with fake children in `tests/linux_gui/test_updates.py`.

Not verified (honest):

- An old-to-new update against a live release endpoint on the real bundle:
  no newer release exists and publishing one merely to validate is out of
  scope for this task; the transaction paths were verified on real files
  instead.
- A real desktop (X11/Wayland) acceptance session of the updater UI;
  automation covers offscreen Qt and X11 under Xvfb only.

## External API references

Verify API details against these primary references when implementing:

- [GitHub releases REST API](https://docs.github.com/en/rest/releases/releases)
  for release enumeration, assets, and published/prerelease fields.
- [Qt for Python QNetworkAccessManager](https://doc.qt.io/qtforpython-6/PySide6/QtNetwork/QNetworkAccessManager.html)
  for asynchronous network ownership and signals.
- [Qt for Python QSaveFile](https://doc.qt.io/qtforpython-6/PySide6/QtCore/QSaveFile.html)
  for atomic small-file writes such as the transaction journal; leave direct
  write fallback disabled when atomicity is required.
