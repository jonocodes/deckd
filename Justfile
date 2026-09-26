# deckd — common commands

# Load a gitignored ./.env if one exists. `just worktree-adopt` writes one per
# worktree holding that checkout's port assignment, so every recipe below picks
# up the right ports with no env-var juggling. Nothing else uses it, the
# primary checkout doesn't need one, and an explicit env var still wins:
# `DECKD_PORT=9000 just dev`.
set dotenv-load := true

# `just` (no args) lists available recipes.
default:
    @just --list

# Per-platform setup recipes. `setup` auto-picks the right one; use the
# explicit recipe when you want to override (e.g. cross-checking on a CI box).

# Linux/GNOME/KDE dev: [dev,uinput,dbus] gives the evdev-backed uinput sink
# used for key injection (browser buttons etc.) plus dbus-fast for the `dbus:`
# action primitive and MPRIS now-playing (issue #27 — both Linux-only, so
# setup-macos skips the [dbus] extra). On x86_64 uinput is the prebuilt
# evdev-binary wheel; on aarch64 (no evdev-binary wheel) we install [dev,dbus]
# then source-build python-evdev via scripts/install_evdev_source.sh, which
# needs a C compiler (the `gcc` flox package). If that build is skipped the
# uinput backend degrades gracefully (input.py imports evdev lazily, no-ops).
setup-linux:
    #!/usr/bin/env bash
    set -euo pipefail
    # See setup-macos: skip venv creation when flox (or any activation)
    # already owns one, or the empty ./.venv shadows it everywhere.
    if [ -z "${VIRTUAL_ENV:-}" ]; then
        uv venv --python 3.11 --allow-existing
    fi
    if [ "$(uname -m)" = x86_64 ]; then
        uv pip install -e ".[dev,uinput,dbus]"
    else
        echo "note: $(uname -m) has no evdev-binary wheel; source-building python-evdev." >&2
        uv pip install -e ".[dev,dbus]"
        PYTHON="${VIRTUAL_ENV:-.venv}/bin/python" bash scripts/install_evdev_source.sh \
            || echo "warn: evdev source build failed; uinput key injection will no-op." >&2
    fi
    cd client && npm install

# macOS dev: [dev] + [macos] (PyObjC Quartz covers scroll, pointer, click,
# and held-button drag for the trackpad). No [dbus] extra: macOS has no
# session bus and the default layout's D-Bus/MPRIS targets don't exist there
# (issue #27), so __main__ wires a null bus factory and the daemon serves
# without those primitives.
setup-macos:
    #!/usr/bin/env bash
    set -euo pipefail
    # Under flox the env already exists ($FLOX_ENV_CACHE/python) and
    # `uv pip install` targets it. Creating ./.venv anyway leaves an empty
    # venv that shadows the real one: it lands first on test-all's PATH,
    # pyright picks it over --pythonpath, and playwright boots
    # .venv/bin/deckd. So only create one when nothing is active.
    if [ -z "${VIRTUAL_ENV:-}" ]; then
        uv venv --python 3.11 --allow-existing
    fi
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
    VLC_HTTP_PASSWORD=dummy deckd --layouts-dir layouts --client-dist client/dist --verbose

# Run the daemon on the LAN without a built client (use dev-client-lan for HMR).
# Binds to 0.0.0.0 so a phone on the LAN (or Tailscale) can reach it
# (issue #66). Token auth still gates every non-localhost connection.
run-daemon-lan:
    VLC_HTTP_PASSWORD=dummy deckd --bind 0.0.0.0 --layouts-dir layouts --verbose

# Default ports, and the knobs that let worktrees coexist. `just worktree-adopt`
# writes all four into a per-checkout ./.env (loaded above); set them by hand
# for a one-off. DECKD_E2E_PORT and DECKD_SMOKE_PORT move the two throwaway
# test daemons, so two worktrees can run `just test-all` at the same time.
DECKD_PORT := env_var_or_default("DECKD_PORT", "8765")
VITE_PORT := env_var_or_default("VITE_PORT", "5173")
DECKD_E2E_PORT := env_var_or_default("DECKD_E2E_PORT", "8975")
DECKD_SMOKE_PORT := env_var_or_default("DECKD_SMOKE_PORT", "18765")

