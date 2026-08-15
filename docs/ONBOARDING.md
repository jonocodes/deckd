# Agent onboarding

This document is the primary navigation map for AI agents (and human developers) working in the deckd repository. It covers the repository map, mandatory read order, protocol locations, development modes, verification ladder, and authoritative artifact guide.

## Repository map

```
.
├── AGENTS.md               # Stable operating rules for agents (you're reading the linked guide)
├── CONTEXT.md              # Domain vocabulary (ubiquitous language — read first)
├── Justfile                # All common commands: setup, dev, test, build, smoke
├── LICENSE                 # MIT
├── README.md               # Human-facing showcase: pitch, screenshots, status, comparison
├── pyproject.toml          # Python package metadata, deps, entry points
├── daemon/                 # Python daemon (deckd) — the brains of the system
│   └── deckd/
│       ├── __main__.py     # CLI entry point (argparse)
│       ├── __init__.py
│       ├── actions.py      # Action dispatch: shell, key, dbus, terminal
│       ├── auth.py         # Shared-password auth, password file management
│       ├── bind.py         # Bind address resolution (literal IPs + iface:<name>)
│       ├── cli.py          # deckctl CLI: status, reload, layout, metrics
│       ├── dev.py          # deckd-dev: file-watching supervisor for Python edits
│       ├── diagnostics.py  # GET /diag endpoint: focus, input, layouts, MPRIS snapshot
│       ├── events.py       # Diagnostic event stream / sensor polling
│       ├── input.py        # uinput sink: key/scroll/pointer injection
│       ├── layouts.py      # YAML layout loader + Pydantic schema + hot-reload watcher
│       ├── logging_setup.py
│       ├── media.py        # VLC media widget: HTTP polling, art, commands
│       ├── mpris.py        # MPRIS D-Bus backend: player discovery, playback state
│       ├── mpris_art.py    # Album art resolution: local, remote, data URI, iTunes lookup
│       ├── platform.py     # Linux platform backend: focus watchers, input injection
│       ├── platform_macos.py  # macOS platform backend: osascript focus, Quartz input
│       ├── protocol.py     # Wire protocol types in both directions (source of truth)
│       └── server.py       # aiohttp HTTP + WebSocket server, main app assembly
├── client/                 # TypeScript/React web frontend
│   ├── index.html          # SPA entry point
│   ├── gallery.html        # Responsive device gallery
│   ├── vite.config.ts      # Vite config: HTTPS, proxy, multi-page, chunks
│   └── src/
│       ├── main.tsx        # React root
│       ├── App.tsx         # Root component: layout, chrome, views
│       ├── protocol.ts     # Public wire-type entry: re-exports protocol.generated.ts + schema types
│       ├── protocol.generated.ts  # AUTO-GENERATED TS mirror of daemon protocol.py (#76)
│       ├── socket.ts       # WebSocket hook: connect, reconnect, auth
│       ├── ButtonGrid.tsx  # Button grid rendering
│       ├── JogStrip.tsx    # Scroll strip widget
│       ├── Trackpad.tsx    # Trackpad surface for manual control
│       ├── ManualControl.tsx  # Combined trackpad + keyboard passthrough mode
│       ├── MediaCell.tsx   # VLC media widget cell
│       ├── NowPlayingCell.tsx  # Now playing row
│       ├── MeterCell.tsx   # Live sensor meter widget
│       ├── StatsCell.tsx   # Stats display cell
│       ├── Settings.tsx    # Per-device client tuning panel
│       ├── PasswordGate.tsx  # Auth password entry screen
│       ├── Icon.tsx        # Icon component: Lucide + Simple Icons
│       ├── Tooltip.tsx     # Tooltip component
│       ├── demo.ts         # Demo/fixture layouts (backend-free mode)
│       ├── settings-store.ts  # Per-device settings in localStorage
│       ├── media-store.ts  # VLC media state store
│       ├── meter-store.ts  # Live meter sensor state store
│       ├── orientation.ts  # Grid transpose for portrait mode
│       ├── wake-lock.ts    # Screen Wake Lock API wrapper
│       ├── a11y.ts         # Accessibility helpers
│       └── style.css       # Global styles
├── layouts/                # Per-app YAML layouts (Linux desktop)
├── layouts.macos/          # macOS overlay layouts (shadow shared ids)
├── packaging/              # Platform packaging artifacts
│   ├── udev/               # udev rule for /dev/uinput access
│   ├── nixos/              # NixOS spike module
│   ├── kwin-script/        # KWin focus script (KDE Plasma Wayland)
│   └── gnome-shell/        # GNOME Shell focus extension
├── scripts/                # Diagnostic and testing utilities
├── tests/                  # Python test suite (pytest + pytest-asyncio)
└── docs/                   # Documentation (see below)
    ├── GUIDE.md            # User & setup guide: install, per-platform setup, config walkthrough, client features, dev loop
    ├── SPIKES.md           # Spike progress and implementation plan
    ├── spike-kde-wayland-focus.md  # KWin focus detection investigation
    ├── adr/                # Architecture Decision Records (index at adr/README.md)
    ├── agents/             # Agent workflow docs (issue tracker, triage labels, domain)
    └── research/           # Research notes
```

