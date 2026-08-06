# Grid layout: ordered-list reflow with a banded cell size

**Supersedes [ADR-0004](0004-orientation-scaling.md).** Tracked in issue #92; **implemented** — the `Widget` schema carries an ordered list with an optional `size` span (no coordinates), the client reflows against a client-side cell-size band, and the transpose is gone.

ADR-0004 authored layouts as a fixed grid of absolute `[x, y, w, h]` coordinates and handled portrait by transposing them diagonally. That model assumes a grid whose shape is known when the layout is written — the Stream Deck premise, where the hardware *is* the grid. deckd's "deck" is an arbitrary browser viewport: a phone, a tablet, a laptop window being dragged narrower, a super-wide-but-short panel. There is no fixed grid shape to author against, so absolute coordinates are the wrong vocabulary. This ADR replaces them.

## Decisions

### Widgets are an ordered list that reflows; there are no coordinates

A layout's `widgets` are an **ordered list**. The client packs them left-to-right and wraps down, computing the column count from the available width. `grid: [x, y, w, h]` is gone. A widget may carry an optional `size: [w, h]` **span** (default `[1, 1]`) for non-uniform widgets (a wide meter, a trackpad-as-cell); it expresses extent, never position.

Positional muscle memory shifts from *absolute grid coordinate* to *sequence*: the third button is always the third button, wherever it wraps. This is acceptable because a user typically drives one machine from one controller and orders the buttons to taste — the case ADR-0004's per-coordinate stability was protecting is not worth the cost of a fixed grid.

Packing is **strict order**: if a spanned widget doesn't fit at the end of a row, the trailing gap is left and the widget wraps down. No dense back-filling — that would reorder widgets visually and break the sequence the model relies on.

### Portrait falls out of reflow; the transpose is deleted

ADR-0004's diagonal transpose exists only to keep cells roughly square when a landscape-authored grid is shown in portrait. Reflow makes it unnecessary: a narrow (portrait) viewport simply fits fewer columns and wraps into more rows. The `[x,y,w,h] → [y,x,h,w]` transpose and the landscape-authoring convention are both removed. ADR-0004's "future extension" (`portrait:` / `landscape:` blocks) is likewise dropped — reflow covers the common case, and orientation-specific *button sets* are not a goal.

### Cell size is a min/max band, held in client-side device settings

Cells are neither a hard pixel size nor a pair of named modes. They live in a **size band** — as many columns of at least `MIN` (a readability floor) as the width allows, then every cell stretches equally to consume leftover width, capped at `MAX`. Cells stay **aspect-locked** (square) as they flex. Fill is **horizontal only**: the grid is top-aligned and leftover height is breathing room below, by choice, not omission.

The band *is* the sizing behaviour that an earlier draft split into `fill` and `fixed` modes: a wide band with a low floor gives few large cells with everything visible ("fill"); a narrow band around a target gives constant density ("fixed"). No mode property is needed.

Crucially, the band is a **client-side per-device preference ([ADR-0006](0006-widget-visual-styling.md)), not a layout property.** How big a comfortable button is depends on the screen and the hand, not on what the layout means — the same bucket as content scale, scroll scale, and wake lock. It lives in `localStorage`, never reaches the daemon, and every layout reflows to whatever band the user set. Layout YAML therefore carries **no pixel sizes**. The existing content-scale control (#37) should be folded into this single sizing setting so the two don't fight: the band sets cell size, and icon/label scale derives from it.

### Overflow is the one genuinely per-layout knob

When the defined widgets exceed the capacity the band yields at the current viewport, the behaviour is:

- **shrink-to-fit** (default) — cells may shrink below the readability floor (respecting a hard 16 px floor) so every widget stays on the same surface. When the total widget set already fits at the floor size, the layout behaves exactly like `clip` (the floor is the same).
- **clip** — trailing widgets are off-surface and currently inaccessible. Ten buttons on a surface that fits eight means the last two cannot be reached. **No pagination in v1** (a candidate follow-on).

This is layout-semantic rather than device-ergonomic, so it may be a layout property (with a global default). It is the only sizing choice the layout author owns.

### Full-surface widgets opt out of the flow

A widget may declare itself full-surface (`size: full`) — it takes the whole chrome-excluded area and does not participate in packing. This is where the MPRIS `nowplaying` widget lands: it is already a full-bleed view under [ADR-0008](0008-chrome-view-carveout.md), not a grid cell. Generalising "full-surface" from the hardcoded view set into a widget property is a follow-on, not required by this ADR.

## Out of scope (deferred, deliberately)

- **More buttons on a bigger screen.** A larger viewport shows the *same* widgets, reflowed — never extra ones. Overflow clips; it does not reveal.
- **Pagination / scrolling** past the clip boundary. Named as the natural successor to clip mode, not built here.
- **Cross-device visual consistency within one layout.** Reflow means the wrap point differs by screen; that is intended, given one-controller-per-machine.
- **Per-device layouts** (a different button set per device). That is issue #38's axis — client identity — and a separate concern. This ADR is resolution/orientation-driven, never device-identity-driven.

## Consequences

- The `Widget` schema loses `grid: [x,y,w,h]` and gains an optional `size` (span or `full`). Both the TypeScript (`client/src/protocol.ts`) and Python protocols change together and must stay in parity (#76). This is a breaking layout-format change; existing `*.yaml` layouts need migration (drop `x,y`, keep `w,h` as `size`).
- `client/src/orientation.ts`'s transpose logic and its call site in `ButtonGrid.tsx` are removed; `deriveDims` is replaced by width-driven column computation against the band.
- `.grid` CSS moves from `repeat(N, 1fr)` to `repeat(auto-fill, minmax(MIN, 1fr))` with a `MAX` cap and an aspect-ratio lock (`client/src/style.css`).
- A new min/max cell-size control joins the settings page (`client/src/settings-store.ts`), subsuming content-scale (#37).
- **This blocks the layout editor (#82):** the editor becomes drag-to-*reorder* with a span control and an overflow toggle — not drag-to-XY on a fixed canvas — plus a viewport-preview toggle to inspect reflow at different widths. Its "grid arrangement UX" question should not be settled until this model lands.
- A visual mockup of the reflow behaviour lives at `docs/mockups/grid-reflow.html`.
