#!/usr/bin/env bash
# Build the Linux release artifacts inside a manylinux_2_28 container (#168).
#
# A PyInstaller bundle needs a glibc at least as new as the one it was frozen
# against, so the release is frozen on the oldest base we support:
# manylinux_2_28 (AlmaLinux 8, glibc 2.28) — runs on Debian 10+, Ubuntu
# 20.04+, RHEL/Alma/Rocky 8+, and anything newer. Building on the stock GitHub
# runner (ubuntu-24.04, glibc 2.39) would lock out Ubuntu 22.04 and Debian 12.
#
# Python comes from python-build-standalone via uv, not manylinux's own
# /opt/python builds: those are linked statically, and PyInstaller needs the
# shared libpython. python-build-standalone targets glibc 2.17, well under
# the floor.
#
# Runs at the repo root inside the container, with client/dist already built
# (the client is static and arch-independent, so it is built once outside).
# Used verbatim by .github/workflows/release-linux.yml and, through
# `just build-linux-portable`, locally with podman/docker.
set -euo pipefail

if [ ! -d /opt/python ]; then
    echo "error: run this inside a quay.io/pypa/manylinux_2_28_* container" >&2
    exit 1
fi
[ -f client/dist/index.html ] \
    || { echo "error: client/dist is missing; build the client first" >&2; exit 1; }

# The checkout is a bind mount owned by another uid; let git (used by pip's
# editable install) read it.
git config --global --add safe.directory "$PWD" 2>/dev/null || true

bootstrap=/opt/python/cp311-cp311/bin
"$bootstrap/pip" install -q --root-user-action=ignore uv rust-just
export PATH="$bootstrap:$PATH"

venv=/tmp/deckd-build-venv
uv python install 3.11
# --seed: scripts/install_evdev_source.sh (aarch64) drives pip directly.
uv venv -q --seed -p 3.11 "$venv"
# shellcheck disable=SC1091
. "$venv/bin/activate"
uv pip install -q -e ".[uinput,dbus,packaging]"

# Pre-seed the appimagetool the AppImage recipe would fetch, with its AppImage
# magic bytes ("AI\x02" at offset 8) zeroed. A host with an AppImage binfmt
# handler (NixOS `programs.appimage`) otherwise routes the exec to an
# interpreter that doesn't exist in this container (ENOENT). The runtime
# doesn't check its own magic, so this is a no-op on hosts without the handler.
arch="$(uname -m)"
tooling="${XDG_CACHE_HOME:-$HOME/.cache}/deckd/appimagetool-${arch}.AppImage"
if [ ! -x "$tooling" ]; then
    mkdir -p "$(dirname "$tooling")"
    curl -fsSL -o "$tooling" \
        "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-${arch}.AppImage"
    printf '\0\0\0' | dd of="$tooling" bs=1 seek=8 conv=notrunc status=none
    chmod +x "$tooling"
fi

just build-linux