# Kill whatever is bound to the two ports we use: the daemon (default :8765)
# and the Vite dev server (default :5173). Handy when a stale daemon still
# holds the port (deckd now fails fast on that) or a dev server outlived its
# terminal, leaving the client with no backend. Honours DECKD_PORT /
# VITE_PORT so multi-worktree `just kill` only tears down the current
# worktree's processes, not every deckd on the box.
kill:
    #!/usr/bin/env bash
    set -uo pipefail
    for port in {{DECKD_PORT}} {{VITE_PORT}}; do
        pids=$(lsof -ti "tcp:$port" 2>/dev/null || true)
        if [ -z "$pids" ]; then
            echo ":$port already free"
            continue
        fi
        echo "killing :$port -> $pids"
        kill $pids 2>/dev/null || true
        sleep 0.3
        pids=$(lsof -ti "tcp:$port" 2>/dev/null || true)
        if [ -n "$pids" ]; then
            echo "  still alive, SIGKILL -> $pids"
            kill -9 $pids 2>/dev/null || true
        fi
    done

# Run the whole dev stack with one command: the daemon (LAN, restart-on-edit)
# plus the Vite client (tailscale HTTPS). Ctrl+C — or either process dying —
# stops both. This replaces the old Procfile
# (daemon: dev-daemon-lan / client: dev-client-tailscale). For a plain
# LAN/HTTP client with no cert, run `just dev-lan` instead. Honours
# DECKD_PORT / VITE_PORT for multi-worktree setups; the recipe prints which
# ports it's using so you know where to point the phone.
dev:
    #!/usr/bin/env bash
    set -uo pipefail
    echo "deckd on :{{DECKD_PORT}}, vite on :{{VITE_PORT}}"
    # kill 0 targets this script's process group, so Ctrl+C tears down both
    # `just` children AND their grandchildren (deckd, node/vite) — no orphans
    # left holding :{{DECKD_PORT}} / :{{VITE_PORT}}.
    trap 'kill 0' EXIT
    just dev-daemon-lan &
    just dev-client-tailscale &
    # Fall through (and via the trap, stop the sibling) the moment either exits.
    wait -n

# Same as `just dev` but with the plain-HTTP LAN client (no tailscale cert,
# no sudo). Reachable at http://<host>:5173/ on the LAN; no PWA install
# prompt (that needs the HTTPS secure context `just dev` provides).
# TODO: consider replacing this with overmind/hivemind
dev-lan:
    #!/usr/bin/env bash
    set -uo pipefail
    echo "deckd on :{{DECKD_PORT}}, vite on :{{VITE_PORT}}"
    trap 'kill 0' EXIT
    just dev-daemon-lan &
    just dev-client-lan &
    wait -n

# Run the daemon under a supervisor that restarts it when daemon/**/*.py
# changes. Layout YAML hot-reload is built into the daemon itself; this is
# only useful when editing Python.
dev-daemon:
    VLC_HTTP_PASSWORD=dummy deckd-dev --port {{DECKD_PORT}} --verbose

# Same, but bind the daemon to all interfaces so a phone on the LAN
# (or Tailscale) can reach it. deckd-dev forwards unknown args to the
# child, so --bind, --port, and --verbose end up on the deckd process.
# Issue #66. --port honours DECKD_PORT so multiple worktrees can coexist.
dev-daemon-lan:
    VLC_HTTP_PASSWORD=dummy deckd-dev --bind 0.0.0.0 --port {{DECKD_PORT}} --verbose

