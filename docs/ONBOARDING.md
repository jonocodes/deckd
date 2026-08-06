# Agent onboarding

This document is the primary navigation map for AI agents (and human developers) working in the deckd repository. It covers the repository map, mandatory read order, protocol locations, development modes, verification ladder, and authoritative artifact guide.

## Repository map

```
.
├── AGENTS.md               # Stable operating rules for agents (you're reading the linked guide)
├── CONTEXT.md              # Domain vocabulary (ubiquitous language — read first)
├── Justfile                # All common commands: setup, dev, test, build, smoke
├── LICENSE                 # MIT
├── README.md               # Human-facing: pitch, screenshots, status, setup, config reference
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
│       ├── protocol.ts     # Wire protocol types (TypeScript mirror of daemon protocol.py)
│       ├── socket.ts       # WebSocket hook: connect, reconnect, auth
│       ├── ButtonGrid.tsx  # Button grid rendering
│       ├── JogStrip.tsx    # Scroll strip widget
│       ├── Trackpad.tsx    # Trackpad surface for manual control
│       ├── ManualControl.tsx  # Combined trackpad + keyboard passthrough mode
│       ├── MediaCell.tsx   # VLC media widget cell
│       ├── MediaBrowserCell.tsx  # Media browser row
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
    ├── INCEPTION.md        # Pre-implementation design document
    ├── SPIKES.md           # Spike progress and implementation plan
    ├── spike-kde-wayland-focus.md  # KWin focus detection investigation
    ├── adr/                # Architecture Decision Records (index at adr/README.md)
    ├── agents/             # Agent workflow docs (issue tracker, triage labels, domain)
    └── research/           # Research notes
```

## Mandatory read order

For an agent or developer new to the codebase, read in this order:

1. **README.md** — Pitch, screenshots, status, setup instructions, config reference.
2. **CONTEXT.md** — Domain vocabulary (ubiquitous language). Every concept used in code, tests, and docs is defined here.
3. **docs/REFERENCE.md** — Canonical CLI flags, environment variables, diagnostic endpoints, and project status.
4. **docs/INCEPTION.md** — Pre-implementation design. Architecture, core principles, v1 scope, deferred work.
4. **docs/adr/README.md** — ADR index with summaries and amend/supersede relationships.
5. **daemon/deckd/protocol.py** — Wire protocol, the executable contract between client and daemon. All message types in both directions.
6. **daemon/deckd/layouts.py** — Layout YAML schema (Pydantic models). How layouts are parsed, validated, and matched to focused apps.
7. **client/src/protocol.ts** — TypeScript mirror of the wire protocol.
8. **Justfile** — All common commands (setup, dev, test, build).
9. Skim the ADRs relevant to the area you're working in.

## Protocol locations

The wire protocol has two authoring locations that must stay in sync:

| Direction | Python (authoritative) | TypeScript (mirror) |
|---|---|---|
| Server to Client | `daemon/deckd/protocol.py` (`ServerMessage`) | `client/src/protocol.ts` |
| Client to Server | `daemon/deckd/protocol.py` (`ClientMessage`) | `client/src/protocol.ts` |

The Python side is authoritative for behavior. The TypeScript side is the client's type-safe rendering of the same contract. When adding a new message type, add it to both files.

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
- `--no-auth` — disable shared-password auth (dev only)
- `--verbose` — debug-level logging

## Verification ladder

Run these in order. Each step must pass before the next.

| Step | Command | What it verifies |
|---|---|---|
| 1. Python typecheck | `pyright daemon` | Type correctness of the daemon |
| 2. Python tests | `pytest` (or `just test`) | Full unit + integration test suite |
| 3. TypeScript compile | `cd client && npx tsc --noEmit` | Type correctness of the client |
| 4. Client unit tests | `cd client && npm run test:unit` | Vitest unit tests |
| 5. Client E2E tests | `cd client && npm run test:e2e` | Playwright browser tests (boots daemon) |
| 6. Smoke test | `just smoke` | End-to-end: boots daemon, connects WS, fires all action primitives |
| 7. Client lint | `cd client && npm run lint` | ESLint |

Step 1 and 3 are cheap type safety gates. Always run at least steps 1–3 before considering changes complete.

Some behaviour sits **above** this ladder — it can only be confirmed by a human on real hardware / a live session (e.g. actual `uinput` injection, focus-watching on a real desktop). When a change is merged but this is its only remaining gate, label the issue `human-verification-required` and keep it open until a human signs off. See [docs/agents/triage-labels.md](agents/triage-labels.md#verification-state-repo-extension).

The full picture — what each layer covers, what it fakes, and the planned
desktop-integration tier that would automate parts of the human step — is in
[docs/TESTING.md](TESTING.md).

## Authoritative artifacts

For each concern, exactly one artifact is authoritative. Others derive from it.

| Concern | Authoritative source | Notes |
|---|---|---|
| Domain vocabulary | `CONTEXT.md` | Ubiquitous language; all code, tests, and docs use these terms |
| Product intent | `docs/INCEPTION.md` | Pre-implementation design; scope, architecture, deferred work |
| Architecture decisions | `docs/adr/` | Individual ADRs are numbered; `docs/adr/README.md` indexes them |
| Wire protocol (downstream) | `daemon/deckd/protocol.py` (`ServerMessage`) | TypeScript mirrors in `client/src/protocol.ts` |
| Wire protocol (upstream) | `daemon/deckd/protocol.py` (`ClientMessage`) | TypeScript mirrors in `client/src/protocol.ts` |
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
