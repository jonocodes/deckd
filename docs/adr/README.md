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

A client can pin its session to a specific layout via `select_view`. Daemon pushes a `view`-tagged `LayoutMessage`. Created for MPRIS media browser; general mechanism for future chrome views.

_Amends: [0003](0003-persistent-chrome.md) — chrome knowledge now includes payload-per-view content delivered by the daemon_

## 0009 — Bind scope control: localhost by default, opt-in LAN

[0009-bind-scope-control.md](0009-bind-scope-control.md)

Replace `--host` with repeatable `--bind` supporting literal IPs and `iface:<name>`. Default `127.0.0.1` + `::1`. Localhost-only by default; LAN reachability is opt-in.
