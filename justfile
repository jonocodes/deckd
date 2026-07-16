# deckd — common commands

# `just` (no args) lists available recipes.
default:
    @just --list

# Create the venv and install Python + JS deps. Idempotent.
setup:
    uv venv --python 3.12
    uv pip install -e ".[dev]"
    cd client && npm install

# Run the daemon against the spike layout, serving the built client.
run-daemon:
    .venv/bin/deckd --layouts layouts/default.yaml --client-dist client/dist --verbose

# Run the daemon without a built client (dev mode uses vite dev server proxy).
run-daemon-dev:
    .venv/bin/deckd --layouts layouts/default.yaml --verbose

# Vite dev server (proxies /ws to the daemon).
dev-client:
    cd client && npm run dev

# Run the daemon under a supervisor that auto-reloads on YAML edits and
# auto-restarts on Python edits. Use together with `just dev-client` in another
# terminal.
dev:
    .venv/bin/deckd-dev

# Build the client (output: client/dist/).
build-client:
    cd client && npm run build

# End-to-end smoke test (boots daemon in-process, fires every action primitive).
smoke:
    .venv/bin/python -u scripts/smoke.py

# Hit /health.
status:
    .venv/bin/deckctl status
