# deckd — common commands

# `just` (no args) lists available recipes.
default:
    @just --list

# Create the venv and install Python + JS deps. Idempotent.
setup:
    uv venv --python 3.12 --allow-existing
    uv pip install -e ".[dev,uinput]"
    cd client && npm install

# Run the daemon against the spike layout, serving the built client.
run-daemon:
    .venv/bin/deckd --layouts layouts/default.yaml --client-dist client/dist --verbose

# Run the built client and daemon on the LAN for phone/tablet testing.
run-daemon-lan:
    .venv/bin/deckd --host 0.0.0.0 --layouts layouts/default.yaml --client-dist client/dist --verbose

# Run the daemon without a built client (dev mode uses vite dev server proxy).
run-daemon-dev:
    .venv/bin/deckd --layouts layouts/default.yaml --verbose

# Run the daemon on the LAN without a built client.
run-daemon-dev-lan:
    .venv/bin/deckd --host 0.0.0.0 --layouts layouts/default.yaml --verbose

# Vite dev server (proxies /ws to the daemon).
dev-client:
    cd client && npm run dev -- --strictPort

# Vite dev server on the LAN, with WS pointed at this host's LAN IP.
dev-client-lan:
    host="$(hostname -s)"; echo "VITE_DECKD_WS=ws://$host:8765/ws"; cd client && VITE_DECKD_WS="ws://$host:8765/ws" npm run dev -- --host 0.0.0.0 --strictPort

# Build the client (output: client/dist/).
build-client:
    cd client && npm run build

# End-to-end smoke test (boots daemon in-process, fires every action primitive).
smoke:
    .venv/bin/python -u scripts/smoke.py

# Hit /health.
status:
    .venv/bin/deckctl status
