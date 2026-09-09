#!/usr/bin/env bash
# Deterministic local AppImage build for Strom (AppImage guide, steps 1-2).
#
# Single command:  packaging/appimage/build.sh
#
# What it does, in the guide's order:
#   1. Creates a FRESH build venv (never the developer's .venv), installs the
#      project non-editably with its GUI extra, plus pinned build tools.
#   2. Freezes the packaged entry point into a clean staging directory with
#      the checked-in PyInstaller spec.
#   3. Assembles Strom.AppDir (AppRun, desktop entry, icon, bundled payload),
#      validates it, and runs the staged AppRun's offline self-test FIRST.
#   4. Audits every bundled ELF against the Ubuntu 22.04 compatibility
#      baseline (glibc 2.35 / GLIBCXX 3.4.30 / CXXABI 1.3.13) and fails with
#      the offending files if the baseline is exceeded.
#   5. Builds Strom-<version>-x86_64.AppImage with a hash-verified, pinned
#      appimagetool and pinned runtime, then re-runs the self-test through
#      the artifact itself (FUSE mount when libfuse2 is present, and the
#      pinned runtime's extract-and-run fallback).
#
# Options:
#   --write-constraints  After the fresh install, regenerate
#                        build-constraints.txt from the resolved environment
#                        (maintainer workflow for updating pinned inputs).
#
# Environment overrides:
#   STROM_BUILD_DIR      Staging root (default: <repo>/build-appimage,
#                        kept out of git).
#   STROM_BUILD_PYTHON   Python 3.12 interpreter for the build venv
#                        (default: python3.12).
#   STROM_MIN_GLIBC / STROM_MIN_GLIBCXX / STROM_MIN_CXXABI
#                        Deliberate compatibility baseline overrides.
#
# The script never touches the developer's .venv or credentials, and never
# contacts providers: every automated check runs the offline self-test.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
BUILD="${STROM_BUILD_DIR:-$REPO/build-appimage}"
APPDIR="$BUILD/Strom.AppDir"
DIST="$BUILD/dist"
WORK="$BUILD/work"
VENV="$BUILD/venv"
TOOLS="$BUILD/tools"
WRITE_CONSTRAINTS=0
[ "${1:-}" = "--write-constraints" ] && WRITE_CONSTRAINTS=1

PY="${STROM_BUILD_PYTHON:-python3.12}"
command -v "$PY" >/dev/null || { echo "Build python '$PY' not found." >&2; exit 1; }

VERSION="$("$PY" -c 'import sys, tomllib; print(tomllib.load(open(sys.argv[1], "rb"))["project"]["version"])' "$REPO/pyproject.toml")"
APPIMAGE_NAME="Strom-$VERSION-x86_64.AppImage"

# Ubuntu 22.04 x86_64 compatibility baseline. Raising it is a deliberate,
# documented decision, not an accident of the build host.
BASE_GLIBC="${STROM_MIN_GLIBC:-2.35}"
BASE_GLIBCXX="${STROM_MIN_GLIBCXX:-3.4.30}"
BASE_CXXABI="${STROM_MIN_CXXABI:-1.3.13}"

TMPROOT="$(mktemp -d)"
trap 'rm -rf "$TMPROOT"' EXIT

log() { printf '[build-appimage] %s\n' "$*"; }
max_of() { printf '%s\n%s\n' "$1" "$2" | sort -V | tail -1; }

# --- 1. fresh build environment -------------------------------------------

log "Version $VERSION; creating fresh build venv at $VENV"
rm -rf "$VENV"
"$PY" -m venv "$VENV"
PIP_ARGS=(--no-cache-dir)
[ -f "$HERE/build-constraints.txt" ] && PIP_ARGS+=(-c "$HERE/build-constraints.txt")
"$VENV/bin/pip" install "${PIP_ARGS[@]}" \
    -r "$HERE/build-requirements.txt" "$REPO[gui]" >/dev/null