# Vite dev server on the LAN. Vite proxies /ws and /health to the local
# daemon (see vite.config.ts), so the client is same-origin at the vite
# origin. Honours VITE_PORT for multi-worktree setups; --strictPort is
# dropped when VITE_PORT is overridden so Vite can fall through to the
# next free port if a sibling worktree grabbed the override.
dev-client-lan:
    #!/usr/bin/env bash
    set -euo pipefail
    port_flag="--port {{VITE_PORT}} --strictPort"
    if [ "{{VITE_PORT}}" != "5173" ]; then
        echo "vite on :{{VITE_PORT}} (DECKD_UPSTREAM=http://127.0.0.1:{{DECKD_PORT}})"
        port_flag="--port {{VITE_PORT}}"
    else
        echo "vite on :{{VITE_PORT}}"
    fi
    cd client && DECKD_UPSTREAM="http://127.0.0.1:{{DECKD_PORT}}" npm run dev -- --host 0.0.0.0 $port_flag

# Vite dev server with HTTPS via a tailscale-provisioned cert. Required
# for Chrome's PWA install prompt (secure-context gate). Provisions the
# cert lazily on first run; caches it under client/.tls (gitignored).
# Phone opens https://<host>.<tailnet>.ts.net:5173/ (or the override of
# VITE_PORT). Honours VITE_PORT for multi-worktree setups; --strictPort
# is dropped when overridden so Vite can fall through if the port is busy.
dev-client-tailscale:
    #!/usr/bin/env bash
    set -euo pipefail
    ts() { local cmd="tailscale"; for c in tailscale /Applications/Tailscale.app/Contents/MacOS/Tailscale; do if command -v "$c" &>/dev/null; then cmd="$c"; break; fi; done; if ! command -v "$cmd" &>/dev/null; then echo "tailscale CLI not found. Install Tailscale or symlink it:" >&2; echo "  sudo ln -s /Applications/Tailscale.app/Contents/MacOS/Tailscale /usr/local/bin/tailscale" >&2; exit 1; fi; echo "$cmd"; }
    ts="$(ts)"
    host="$("$ts" status --self --json | jq -r .Self.DNSName | sed 's:\.$::')"
    tls="client/.tls"
    mkdir -p "$tls"
    if [ ! -f "$tls/$host.crt" ] || [ ! -f "$tls/$host.key" ]; then
      echo "Provisioning tailscale cert for $host in $tls/ (requires sudo)..."
      (cd "$tls" && sudo "$ts" cert "$host" && sudo chown "$USER" "$host.crt" "$host.key")
    fi
    echo "-> https://$host:{{VITE_PORT}}/"
    port_flag="--port {{VITE_PORT}} --strictPort"
    if [ "{{VITE_PORT}}" != "5173" ]; then
        port_flag="--port {{VITE_PORT}}"
    fi
    cd client && DECKD_TLS_DIR="./.tls" DECKD_TLS_HOST="$host" DECKD_UPSTREAM="http://127.0.0.1:{{DECKD_PORT}}" npm run dev -- --host 0.0.0.0 $port_flag

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

ladle:
    cd client && npm run ladle

# Take phone-framed screenshots of the demo layouts. Starts a Vite dev
# server, opens /screenshots.html in Chromium (Playwright, reuses the
# nix-store binary from e2e), snaps each configured shot, and saves them
# to docs/screenshots/. Edit client/src/Screenshots.tsx to curate the list.
screenshots:
    cd client && node screenshots.mjs

# Run the full verification ladder (docs/ONBOARDING.md) in order:
# typechecks first (cheap gates), then Python unit/integration, then
# TypeScript compile, client unit tests, Playwright e2e, the daemon
# smoke test, and finally the lint sweep. Each step must pass before
# the next. Skips nothing; anything that needs human-on-hardware
# verification lives above this ladder (see docs/TESTING.md).
test-all:
    #!/usr/bin/env bash
    set -euo pipefail
    # Only prepend ./.venv when it's the real env — under flox it either
    # doesn't exist or (historically) is an empty shell that shadows the
    # active interpreter and breaks every step below.
    if [ -x .venv/bin/python ]; then
        export PATH="$PWD/.venv/bin:$PATH"
    fi
    echo "== 1/7  pyright daemon =="
    # --pythonpath resolves imports against whichever env is active
    # (flox cache or ./.venv); see [tool.pyright] in pyproject.toml.
    pyright --pythonpath "$(command -v python)" daemon
    echo "== 2/7  pytest =="
    pytest
    echo "== 3/7  tsc --noEmit =="
    (cd client && npx tsc --noEmit)
    echo "== 4/7  vitest unit =="
    (cd client && npm run test:unit)
    # Build the client before e2e — playwright serves client/dist, so
    # any TypeScript change in client/src must be bundled for the
    # browser to pick it up.
    (cd client && npm run build)
    echo "== 5/7  playwright e2e =="
    (cd client && npm run test:e2e)
    echo "== 6/7  smoke =="
    just smoke
    echo "== 7/7  eslint =="
    (cd client && npm run lint)

