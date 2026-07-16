# deckd

App-aware touch control surface for the Linux desktop. A Stream Deck-like deck of buttons, sliders, scroll strips, and a trackpad mode, rendered in any browser on any touchscreen device, driven by a local daemon that watches the focused application and swaps layouts automatically.

See [`docs/INCEPTION.md`](docs/INCEPTION.md) for the full design.

## Status

Pre-alpha. Spikes from §12 of the design doc are resolved:

- **uinput scroll end-to-end** (spike #1) — *done*
- **Focus watcher** (spike #2) — *done*

What works today: a minimal daemon + web client that proves the wire protocol and config-driven action dispatch (`shell`, `terminal`, `key` stub, `page`) plus a hardcoded jogstrip that sends high-resolution scroll deltas via uinput. Active-window detection uses a GNOME Shell extension over session D-Bus; the daemon polls it at 100ms to track focus changes.

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
                     scroll deltas     ┌───────┴───────┐
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

## Running the spike

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

Open `http://127.0.0.1:8765` in any browser. You should see the spike buttons plus a `Scroll` jogstrip. Drag or flick vertically on the jogstrip to emit `REL_WHEEL_HI_RES` deltas through uinput, or log-only deltas when uinput is unavailable.

### Phone/tablet testing

The phone must load the web client from a daemon address it can reach. Build the client, run the daemon on all interfaces, then open the desktop's LAN IP from the phone:

```sh
just build-client
just run-daemon-lan

# In another terminal, find the desktop IP:
hostname -I
```

Open `http://<desktop-lan-ip>:8765` on the phone, for example `http://192.168.30.117:8765`. The client connects its WebSocket back to the same host automatically, so no separate `VITE_DECKD_WS` setting is needed for this built-client path.

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

### Dev mode (Vite HMR)

Two terminals:

```sh
# Terminal 1: daemon (no --client-dist; vite handles the UI)
just run-daemon-dev

# Terminal 2: vite dev server, proxies /ws to the daemon
just dev-client
# open http://127.0.0.1:5173
```

For phone/tablet testing with Vite HMR, both the daemon and Vite need LAN bindings:

```sh
# Terminal 1
just run-daemon-dev-lan

# Terminal 2
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

A directory of YAML files in `layouts/` — one per app, plus a `default.yaml` fallback. Each widget has an `id`, `kind` (`button`, `jogstrip`; `trackpad` is declared in the schema but unsupported in the spike), a `grid: [x, y, w, h]` placement, and an optional `action`. A layout's top-level `match:` list says which apps it covers (matched by `app_id` or `wm_class`); the layout with `match: [default]` is the fallback. Action primitives:

- `shell: "..."` — run a subprocess (fire-and-forget; stdout/stderr discarded).
- `key: "ctrl+t"` — fire the keystroke through uinput as a single combo.
- `dbus: "service:path org.Interface.Method arg1 arg2"` — call a D-Bus method via `dbus-fast`. The bus is inferred from the interface name (`org.freedesktop.login1.*`, `systemd1.*`, `timedate1.*`, `locale1.*`, etc. → system bus; everything else → session bus). Errors are logged, not surfaced to the client. With the `service:path` prefix omitted, the daemon derives them from the first two / three segments of the interface name.
- `page: "<name>"` — switch the client to another page in the same layout.

## What the spikes prove

- WebSocket wire protocol in both directions (layout push, `press`, `jog`, and `jog_end` events).
- YAML config → Pydantic → `Widget` graph → action dispatch.
- Jogstrip scroll plumbing from browser pointer movement to daemon-side uinput, including release momentum.
- Active-window detection via GNOME Shell extension + session D-Bus (`app_id`, `wm_class`, `title`, `pid`).
- Reconnecting client (`useDeckdSocket` exponential backoff).
- Build output is plain static files — `client/dist/` — served by the daemon.

## Why a venv, not a Nix shell?

The daemon is normal Python — `pip install -e .` is the contract. We keep the Nix-based packaging (udev rules, `input` group, `systemd.user.service`) in the lifecycle milestone [#5](https://github.com/jonocodes/deckd/issues/5) for when a clean-machine install story matters; the per-day edit/run loop should not need a sandbox.