if [ "$WRITE_CONSTRAINTS" = 1 ]; then
    # The deliberate, resolved build set (the project itself is excluded;
    # it is installed from this checkout, never pinned by path).
    "$VENV/bin/pip" freeze | grep -v '^strom ' > "$HERE/build-constraints.txt"
    log "Wrote resolved build pins to $HERE/build-constraints.txt"
fi

# --- 2. freeze into a clean staging directory ------------------------------

log "Freezing with PyInstaller"
rm -rf "$DIST" "$WORK"
"$VENV/bin/pyinstaller" --noconfirm --clean \
    --distpath "$DIST" --workpath "$WORK" "$HERE/strom.spec" \
    > "$BUILD/pyinstaller.log" 2>&1 \
    || { tail -40 "$BUILD/pyinstaller.log" >&2; exit 1; }

# --- 3. assemble the AppDir, validate, run the staged AppRun first ---------

log "Assembling $APPDIR"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin"
cp -a "$DIST/strom-gui/." "$APPDIR/usr/bin/"
install -m 755 "$HERE/AppRun" "$APPDIR/AppRun"
install -m 644 "$HERE/strom.desktop" "$APPDIR/strom.desktop"
cp "$APPDIR/usr/bin/_internal/strom/linux_gui/assets/strom-256.png" "$APPDIR/strom.png"
ln -sfn strom.png "$APPDIR/.DirIcon"

test -x "$APPDIR/AppRun" || { echo "AppRun not executable" >&2; exit 1; }
test -x "$APPDIR/usr/bin/strom-gui" || { echo "Bundled executable missing" >&2; exit 1; }
test -f "$APPDIR/strom.png" || { echo "Icon missing" >&2; exit 1; }
if command -v desktop-file-validate >/dev/null; then
    desktop-file-validate "$APPDIR/strom.desktop"
fi

log "Staged AppRun self-test (offline, clean environment)"
timeout 300 env -i PATH=/usr/bin:/bin LANG=C.UTF-8 HOME="$TMPROOT/staged-home" \
    "$APPDIR/AppRun" --strom-self-test

# --- 4. ELF compatibility audit against the Ubuntu 22.04 baseline ----------

MAX_GLIBC=0; MAX_GLIBCXX=0; MAX_CXXABI=0
: > "$BUILD/baseline-report.txt"
audit_requires() { # $1=file $2=symbol-prefix $3=baseline $4=nameref of max var
    local -n maxvar="$4"
    local file="$1" prefix="$2" baseline="$3" req short
    while IFS= read -r req; do
        short="${req#"$prefix"}"
        maxvar="$(max_of "$maxvar" "$short")"
        if [ "$(max_of "$short" "$baseline")" != "$baseline" ]; then
            printf '%s\t%s_%s\n' "$file" "$prefix" "$short" >> "$BUILD/baseline-report.txt"
        fi
    done < <(printf '%s' "$DUMP" | grep -oE "${prefix}[0-9.]+" | sort -Vu)
}
while IFS= read -r -d '' f; do
    readelf -h "$f" >/dev/null 2>&1 || continue
    DUMP="$(objdump -T "$f" 2>/dev/null || true)"
    [ -n "$DUMP" ] || continue
    audit_requires "$f" "GLIBC_" "$BASE_GLIBC" MAX_GLIBC
    audit_requires "$f" "GLIBCXX_" "$BASE_GLIBCXX" MAX_GLIBCXX
    audit_requires "$f" "CXXABI_" "$BASE_CXXABI" MAX_CXXABI
done < <(find "$APPDIR" -type f \( -name '*.so' -o -name '*.so.*' -o -perm /111 \) -print0)
log "ELF baseline audit: max GLIBC_$MAX_GLIBC, GLIBCXX_$MAX_GLIBCXX, CXXABI_$MAX_CXXABI (baseline $BASE_GLIBC / $BASE_GLIBCXX / $BASE_CXXABI)"
if [ -s "$BUILD/baseline-report.txt" ]; then
    echo "Bundle exceeds the Ubuntu 22.04 baseline; offenders in $BUILD/baseline-report.txt" >&2
    echo "Raising STROM_MIN_GLIBC / STROM_MIN_GLIBCXX / STROM_MIN_CXXABI is a documented decision." >&2
    exit 2
