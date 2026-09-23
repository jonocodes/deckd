# Reflow: the row count is the only free variable

**Supersedes [ADR-0010](0010-grid-reflow.md).** Keeps that ADR's model — widgets are an ordered list with no coordinates, packed in strict order — and replaces the geometry that sized them, plus the settings that drove it.

ADR-0010 sized the grid by asking *"how many columns fit the width?"* and letting rows fall out ragged. Column count only sees one axis, so height had to be smuggled back in as a proxy; the shipped implementation ended up with a tuned constant (`Math.min(w / 3, Math.max(cellSize * 1.5, 200))`) whose comments named the specific test cases it existed to satisfy. That is the signal that the free variable was wrong.

## Decisions

### Choose the row count; everything else follows

Row count `R` is the only genuinely free integer in the problem. For a given `R`:

```
c    = ceil(units / R)                    widest row needed
cell = min( (W - (c-1)·gap) / c ,          what the width allows
            (H - (R-1)·gap) / R )          what the height allows
```

Pick the `R` that maximises `cell`, clamped to a comfort cap. Ties — common once the cap binds — break toward the grid shape closest to the container's shape, which is derived from the viewport, not tuned. There are no magic constants.

Both axes now enter honestly. This **reverses ADR-0010's "fill is horizontal only; leftover height is breathing room below, by choice, not omission."** The grid is centred on both axes instead.

A candidate `R` is skipped when `(R - 1) · c >= units` — its columns would already hold everything in one fewer row, so it only shrinks cells for nothing. **This prune is load-bearing, not an optimisation.** It is exactly what keeps the candidate set closed under `(rows, cols) -> (cols, rows)`, so a portrait grid and its landscape counterpart resolve consistently; and it guarantees plain fill-wrapping yields exactly `R` non-empty rows. Deleting it breaks both properties silently.

### Rows fill to the column count; the remainder lands in the bottom row

Not balanced across rows. Ten widgets in four rows is `3+3+3+1`, **not** `3+3+2+2`. The bottom row holds the fewest, and no row above repeats that count unless every row is equal.

This is ordinary text wrapping at width `c` — which is already ADR-0010's strict-order packing, and which CSS grid auto-placement performs natively. So this stage adds no new concept and almost no code; all the novelty is in choosing `c` via the row count. It also means **spans need no special handling**: a spanned widget shelf-packs in strict order exactly as before.

### The grid block is centred; rows wash left within it

The block is as wide as the widest row. It is centred in the area, and every row starts at the block's left edge — so columns stay aligned (widget 5 of a `2+2+1` sits directly under widget 1) while a short row leaves its gap on the right. Centring each row *independently* was considered and rejected: it breaks the column alignment that makes the arrangement read as a grid.

`justify-content: center` over a fixed track list produces this for free.

### The band is a floor and a cap, with distinct jobs

ADR-0010 described a min/max band but shipped a single `cellSize` target. The band is now real, and **cell size is derived from the viewport — neither value sets it**:

- **`minCell`** — *how many buttons you see.* Capacity is `cols × rows` of whole cells at this size. Under `clip` it is a promise the renderer keeps, not a hint.
- **`maxCell`** — *how big they may get.* Stops a two-widget deck from becoming two enormous buttons on a large panel.

Both remain client-side per-device preferences ([ADR-0006](0006-widget-visual-styling.md)) in `localStorage`. Layout YAML still carries no pixel sizes.

### Overflow is a device setting with a layout-supplied default

ADR-0010 made overflow layout-only, as "layout-semantic rather than device-ergonomic". That no longer holds: `minCell` is a device preference that *creates* the shortage, so the policy resolving it must be reachable from the same place. The layout's `overflow` field now supplies the **default**, which the device may override (`deckd.overflow`; unset means follow the layout).

**The default changes from `shrink-to-fit` to `clip`.** The reason is not aesthetic: under `shrink-to-fit` the visible count is always every widget, so capacity is never consulted and **`minCell` has no effect at all**. Defaulting to it would ship a preference that does nothing. Note the two modes are **identical whenever the deck already fits** — they diverge only on oversized decks.

`clip` is also materially better than it was. ADR-0010 realised it as CSS `overflow: hidden` over a height-blind column count, so rows past the fold were *sliced mid-cell*. It now trims the widget list to whole cells before render, so the surface shows complete, well-sized buttons and never a cropped half-row.

## Consequences

- **Breaking default change.** `Layout.overflow` defaults to `clip` in the daemon, and `ButtonGrid`'s prop default matches. No layout YAML in the repo sets `overflow`, so every deck that currently overflows will start hiding trailing widgets instead of shrinking everything. Decks that fit are unaffected.
- **A hidden widget is unreachable, with no affordance announcing it.** The hidden count is known at render time, so surfacing it is cheap and worth doing. Pagination — named in ADR-0010 as the successor to clip — dissolves the trade-off entirely and remains the real fix.
- `client/src/reflow.ts` is rewritten: `capacityUnits` + a row-count search, returning `cols`, `rows`, `cellPx`, `visibleUnits`, `hiddenUnits`. Before the first measurement it reports everything visible at zero size — trimming is a decision that requires a measurement, and reporting nothing would blank the surface for a frame.
- `settings-store.ts` replaces `useCellSize` with `useCellBand` (which keeps floor ≤ cap) and adds `useOverflowPreference`. Keys: `deckd.minCell`, `deckd.maxCell`, `deckd.overflow`.
- Settings gains **Min button size**, **Max button size**, and **When there's no room** (Follow layout / Hide extras / Shrink buttons).
- The interactive model, with both orientations at true ratios, lives at `docs/mockups/reflow-adr0011.html`.
