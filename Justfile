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
    # See setup-macos: skip venv creation when flox (or any activation)
    # already owns one, or the empty ./.venv shadows it everywhere.
    if [ -z "${VIRTUAL_ENV:-}" ]; then
        uv venv --python 3.12 --allow-existing
    fi
    if [ "$(uname -m)" = x86_64 ]; then
        uv pip install -e ".[dev,uinput]"
    else
        echo "note: $(uname -m) has no evdev-binary wheel; source-building python-evdev." >&2
        uv pip install -e ".[dev]"
        PYTHON="${VIRTUAL_ENV:-.venv}/bin/python" bash scripts/install_evdev_source.sh \
            || echo "warn: evdev source build failed; uinput key injection will no-op." >&2
    fi
    cd client && npm install

# macOS dev: [dev] + [macos] (PyObjC Quartz covers scroll, pointer, click,
# and held-button drag for the trackpad).
setup-macos:
    #!/usr/bin/env bash
    set -euo pipefail
    # Under flox the env already exists ($FLOX_ENV_CACHE/python) and
    # `uv pip install` targets it. Creating ./.venv anyway leaves an empty
    # venv that shadows the real one: it lands first on test-all's PATH,
    # pyright picks it over --pythonpath, and playwright boots
    # .venv/bin/deckd. So only create one when nothing is active.
    if [ -z "${VIRTUAL_ENV:-}" ]; then
        uv venv --python 3.12 --allow-existing
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

# Kill whatever is bound to the two ports we use: the daemon (:8765) and
# the Vite dev server (:5173). Handy when a stale daemon still holds the
# port (deckd now fails fast on that) or a dev server outlived its
# terminal, leaving the client with no backend. Reports free ports and
# no-ops cleanly when nothing is running.
kill:
    #!/usr/bin/env bash
    set -uo pipefail
    for port in 8765 5173; do
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
# LAN/HTTP client with no cert, run `just dev-lan` instead.
dev:
    #!/usr/bin/env bash
    set -uo pipefail
    # kill 0 targets this script's process group, so Ctrl+C tears down both
    # `just` children AND their grandchildren (deckd, node/vite) — no orphans
    # left holding :8765 / :5173.
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
    trap 'kill 0' EXIT
    just dev-daemon-lan &
    just dev-client-lan &
    wait -n

# Run the daemon under a supervisor that restarts it when daemon/**/*.py
# changes. Layout YAML hot-reload is built into the daemon itself; this is
# only useful when editing Python.
dev-daemon:
    VLC_HTTP_PASSWORD=dummy deckd-dev --verbose

# Same, but bind the daemon to all interfaces so a phone on the LAN
# (or Tailscale) can reach it. deckd-dev forwards unknown args to the
# child, so --bind and --verbose end up on the deckd process. Issue #66.
dev-daemon-lan:
    VLC_HTTP_PASSWORD=dummy deckd-dev --bind 0.0.0.0 --verbose

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
    ts() { local cmd="tailscale"; for c in tailscale /Applications/Tailscale.app/Contents/MacOS/Tailscale; do if command -v "$c" &>/dev/null; then cmd="$c"; break; fi; done; if ! command -v "$cmd" &>/dev/null; then echo "tailscale CLI not found. Install Tailscale or symlink it:" >&2; echo "  sudo ln -s /Applications/Tailscale.app/Contents/MacOS/Tailscale /usr/local/bin/tailscale" >&2; exit 1; fi; echo "$cmd"; }
    ts="$(ts)"
    host="$("$ts" status --self --json | jq -r .Self.DNSName | sed 's:\.$::')"
    tls="client/.tls"
    mkdir -p "$tls"
    if [ ! -f "$tls/$host.crt" ] || [ ! -f "$tls/$host.key" ]; then
      echo "Provisioning tailscale cert for $host in $tls/ (requires sudo)..."
      (cd "$tls" && sudo "$ts" cert "$host" && sudo chown "$USER" "$host.crt" "$host.key")
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

# Run the GNOME focus JSON producer contract independently.
test-focus-wire:
    node scripts/test_focus_wire_shape.mjs

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
status:
    deckctl status

# Hit /diag (issue #70): one-shot machine-readable snapshot of the
# daemon's focus, input, layouts, sessions, and MPRIS state. Open-auth,
# so it works without the password. Same shape ``deckctl status``
# uses, just on a richer endpoint.
diag:
    #!/usr/bin/env bash
    set -euo pipefail
    deckctl diag

# Hit /layouts (issue #70): enumeration of loaded layouts and safe
# widget summaries (no action bodies).
layouts:
    #!/usr/bin/env bash
    set -euo pipefail
    deckctl layouts

# Hit /metrics (issue #71): Prometheus text-format scrape. Open-auth
# and stdlib-only on the server side; pipe into ``head`` or
# ``grep deckd_`` for a quick check.
metrics:
    #!/usr/bin/env bash
    set -euo pipefail
    deckctl metrics