fi

# --- 5. AppImage with pinned, hash-verified tools ---------------------------

log "Fetching pinned packaging tools"
mkdir -p "$TOOLS"
for f in appimagetool-x86_64.AppImage runtime-x86_64; do
    if [ ! -f "$TOOLS/$f" ]; then
        case "$f" in
            appimagetool-*) url="https://github.com/AppImage/appimagetool/releases/download/1.9.1/$f" ;;
            runtime-*)      url="https://github.com/AppImage/type2-runtime/releases/download/20251108/$f" ;;
        esac
        curl -fsSL -o "$TOOLS/$f" "$url"
    fi
done
(cd "$TOOLS" && sha256sum -c "$HERE/tool-hashes.sha256")

log "Building $APPIMAGE_NAME"
chmod +x "$TOOLS/appimagetool-x86_64.AppImage"
"$TOOLS/appimagetool-x86_64.AppImage" --appimage-extract-and-run \
    --runtime-file "$TOOLS/runtime-x86_64" \
    "$APPDIR" "$BUILD/$APPIMAGE_NAME" > "$BUILD/appimagetool.log" 2>&1 \
    || { tail -40 "$BUILD/appimagetool.log" >&2; exit 1; }

ARTIFACT="$BUILD/$APPIMAGE_NAME"
chmod +x "$ARTIFACT"

# --- 6. artifact verification (the exact published object) -----------------

# grep without -q consumes all input; with -q and pipefail an early match
# would SIGPIPE ldconfig and report libfuse2 as missing.
if ldconfig -p 2>/dev/null | grep 'libfuse\.so\.2' >/dev/null; then
    log "Artifact self-test via FUSE mount"
    timeout 300 env -i PATH=/usr/bin:/bin LANG=C.UTF-8 HOME="$TMPROOT/fuse-home" \
        "$ARTIFACT" --strom-self-test
else
    log "libfuse2 not present; skipping FUSE-mount test (documented fallback)"
fi
log "Artifact self-test via extract-and-run"
timeout 300 env -i PATH=/usr/bin:/bin LANG=C.UTF-8 HOME="$TMPROOT/extract-home" \
    "$ARTIFACT" --appimage-extract-and-run --strom-self-test

if command -v podman >/dev/null; then
    log "Ubuntu 22.04 container verification (offscreen self-test + X11/Xvfb)"
    "$HERE/verify-ubuntu2204.sh" "$ARTIFACT"
else
    log "podman not present; skipping Ubuntu 22.04 container verification"
fi

# --- provenance -------------------------------------------------------------

COMMIT="$(git -C "$REPO" describe --always --dirty)"
{
    echo "date: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "commit: $COMMIT"
    echo "version: $VERSION"
    echo "arch: x86_64"
    echo "build python: $("$PY" --version 2>&1)"
    echo "pyinstaller: $("$VENV/bin/pyinstaller" --version)"
    echo "pyside6: $("$VENV/bin/python" -c 'import PySide6; print(PySide6.__version__)')"
    echo "build baseline: glibc $BASE_GLIBC / GLIBCXX $BASE_GLIBCXX / CXXABI $BASE_CXXABI"
    echo "bundle maxima: glibc $MAX_GLIBC / GLIBCXX $MAX_GLIBCXX / CXXABI $MAX_CXXABI"
    echo "appimagetool: 1.9.1 ($(sha256sum "$TOOLS/appimagetool-x86_64.AppImage" | cut -d' ' -f1))"
    echo "runtime: 20251108 ($(sha256sum "$TOOLS/runtime-x86_64" | cut -d' ' -f1))"
    echo "artifact: $APPIMAGE_NAME"
    echo "artifact sha256: $(sha256sum "$ARTIFACT" | cut -d' ' -f1)"
    echo "artifact size: $(du -h "$ARTIFACT" | cut -f1)"
} > "$BUILD/provenance.txt"
cat "$BUILD/provenance.txt"
log "Done: $ARTIFACT"
