# Implement Strom AppImage distribution through GitHub Releases

This is an implementation handoff, not a claim that packaging already works.
Repository inspected: `Bloodwing1/Strom`, 2026-09-09. Re-read the referenced
code before editing: it may have changed since this document was written.

## Objective and boundaries

Implement a reproducible build of `Strom-<version>-x86_64.AppImage`, test the
actual bundle, and configure GitHub Actions to attach it and `SHA256SUMS` to
GitHub Releases when a matching version tag is pushed.

Start with x86_64 only. Users must not need Python, pip, a source checkout,
or a virtual environment. Keep the ordinary pip installation and CLI working.
Flatpak, automatic updates, ARM builds, and Windows/macOS packaging are outside
this task. Keep the implementation usable as a foundation for Flatpak later.

Implement and validate the files before proposing a first public release.
Do not create/push a version tag or publish a release just to test the workflow
unless the user has authorized that action. Local builds and build-only CI
must be enough to review the implementation first.

## Read these files first

| File | Why it matters |
| --- | --- |
| `pyproject.toml` | Python is constrained to 3.12; runtime dependencies and GUI entry point live here. |
| `strom/linux_gui/app.py` | Builds QApplication, loads icons relative to the package, sets stable settings identifiers. |
| `strom/linux_gui/runner.py` | Launches and owns the backend child process. |
| `strom/linux_gui/window.py` | Adds `--city`, saves preferences, confirms real actuation, refuses closing during a cycle. |
| `strom/linux_gui/setup_files.py` | Writes credentials with restrictive permissions. |
| `strom/cli.py`, `strom/__main__.py` | Existing command-line argument handling and exit codes. |
| `strom/config.py` | Configuration directory and credentials precedence. |
| `strom/optimization_utils.py` | Calls CVXPY with the CLARABEL solver explicitly. |
| `packaging/strom.desktop` | Existing desktop entry; `Exec=strom-gui`, `Icon=strom`. |
| `strom/linux_gui/assets/` | Existing application icons. |
| `.github/workflows/strom-tests.yml` | Existing lint, typing, coverage, GUI and clean-install checks. |
| `tests/linux_gui/` | Existing runner, settings, GUI and fake-child coverage. |

Run `git status --short` first. Preserve unrelated and uncommitted user work.
Read any applicable `AGENTS.md`. Do not use the developer's existing `.venv`
or credentials as build inputs.

## Chosen starting design

Use **PyInstaller in one-directory mode**, then place that directory inside an
AppDir and create an AppImage with a pinned `appimagetool` and pinned runtime.
This is a proposed implementation choice, not an existing dependency. Verify
current Python 3.12/PySide6 support and pin versions that actually pass tests.

Avoid putting a PyInstaller one-file executable inside an AppImage: that adds
a second extraction layer and complicates child-process behavior. Do not
switch packaging systems repeatedly without evidence of a blocker.

Create one bundled executable with an explicit internal command dispatcher:

```text
strom-gui                              -> normal Qt GUI
strom-gui --strom-cli <CLI arguments>   -> strom.cli.run(arguments)
strom-gui --strom-self-test             -> offline packaging verification
```

Handle internal switches before QApplication creation. Remove the internal
switch before handing arguments to the CLI. Keep internal diagnostics out of
normal product screens. `--strom-self-test` must terminate by itself and must
never discover a plug, contact providers, or operate a heater.

