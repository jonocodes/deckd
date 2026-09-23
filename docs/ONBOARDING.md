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
├── flake.nix               # Nix flake: packages, NixOS + home-manager modules, checks
├── nix/                    # Flake internals
│   ├── deckd.nix           # daemon + built client package
│   ├── focus-gnome.nix     # deckd-focus@local extension bundle
│   ├── focus-kwin.nix      # deckd-focus KWin script bundle
│   ├── seed-layouts.nix    # activation-time layouts seeding
│   ├── seed-layouts.sh     #   the shell unit it wraps
│   ├── install-kwin.nix    # activation-time KWin script install
│   ├── install-kwin.sh     #   the shell unit it wraps
│   ├── modules/            # nixos.nix, home.nix, home-gnome.nix, home-kde.nix
│   └── tests/              # flake checks: script units, module evals, runtime smoke
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
│   ├── nixos/              # retired spike module (points at the flake modules)
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

Each `git worktree add` is a fully independent checkout. Paths inside the
daemon, tests, and scripts are anchored to the file's own location
(`Path(__file__).resolve().parents[N]`), so layouts, fixtures, and the built
client all resolve correctly with no symlinks or rewrites — **no code change
is required for worktree support.**

What a fresh worktree *does* lack is everything git deliberately doesn't carry
across: the gitignored scaffolding (`.envrc`, `.flox/`, `.venv/`,
`client/node_modules/`, `client/.tls/`) and a port assignment that doesn't
collide with its siblings. One command fixes all of it:

```sh
cd /path/to/the/new/worktree
just worktree-adopt
```

"Adopt", not "create", because the checkout usually already exists — an agent
harness (Paseo, Cursor) or a plain `git worktree add` made it, and this claims
it afterwards. It is idempotent, so it's also the repair command. It:

1. assigns the lowest free port offset and writes it to a gitignored `./.env`
   (the primary prefers offset 0, but moves off it if those ports are taken);
2. writes an `.envrc` that resolves the **primary** checkout's flox
   environment (only if the primary itself uses direnv/flox — the repo doesn't
   prescribe either), and runs `direnv allow`;
3. copies gitignored-but-shareable files over, currently `client/.tls`
   (host-wide certs that otherwise cost a `sudo` prompt per worktree);
4. runs `just setup` — pass `--no-install` to skip that and do it yourself.

Then:

```sh
just worktree-doctor   # why isn't this worktree working? every failure prints its fix
just worktree-list     # all worktrees, their ports, and whether they're ready
just worktree-create B # git worktree add ../deckd-B on a new branch, then adopt it
```

#### Ports

The one genuinely shared resource is the host's port space. Every checkout
gets an offset applied to all four bases at once, so its ports stay mentally
grouped:

| offset | `DECKD_PORT` | `VITE_PORT` | `DECKD_E2E_PORT` | `DECKD_SMOKE_PORT` | who |
| --- | --- | --- | --- | --- | --- |
| 0 | 8765 | 5173 | 8975 | 18765 | the primary checkout, *if the defaults are free* |
| 1 | 8766 | 5174 | 8976 | 18766 | first adopted checkout |
| 2 | 8767 | 5175 | 8977 | 18767 | second, and so on |

The primary prefers offset 0 and normally needs no `.env` at all, so on a
machine with no installed deckd nothing about the main checkout changes. It
does **not** own offset 0 though: if something already holds `:8765` — almost
always an installed deckd service — `worktree-adopt` moves the primary to a
free offset like any other checkout, and says so. Delete its `.env` and
re-adopt to move back once the port frees up.

An offset is only free when *all four* of its ports are, so a stray process on
one port pushes the whole group along rather than producing a half-working
checkout.

`.env` is loaded automatically by every recipe (`set dotenv-load` in the
Justfile), so `just dev`, `just kill`, `just smoke`, and `just test-all` all
target the current checkout with no env-var juggling. An explicit variable
still wins for a one-off: `DECKD_PORT=9000 just dev`.

- `DECKD_PORT` becomes `deckd-dev`'s `--port` (`dev-daemon`, `dev-daemon-lan`,
  `dev`, `dev-lan`) — and `deckctl`'s `--port` in `just status`, `diag`,
  `layouts`, and `metrics`, so those report on *this* checkout's daemon rather
  than whatever holds the default port.
