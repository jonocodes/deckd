# ADR index

Architecture Decision Records for deckd, in numbered chronological order.

## 0001 — Key strings map to physical evdev keycodes, not characters

[0001-keymap-physical-keys.md](0001-keymap-physical-keys.md)

Config key strings (e.g. `ctrl+t`) are parsed as physical evdev key names with no keymap translation. On non-QWERTY layouts users may need to specify physical keys rather than the character they see.

## 0002 — Scroll momentum is computed daemon-side

[0002-momentum-daemon-side.md](0002-momentum-daemon-side.md)

The client sends `jog_end` with release velocity; the daemon owns the decay loop. All clients inherit correct momentum behavior without reimplementing it.

## 0003 — Persistent chrome: bottom strip + right-side jogstrip

[0003-persistent-chrome.md](0003-persistent-chrome.md)

Client has fixed chrome always visible: right-side full-height jogstrip (suppressible per-layout) and bottom strip with app badge + controls. Per-app layouts render in the remaining space.

_Amended by: [0006](0006-widget-visual-styling.md), [0007](0007-chrome-app-identity-badge.md), [0008](0008-chrome-view-carveout.md)_

## 0004 — Orientation: scaling grid, not locked to portrait

[0004-orientation-scaling.md](0004-orientation-scaling.md)

Layouts authored in landscape. Portrait transposes every widget's grid diagonally `[x,y,w,h] -> [y,x,h,w]`. Same buttons, same arrangement, cells sized for the surface.

_Superseded by: [0010](0010-grid-reflow.md) — there is no fixed grid shape to author against_

## 0005 — Future: dynamic widget state for MPRIS and runtime content

[0005-dynamic-widget-state-future.md](0005-dynamic-widget-state-future.md)

Protocol is stateless per widget now. Planned: delta updates to widget properties (label, icon, value) without replacing whole layout. Primary driver: MPRIS live state.

## 0006 — Widget visual styling: opaque presentation relay + bundled icon sets

[0006-widget-visual-styling.md](0006-widget-visual-styling.md)

Widgets carry `color` and `icon` attributes. Daemon treats them as opaque strings; client bundles Lucide (glyphs) + Simple Icons (brand logos).

_Amends: [0003](0003-persistent-chrome.md) — presentation is a second class of info the daemon carries without interpreting_

## 0007 — Chrome app-identity badge: opaquely-relayed display name, theme, icon

[0007-chrome-app-identity-badge.md](0007-chrome-app-identity-badge.md)

Bottom chrome's app badge carries `display_name`, `theme` (CSS colour), and `icon` from the layout YAML. Daemon relays verbatim; no `.desktop` file or web resolution.

_Extends: [0006](0006-widget-visual-styling.md) — presentation-relay seam reaches per-layout now, not just per-widget_

## 0008 — Chrome view carve-out: client-requested daemon-rendered chrome surfaces

[0008-chrome-view-carveout.md](0008-chrome-view-carveout.md)

A client can pin its session to a specific layout via `select_view`. Daemon pushes a `view`-tagged `LayoutMessage`. Created for MPRIS now-playing; general mechanism for future chrome views.

_Amends: [0003](0003-persistent-chrome.md) — chrome knowledge now includes payload-per-view content delivered by the daemon_

## 0009 — Bind scope control: localhost by default, opt-in LAN

[0009-bind-scope-control.md](0009-bind-scope-control.md)

Replace `--host` with repeatable `--bind` supporting literal IPs and `iface:<name>`. Default `127.0.0.1` + `::1`. Localhost-only by default; LAN reachability is opt-in.

## 0010 — Grid layout: ordered-list reflow with a banded cell size

[0010-grid-reflow.md](0010-grid-reflow.md)

Widgets become an ordered list that reflows to the viewport; `grid: [x,y,w,h]` coordinates and the portrait transpose are deleted. Cell size is a client-side device preference, never authored in layout YAML.

_Supersedes: [0004](0004-orientation-scaling.md) — authored coordinates + diagonal transpose_
_Superseded by: [0011](0011-reflow.md) — the sizing geometry, the band, and the overflow default_

## 0011 — Reflow: the row count is the only free variable

[0011-reflow.md](0011-reflow.md)

Sizing picks the row count that makes cells largest, using both axes, so no tuned constants remain. Rows fill to the column count with the remainder in the bottom row; the grid block centres on both axes with rows washed left. `minCell` / `maxCell` gain distinct jobs, and overflow becomes a device setting defaulting to `clip`.

_Supersedes: [0010](0010-grid-reflow.md) — keeps the ordered-list model, replaces the geometry_

## 0012 — Linux distribution: AppImage primary, Flatpak/Snap rejected

[0012-linux-distribution-appimage.md](0012-linux-distribution-appimage.md)

AppImage is the primary Linux artifact (unsandboxed, distro-agnostic); the root-only uinput step is a first-run `pkexec`/`sudo` helper shared by all channels. Flatpak/Snap are rejected — a sandbox cannot write the udev rule, see `/dev/uinput`, reach the session bus unfiltered, or install the compositor plugin. deb/rpm remain a later thin wrap of the same relocatable tree.
