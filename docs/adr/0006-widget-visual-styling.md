# Widget visual styling: opaque presentation relay + bundled icon sets

Widgets carry visual attributes — a background `color` and an `icon` — that
control how a button looks. This ADR records where those attributes live,
how the daemon treats them, and what the client bundles to render them.

It amends ADR-0003 ("the daemon has no chrome knowledge except one protocol
field"). Presentation is now a second class of information the daemon carries.
The seam that stays sacred is *semantic*: the daemon hard-codes no
app-specific behaviour and interprets no presentation value — it relays.

## Decisions

### Presentation is opaque config the daemon relays, never interprets

Visual attributes are part of the user-owned layout config. The daemon
validates their *shape* and passes them through unchanged; it never assigns
meaning to a colour or resolves an icon. This keeps ADR-0003's real
guarantee (no app-specific behaviour baked into the daemon) intact while
acknowledging that presentation legitimately flows through the protocol.

Because deckd's daemon is a single-user local process over user-authored
config — not a multi-tenant server — there is no trust boundary that would
otherwise argue for keeping presentation client-only.

### `color` is a raw CSS colour, background only

`color: "#1e3a8a"` sets the button background. Any string the browser
accepts is valid; the daemon does not sanitise (layouts are user-owned
config, not untrusted input). It affects the background only — label and
icon colour are a fixed light foreground, and the pressed state is derived
(`filter: brightness()` on `:active`), so no second colour field is needed.

Contrast is the layout author's responsibility. The client does **not**
auto-pick a legible foreground from background luminance — a bad colour
choice is the author's to fix. Chosen for predictability over cleverness.

### `icon` is a `{source, name}` dispatch, not a parsed token

```yaml
icon:
  source: lucide          # which renderer resolves ``name``
  name: arrow-left
```

`source` selects a renderer from the client's registry; `name` is looked up
within it. This is a dispatch table, not a fallback chain — no guessing
whether a string is a filename or a set token, and a typo fails visibly
rather than silently degrading to text.

The daemon validates only that `source` and `name` are non-empty strings.
It does **not** know the set of valid sources — that registry belongs to the
client. A layout naming a source the client doesn't bundle renders a visible
"unknown icon" placeholder, not a load-time error. This keeps new icon
sources a client-only change.

### Bundled sets: Lucide (UI glyphs) + Simple Icons (brand logos)

The client bundles two complementary sets:

- **Lucide** (`source: lucide`) — regular UI glyphs (arrows, search, media).
- **Simple Icons** (`source: simple-icons`) — brand/app logos (Firefox, …).

Both are monochrome and inherit the fixed foreground colour. Neither is
subset to referenced icons, so adding an icon to a layout is a YAML edit with
no client rebuild — any name in either set resolves at runtime.

**Loading is asymmetric, because the sets differ ~10× in weight.** Measured:
Lucide whole is ~198 KB gzipped; Simple Icons whole is ~2.1 MB gzipped (3450
brand paths). So:

- **Lucide is bundled into the main chunk** (renders synchronously — its
  glyphs are on most buttons, and 198 KB in the initial load is fine).
- **Simple Icons is a lazy on-demand chunk**, imported the first time a
  layout references a brand logo. Its 2.1 MB is never fetched unless a brand
  icon is actually used, and is cached by the PWA service worker thereafter.

(The earlier ~0.5 MB "bundle both whole" estimate was wrong — whole-bundling
Simple Icons pushed the initial payload to ~2.4 MB gzipped. Lazy-loading it
keeps the initial load at ~198 KB while preserving no-rebuild authoring.)

This mirrors the category norm (Elgato Stream Deck, MacroDeck, Touch Portal):
a baseline bundled set, later joined by per-icon uploads and installable
packs.

### Global look preferences live client-side; per-widget presentation lives in YAML

A clean seam for "where does a visual choice live":

- **Per-widget** presentation (`color`, `icon`) is part of the *layout* —
  authored in YAML, relayed by the daemon.
- **Global** look preferences (e.g. show-labels) are *device/client* choices
  — persisted in client Settings (`settings-store.ts`), never daemon config.

The first such preference is **show-labels** (default on): when off, buttons
render icon-only. A button that omits `label` is icon-only regardless.

### Per-widget-kind look is hard-coded client CSS; `color` is button-only

Widget kinds are visually distinguished by fixed client CSS, not by
YAML-driven theming. `button` and `jogstrip` cells differ by treatment
(the jogstrip carries a gradient, a distinct border, and a scroll-affordance
glyph). Trackpad is a full-screen *mode*, not a grid cell, so it needs no
per-cell identity treatment (`kind: "trackpad"` is not a renderable cell).

`color` applies to **buttons only**. On a jogstrip it is silently ignored —
kind identity outranks per-button tint on non-button surfaces, which keeps
"tell surfaces apart at a glance" intact. The daemon still relays `color`
opaquely; the client chooses not to apply it to jogstrips (no validation
error for a `color` on a jogstrip).

Extensible / user-defined control kinds (colour picker, jog wheel, …) are a
separate future exploration (#35), out of scope here.

### One fixed style — no light/dark, no per-layout theme

There is no theme system. The client has a single dark look. No OS
light/dark following, no `theme:` field, no per-layout accent overrides
beyond per-button `color`. (Night Light theming is out of scope per #6.)

## Out of scope (deferred, deliberately)

These are known future work, designed *for* but not built now. The
`{source, name}` schema already accommodates them without change:

- **Per-icon image upload** — `source: local`, a `name` the daemon serves
  from a user asset directory. Makes the daemon an asset host.
- **Uploadable icon/font sets** — a new `source` the client registers at
  runtime from a daemon-served manifest. Moves a source from *bundled* to
  *daemon-served*; the schema is identical.

## Consequences

- ADR-0003's wording ("no chrome knowledge except one protocol field") is
  superseded here: presentation attributes are a sanctioned second class of
  relayed data. Its *intent* (no app-specific daemon behaviour) is preserved.
- The daemon's `Widget` schema gains a structured `icon` (was a bare string);
  the client's `icon` render path changes from emitting literal text to
  dispatching on `source`.
- Adding or swapping an icon set is a client-only bundling change — the
  daemon and protocol are unaffected.
- Illegible colour choices are possible and accepted; they are the layout
  author's to fix.