- `VITE_PORT` becomes Vite's `--port`; when it differs from 5173 the recipe
  drops `--strictPort` so Vite falls through if the port is busy, and sets
  `DECKD_UPSTREAM` so the `/ws` + `/health` proxy reaches *this* checkout's
  daemon.
- `DECKD_E2E_PORT` moves the Playwright fixture daemon and its throwaway
  layouts dir; `DECKD_SMOKE_PORT` moves the in-process smoke server. Together
  they let two checkouts run `just test-all` simultaneously.
- `just kill` only tears down the current checkout's ports.

#### Running dev alongside an installed deckd

A machine can run an installed deckd service (systemd/launchd/home-manager)
and any number of dev instances at once. What's isolated, and what isn't:

**Isolated, no action needed.** Layouts — the service reads
`~/.config/deckd/layouts`, dev checkouts read their own `./layouts`, so an
editor save in a dev instance can't touch the service's. Client state — each
port is a distinct browser origin, so every instance gets its own PWA storage
and service worker. The password file (`~/.config/deckd/password`) *is*
shared, which is a convenience rather than a conflict: one password opens
every instance.

**Handled by the offsets.** Ports, including the primary checkout, per above.

**Not isolated, and can't be.** These act on shared session state, so every
running daemon competes:

- **Input injection.** Each daemon opens its own uinput device (all named
  `deckd`) and injects into whatever window currently has focus. Press a
  button on the service's client and on a dev client and the target app
  receives both.
- **MPRIS transport and `dbus:` actions.** Same story — they drive the
  session's real players and services.
- **KDE focus (`org.deckd.Focus`).** On KDE the *daemon* owns the bus name,
  and it requests it with `NameFlag.REPLACE_EXISTING` — so the last daemon to
  start silently takes focus pushes away from every other one, including the
  installed service. GNOME is unaffected: there the Shell extension owns the
  name and daemons only call it, so any number coexist.

In practice: run as many daemons as you like, but only drive *one* client at a
time, and on KDE expect focus-dependent behaviour to follow the most recently
started daemon.

#### Toolchain: shared env, per-worktree venv

A worktree has no `.flox/` of its own, and direnv's stdlib `use flox` requires
a local one — so the generated `.envrc` calls `flox activate -d <primary>`
directly. flox leaves `$PWD` alone, so the toolchain resolves from the primary
while this worktree's own `.venv` is the one that gets used. That split is
deliberate and load-bearing:

- **Toolchain is shared** (python, node) — nothing to rebuild per worktree.
- **The venv is not.** `uv pip install -e .` bakes an absolute path into the
  editable install, so a shared venv would silently point `deckd` at whichever
  worktree installed last.

The manifest's `[profile]` hook is what exports `$PWD/.venv/bin`, but flox
only sources it for an **interactive** shell — direnv's non-interactive env
dump never carries it. So the generated `.envrc` adds `.venv/bin` to `PATH`
(and exports `VIRTUAL_ENV`) itself. Without that, `just dev-daemon` and the
`deckctl` recipes fail with `deckd-dev: command not found` in an activated
worktree, even though `.venv/bin/deckd-dev` exists. If you hand-edit `.envrc`,
keep that block.

Caveats that remain:

- **`just install-service` should only be run from your main checkout.** It
  writes the literal `$(pwd)` into the systemd unit / launchd plist; from a
  feature worktree it pins the service to a checkout that will be removed.
- **Live MPRIS / focus smoke tests** (`just smoke-mpris`, `just smoke-focus`)
  hit the real session bus, so two worktrees can't run them at once.
- **`uv.lock` is per-repo, not per-worktree.** A `uv pip install` in one
  worktree edits the lockfile every worktree shares; if you're intentionally
  diverging dependencies, commit the change deliberately.

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

Nix packaging has its own ladder entry: `just nix-check` (or `nix flake check -L`) builds `packages.deckd` and the watcher bundles, evaluates the NixOS and home-manager modules against dummy configs (`nix/tests/modules.nix`), unit-tests the activation scripts in a sandbox (`nix/tests/scripts.nix`), and boots the packaged daemon on loopback to check `/health`, the bundled client, and the bundled layouts (`nix/tests/smoke.nix`).

**Python version policy.** The declared floor is 3.11 (`requires-python`): the main ladder runs on 3.11 and local dev venvs use it. The Nix package ships 3.12 because nixos-unstable's 3.11 package set can no longer build the dependency closure, so CI carries a separate 3.12 job (pytest + smoke) to cover the interpreter Nix users actually run. Don't add a third version without a reason recorded here.

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
