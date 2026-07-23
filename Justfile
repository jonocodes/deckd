# deckd — common commands

# `just` (no args) lists available recipes.
default:
    @just --list

# Per-platform setup recipes. `setup` auto-picks the right one; use the
# explicit recipe when you want to override (e.g. cross-checking on a CI box).

# Linux/GNOME/KDE dev: [dev,uinput] gives the evdev-backed uinput sink used
# for key injection (browser buttons etc.). On x86_64 that's the prebuilt
# evdev-binary wheel; on aarch64 (no evdev-binary wheel) we install [dev]
# then source-build python-evdev via scripts/install_evdev_source.sh, which
# needs a C compiler (the `gcc` flox package). If that build is skipped the
# uinput backend degrades gracefully (input.py imports evdev lazily, no-ops).
setup-linux:
    #!/usr/bin/env bash
    set -euo pipefail
    uv venv --python 3.12 --allow-existing
    if [ "$(uname -m)" = x86_64 ]; then
        uv pip install -e ".[dev,uinput]"
    else
        echo "note: $(uname -m) has no evdev-binary wheel; source-building python-evdev." >&2
        uv pip install -e ".[dev]"
        PYTHON=".venv/bin/python" bash scripts/install_evdev_source.sh \
            || echo "warn: evdev source build failed; uinput key injection will no-op." >&2
    fi
    cd client && npm install

# macOS dev: [dev] + [macos] (PyObjC Quartz covers scroll, pointer, click,
# and held-button drag for the trackpad).
setup-macos:
    uv venv --python 3.12 --allow-existing
    uv pip install -e ".[dev,macos]"
    cd client && npm install

# Dispatch: picks setup-linux on Linux, setup-macos on macOS. flox users
# don't need this -- flox activate handles its own venv.
setup:
    @if [ "$(uname)" = Darwin ]; then \
        just setup-macos; \
    else \
        just setup-linux; \
    fi

# Run the daemon against the layouts directory, serving the built client.
run-daemon:
    deckd --layouts-dir layouts --client-dist client/dist --verbose

# Run the daemon on the LAN without a built client (use dev-client-lan for HMR).
run-daemon-lan:
    deckd --host 0.0.0.0 --layouts-dir layouts --verbose

# Run the daemon under a supervisor that restarts it when daemon/**/*.py
# changes. Layout YAML hot-reload is built into the daemon itself; this is
# only useful when editing Python.
dev-daemon:
    deckd-dev --verbose

# Same, but bind the daemon to all interfaces so a phone on the LAN
# (or Tailscale) can reach it. deckd-dev forwards unknown args to the
# child, so --host and --verbose end up on the deckd process.
dev-daemon-lan:
    deckd-dev --host 0.0.0.0 --verbose

# Vite dev server on the LAN. Vite proxies /ws and /health to the local
# daemon (see vite.config.ts), so the client is same-origin at :5173.
dev-client-lan:
    cd client && npm run dev -- --host 0.0.0.0 --strictPort

# Vite dev server with HTTPS via a tailscale-provisioned cert. Required
# for Chrome's PWA install prompt (secure-context gate). Provisions the
# cert lazily on first run; caches it under client/.tls (gitignored).
# Phone opens https://<host>.<tailnet>.ts.net:5173/ .
dev-client-tailscale:
    #!/usr/bin/env bash
    set -euo pipefail
    host="$(tailscale status --self --json | jq -r .Self.DNSName | sed 's:\.$::')"
    tls="client/.tls"
    mkdir -p "$tls"
    if [ ! -f "$tls/$host.crt" ] || [ ! -f "$tls/$host.key" ]; then
      echo "Provisioning tailscale cert for $host in $tls/ (requires sudo)..."
      (cd "$tls" && sudo tailscale cert "$host" && sudo chown "$USER" "$host.crt" "$host.key")
    fi
    echo "-> https://$host:5173/"
    cd client && DECKD_TLS_DIR="./.tls" DECKD_TLS_HOST="$host" npm run dev -- --host 0.0.0.0 --strictPort

# Build the client (output: client/dist/).
build-client:
    cd client && npm run build

