#!/usr/bin/env bash
# Build + install python-evdev from source, for platforms that have no
# prebuilt wheel — notably aarch64/arm64, where `evdev-binary` ships x86_64
# wheels only and the plain `evdev` package is sdist-only (needs a compiler).
#
# On a stock Linux distro `pip install evdev` "just works" because the kernel
# headers live in /usr/include and evdev's `build_ecodes` step finds them
# there. Under Nix/flox there is no /usr/include, so build_ecodes (which opens
# linux/input.h, input-event-codes.h and uinput.h *by path*) can't find them.
# We therefore locate the header dir via the C compiler's own include search
# and pass it explicitly with `--evdev-headers`.
#
# Requires a C toolchain (cc/gcc) on PATH. flox users get it from the `gcc`
# package (see .flox/env/manifest.toml). No-op if evdev already imports.
#
# Usage:  PYTHON=/path/to/venv/python scripts/install_evdev_source.sh
#         (PYTHON defaults to `python` on PATH.)
set -euo pipefail

PY="${PYTHON:-python}"

if "$PY" -c 'import evdev' 2>/dev/null; then
    echo "evdev already importable under $PY; nothing to do."
    exit 0
fi

# Fast path: on distros with headers in /usr/include this builds cleanly.
if "$PY" -m pip install -q 'evdev>=1.9' 2>/dev/null && "$PY" -c 'import evdev' 2>/dev/null; then
    echo "evdev installed from source via pip (standard header layout)."
    exit 0
fi

# Slow path (Nix/flox): find the include dir that actually holds the kernel
# headers and hand it to build_ecodes explicitly.
if ! command -v cc >/dev/null 2>&1; then
    echo "error: no C compiler (cc) on PATH; cannot build evdev from source." >&2
    echo "  flox: 'flox install gcc'   distro: install gcc + kernel headers." >&2
    exit 1
fi

hdr=""
for d in $(echo | cc -xc -E -v - 2>&1 \
        | sed -n '/#include <...> search starts/,/End of search/p' | grep '^ '); do
    if [ -f "$d/linux/uinput.h" ]; then hdr="$d"; break; fi
done
if [ -z "$hdr" ]; then
    echo "error: could not locate linux/uinput.h in the compiler include path." >&2
    exit 1
fi
echo "building evdev against kernel headers in: $hdr"

"$PY" -m pip install -q setuptools wheel

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
"$PY" -m pip download -q --no-deps --no-binary :all: 'evdev>=1.9' -d "$work"
tar xzf "$work"/evdev-*.tar.gz -C "$work"
src=$(echo "$work"/evdev-*/)
(
    cd "$src"
    "$PY" setup.py -q \
        build_ecodes --evdev-headers "$hdr/linux/input.h:$hdr/linux/input-event-codes.h:$hdr/linux/uinput.h" \
        build_ext --include-dirs "$hdr" \
        bdist_wheel
    "$PY" -m pip install -q --force-reinstall --no-deps dist/evdev-*.whl
)
"$PY" -c 'import evdev; from evdev import UInput; print("evdev built + installed OK")'
