#!/usr/bin/env bash
# Prove the Linux tarball runs on old and non-Debian distros (#168).
#
#   scripts/test_linux_floor.sh dist/deckd-<version>-<arch>.tar.gz [IMAGE...]
#
# For each container image: extract the tarball, boot the frozen daemon, and
# read /health over bash's /dev/tcp (so the image needs only bash, no curl).
# A missing GLIBC_x.yy symbol fails at exec, so a too-new build base shows up
# here as a hard failure. Default images span the glibc floor (debian:10 is
# 2.28, the manylinux_2_28 base) and the distros the old ubuntu-24.04 build
# locked out. Uses podman if present, else docker.
set -euo pipefail

tarball="${1:?usage: $0 TARBALL [IMAGE...]}"
shift
images=("$@")
[ ${#images[@]} -gt 0 ] || images=(debian:10 ubuntu:22.04 debian:12 fedora:latest)

engine="$(command -v podman || command -v docker || true)"
[ -n "$engine" ] || { echo "error: needs podman or docker" >&2; exit 1; }

tarball="$(cd "$(dirname "$tarball")" && pwd)/$(basename "$tarball")"

probe='
set -euo pipefail
mkdir /deckd && tar -C /deckd -xzf /artifact.tar.gz
bin="$(ls -d /deckd/deckd-*/)bin/deckd"
"$bin" --help >/dev/null
DECKD_FAKE_INPUT=1 "$bin" --no-open --no-focus --no-auth >/tmp/deckd.log 2>&1 &
for _ in $(seq 60); do
    if { exec 3<>/dev/tcp/127.0.0.1/8765; } 2>/dev/null; then
        printf "GET /health HTTP/1.0\r\nHost: x\r\n\r\n" >&3
        if grep -q "\"ok\": true" <&3; then echo ok; exit 0; fi
    fi
    sleep 0.5
done
cat /tmp/deckd.log >&2
exit 1
'

fail=0
for image in "${images[@]}"; do
    # Some minimal images lack tar/gzip; install them quietly when needed.
    prep='command -v tar >/dev/null && command -v gzip >/dev/null || { (dnf -yq install tar gzip || (apt-get -qq update && apt-get -qq install -y tar gzip)) >/dev/null 2>&1; }'
    glibc="$("$engine" run --rm "$image" sh -c 'ldd --version 2>&1 | head -n1 | grep -o "[0-9]\+\.[0-9]\+$"' || echo '?')"
    if "$engine" run --rm -v "$tarball:/artifact.tar.gz:ro" "$image" \
        bash -c "$prep; $probe" >/dev/null; then
        echo "PASS  $image (glibc $glibc)"
    else
        echo "FAIL  $image (glibc $glibc)"
        fail=1
    fi
done
exit "$fail"
