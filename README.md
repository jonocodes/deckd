# deckd

App-aware touch control surface for the Linux desktop. A Stream Deck-like deck of buttons, sliders, scroll strips, and a trackpad mode, rendered in any browser on any touchscreen device, driven by a local daemon that watches the focused application and swaps layouts automatically.

See [`docs/INCEPTION.md`](docs/INCEPTION.md) for the full design.

## Status

Pre-alpha spike. The de-risking work from §12 of the design doc is in progress:

- **uinput scroll end-to-end** (spike #1) — *in progress*
- **Focus watcher** (spike #2) — *not started*

What works today: a minimal daemon + web client that proves the wire protocol and config-driven action dispatch (`shell`, `terminal`, `key` stub, `page`) plus a hardcoded jogstrip that sends high-resolution scroll deltas. Synthetic scroll uses uinput when `python-evdev` is installed and `/dev/uinput` is accessible; otherwise it falls back to logging emitted deltas.

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
.venv/bin/deckd --layouts layouts/default.yaml \
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

### Focus watcher spike

GNOME Shell's built-in `org.gnome.Shell.Introspect` API is present on this machine but returns `AccessDenied` for window/app queries. Spike #2 therefore uses a tiny GNOME Shell extension that publishes the focused window over session D-Bus.

Install and enable the local extension:

```sh
just install-focus-extension
```

On Wayland, GNOME Shell may not list a newly installed extension until the next login. If the recipe says the extension was installed but not enabled, log out and back in, then run:

```sh
gnome-extensions enable deckd-focus@local
```

Then print focus changes:

```sh
just watch-focus
```

Expected output shape:

```text
app_id='org.gnome.Console' wm_class='org.gnome.Console' pid=1234 title='Terminal'
```

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

A single YAML file for the spike (`layouts/default.yaml`). Each widget has an `id`, `kind` (`button`, `jogstrip`; `trackpad` is declared in the schema but unsupported in the spike), a `grid: [x, y, w, h]` placement, and an optional `action`. Action primitives:

- `shell: "..."` — run a subprocess (fire-and-forget; stdout/stderr discarded).
- `key: "ctrl+t"` — *(stubbed: logged only; key injection is not wired yet.)*
- `dbus: "..."` — *(stubbed: logged only.)*
- `page: "<name>"` — switch the client to another page in the same layout.

## What the spike proves

- WebSocket wire protocol in both directions (layout push, `press`, `jog`, and `jog_end` events).
- YAML config → Pydantic → `Widget` graph → action dispatch.
- Jogstrip scroll plumbing from browser pointer movement to daemon-side uinput/log sink, including daemon-side release momentum.
- Reconnecting client (`useDeckdSocket` exponential backoff).
- Build output is plain static files — `client/dist/` — served by the daemon.

## Why a venv, not a Nix shell?

The daemon is normal Python — `pip install -e .` is the contract. We keep the Nix-based packaging (udev rules, `input` group, `systemd.user.service`) in the lifecycle milestone [#5](https://github.com/jonocodes/deckd/issues/5) for when a clean-machine install story matters; the per-day edit/run loop should not need a sandbox.
