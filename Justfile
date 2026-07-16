# deckd — common commands

# `just` (no args) lists available recipes.
default:
    @just --list

# Create the venv and install Python + JS deps. Idempotent.
# Run once. flox activate handles PATH; this sets up the venv itself.
setup:
    uv venv --python 3.12 --allow-existing
    uv pip install -e ".[dev,uinput]"
    cd client && npm install

# Run the daemon against the layouts directory, serving the built client.
run-daemon:
    .venv/bin/deckd --layouts-dir layouts --client-dist client/dist --verbose

# Run the daemon on the LAN without a built client (use dev-client-lan for HMR).
run-daemon-lan:
    .venv/bin/deckd --host 0.0.0.0 --layouts-dir layouts --verbose

# # Run the daemon without a built client (use dev-client for HMR).
# run-daemon-dev:
#     .venv/bin/deckd --layouts-dir layouts --verbose

# # Vite dev server (proxies /ws to the daemon).
# dev-client:
#     cd client && npm run dev -- --strictPort

# Vite dev server on the LAN, with WS pointed at this host's LAN IP.
dev-client-lan:
    host="$(hostname -s)"; echo "VITE_DECKD_WS=ws://$host:8765/ws"; cd client && VITE_DECKD_WS="ws://$host:8765/ws" npm run dev -- --host 0.0.0.0 --strictPort

# Build the client (output: client/dist/).
build-client:
    cd client && npm run build

# Run the test suite.
test:
    pytest

# End-to-end smoke test (boots daemon in-process, fires every action primitive).
smoke:
    python -u scripts/smoke.py

# Check whether this shell can create a uinput scroll device.
check-uinput:
    python -u scripts/check_uinput.py

# Install and enable the local GNOME Shell focus extension for Spike #2.
install-focus-extension:
    tmpdir="$(mktemp -d)"; gnome-extensions pack -f -o "$tmpdir" packaging/gnome-shell/deckd-focus@local; gnome-extensions install --force --print-uuid "$tmpdir/deckd-focus@local.shell-extension.zip"; rm -rf "$tmpdir"; if gnome-extensions list | grep -qx deckd-focus@local; then gnome-extensions enable deckd-focus@local; else echo "Installed deckd-focus@local. Log out/in, then run: gnome-extensions enable deckd-focus@local"; fi

# Print active app/window changes for Spike #2.
watch-focus:
    .venv/bin/python -u scripts/watch_focus.py

# Single snapshot of the active app/window.
watch-focus-once:
    .venv/bin/python -u scripts/watch_focus.py --once

# Hit /health.
status:
    .venv/bin/deckctl status