# Run the test suite.
test:
    pytest
    node scripts/test_focus_wire_shape.mjs
    node scripts/test_kwin_focus_bridge.mjs

# Protocol drift guard (#76): regenerate the TypeScript wire types from
# daemon/deckd/protocol.py and fail if the checked-in
# client/src/protocol.generated.ts has drifted. Edit protocol.py and
# run `just check-protocol` (or
# `python scripts/codegen_protocol_ts.py --out client/src/protocol.generated.ts`
# to regenerate). The companion drift test in
# tests/test_protocol_ts_drift.py runs the same check in pytest so CI
# catches drift without needing the Justfile recipe.
check-protocol:
    python scripts/codegen_protocol_ts.py --check --out client/src/protocol.generated.ts

# Regenerate the TypeScript wire types from daemon/deckd/protocol.py (#76).
# Run after editing the protocol; check-protocol (and CI) will fail until
# the generated file is in sync.
gen-protocol:
    python scripts/codegen_protocol_ts.py --out client/src/protocol.generated.ts

# Run the GNOME + KDE focus JSON producer contracts independently.
test-focus-wire:
    node scripts/test_focus_wire_shape.mjs
    node scripts/test_kwin_focus_bridge.mjs

# Live-bus MPRIS smoke test — NOT part of `test` / CI. Publishes a real
# MPRIS player on the session bus and asserts the production
# DbusMprisBackend enumerates it with correct metadata. Needs a desktop
# session bus; skips (exit 0) on a headless box. See
# scripts/smoke_mpris_live.py.
smoke-mpris:
    "${VIRTUAL_ENV:-.venv}/bin/python" scripts/smoke_mpris_live.py

# Live-bus GNOME focus smoke test (#129) — NOT part of `test` / CI.
# Drives the production GnomeShellFocusBackend over the live session bus
# and asserts GetActiveWindow / ListWindows / RaiseWindow are well-formed
# — catches extension↔compositor drift daemon-side mocks can't (the
# e166242 empty-list bug). Needs a GNOME session with deckd-focus@local
# enabled and a window open; skips (exit 0) when org.deckd.Focus isn't on
# the bus. See scripts/smoke_focus_live.py.
smoke-focus:
    "${VIRTUAL_ENV:-.venv}/bin/python" scripts/smoke_focus_live.py

# Run the client test suite (Vitest unit tests + Playwright e2e). The e2e
# half boots the daemon with PYTHONPATH=scripts/no-evdev so its uinput sink
# is shadowed to LoggingKeySink — keystrokes are logged, not injected into
# the host desktop. See client/e2e/kbd-mode.spec.ts for the suite.
test-client:
    cd client && npm run test:unit
    cd client && npm run test:e2e

# End-to-end smoke test (boots daemon in-process, fires every action
# primitive). Uses a stable fixture layout (scripts/smoke_fixtures/)
# so shipping-layout edits can't break CI (#77). Pass --layouts-dir to
# point at shipping layouts (or anything else) instead. Binds DECKD_SMOKE_PORT
# (default :18765, well away from any live daemon) so two worktrees can run
# it concurrently.
smoke:
    DECKD_SMOKE_PORT={{DECKD_SMOKE_PORT}} python -u scripts/smoke.py

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

