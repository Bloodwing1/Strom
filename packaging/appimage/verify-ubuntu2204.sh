#!/usr/bin/env bash
# Verify a built Strom AppImage inside a clean Ubuntu 22.04 x86_64 container
# (the documented compatibility baseline). Requires podman.
#
# Usage: packaging/appimage/verify-ubuntu2204.sh <path-to-AppImage>
#
# The container provides only the documented OS display/runtime
# prerequisites; the AppImage is exercised through the pinned runtime's
# extract-and-run mode because containers lack /dev/fuse. Two checks run:
#   1. the offline --strom-self-test in a sanitized environment, and
#   2. an X11 smoke test under Xvfb: the real "Strom" window must map on the
#      X server (verified via xwininfo, not by a timeout kill).
set -euo pipefail

ARTIFACT="$(readlink -f "${1:?Usage: verify-ubuntu2204.sh <AppImage>}")"
[ -f "$ARTIFACT" ] || { echo "Artifact not found: $ARTIFACT" >&2; exit 1; }
command -v podman >/dev/null || { echo "podman not found" >&2; exit 1; }

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
cp "$ARTIFACT" "$STAGE/artifact.AppImage"

exec podman run --rm -v "$STAGE:/mnt:ro,Z" ubuntu:22.04 bash -c '
set -euo pipefail
echo "Ubuntu 22.04 container: $(ldd --version | head -1)"
apt-get update -qq >/dev/null
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends \
  libglib2.0-0 libfontconfig1 libegl1 libgl1 libdbus-1-3 \
  libx11-6 libx11-xcb1 libxkbcommon0 libxkbcommon-x11-0 \
  libxcb1 libxcb-util1 libxcb-cursor0 libxcb-icccm4 libxcb-image0 \
  libxcb-keysyms1 libxcb-randr0 libxcb-render-util0 libxcb-render0 \
  libxcb-shape0 libxcb-shm0 libxcb-sync1 libxcb-xfixes0 libxcb-xkb1 \
  xvfb x11-utils >/dev/null
cp /mnt/artifact.AppImage /work.AppImage && chmod +x /work.AppImage

echo "=== self-test on Ubuntu 22.04 (extract-and-run, clean env) ==="
timeout 300 env -i PATH=/usr/bin:/bin LANG=C.UTF-8 HOME=/tmp/selftest-home \
    /work.AppImage --appimage-extract-and-run --strom-self-test

echo "=== X11 smoke test under Xvfb ==="
Xvfb :99 -screen 0 1024x768x24 &
sleep 2
env -i PATH=/usr/bin:/bin DISPLAY=:99 HOME=/tmp/gui-home \
    /work.AppImage --appimage-extract-and-run &
GUIPID=$!
sleep 15
DISPLAY=:99 xwininfo -root -tree | grep -i "Strom" \
    || { echo "NO STROM WINDOW MAPPED" >&2; kill "$GUIPID" 2>/dev/null || true; exit 1; }
kill "$GUIPID" 2>/dev/null || true
wait "$GUIPID" 2>/dev/null || true
echo "X11 smoke test passed: Strom window mapped under Xvfb"
'
