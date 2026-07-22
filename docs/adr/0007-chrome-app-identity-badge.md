# Chrome app-identity badge: opaquely-relayed display name, theme, icon

The bottom chrome strip's "current app" was a single plain-text string — the
raw YAML match token (`firefox`, `org.gnome.Console`, …). Issue #41 asked for
the focused app to be visually apparent at a glance: an icon, a brand colour,
a human-readable name. This ADR records how the chrome badge carries that
identity, and where each piece lives.

It extends the ADR-0006 presentation-relay seam from per-widget presentation
to **per-layout** presentation. The sacred seam is unchanged: the daemon
hard-codes no app-specific behaviour and interprets no presentation value —
it relays. The client owns the rendering and the icon-source registry.

## Decisions

### Three optional layout fields, all relayed opaquely

A layout YAML may declare any of:

```yaml
display_name: Mozilla Firefox
theme: "#ff7139"
icon:
  source: simple-icons
  name: firefox
```

- `display_name` — a human-readable string shown in place of the raw match
  token. Absent, the chrome falls back to the existing `app` field (the
  match token) so current layouts keep working unchanged.
- `theme` — any CSS colour string the browser accepts (hex, `hsl(...)`,
  named), reused exactly as the per-widget `color` is. The client tints the
  badge and the bottom chrome's accent line. Same trust stance as `color`
  (ADR-0006): layouts are user-owned config, so no sanitisation.
- `icon` — the same `{source, name}` dispatch widgets already use. This
  reuses the bundled Lucide + Simple Icons sets, the lazy-load chunking, and
  the "unknown source renders a placeholder" rule verbatim. No new client
  bundle, no daemon-side `.desktop` augmentation.

All three are optional and default to `null`. The daemon never interprets
them; it validates shape only (`icon.source`/`icon.name` are non-empty
strings, inherited from the widget `Icon` schema) and serialises them to
`LayoutMessage` as `display_name` / `theme` / `icon`. The message keys are
present and `null` when the layout omits them, so the client has a stable
shape to destructure.

### The daemon does not resolve app icons from `.desktop` files

Issue #41's "Further Notes" floated daemon-side `.desktop` parsing to extract
the focused app's icon. **Out of scope.** It would make the daemon an asset
resolver, would require either serving the icon bytes or shipping a path the
browser could fetch (a second daemon-served asset surface), and would
re-derive presentation that's already expressible in YAML. A layout author
who wants the Firefox logo writes `icon: { source: simple-icons, name:
firefox }`. The "out of scope for a daemon" half of ADR-0006 stands.

### The badge is a client-only render; chrome remains client-only

Per ADR-0003 the daemon has no chrome knowledge. The badge is part of the
chrome — bottom strip only — and the daemon is unaware it exists. The
client renders the badge from the relaid fields; with none set, the badge
renders as bold text of the `app` match token, cheek-by-jowl with the
pre-existing `app-name` treatment. **No layout is required to set
chrome fields**, and a layout with only per-widget `icon`/`color` looks
unchanged in the chrome.

### The theme tints, it does not theme

`theme` is a single accent colour, applied to:
- the badge icon's backing disc (so a monochrome brand logo reads against any
  chrome),
- the badge border (darkened via `color-mix` so it survives on bright brand
  colours),
- a thin accent stripe at the top edge of the bottom chrome (so the focused
  app reads at a glance from across the room, even when the badge itself is
  off-screen in landscape pan).

No light/dark, no per-layout full CSS override, no second colour field for
hover/active. Pressed states stay derived from `filter: brightness()`. Same
"one fixed look" rule ADR-0006 chose for widgets.

### Out of scope

- Animated app-switching transitions.
- Full per-app CSS overrides beyond a primary colour.
- Fetching brand icons from the web (use the bundled Simple Icons set).
- Daemon-side `.desktop` icon resolution (see above).
- A secondary / "now-playing" app indicator (issue #41's exploration area 5
  is deferred; the badge surfaces only the primary focused app today).

## Consequences

- `LayoutMessage` gains `display_name`, `theme`, `icon` (all optional,
  default `null`); the client `ServerLayout` type mirrors them. Both the TS
  and Python protocols were extended; existing layouts and clients that
  ignore unknown fields keep working.
- The client `Icon` renderer is reused for the badge — no new icon pipeline.
- Badging a new app is a YAML edit (add `display_name`/`theme`/`icon` to its
  layout); no daemon rebuild, no client rebuild (Lucide and Simple Icons are
  bundled whole — see ADR-0006's loading asymmetry).
- Illegible `theme` choices are possible and accepted; they are the layout
  author's to fix, same as per-widget `color`.