# Install deckd as a per-user session service so it starts with your desktop.
#
# OS-aware (like `just setup`): on Linux installs the systemd *user* unit
# (packaging/systemd/deckd.service) to ~/.config/systemd/user and enables it;
# on macOS installs the launchd LaunchAgent (packaging/launchd/...) to
# ~/Library/LaunchAgents and loads it. Both substitute this checkout's path in.
# deckd is a per-user desktop-session daemon, hence a *user* service, not a
# system one. Run `just setup && just build-client` and set up the focus watcher
# (`just install-focus-extension` / `install-focus-kwin`) first. Re-run anytime.
install-service:
    #!/usr/bin/env bash
    set -euo pipefail
    project_dir="$(pwd)"
    if [ "$(uname)" = "Darwin" ]; then
        dest="$HOME/Library/LaunchAgents/com.deckd.daemon.plist"
        sed "s|@PROJECT_DIR@|${project_dir}|g" packaging/launchd/com.deckd.daemon.plist > "$dest"
        launchctl unload "$dest" 2>/dev/null || true
        launchctl load "$dest"
        echo "com.deckd.daemon LaunchAgent installed and loaded. Logs: tail -f ${project_dir}/deckd.log"
    else
        dest_dir="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
        mkdir -p "$dest_dir"
        sed "s|@PROJECT_DIR@|${project_dir}|g" packaging/systemd/deckd.service > "$dest_dir/deckd.service"
        systemctl --user daemon-reload
        systemctl --user enable --now deckd.service
        echo "deckd.service installed and started. Logs: journalctl --user -u deckd -f"
        echo "Optional: 'sudo loginctl enable-linger $USER' keeps it running when you're logged out."
    fi

# Print active app/window changes for Spike #2.
watch-focus:
    python -u scripts/watch_focus.py

# Single snapshot of the active app/window.
watch-focus-once:
    python -u scripts/watch_focus.py --once

# Hit /health.
#
# These four all target DECKD_PORT — i.e. *this* checkout's daemon. Without
# that, deckctl's own default (:8765) would answer from whatever holds the
# default port, which on a machine running an installed deckd service is the
# prod daemon rather than the dev one you just started. To aim at another
# instance deliberately: `DECKD_PORT=8765 just status`.
status:
    deckctl --port {{DECKD_PORT}} status

# Hit /diag (issue #70): one-shot machine-readable snapshot of the
# daemon's focus, input, layouts, sessions, and MPRIS state. Open-auth,
# so it works without the password. Same shape ``deckctl status``
# uses, just on a richer endpoint.
diag:
    #!/usr/bin/env bash
    set -euo pipefail
    deckctl --port {{DECKD_PORT}} diag

# Hit /layouts (issue #70): enumeration of loaded layouts and safe
# widget summaries (no action bodies).
layouts:
    #!/usr/bin/env bash
    set -euo pipefail
    deckctl --port {{DECKD_PORT}} layouts

# Hit /metrics (issue #71): Prometheus text-format scrape. Open-auth
# and stdlib-only on the server side; pipe into ``head`` or
# ``grep deckd_`` for a quick check.
metrics:
    #!/usr/bin/env bash
    set -euo pipefail
    deckctl --port {{DECKD_PORT}} metrics

# Print the version from pyproject.toml. The single source for artifact
# names (the DMG) and the release tag guard, so they can't drift.
version:
    @sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml | head -n1

# Build the self-contained macOS app bundle (dist/deckd.app, issue #165).
# macOS only: a .app needs Apple tooling, so this refuses to run elsewhere.
# Installs the [packaging] extra (PyInstaller) on demand and builds the
# client first if it's missing. Output is ad-hoc signed, not notarized.
build-macos-app:
    #!/usr/bin/env bash
    set -euo pipefail
    if [ "$(uname)" != "Darwin" ]; then
        echo "build-macos-app needs macOS; a .app can't be built on $(uname)." >&2
        exit 1
    fi
    if ! command -v pyinstaller >/dev/null 2>&1; then
        echo "installing PyInstaller ([packaging] extra)..."
        uv pip install -e ".[packaging]"
    fi
    if [ ! -f client/dist/index.html ]; then
        echo "client/dist missing; building client..."
        just build-client
    fi
    pyinstaller --noconfirm --clean packaging/macos/deckd.spec
    echo "Built dist/deckd.app (ad-hoc signed, not notarized)."

