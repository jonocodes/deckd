# deckd

App-aware touch control surface for the Linux desktop. A Stream Deck-like deck of buttons, sliders, scroll strips, and a trackpad mode, rendered in any browser on any touchscreen device, driven by a local daemon that watches the focused application and swaps layouts automatically.

See [`docs/INCEPTION.md`](docs/INCEPTION.md) for the full design.

## Status

Pre-alpha spike. The de-risking work from §12 of the design doc is in progress:

- **uinput scroll end-to-end** (spike #1) — *not started*
- **Focus watcher** (spike #2) — *not started*

What works today: a minimal daemon + web client that proves the wire protocol and config-driven action dispatch (one `shell`, one `key`, one `page` action across two pages). Synthetic input is **not** wired up yet — `key` actions are logged only.

## Layout

```
daemon/deckd/      Python daemon: aiohttp server, WebSocket, layout loader, action dispatch
client/            Vite + React + TS web client (the dumb renderer)
layouts/           Per-app YAML layouts (one for the spike; default.yaml)
scripts/smoke.py   End-to-end test that boots the daemon over WS, clicks every button
docs/INCEPTION.md  Full design doc — source of truth for *what* and *why*
```

## Running the spike

You need Python 3.11+ and Node 18+. Dependencies are managed with [`uv`](https://docs.astral.sh/uv/):

```sh
# 1. Install uv (one-time)
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"

# 2. Create the venv and install deps
uv venv --python 3.12
uv pip install -e ".[dev]"

# 3. Install JS client deps (once)
cd client && npm install && cd ..

# 4. Build the client so the daemon can serve it
just build-client

# 5. Run the daemon (serves the built client at http://127.0.0.1:8765)
just run-daemon
```

Open `http://127.0.0.1:8765` in any browser. You should see three buttons: `Open example.com` (fires `xdg-open`), `Send Ctrl+T (stub)` (logs `[key stub]`), and `Second page →` (navigates to a second page).

### Dev mode (Vite HMR + auto-reload)

Two terminals:

```sh
# Terminal 1: supervisor — runs the daemon, auto-reloads on YAML edits,
# auto-restarts on Python edits.
just dev

# Terminal 2: vite dev server (HMR for client/src/**).
just dev-client
# open http://127.0.0.1:5173
```

Edit any YAML in `layouts/` → layout hot-pushes to your open browser tab.
Edit any Python in `daemon/deckd/` → daemon restarts in place; reload your
browser tab to reconnect. Edit any TSX/CSS in `client/src/` → Vite HMR.

### Smoke test

`scripts/smoke.py` boots the daemon in-process, connects a WS client, fires every action primitive, and asserts the right things happen. Useful as a quick "did I just break the wire?" check:

```sh
uv pip install -e ".[dev]"   # installs the websockets test dep
.venv/bin/python -u scripts/smoke.py
```

### CLI

```sh
deckctl status    # hit /health
```

## Configuration

A single YAML file for the spike (`layouts/default.yaml`). Each widget has an `id`, `kind` (`button` for now; `jogstrip` and `trackpad` declared in the schema but unsupported in the spike), a `grid: [x, y, w, h]` placement, and an `action`. Action primitives:

- `shell: "..."` — run a subprocess (fire-and-forget; stdout/stderr discarded).
- `key: "ctrl+t"` — *(stubbed: logged only; uinput wiring is the next spike.)*
- `dbus: "..."` — *(stubbed: logged only.)*
- `page: "<name>"` — switch the client to another page in the same layout.

## What the spike proves

- WebSocket wire protocol in both directions (layout push, `press` event).
- YAML config → Pydantic → `Widget` graph → action dispatch.
- Three of the four action primitives end-to-end (`shell` for real; `key` and `page` for real but with `key` stubbed at the injection layer; `page` swaps the rendered layout).
- Reconnecting client (`useDeckdSocket` exponential backoff).
- Build output is plain static files — `client/dist/` — served by the daemon.

## Why a venv, not a Nix shell?

The daemon is normal Python — `pip install -e .` is the contract. We keep the Nix-based packaging (udev rules, `input` group, `systemd.user.service`) in the lifecycle milestone [#5](https://github.com/jonocodes/deckd/issues/5) for when a clean-machine install story matters; the per-day edit/run loop should not need a sandbox.