# Build the client and Ladle with the GitHub Pages base paths
# (jonocodes.github.io/deckd/) so the deploy-pages workflow can be
# repro'd locally. Output: client/dist/ (index.html, gallery.html,
# ladle/). Use `npx serve client/dist` to browse before pushing.
build-pages:
    #!/usr/bin/env bash
    set -euo pipefail
    cd client
    VITE_BASE_PATH=/deckd/ npm run build
    mkdir -p dist/ladle
    npm run ladle:build -- --base /deckd/ladle/ --outDir dist/ladle

# Run the test suite.
test:
    pytest

# Run the client test suite (Vitest unit tests + Playwright e2e). The e2e
# half boots the daemon with PYTHONPATH=scripts/no-evdev so its uinput sink
# is shadowed to LoggingKeySink — keystrokes are logged, not injected into
# the host desktop. See client/e2e/kbd-mode.spec.ts for the suite.
test-client:
    cd client && npm run test:unit
    cd client && npm run test:e2e

# End-to-end smoke test (boots daemon in-process, fires every action primitive).
smoke:
    python -u scripts/smoke.py

# Check whether this shell can create a uinput scroll device.
check-uinput:
    python -u scripts/check_uinput.py

# Install and enable the local GNOME Shell focus extension for Spike #2.
install-focus-extension:
    tmpdir="$(mktemp -d)"; gnome-extensions pack -f -o "$tmpdir" packaging/gnome-shell/deckd-focus@local; gnome-extensions install --force --print-uuid "$tmpdir/deckd-focus@local.shell-extension.zip"; rm -rf "$tmpdir"; if gnome-extensions list | grep -qx deckd-focus@local; then gnome-extensions enable deckd-focus@local; else echo "Installed deckd-focus@local. Log out/in, then run: gnome-extensions enable deckd-focus@local"; fi

# Install and enable the deckd-focus KWin script for KDE Plasma Wayland (#31).
#
# Mirrors install-focus-extension: installs the script package into
# ~/.local/share/kwin/scripts/, persists the kwinrc enable flag so it
# survives relogin, applies the change with reconfigure, and hot-starts
# the script via org.kde.kwin.Scripting.loadScript so focus events flow
# immediately without a relogin. Re-run anytime to reload the in-process
# script (e.g. after editing main.js, or after the daemon restarts later
# than the script's initial push).
#
# Requires: kpackagetool6, kwriteconfig6, qdbus6 (qdbus) on $PATH —
# stock Plasma 6 dev packages.
install-focus-kwin:
    #!/usr/bin/env bash
    set -euo pipefail
    pkg="packaging/kwin-script/deckd-focus"
    script_id="deckd-focus"
    script_path="$HOME/.local/share/kwin/scripts/${script_id}/contents/code/main.js"
    # 1. Install (or upgrade) the KWin script package into the user dir.
    #    -u fails on a first run ("Plugin deckd-focus is not installed"),
    #    so install first and fall back to upgrade when it already exists.
    kpackagetool6 --type=KWin/Script -i "$pkg" 2>/dev/null \
        || kpackagetool6 --type=KWin/Script -u "$pkg"
    # 2. Persist enable across relogins (kwinrc [Plugins] deckd-focusEnabled=true).
    kwriteconfig6 --file kwinrc --group Plugins --key "${script_id}Enabled" true
    # 3. Apply kwinrc changes so a KWin restart picks the script up automatically.
    qdbus org.kde.KWin /KWin org.kde.KWin.reconfigure >/dev/null
    # 4. Hot-start: unload any in-process copy so we never get duplicate
    #    handlers, then loadScript fires the script's initial
    #    push(workspace.activeWindow) against the running daemon's
    #    org.deckd.Focus cache.
    qdbus org.kde.KWin /Scripting org.kde.kwin.Scripting.unloadScript "${script_id}" >/dev/null 2>&1 || true
    qdbus org.kde.KWin /Scripting org.kde.kwin.Scripting.loadScript "${script_path}" "${script_id}" >/dev/null
    echo "deckd-focus KWin script installed, enabled, and hot-started."
    echo "Run 'just watch-focus' to confirm focus events land."

# Print active app/window changes for Spike #2.
watch-focus:
    python -u scripts/watch_focus.py

# Single snapshot of the active app/window.
watch-focus-once:
    python -u scripts/watch_focus.py --once

# Hit /health.
status:
    deckctl status