# Wrap dist/deckd.app in a distributable DMG for a GitHub release (#165).
# ``DECKD_VERSION`` names the artifact (the release workflow sets it from the
# git tag); otherwise it falls back to pyproject's version.
build-macos-dmg: build-macos-app
    #!/usr/bin/env bash
    set -euo pipefail
    version="${DECKD_VERSION:-$(just version)}"
    stage="$(mktemp -d)"
    trap 'rm -rf "$stage"' EXIT
    cp -R dist/deckd.app "$stage/"
    ln -s /Applications "$stage/Applications"
    hdiutil create -volname "deckd ${version}" -srcfolder "$stage" \
        -ov -format UDZO "dist/deckd-${version}.dmg"
    echo "Built dist/deckd-${version}.dmg"

# Build the self-contained Linux AppImage (dist/deckd-<version>-<arch>.AppImage,
# issue #168). Linux only: appimagetool wraps a PyInstaller onedir tree in a
# squashfs. Installs the [uinput,dbus,packaging] extras on demand and builds
# the client first if it's missing. The udev rule and focus-watcher sources ride
# along under usr/share/deckd/integration for the install helper.
build-linux-appimage:
    #!/usr/bin/env bash
    set -euo pipefail
    if [ "$(uname)" != "Linux" ]; then
        echo "build-linux-appimage needs Linux; an AppImage can't be built on $(uname)." >&2
        exit 1
    fi
    arch="$(uname -m)"
    if ! command -v pyinstaller >/dev/null 2>&1; then
        echo "installing packaging deps..."
        uv pip install -e ".[uinput,dbus,packaging]"
    fi
    if [ "$arch" != "x86_64" ]; then
        echo "note: $arch has no evdev-binary wheel; ensuring a source build." >&2
        PYTHON="$(command -v python)" bash scripts/install_evdev_source.sh \
            || echo "warn: evdev source build failed; key injection will no-op." >&2
    fi
    if [ ! -f client/dist/index.html ]; then
        echo "client/dist missing; building client..."
        just build-client
    fi
    pyinstaller --noconfirm --clean packaging/linux/deckd.spec

    version="${DECKD_VERSION:-$(just version)}"
    work="$(mktemp -d)"
    trap 'rm -rf "$work"' EXIT
    appdir="$work/deckd.AppDir"
    mkdir -p "$appdir/usr/bin" "$appdir/usr/share/deckd/integration/gnome-shell" \
             "$appdir/usr/share/deckd/integration/kwin-script"
    cp -R dist/deckd/. "$appdir/usr/bin/"
    cp packaging/udev/70-deckd-uinput.rules "$appdir/usr/share/deckd/integration/"
    cp -R packaging/gnome-shell/deckd-focus@local "$appdir/usr/share/deckd/integration/gnome-shell/"
    cp -R packaging/kwin-script/deckd-focus "$appdir/usr/share/deckd/integration/kwin-script/"
    cp packaging/linux/install-system-integration.sh "$appdir/usr/share/deckd/integration/"
    cp packaging/linux/appimage/AppRun "$appdir/AppRun"
    chmod +x "$appdir/AppRun"
    cp packaging/linux/appimage/deckd.desktop "$appdir/"
    # appimagetool wants deckd.png (or deckd.svg) at the AppDir root.
    if command -v rsvg-convert >/dev/null 2>&1; then
        rsvg-convert -w 512 -h 512 -o "$appdir/deckd.png" client/public/icon.svg
    elif command -v magick >/dev/null 2>&1; then
        magick -background none client/public/icon.svg -resize 512x512 "$appdir/deckd.png"
    elif command -v convert >/dev/null 2>&1; then
        convert -background none client/public/icon.svg -resize 512x512 "$appdir/deckd.png"
    else
        cp client/public/icon.svg "$appdir/deckd.svg"
    fi

    tooling="${XDG_CACHE_HOME:-$HOME/.cache}/deckd/appimagetool-${arch}.AppImage"
    if [ ! -x "$tooling" ]; then
        echo "fetching appimagetool (${arch})..."
        mkdir -p "$(dirname "$tooling")"
        curl -fsSL -o "$tooling" \
            "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-${arch}.AppImage"
        chmod +x "$tooling"
    fi
    export ARCH="$arch"
    APPIMAGE_EXTRACT_AND_RUN=1 "$tooling" "$appdir" "dist/deckd-${version}-${arch}.AppImage"
    cp packaging/linux/install-system-integration.sh dist/deckd-install-system-integration.sh
    echo "Built dist/deckd-${version}-${arch}.AppImage (+ dist/deckd-install-system-integration.sh)"