## Mandatory read order

For an agent or developer new to the codebase, read in this order:

1. **README.md** — Pitch, screenshots, status, comparison (the showcase).
2. **docs/GUIDE.md** — Install, per-platform setup, layout/configuration walkthrough, client features, and the dev loop.
3. **CONTEXT.md** — Domain vocabulary (ubiquitous language). Every concept used in code, tests, and docs is defined here.
3. **docs/REFERENCE.md** — Canonical CLI flags, environment variables, diagnostic endpoints, and project status.
4. **docs/adr/README.md** — ADR index with summaries and amend/supersede relationships.
5. **daemon/deckd/protocol.py** — Wire protocol, the executable contract between client and daemon. All message types in both directions. Single source of truth (#76); TS mirror is generated by `scripts/codegen_protocol_ts.py`.
6. **daemon/deckd/layouts.py** — Layout YAML schema (Pydantic models). How layouts are parsed, validated, and matched to focused apps.
7. **client/src/protocol.generated.ts** — Auto-generated TS mirror of the wire protocol. Do not hand-edit; run `just gen-protocol` instead. Drift guard: `tests/test_protocol_ts_drift.py`.
8. **client/src/protocol.ts** — Public surface consumers import from. Re-exports the generated wire types and adds hand-curated schema-layer types (`Widget`, `Icon`) that mirror `daemon/deckd/layouts.py`.
8. **Justfile** — All common commands (setup, dev, test, build).
9. Skim the ADRs relevant to the area you're working in.

## Protocol locations

The wire protocol has one authoring location (#76):

| Direction | Authoritative source | Generated mirror |
|---|---|---|
| Server to Client | `daemon/deckd/protocol.py` (`ServerMessage`) | `client/src/protocol.generated.ts` |
| Client to Server | `daemon/deckd/protocol.py` (`ClientMessage`) | `client/src/protocol.generated.ts` |

`daemon/deckd/protocol.py` is the single source of truth. `scripts/codegen_protocol_ts.py` reads it via AST and emits `client/src/protocol.generated.ts`; the drift guard (`tests/test_protocol_ts_drift.py` + `just check-protocol`) fails CI if the two diverge. When adding or changing a message type, edit the Python side and regenerate (`just gen-protocol`); the TS file is a build artifact and must not be hand-edited.

`client/src/protocol.ts` is the public surface consumers import from. It re-exports the wire types from `protocol.generated.ts` and adds hand-curated schema-layer types (`Widget`, `Icon`, …) that mirror `daemon/deckd/layouts.py` — the YAML-loader concern, not the wire. Backwards-compat aliases (`ServerLayout` for `LayoutMessage`, etc.) preserve the original public surface.

## Development modes

All commands are `just` recipes (see `Justfile`). Key modes:

| Mode | Command | What it does |
|---|---|---|
| Setup | `just setup` | Auto-detects platform, installs Python + Node deps |
| Full dev stack | `just dev` | Daemon (LAN, auto-restart) + Vite (Tailscale HTTPS) |
| Dev LAN (no HTTPS) | `just dev-lan` | Daemon (LAN) + Vite (plain HTTP) |
| Daemon-only dev | `just dev-daemon` | Daemon under file-watch supervisor |
| Daemon LAN dev | `just dev-daemon-lan` | Same but binds 0.0.0.0 |
| Client-only dev | `just dev-client-lan` | Vite on LAN, proxies to local daemon |
| Client Tailscale | `just dev-client-tailscale` | Vite with HTTPS for PWA install |
| Build client | `just build-client` | TypeScript compile + Vite production build |
| Static daemon | `just run-daemon` | Daemon with `--client-dist` (serves built client) |
| Static daemon LAN | `just run-daemon-lan` | Same but binds 0.0.0.0 |

Key daemon CLI flags (in `daemon/deckd/__main__.py`):
- `--layouts-dir PATH` — where to load YAML layouts from
- `--client-dist PATH` — serve built client static files
- `--bind ADDR` — repeatable, literal IP or `iface:<name>` (default: `127.0.0.1` + `::1`)
- `--port N` — listen port (default `8765`; `0` asks the kernel for an ephemeral one)
- `--no-auth` — disable shared-password auth (dev only)
- `--verbose` — debug-level logging

### Worktrees (`git worktree`)

Each `git worktree add` is a fully independent checkout of the repo. Paths
inside the daemon, tests, and scripts are anchored to the file's own
location (`Path(__file__).resolve().parents[N]`), so layouts, fixtures, and
the built client all resolve correctly without any symlinks or rewrites —
no code change is required for worktree support.

The one resource that *is* shared is the host's port space: every worktree
that runs `just dev` defaults to `:8765` (daemon) and `:5173` (Vite), so a
second worktree can't bind the same ports. Override with env vars before
launching:

```sh
# worktree 1 (defaults)
just dev

# worktree 2 — pick free ports and keep them consistent across all recipes
DECKD_PORT=8766 VITE_PORT=5174 just dev
```

The dev recipes read these vars and pass them to both halves:

- `DECKD_PORT` is forwarded as `deckd-dev`'s `--port`; `dev-daemon`,
  `dev-daemon-lan`, `dev`, and `dev-lan` all honour it.
- `VITE_PORT` is forwarded as Vite's `--port`. When it's been overridden
  the recipe drops `--strictPort` so Vite falls through to the next free
  port instead of failing; it also sets `DECKD_UPSTREAM` so Vite's
  `/ws`/`/health` proxy reaches the *current* worktree's daemon.
- `just kill` only tears down the *current* worktree's ports, so two
  worktrees running side-by-side won't take each other down.

Caveats:

- **`just install-service` should only be run from your main checkout.**
  It writes the literal `$(pwd)` into the systemd unit / launchd plist;
  doing it from a feature worktree pins the service to a worktree that
  will eventually be removed.
- **Live MPRIS / focus smoke tests** (`just smoke-mpris`, `just
  smoke-focus`) hit the real session bus, so two worktrees can't run
  them simultaneously.
- **`uv.lock` is per-repo, not per-worktree.** A `uv pip install` in one
  worktree edits the lockfile that all worktrees share; if you're
  intentionally diverging dependencies, isolate with a worktree-local
  venv (`uv venv --python 3.12 .venv`) and commit changes deliberately.
- **Each worktree needs its own `.venv/`** (run `just setup` per
  worktree); `just test-all` only prepends `./.venv/bin` when one
  exists, so a worktree without one will fall back to whatever Python
  is on PATH (flox's, or the active interpreter).

## Verification ladder

Run these in order. Each step must pass before the next.

| Step | Command | What it verifies |
|---|---|---|
| 1. Python typecheck | `pyright daemon` | Type correctness of the daemon |
| 2. Python tests | `pytest` (or `just test`) | Full unit + integration test suite, including the protocol drift guard (#76) |
| 3. TypeScript compile | `cd client && npx tsc --noEmit` | Type correctness of the client |
| 4. Client unit tests | `cd client && npm run test:unit` | Vitest unit tests |
| 5. Client E2E tests | `cd client && npm run test:e2e` | Playwright browser tests (boots daemon) |
| 6. Smoke test | `just smoke` | End-to-end: boots daemon, connects WS, fires all action primitives against a stable fixture (`scripts/smoke_fixtures/`, #77) |
| 7. Client lint | `cd client && npm run lint` | ESLint |

Step 1 and 3 are cheap type safety gates. Always run at least steps 1–3 before considering changes complete.

One-command reproduction of CI locally (#77): `just test-all` runs the whole ladder in order, with the same per-step headers CI emits so failures identify the subsystem. The GitHub Actions workflow (`.github/workflows/ci.yml`) mirrors the same ladder.

Host-safe modes (#77): `just smoke` boots the daemon against `scripts/smoke_fixtures/` — no real desktop, no real input devices, no media player required. The `scripts/no-evdev/` shim (used by `client/e2e`) replaces the uinput sink with a logging-only one when the host can't open `/dev/uinput`. The macOS CI job runs the platform-parity + macOS-backend tests only, which read PyObjC capability flags and never require a live desktop or input device.

Some behaviour sits **above** this ladder — it can only be confirmed by a human on real hardware / a live session (e.g. actual `uinput` injection, focus-watching on a real desktop). When a change is merged but this is its only remaining gate, label the issue `human-verification-required` and keep it open until a human signs off. See [docs/agents/triage-labels.md](agents/triage-labels.md#verification-state-repo-extension).

The full picture — what each layer covers, what it fakes, and the planned
desktop-integration tier that would automate parts of the human step — is in
[docs/TESTING.md](TESTING.md).

## Authoritative artifacts

For each concern, exactly one artifact is authoritative. Others derive from it.

| Concern | Authoritative source | Notes |
|---|---|---|
| Domain vocabulary | `CONTEXT.md` | Ubiquitous language; all code, tests, and docs use these terms |
| Architecture decisions | `docs/adr/` | Individual ADRs are numbered; `docs/adr/README.md` indexes them |
| Wire protocol (downstream) | `daemon/deckd/protocol.py` (`ServerMessage`) | TS mirror generated to `client/src/protocol.generated.ts` by `scripts/codegen_protocol_ts.py`; drift guard in `tests/test_protocol_ts_drift.py` |
| Wire protocol (upstream) | `daemon/deckd/protocol.py` (`ClientMessage`) | (same as downstream) |
| Layout schema | `daemon/deckd/layouts.py` (`Layout`, `Widget`, `Action`) | Layout YAML is validated against these Pydantic models |
| Action dispatch | `daemon/deckd/actions.py` | What happens when a button is pressed |
| Platform backend interface | `daemon/deckd/platform.py` (`PlatformBackend` Protocol) | OS-specific backends implement this |
| CLI flags | `daemon/deckd/__main__.py` (argparse) | The running daemon is self-documenting via `--help` |
| HTTP endpoints | `daemon/deckd/server.py` (aiohttp routes) | `/health`, `/diag`, `/layouts`, `/metrics`, `/media/...`, `/mpris/...`; mutating: `POST /reload`, `POST /layout/{id}` (runtime override), `PUT /layouts/{id}` (save), `POST /layouts` (create) |
| Build/test commands | `Justfile` | All common commands in one place |
| Client rendering | `client/src/App.tsx` | Root component; widget components render per their kind |
| Triage labels | `docs/agents/triage-labels.md` | Five-label triage vocabulary + the `human-verification-required` lifecycle state |
| Research notes | `docs/research/` | Built-in actions catalog, etc. |

Prose documentation links to code for schematic, flag, endpoint, and behavioral details — it does not duplicate them. The code is the ultimate source of truth for behavior.
