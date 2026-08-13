# Reference

Canonical operational reference — daemon flags, `deckctl` commands, environment variables, authentication, diagnostic workflows, and project status. This is the single source of truth; other documentation links here rather than duplicating command tables.

## Daemon (`deckd`)

```
deckd [--bind ADDR] [--port PORT] [--layouts-dir PATH] [--no-overlay]
      [--no-focus] [--client-dist PATH] [--password-file PATH] [--no-auth]
      [--scroll-momentum-friction F] [--scroll-momentum-cutoff C]
      [--log-format {text,json}] [--log-file PATH] [-v]
```

### Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--bind ADDR` | `127.0.0.1` + `::1` | Repeatable. Literal IP or `iface:<name>`. `0.0.0.0` opens to the LAN. |
| `--port PORT` | `8765` | `0` asks the kernel for an ephemeral port. |
| `--layouts-dir PATH` | (required) | Directory of per-app YAML layouts. |
| `--no-overlay` | off | Skip platform overlay (`layouts.linux/`, `layouts.macos/`). |
| `--no-focus` | off | Disable the focus watcher; serve only the default layout. |
| `--client-dist PATH` | none | Serve a built client at `/`. |
| `--password-file PATH` | `$XDG_CONFIG_HOME/deckd/password` | Shared password file. Generated on first start if absent. |
| `--no-auth` | off | Disable password auth entirely. |
| `--scroll-momentum-friction F` | `0.90` | Momentum decay per 60 Hz frame. |
| `--scroll-momentum-cutoff C` | `20` | Min absolute velocity before momentum stops. |
| `--log-format {text,json}` | `text` | `json` emits structured JSON-per-record. |
| `--log-file PATH` | stderr only | Append structured logs to file (also writes stderr). |
| `-v`, `--verbose` | off | Increase log level to DEBUG. |

### Dev supervisor (`deckd-dev`)

```
deckd-dev [--port PORT] [-- <forwarded deckd args>]
```

Restarts the daemon in-process when any `daemon/**/*.py` file changes. Layout YAML hot-reload is built into the daemon itself; this supervisor is only needed when editing Python.

## Control CLI (`deckctl`)

```
deckctl [--host HOST] [--port PORT] [--password PASSWORD] <command>
```

### Global flags

| Flag | Default | Description |
|------|---------|-------------|
| `--host HOST` | `127.0.0.1` | Daemon address. Set to a LAN IP or Tailscale name for remote daemons. |
| `--port PORT` | `8765` | Daemon port. |
| `--password PASSWORD` | `$DECKD_PASSWORD` | Shared password (required when auth is on; not needed with `--no-auth`). |

### Commands

| Command | Auth? | Description |
|---------|-------|-------------|
| `deckctl status` | no | Hit `/health` — sessions, app, bind surface, pairing URL. |
| `deckctl diag` | no | Hit `/diag` — full diagnostic snapshot (focus, input, layouts, sessions, MPRIS). |
| `deckctl metrics` | no | Hit `/metrics` — Prometheus text-format counters. |
| `deckctl layouts` | no | Hit `/layouts` — loaded layout enumeration with safe widget summaries. |
| `deckctl reload` | yes | Hit `/reload` — reload all layouts on disk and push to clients. |
| `deckctl layout <id>` | yes | Hit `/layout/<id>` — force-switch all clients to the named layout. |

## Environment variables

### Daemon

| Variable | Used by | Purpose |
|----------|---------|---------|
| `TERMINAL` | `actions.py` | Override auto-detected terminal emulator. |
| `DECKD_PASSWORD` | (user supply) | Typical name for passing the password to `deckctl`. Not read by the daemon itself. |
| `VLC_HTTP_PASSWORD` | (user supply) | Named in layout `password_ref` for VLC HTTP auth. |
| `XDG_CONFIG_HOME` | `auth.py` | Base for the default password-file path (`$XDG_CONFIG_HOME/deckd/password`). |
| `XDG_CURRENT_DESKTOP` | `platform.py`, `diagnostics.py` | Desktop-env identification for focus-backend selection and `/health`. |
| `XDG_SESSION_TYPE` | `platform.py` | Wayland vs X11 detection. |
| `SSL_CERT_FILE` / `NIX_SSL_CERT_FILE` | `mpris_art.py` | CA bundle for iTunes art HTTPS lookups on NixOS. |

### Client

| Variable | Purpose |
|----------|---------|
| `DECKD_PASSWORD` | Passed by `vite.config.ts` proxy to the daemon. Also consumed by local scripts. |
| `VITE_BASE_PATH` | Base URL when deploying to a subdirectory (e.g. GitHub Pages). |

## Authentication

The daemon uses a single shared password for all clients:

- **File:** `~/.config/deckd/password` (mode `0640`). First start generates a random 32-char password and logs it once at WARN.
- **WebSocket:** Client sends `{"type": "hello", "password": "..."}` in the first frame. Invalid/auth-missing frames get `{"type": "error", "reason": "unauthorized"}` followed by a close (code `4401`).
- **HTTP:** Control endpoints (`/reload`, `/layout/<id>`, `PUT /layouts/<id>`, `POST /layouts`, `/mpris/<row>/command`) require `X-Deckd-Password` header.
- **Bypass:** `--no-auth` disables all checks. `/health`, `/diag`, `/metrics`, `GET /layouts`, and the art proxies are always open (read-only, no secret leak).
- **Rotation:** Edit the password file and restart the daemon.

See [README#client-auth](../README.md#client-auth) for the full flow.

## Diagnostic HTTP endpoints

All are read-only and unauthenticated unless noted.

| Endpoint | Description |
|----------|-------------|
| `GET /health` | Host identity (`hostname`, `os`, `desktop`), sessions, current app, bind surface (`bind`, `addresses`, `url`). Used by `deckctl status` and the client Settings panel. |
| `GET /diag` | Full snapshot: focus watcher status, input sink, layout store, sessions, tasks, MPRIS state (if active). Machine-readable for AI-assisted debugging. |
| `GET /metrics` | Prometheus text-format scrape target. Counters: `deckd_actions_total{primitive,outcome}`, `deckd_dbus_calls*`, `deckd_layout_reloads*`, `deckd_ws_sessions_active`, `deckd_mpris_*`, etc. |
| `GET /layouts` | Enumeration of every loaded layout with safe widget summaries (id, kind, label, grid, `has_action`; no raw shell/dbus/url/text command bodies). |
| `GET /actions/recent?limit=N` | Bounded ring buffer of recent action attempts (id, outcome, timestamp; no command text). Default 64. |
| `GET /mpris/players` | Redacted MPRIS player snapshot. |
| `GET /mpris/events/recent?limit=N` | Bounded ring buffer of MPRIS subsystem events. Default 64. |
| `POST /reload` | **Auth.** Reload all layouts on disk, push to clients. |
| `POST /layout/<id>` | **Auth.** Force-switch all clients to the named layout (runtime override, not sticky; singular `/layout` to distinguish from the write API below). |
| `PUT /layouts/<id>` | **Auth.** Idempotent full-snapshot save of an existing layout (issue #84). URL `<id>` must equal `match[0]`; `409` on a `match[0]` change (rename). `400` sanitized structured Pydantic errors (`loc`/`msg`/`type` only); `404` unknown id. `200` echoes the canonical re-read (`{ok, layout}`); atomic temp-write + `os.replace`, natural `watchfiles` reload. |
| `POST /layouts` | **Auth.** Create-on-first-save (issue #99). Body = a full layout snapshot; id/filename derived from slugified `match[0]`; `409` if the id (or slugified filename) already exists; `400` on validation failure / empty `match`; `200` echoes the canonical re-read. |
| `POST /mpris/<row>/command` | **Auth.** Dispatch a play-pause/next/previous command to the named MPRIS row. |
| `GET /media/<widget_id>/art` | Proxy VLC album art. |
| `GET /mpris/<row_id>/art` | Proxy MPRIS album art. |

### Diagnostic workflow

```
# Is the daemon running and which app has focus?
deckctl status

# What does the daemon believe about its own state?
deckctl diag

# Any action failures? MPRIS issues?
curl -s localhost:8765/metrics | grep -E 'deckd_(actions_total|mpris_)'

# What layouts are currently loaded?
deckctl layouts

# What was the last thing pressed?
curl -s localhost:8765/actions/recent | jq

# Find the stale process and restart cleanly
just kill
just run-daemon
```

## Just recipes

Primary development operations. Run `just` (no args) to list all available recipes.

| Recipe | What it does |
|--------|-------------|
| `just setup` | Install dependencies (uv + npm). Auto-picks `setup-linux` or `setup-macos`. |
| `just run-daemon` | Start the daemon serving a built client. |
| `just run-daemon-lan` | Start the daemon bound to `0.0.0.0` (LAN-visible). |
| `just dev` | Dev stack: daemon (LAN, restart-on-edit) + Vite client (Tailscale HTTPS). |
| `just dev-lan` | Dev stack: daemon + Vite client on plain HTTP LAN. |
| `just kill` | Kill whatever is on `:8765` and `:5173`. |
| `just build-client` | Build the client to `client/dist/`. |
| `just test` | Run the Python test suite (`pytest`). |
| `just test-client` | Run the client tests (Vitest unit + Playwright e2e). |
| `just smoke` | End-to-end smoke test (boots daemon in-process, fires every action primitive). |
| `just status` | Run `deckctl status`. |
| `just diag` | Run `deckctl diag`. |
| `just layouts` | Run `deckctl layouts`. |
| `just metrics` | Run `deckctl metrics`. |
| `just watch-focus` | Print active-app changes in real time. |
| `just install-focus-extension` | Install the GNOME Shell focus extension. |
| `just install-focus-kwin` | Install the KDE Plasma KWin focus script. |

## Shipped behavior, limitations, and planned work

### Working today

- Automatic per-app layouts driven by focus detection (GNOME Shell extension, KWin script, X11 `xdotool`).
- Button widgets with `shell:`, `terminal:`, `key:`, `dbus:`, `url:`, and `text:` action primitives.
- Macros — chain multiple steps (`key`, `shell`, `dbus`, `delay`, `url`, `text`) with optional `continue_on_error`.
- Client chrome: app badge, connection indicator, manual-control toggle, media icon, settings.
- Scroll strip (persistent right-side jogstrip with release momentum, per-layout disable).
- Manual control mode: combined trackpad + keyboard passthrough (IME → evdev).
- Now playing (chrome view with per-player transport, album art proxy, passive playback indicator).
- VLC media widget (HTTP-backed live state, album art proxy).
- Live `meter` / `stats` widgets (`cpu_percent`, `mem_percent` sensors).
- Layout hot-reload (watches `layouts/` directory; bad YAML surfaces as diagnostic on client).
- Platform overlay (`layouts.macos/`, `layouts.linux/`).
- Bind-scope control (`--bind 127.0.0.1`, `--bind iface:wlan0`, `--bind 0.0.0.0`).
- Token-based auth (`--no-auth` to disable).
- Diagnostic surface (`/diag`, `/metrics`, `/layouts`, `/actions/recent`, `/mpris/*`).
- Reconnecting WebSocket client with exponential backoff.

### Limitations

- Keystroke injection is **US-layout only** (`input.py` maps ASCII + shift-symbols to evdev keycodes). Non-US keyboard layouts will produce wrong characters.
- macOS has no equivalent media integration — the now-playing surface and chrome indicator are Linux-only.
- The `nowplaying` widget requires a per-layout YAML file; there is no auto-discovery without it.
- `deckctl` does not read the daemon's password file — supply `--password` or `$DECKD_PASSWORD` explicitly.
- `sudo` is required for the Tailscale TLS cert provisioning (`just dev`).
- Build output is static files only; there is no SSR or server-side rendering.

### Planned work (milestone issues)

| Issue | What |
|-------|------|
| #17 | NixOS production module |
| #15 | Screensaver/suspend sync via `StateMessage` D-Bus |
| #38 | Multiple simultaneous clients with different resolutions |
| #25 | Multi-backend chooser (user-managed paired-daemon list) |
| #22 | GUI layout editor (exploration spike) |
| #20 | Raise/switch to already-running app from the controller |
| #27 | Make `dbus-fast` optional (no-op on macOS) |
| #26 | macOS power sync (screensaver/sleep) |
| #32 | Windows platform backend |
| #69 | Confirmation prompt before dangerous actions and macros |
| #67 | Long-press and double-tap gestures on layout widgets |
| #64 | Reconnect, locked, and error feedback |
| #61 | Touch target sizing and spacing for chrome and widgets |

See [GitHub Issues](https://github.com/jonocodes/deckd/issues) for the full, current list.

## Layout wire protocol

For the full wire shape, the authoritative source is `daemon/deckd/protocol.py` — its Pydantic models define every field, type, and constraint. The TypeScript mirror is generated by `scripts/codegen_protocol_ts.py` into `client/src/protocol.generated.ts` (drift guard: `tests/test_protocol_ts_drift.py` + `just check-protocol`, #76); `client/src/protocol.ts` re-exports it and adds the schema-layer types (`Widget`, `Icon`) imported by the rest of the client. The daemon never interprets action bodies.

## Where to read next

| Document | For |
|----------|-----|
| [ONBOARDING.md](ONBOARDING.md) | Repository map, mandatory read order, dev modes. |
| [ARCHITECTURE.md](ARCHITECTURE.md) | System diagram and module index. |
| [CONTEXT.md](../CONTEXT.md) | Domain lexicon (ubiquitous language). |
| [INCEPTION.md](INCEPTION.md) | Project origin and design philosophy. |
| [README.md](../README.md) | User-facing overview, configuration walkthrough, platform documentation. |
| [docs/adr/](adr/) | Architectural decision records (ADR-0001 through ADR-0009+). |
| [docs/SPIKES.md](SPIKES.md) | Spike proposals and outcomes. |