**Critical:** a frozen `sys.executable` is the application, not a Python
interpreter. The current `sys.executable -u -m strom ...` launch would be wrong
inside this design. [PyInstaller runtime documentation](https://pyinstaller.org/en/stable/runtime-information.html)

Update `make_launch_spec()` with two paths:

- Source/pip execution: preserve `sys.executable -u -m strom ...`.
- Frozen execution: use `sys.executable --strom-cli ...`, omitting Python's
  `-u -m strom` arguments. Make child output flush promptly by a supported
  mechanism; test it rather than assuming an environment flag works.

Use the packager's actual frozen-runtime indicator, not merely `$APPIMAGE`,
to distinguish these paths. The extracted AppDir must work too. Preserve
argument-list construction, `STROM_CONFIG_DIR`, horizon, log level, and the
GUI's `--city` argument. Never construct a shell command from these values.

## Build in this order

### 1. Prove the dispatcher and child launch

Add a small packaged entry-point file, preferably under `packaging/appimage/`.
Keep CLI and GUI imports in their appropriate branches. Test both source and
frozen launch specifications, including paths and city names containing spaces
and accents. Prove the CLI branch cannot accidentally open another GUI.

Do not change the runner's actuation safeguards: it must still own one child,
refuse a second cycle, preserve output and exit status, and keep the GUI alive
until the child finishes. Do not add a force-cancel button or detach the child.

### 2. Freeze into a clean staging directory

Add a checked-in PyInstaller spec and a deterministic build script. Install
the project non-editably with its GUI dependencies in a fresh build environment.
Keep packaging tools separate from application runtime dependencies.

Pin resolved build dependencies and tools in a maintained lock/requirements
file. Verify downloaded tools against checked-in hashes. Do not use an
unverified `latest` URL, an unpinned continuous release, or the developer's
`pip freeze` as a substitute for a deliberate build dependency set.

Use an explicit Linux compatibility baseline, initially Ubuntu 22.04 x86_64
if the selected Python/Qt wheels support it. Build and test that assumption.
If it does not work, document and deliberately raise the baseline. Do not use
`ubuntu-latest` as an implicit compatibility promise. An older build host also
does not magically lower the glibc requirements of downloaded binary wheels.
[AppImage compatibility guidance](https://docs.appimage.org/introduction/concepts.html)

Bundle and verify:

- Python runtime and standard-library modules used by both entry points.
- PySide6, shiboken6, required Qt libraries, platform plugins and icon assets.
- NumPy, pandas, SciPy, CVXPY and the **CLARABEL** native solver.
- Requests, TLS/certificate resources, ENTSO-E dependencies, python-kasa and
  dependencies imported dynamically by provider/device code.
- Package metadata needed by `importlib.metadata` and runtime dependency checks.
- Required third-party license notices. Check redistribution requirements for
  the actual chosen dependencies; do not invent a license for Strom.

Read PyInstaller warnings and trace runtime failures. Add hooks/hidden imports
based on evidence. Do not immediately collect every Qt module: WebEngine and
other unused modules can inflate the result significantly. Do not remove
scientific dependencies merely because the GUI opens without them.

### 3. Assemble an AppDir

Suggested layout (adapt the PyInstaller internal directory to its pinned version):

```text
Strom.AppDir/
  AppRun                       # executable shell launcher
  strom.desktop                # matching desktop entry
  strom.png                    # existing appropriate-resolution icon
  usr/bin/strom-gui             # PyInstaller executable
  usr/bin/_internal/            # bundled payload, if this version uses it
```

AppRun resolves its own directory, quotes paths, forwards `"$@"`, and uses
`exec` to launch the bundled executable. It must not invoke host `python`, pip,
or the installed `strom-gui` from PATH. Do not depend on the working directory
or a fixed `/tmp/.mount_*` name. The AppImage/AppDir is read-only application
content; all settings and credentials must remain in writable user storage.
[AppDir packaging guidance](https://docs.appimage.org/packaging-guide/from-source/native-binaries.html)

Reuse the existing icon and desktop identifiers. Validate the staged desktop
file and executable bits. Do not change QSettings organization/application
names, because that would make saved preferences appear lost.

Run the staged AppRun first. Only after it passes, turn it into an AppImage.
Record the source commit, app version, architecture, build baseline, dependency
versions, and packaging-tool versions alongside the build logs.

### 4. Verify the artifact, not just the source tree

Provide `--strom-self-test` with an explicit nonzero exit on failure. It should:

1. Create QApplication and a real MainWindow with isolated temporary QSettings;
   process Qt events and close normally. Use temporary config paths and clear
   inherited provider/device credentials for this test.
2. Check that packaged icons load and the Spanish translation module imports.
3. Import the real weather, price and Tapo modules without contacting services.
4. Run a tiny, deterministic optimization explicitly using CLARABEL, check its
   solver status and numerical result, and exit with no actuation.
5. Launch the bundled child dispatcher through the production launch-spec path
   using harmless `--help`, verify completion/exit status and captured output.
   Exercise representative arguments separately with safe tests, including city.

Do not treat `cp.installed_solvers()` alone as proof that a native solver works.
Do not treat a GUI killed by a timeout as a successful smoke test.

Run artifact verification outside the repository with no project virtualenv,
no PYTHONPATH, no provider keys and a temporary user configuration directory.
Use a clean baseline test image/VM with only documented OS display/runtime
prerequisites; do not let development libraries on the build machine hide
missing bundle dependencies. Never disable TLS verification to fix packaging.

Test both extracted AppRun and the final AppImage. On CI without working FUSE,
use the pinned runtime's supported extraction/extract-and-run mode. Also test
ordinary AppImage execution on a machine with FUSE; extraction success does
not prove normal mount-based launch. Document the fallback for users.
[AppImage FUSE troubleshooting](https://docs.appimage.org/user-guide/troubleshooting/fuse.html)

Offscreen Qt verifies basic construction only. Test X11 under Xvfb and verify a
Wayland session manually or with a suitable compositor. Record what actually
ran; do not claim Wayland support solely from `QT_QPA_PLATFORM=offscreen`.

### 5. Add GitHub Actions build and release automation

Suggested new workflow: `.github/workflows/strom-appimage.yml`.

Use these trigger semantics:

| Event | Expected behavior |
| --- | --- |
| Pull request | Build and smoke-test; upload Actions artifacts; never publish. |
| `workflow_dispatch` | Build-only preview by default; never silently create tags. |
| Push of `v*` tag | Validate version, run required gates and bundle tests, then upload release assets. |

The `v*` glob is only a trigger filter. Validate the tag explicitly and require
its version to match `pyproject.toml`; support and correctly mark prereleases
or clearly reject them. Derive version from the tagged source, not a hardcoded
example or the default branch. Never create a missing tag automatically.

Use read-only workflow permissions by default and `contents: write` only in
the release job, using `GITHUB_TOKEN`/`GH_TOKEN`. Pin actions to verified commit
SHAs with readable version comments. Do not use `pull_request_target` to build
untrusted PR code with write permissions. Validate tag data and pass GitHub
context values through environment variables rather than interpolating them
directly into shell source. [GitHub token guidance](https://docs.github.com/en/actions/tutorials/authenticate-with-github_token)

Make publication depend on successful lint, typing, existing deterministic
tests, GUI tests and packaged-artifact checks for the **same commit**. A green
separate workflow is not automatically a dependency. Reuse checks through a
reusable workflow or run the required commands in the release workflow; do not
remove or weaken existing coverage gates. Do not run live integration tests.

Use the exact tested artifact for publication; do not rebuild in the publish
job. Transport it through Actions artifacts, then verify its checksum. Release
uploads do not replace a public GitHub Release with an Actions-only download.

Name the asset `Strom-<version>-x86_64.AppImage`. Generate `SHA256SUMS` with a
relative asset filename so `sha256sum -c SHA256SUMS` works in a download folder.
Include build provenance in release notes or a small accompanying manifest.

Create a draft release for the existing tag, attach and verify all assets,
then publish it only after the gates succeed. Use `gh release create` with
`--verify-tag`; do not rely on its default ability to create tags. Set
prerelease status correctly. Write multiline release notes to a file.
[GitHub release CLI](https://cli.github.com/manual/gh_release_create)

Make reruns safe: a matching complete release is a no-op; an incomplete draft
may be resumed after validating its tag/commit. Never overwrite a differing
published binary under the same version or use unconditional `--clobber`.
Handle immutable releases by uploading everything before publication. Reject
conflicts clearly and serialize release work per tag with concurrency controls.

### 6. Document installation and maintenance

Update README with the Releases download link, supported architecture and
tested distributions, checksum verification, executable permission, launch,
and FUSE fallback. Explain that replacing the AppImage updates the app while
settings remain in the user configuration directory. Do not promise automatic
updates, automatic menu integration, or compatibility with every Linux distro.

Document a single local build command, how to update pinned dependencies/tool
hashes, and how a maintainer creates the next versioned release. Keep large
binaries and staging directories out of git.

## Failure checklist

| Symptom | Likely cause / next check |
| --- | --- |
| Clicking Run opens another GUI | Frozen executable received `-m strom`; fix dispatcher and launch specification. |
| Window opens, optimization fails | Missing CLARABEL/native libraries or metadata; execute a real tiny solve in the bundle. |
| Works from repo only | Editable install, relative resource path, PYTHONPATH or host-library leakage. |
| Qt platform plugin error | Check actual plugin dependencies, not just whether `libqxcb.so` exists. |
| Offscreen works, desktop fails | X11/Wayland plugin dependencies, graphics integration or missing system prerequisites. |
| Signup links stop opening | Frozen library search paths may contaminate external desktop helpers; diagnose helper environment. |
| Child cannot import bundled libraries | Do not indiscriminately clear library paths needed by bundled subprocesses. |
| GLIBC/GLIBCXX version error | Build environment or binary wheel requires a newer target system than documented. |
| Saved location/language disappears | Changed QSettings identifiers or writes into temporary bundle directories. |
| Build succeeds, release absent | Wrong trigger, missing publication dependency/permission, or only Actions artifacts uploaded. |
| FUSE failure in CI | Use extraction for CI and retain a separate real FUSE launch check. |
| AppImage unexpectedly huge | Audit included Qt modules, plotting packages, tests/caches; optimize only after functionality passes. |

Frozen applications change library search behavior. External system helpers
and bundled children need different treatment; do not globally sanitize the
environment as a blanket fix. [PyInstaller subprocess pitfalls](https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html)

## Definition of done

- Source/pip behavior remains supported and existing gates pass.
- Build script, pinned dependency/tool inputs, spec, launcher, workflow, artifact
  smoke verification and user documentation are committed as reviewable code.
- An AppImage built from a clean checkout runs without host Python or a checkout.
- The packaged GUI, backend child and CLARABEL solve have actually been exercised.
- No build or automated test contacts a heater or requires real account keys.
- The release workflow cannot publish on a PR or a failed gate, and publishes
  only the exact tested artifact for a verified version tag.
- The handoff report lists commands/results, artifact path and size, tested
  environments and any unverified manual checks. Clearly distinguish a workflow
  implemented locally from one actually run on GitHub, and a draft from a
  published release. Do not claim an unperformed publication succeeded.

For later Flatpak work, reuse the application entry points, icons and safe
offline verification. Flatpak will need its own manifest/runtime and sandbox
storage/network decisions; do not put the AppImage inside a Flatpak.

## Implementation plan: three steps

The six "Build in this order" sections above are grouped into three reviewable
steps. Each step must be verifiable on its own before the next one starts.

### Step 1 — Packaged dispatcher and child launch specification

Covers sections 1–2. Deliverables:

- `packaging/appimage/` entry-point file with the internal command dispatcher
  (`strom-gui`, `--strom-cli <args>`, `--strom-self-test`), internal switches
  handled before QApplication creation.
- `make_launch_spec()` with explicit source and frozen paths; frozen child
  output flushes promptly by a supported, tested mechanism (not `-u`).
- A PyInstaller spec, deterministic build script and pinned build dependency
  set producing a clean staging directory (bundled payload, no host leakage).

Exit criteria: dispatcher tests pass in source mode, the frozen launch
specification shape is proven (including paths/city names with spaces and
accents), the CLI branch is proven unable to open another GUI, `--strom-self-test`
terminates by itself offline, and the staging build starts from a clean,
non-editable install with pinned inputs.

### Step 2 — AppDir assembly and artifact verification

Covers sections 3–4. Deliverables:

- `Strom.AppDir/` with a quoted, `exec`-ing AppRun, matching desktop entry and
  the existing icon; staged AppRun runs before any AppImage is created.
- `--strom-self-test` extended to the full section-4 checklist (isolated
  MainWindow, icons, translation module, provider module imports without
  contact, real tiny CLARABEL solve, child dispatcher round trip).
- Verification of both the extracted AppDir and the final AppImage outside the
  repository (no venv, no PYTHONPATH, temp config dir), X11 under Xvfb, FUSE
  and extraction modes, with recorded provenance (commit, versions, baseline).

Exit criteria: an AppImage built from the staging tree passes `--strom-self-test`
and manual X11 checks on a clean baseline system; failures feed back into
hooks/hidden imports with evidence.

### Step 3 — Release automation and documentation

Covers sections 5–6. Deliverables:

- `.github/workflows/strom-appimage.yml`: PR and `workflow_dispatch` build-only,
  `v*` tag push validates the tag against `pyproject.toml`, reuses the existing
  gates for the same commit, publishes the exact tested artifact plus
  `SHA256SUMS` as a draft-then-published GitHub Release with pinned actions and
  rerun-safe semantics.
- README installation section (download, checksum, FUSE fallback, settings
  persistence) and maintainer documentation (local build command, pinned-input
  updates, release procedure).

Exit criteria: publication is impossible on a PR or failed gate; a matching
complete release rerun is a no-op; documentation makes no untested promises.

### Status

- [x] Step 1 — complete (dispatcher, frozen-aware launch specification, tests).
- [x] Step 2 — complete (staging build, AppDir, AppImage, artifact verification;
      log above).
- [x] Step 3 — implemented and locally validated; **not yet run on GitHub**
      (log below). No release has been published and no tag has been pushed.

### Step 3 log (2026-09-09)

Implemented:

- `.github/workflows/strom-tests.yml`: additive `workflow_call` trigger so
  the AppImage release reuses the existing blocking gates (lint, typing,
  deterministic tests, GUI tests, clean-install smoke) for the same commit;
  nothing was removed or weakened.
- `.github/workflows/strom-appimage.yml`: PR builds and `workflow_dispatch`
  previews never publish; only an actual `v*` tag push reaches the release
  job (`github.event_name == 'push'` and tag ref are both required). The
  release job validates the tag against `pyproject.toml` (PEP 440
  `vMAJOR.MINOR.PATCH` with optional `a`/`b`/`rc` prerelease, marked as such;
  `.dev` and mismatches rejected), verifies the transported artifact against
  the build job's recorded sha256 (job output plus a second in-artifact
  record), creates a draft release with `gh release create --verify-tag`,
  attaches `Strom-<version>-x86_64.AppImage` and a relative-filename
  `SHA256SUMS`, downloads both back and re-verifies, and only then publishes.
  Rerun-safe semantics: identical published artifact → no-op; differing
  published binary → loud refusal; incomplete draft → resumed after tag
  validation. Workflow-level concurrency groups per ref (no cancellation for
  tag pushes). All actions pinned to verified commit SHAs (checkout v7.0.1,
  setup-python v7.0.0, upload-artifact v7.0.1, download-artifact v8.0.1);
  runner pinned to `ubuntu-22.04`; GitHub context reaches scripts only
  through environment variables; `contents: write` is scoped to the release
  job alone.
- README: AppImage install section (download, checksum verification,
  executable permission, FUSE fallback, settings persistence) with no
  untested promises; the "standalone executable" future item is retired.
- `packaging/appimage/README.md`: maintainer documentation (local build
  command, pin-update procedures, release procedure, rerun semantics).

Local validation performed (not a GitHub run):

- YAML parses; `actionlint` 1.7.7 passes clean on both workflows; every
  inline `run:` script passes `bash -n`; the tag-validation regex and the
  pyproject version comparison were exercised directly.
- The build, verification, and release scripts themselves were exercised
  end to end locally in step 2 (see the step 2 log above).

Not yet verified — deliberately left for the first real run on GitHub:

- The workflow has never executed on GitHub Actions; its first PR/dispatch
  run must be observed before any release is cut, and the tag-triggered
  publication path must be watched end to end (including `--verify-tag`
  behavior and asset round-trip) for the actual first versioned release.
- No tag has been pushed and no release, draft or published, exists.

### Step 2 verification log (2026-09-09)

Build (one command: `packaging/appimage/build.sh`):

- Fresh build venv (Python 3.12.8, never the developer's `.venv`), project
  installed non-editably with `[gui]`; resolved inputs pinned in
  `packaging/appimage/build-requirements.txt` (PyInstaller 6.22.2, tzdata
  2026.3) and `build-constraints.txt` (60 pins); PySide6 6.11.2.
- Bundle kept at the Ubuntu 22.04 baseline by shipping only wheel-provided
  binaries plus `libpython` (spec filter); the build host's system libraries
  (Bazzite 44, glibc 2.43) are resolved from the target system instead.
- Runtime gaps found by the staged self-test and fixed with evidence in
  `strom.spec`: cvxpy needs its package directory on disk (`py.typed` data
  entry, for `os.listdir` at import), `osqp.ext_builtin` hidden import (every
  frozen cvxpy import otherwise logs a solver error into the child log), and
  bundled `tzdata` as zoneinfo's fallback (system `/usr/share/zoneinfo` was
  missing only in the minimal container — the build host had hidden the gap).
- ELF audit (in build.sh): bundle maxima GLIBC 2.34 / GLIBCXX 3.4.29 /
  CXXABI 1.3.13 — within the Ubuntu 22.04 baseline (2.35 / 3.4.30 / 1.3.13).
- AppDir: quoted, exec-ing `AppRun`; desktop entry validated with
  `desktop-file-validate`; icon from the bundled assets; staged AppRun
  self-test ran before any AppImage existed.
- Artifact `Strom-0.2.0-x86_64.AppImage` (157 MiB,
  sha256 751e129497e1e3ed73274c3a8e45545ad0a6f4992c7ebaaa635ea68501de405b)
  built with hash-verified appimagetool 1.9.1 and type2-runtime 20251108.

Verification of the exact artifact:

- FUSE-mounted launch (build host, libfuse2): self-test passed, including the
  frozen child dispatcher round trip through `make_launch_spec`.
- Extract-and-run (build host and Ubuntu 22.04 container, glibc 2.35):
  self-test passed with only the documented OS prerequisites installed
  (libglib2.0-0, libfontconfig1, libegl1, libgl1, libdbus-1-3, libx11-6,
  libx11-xcb1, libxkbcommon0, libxkbcommon-x11-0, libxcb1, libxcb-util1,
  libxcb-cursor0, libxcb-icccm4, libxcb-image0, libxcb-keysyms1,
  libxcb-randr0, libxcb-render-util0, libxcb-render0, libxcb-shape0,
  libxcb-shm0, libxcb-sync1, libxcb-xfixes0, libxcb-xkb1). The repeatable
  recipe is checked in as `packaging/appimage/verify-ubuntu2204.sh` and runs
  automatically from build.sh when podman is present.
- Plain `--appimage-extract` + `squashfs-root/AppRun`: self-test passed.
- X11 under Xvfb (Ubuntu 22.04 container): the real "Strom" window
  (720x620, class `strom-gui`/`Strom`) mapped on the X server, verified via
  `xwininfo` — not by a timeout kill.
- Qt session note: bundled `libQt6Gui` links `libQt6DBus`, which requires
  system `libdbus-1.so.3`; it joins libX11/libglib/etc. as documented
  display/session prerequisites and is present on every desktop system.

Not yet verified (recorded honestly):

- A Wayland session: automation covers offscreen Qt and X11/Xvfb only.
- FUSE-mounted launch on an Ubuntu 22.04 desktop (proven on the build host;
  containers have no `/dev/fuse`).
- Running the artifact on real hardware/distributions beyond the container.