# Stage the integration assets from a checkout and run the privileged helper
# for the current user (issue #168): udev rule + input group (root), plus the
# focus watcher and an XDG autostart entry (user). Prompts for sudo. Useful for
# a source install and for testing the helper without building an AppImage.
# Extra args pass through (e.g. `--desktop gnome`, `--uninstall`).
install-system-integration *args:
    #!/usr/bin/env bash
    set -euo pipefail
    stage="$(mktemp -d)"
    trap 'rm -rf "$stage"' EXIT
    mkdir -p "$stage/gnome-shell" "$stage/kwin-script"
    cp packaging/udev/70-deckd-uinput.rules "$stage/"
    cp -R packaging/gnome-shell/deckd-focus@local "$stage/gnome-shell/"
    cp -R packaging/kwin-script/deckd-focus "$stage/kwin-script/"
    sudo packaging/linux/install-system-integration.sh --assets "$stage" {{args}}

# Run the Nix flake checks: builds packages.deckd and the focus-watcher
# bundles, evaluates the NixOS + home-manager modules, unit-tests the
# activation scripts in a sandbox, and boots the packaged daemon on
# loopback (health, client dist, bundled layouts). Needs Nix with flakes.
# See docs/GUIDE.md "Nix flake, NixOS, and home-manager".
nix-check:
    nix flake check -L

# --- Worktrees ------------------------------------------------------------
# Code needs nothing for `git worktree` (every path resolves from the file's
# own location). What a fresh checkout lacks is the gitignored scaffolding —
# .envrc, .venv, client/node_modules, TLS certs — plus a port assignment that
# doesn't collide with its siblings. See docs/ONBOARDING.md#worktrees-git-worktree.

# "Adopt" because the worktree usually already exists: an agent harness
# (Paseo, Cursor) or a plain `git worktree add` made it, and this claims it
# afterwards. Assigns free ports -> ./.env, wires .envrc to the primary
# checkout's flox env, copies over gitignored bits worth sharing (TLS certs),
# then runs `just setup`. Idempotent, so it's also the repair command. Pass
# --no-install to skip the slow dependency step, --force to reassign ports.
#
# Make THIS worktree dev-ready: ports, env, dependencies. [--no-install] [--force]
worktree-adopt *args:
    @bash scripts/worktree.sh adopt {{args}}

# Checks port assignment (including collisions with siblings), .envrc,
# toolchain on PATH, venv, and client deps. Every failure prints its fix;
# exits non-zero if the checkout isn't ready.
#
# Why isn't this worktree working?
worktree-doctor:
    @bash scripts/worktree.sh doctor

# Every worktree with its assigned ports and readiness. `*` marks this one.
worktree-list:
    @bash scripts/worktree.sh list

# For harness-created worktrees, run `worktree-adopt` inside the checkout
# instead — this is only for the from-scratch case.
#
# Add a worktree at ../deckd-<branch> on a new branch off HEAD, then adopt it.
worktree-create branch *args:
    #!/usr/bin/env bash
    set -euo pipefail
    dir="$(cd "$(git rev-parse --show-toplevel)/.." && pwd)/deckd-{{branch}}"
    git worktree add -b "{{branch}}" "$dir"
    cd "$dir" && just worktree-adopt {{args}}
