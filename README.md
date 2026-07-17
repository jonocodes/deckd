# deckd

App-aware touch control surface for the Linux desktop. A Stream Deck-like deck of buttons, sliders, scroll strips, and a trackpad mode, rendered in any browser on any touchscreen device, driven by a local daemon that watches the focused application and swaps layouts automatically.

See [`docs/INCEPTION.md`](docs/INCEPTION.md) for the full design.

## Status

Pre-alpha, but the v1 milestone spine is landing. Both design-doc spikes are resolved and the T-series milestones through T8 are shipped:

- **uinput scroll end-to-end** (spike #1) — *done*
- **Focus watcher** (spike #2) — *done*
- **T1** pytest suite + domain docs — *done*
- **T2** keystroke injection — *done*
- **T3** D-Bus action primitive — *done*
- **T4** per-app layout switching from focus — *done*
- **T5** dev UX (auto-ignore + `deckctl layout` override) — *done*
- **T6** client chrome (bottom strip + persistent jogstrip) — *done*
- **T8** trackpad mode (cursor + tap + drag-lock) — *done*

What works today: focus a window on the desktop and the phone's browser flips to that app's layout automatically. Tap layout buttons to fire `shell`, `terminal`, `key`, or `dbus` actions. Drag the always-on right-side jogstrip to scroll the focused window through `REL_WHEEL_HI_RES`. Tap the chrome trackpad button and the phone becomes a mouse — drag to move the cursor, tap to click, two-finger tap to right-click, tap-and-a-half to drag. Edit any `layouts/*.yaml` file on the desktop and every connected client re-renders; a broken save shows an error diagnostic in place of the grid without killing the daemon.

```
                        ┌──────────┐
                        │  Phone /  │
                        │  Tablet   │
                        │  Browser  │
                        └────┬─────┘
                             │
                      WebSocket (ws://)
                             │
          ┌──────────────────┼──────────────────┐
          │             deckd daemon             │
          │            (aiohttp, asyncio)        │
          │                                      │
          │  ┌──────────┐  ┌──────────┐          │
          │  │  Layout   │  │  Action  │          │
          │  │  Loader   │  │ Dispatch │          │
          │  └──────────┘  └────┬─────┘          │
          │         │           │                │
          └─────────┼───────────┼────────────────┘
                    │           │
        layouts/*.yaml    ┌─────┴─────┬──────────┐
                          │           │          │
                      uinput       shell     D-Bus
                     (evdev)     (subprocess)  gdbus
                          │                    │
              scroll + keys + pointer  ┌───────┴───────┐
                          │           │                │
                     /dev/uinput   GNOME Shell     (X11 fallback
                                   Extension        xdotool —
                                  deckd-focus      unsupported)
                                   @local
```

## Layout

```
daemon/deckd/      Python daemon: aiohttp server, WebSocket, layout loader, action dispatch
client/            Vite + React + TS web client (the dumb renderer)
layouts/           Per-app YAML layouts (default.yaml + one per app)
scripts/smoke.py   End-to-end test that boots the daemon over WS, clicks every button
docs/INCEPTION.md  Full design doc — source of truth for *what* and *why*
```

## Running deckd

You need Python 3.11+ and Node 18+. Dependencies are managed with [`uv`](https://docs.astral.sh/uv/):

```sh
# 1. Install uv (one-time)
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"

# 2. Create the venv and install deps
uv venv --python 3.12
uv pip install -e ".[dev,uinput]"

# 3. Install JS client deps (once)
cd client && npm install && cd ..

# 4. Build the client so the daemon can serve it
just build-client

# 5. Run the daemon (serves the built client at http://127.0.0.1:8765)
just run-daemon
```

Open `http://127.0.0.1:8765` in any browser. You should see the active layout's buttons filling the main area, an always-on jogstrip pinned to the right edge, and a chrome bottom strip with the app name, a connection status dot, and a `trackpad` button. Drag or flick vertically on the right-side jogstrip to emit `REL_WHEEL_HI_RES` deltas through uinput (log-only when uinput is unavailable). Tap the `trackpad` button to swap the button grid for a full-area trackpad surface — see the [Trackpad mode](#trackpad-mode) section for the gesture list.

### Phone/tablet testing

The phone must load the web client from a daemon address it can reach. Build the client, run the daemon on all interfaces, then open the desktop's LAN IP from the phone:

```sh
just build-client
just run-daemon-lan

# In another terminal, find the desktop IP:
hostname -I
```

Open `http://<desktop-lan-ip>:8765` on the phone, for example `http://192.168.30.117:8765`. The client connects its WebSocket back to the same host automatically, so no separate `VITE_DECKD_WS` setting is needed for this built-client path.

### Client chrome

Every layout renders inside a persistent **chrome** shell that the daemon does not know about:

- **Bottom strip** (always visible): the current app name (from `LayoutMessage.app`), a connection dot (live / reconnecting / disconnected), a `trackpad` button that swaps the main area for the trackpad view, and a `settings` placeholder (T13).
- **Right-side jogstrip** (always visible): a full-height scroll strip that works the same as the in-grid `jogstrip` widget. A layout can suppress it with `jogstrip: false` at the YAML top level — the daemon forwards this as `jogstrip_enabled` on every `LayoutMessage`.

Layout widget coordinates are relative to the chrome-excluded area; the client computes cell sizes from whatever space remains after the strips are subtracted.

### Trackpad mode

Tap the `trackpad` button in the bottom chrome and the layout area is replaced by a full-surface trackpad. All gesture recognition is client-side; the daemon receives high-level events over WebSocket and maps them to `REL_X` / `REL_Y` + `BTN_LEFT` / `BTN_RIGHT` events on the same uinput device that handles keys and scroll.

| Gesture | Action |
|---|---|
| One-finger drag | Move the desktop cursor (relative motion, like a laptop trackpad) |
| Quick tap (< 250ms, < 10px) | Left click |
| Two-finger tap (both down, both up together) | Right click |
| Tap-and-a-half (tap, then touch again within 400ms and drag) | Left button held during the drag; release on finger lift |

Chrome stays visible in trackpad mode — the right-side jogstrip is still available for scrolling while you're pointing. Tap the `trackpad` button again to return to the app layout.

### Scroll tuning

The jogstrip's drag scale can be tuned from the phone URL without rebuilding:

```text
http://lute:5173?scrollScale=2
http://lute:5173?scrollScale=4&scrollInvert=1
```

`scrollScale` is high-resolution wheel units per CSS pixel. `scrollInvert=1` flips the direction.

Daemon-side flick momentum can be tuned with CLI flags:

```sh
.venv/bin/deckd --layouts-dir layouts \
  --scroll-momentum-friction 0.90 \
  --scroll-momentum-cutoff 20 \
  --verbose
```

Lower friction decays faster; `--scroll-momentum-friction 0` effectively disables momentum after one frame. The helper script can test release momentum without the touch UI:

```sh
sleep 2 && .venv/bin/python -u scripts/send_scroll.py --velocity 1200
```

### uinput permissions

For real scroll injection, deckd needs write access to `/dev/uinput`. Current-session ACLs may work temporarily, but the reproducible setup is to install the udev rule and add the daemon user to `input`:

```sh
sudo install -m 0644 packaging/udev/70-deckd-uinput.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=misc --sysname-match=uinput
sudo usermod -aG input "$USER"
```

Log out and back in, then check:

```sh
ls -l /dev/uinput
id
just check-uinput
```

On NixOS, import `packaging/nixos/deckd-spike.nix` and enable the spike service:

```nix
{
  imports = [ /home/jono/src/deckd/packaging/nixos/deckd-spike.nix ];

  services.deckd-spike = {
    enable = true;
    user = "jono";
    projectDir = "/home/jono/src/deckd";
    lan = true;
  };
}
```

Run `just setup` and `just build-client` in the checkout before starting the user service.

### Live reload

Layout YAML is watched by the daemon itself — any edit under `layouts/` is picked up automatically and pushed to every connected client. No manual `deckctl reload` needed. A broken save (bad YAML, schema violation) is trapped: the daemon keeps the last-good layouts live and sends a `LayoutMessage` with `error: "<parse error>"` so the client shows a diagnostic in place of the grid until the next successful save.

Python changes need a daemon restart. `just dev-daemon` runs a supervisor that watches `daemon/**/*.py` and restarts the child on save:

```sh
# Terminal 1
just dev-daemon           # daemon under a Python-file-restart supervisor

# Terminal 2 (LAN so a phone can hit it)
just dev-client-lan
```

Open `http://lute:5173` on the phone when hostname resolution is available, or use the Network URL printed by Vite. `lute` is listed in Vite's `server.allowedHosts`. `dev-client-lan` sets `VITE_DECKD_WS=ws://lute:8765/ws` automatically, so the Vite page still talks to the daemon.

### Focus watcher

GNOME Shell's built-in `org.gnome.Shell.Introspect` API returns `AccessDenied` for window queries. Instead, a tiny GNOME Shell extension (`deckd-focus@local`) publishes the focused window as JSON over session D-Bus (`org.deckd.Focus`). The daemon polls this at 100ms via `GnomeShellFocusBackend`.

Install and enable (relogin required on Wayland if the extension is not yet listed):

```sh
just install-focus-extension
# If it says "Installed but not enabled", log out/in then:
gnome-extensions enable deckd-focus@local
```

Verify:

```sh
just watch-focus           # polls and prints focus changes
just watch-focus-once      # single snapshot
```

Expected output:

```text
app_id='org.gnome.Console' wm_class='org.gnome.Console' pid=1234 title='Terminal'
app_id=None wm_class='firefox' pid=188566 title='YouTube — Mozilla Firefox'
```

X11 (`xdotool`) fallback exists in `daemon/deckd/platform.py` but is not a supported target.

### Dev UX: auto-ignore + layout override

Two conveniences for local development without a separate device:

**Auto-ignore.** When the focus watcher reports the deckd client browser window gaining focus (matched by the daemon's own port appearing in the window title, or the deckd page title `"deckd"` in the title), the daemon **holds the current layout** instead of switching away. So clicking the browser tab that's rendering the control surface doesn't flip the layout to the browser's own (e.g. Firefox) layout while you're testing something else.

**Layout override.** `deckctl layout <name>` force-switches every connected client to a named layout regardless of focus, so you can test a specific app's layout without opening that app:

```sh
deckctl layout firefox    # force the firefox layout on all clients
deckctl layout default    # back to the default layout
deckctl layout nonexistent  # error: unknown layout (exit 1)
```

This hits `POST /layout/<name>` on the daemon. The override is **not sticky**: the next genuine (non-deckd-window) focus change clears it and normal focus-driven switching resumes.

### Smoke test

`scripts/smoke.py` boots the daemon in-process, connects a WS client, fires every action primitive, and asserts the right things happen. Useful as a quick "did I just break the wire?" check:

```sh
uv pip install -e ".[dev]"   # installs the websockets test dep
.venv/bin/python -u scripts/smoke.py
```

### CLI

```sh
deckctl status              # hit /health
deckctl reload              # POST /reload — re-read layout YAML and push
deckctl layout firefox      # force all clients to the firefox layout (dev)
deckctl layout default      # force the default layout
```

## Configuration

A directory of YAML files in `layouts/` — one per app, plus a `default.yaml` fallback. Shipped layouts today: `default`, `firefox`, terminals (`org.gnome.Console`, `foot`, `kitty`, `gnome-terminal`, `konsole`, `alacritty`), `com.gexperts.Tilix`. Each widget has an `id`, `kind` (`button` or `jogstrip` — the trackpad is a chrome mode, not a widget kind), a `grid: [x, y, w, h]` placement, an optional `label` / `icon`, an optional `color:` (any CSS colour string — hex, `hsl(...)`, named — applied as the button background), and an optional `action`. A layout's top-level `match:` list says which apps it covers (matched by `app_id` or `wm_class`); the layout with `match: [default]` is the fallback. A layout may set `jogstrip: false` at the top level to suppress the client's persistent right-side chrome jogstrip (defaults to `true`); the daemon echoes this to the client as `jogstrip_enabled` on every `LayoutMessage`. Action primitives:

- `shell: "..."` — run a subprocess (fire-and-forget; stdout/stderr discarded).
- `terminal: true` or `terminal: "foot"` — launch a terminal emulator. `true` resolves via `$TERMINAL` then a candidate list (`foot`, `kitty`, `gnome-terminal`, `konsole`, `alacritty`); a string names a specific one.
- `key: "ctrl+t"` — fire the keystroke through uinput as a single combo.
- `dbus: "service:path org.Interface.Method arg1 arg2"` — call a D-Bus method via `dbus-fast`. The bus is inferred from the interface name (`org.freedesktop.login1.*`, `systemd1.*`, `timedate1.*`, `locale1.*`, etc. → system bus; everything else → session bus). Errors are logged, not surfaced to the client. With the `service:path` prefix omitted, the daemon derives them from the first two / three segments of the interface name.

## What works today

- **Wire protocol** in both directions: `LayoutMessage` (with `jogstrip_enabled` + optional `error`) and `press` / `jog` / `jog_end` / `pad` / `pad_tap` / `pad_drag` events.
- **YAML config → Pydantic → `Widget` graph → action dispatch** for `shell`, `terminal`, `key`, `dbus` primitives.
- **Jogstrip** scroll plumbing from browser pointer movement to daemon-side uinput, including release momentum.
- **Trackpad mode**: `REL_X` / `REL_Y` motion plus `BTN_LEFT` / `BTN_RIGHT` / `BTN_MIDDLE` on the same uinput device, with client-side gesture recognition (tap / two-finger tap / tap-and-a-half drag lock).
- **Active-window detection** via GNOME Shell extension + session D-Bus (`app_id`, `wm_class`, `title`, `pid`).
- **Persistent client chrome** — bottom strip (app name + connection dot + trackpad button) and right-side jogstrip — layered above every layout with zero daemon involvement.
- **Layout hot-reload** — the daemon watches `layouts/*.yaml` and re-pushes on any edit; bad YAML surfaces as a diagnostic on the client without crashing the daemon.
- **Reconnecting client** (`useDeckdSocket` exponential backoff).
- **Build output** is plain static files — `client/dist/` — served by the daemon.

## Why a venv, not a Nix shell?

The daemon is normal Python — `pip install -e .` is the contract. We keep the Nix-based packaging (udev rules, `input` group, `systemd.user.service`) in the lifecycle milestone [#5](https://github.com/jonocodes/deckd/issues/5) for when a clean-machine install story matters; the per-day edit/run loop should not need a sandbox.
