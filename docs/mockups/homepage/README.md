# Homepage mockups

Three design directions for a GitHub Pages homepage. The content is the same
in each; only the style differs.

| File | Direction |
|---|---|
| `a-notebook.html` | Warm paper, serif text, reads like a project write-up |
| `b-desk.html` | Dark, close to the app; the hero's window list cycles focus |
| `c-press.html` | The page is a deck: each key loads a demo below it |

**B is the chosen direction** (2026-11-12). A and C are kept, sharing the same
content, in case that changes.

`shared/scenes.{js,css}` holds the parts all three use: auto-cycling hero,
web-app row, now-playing phone, trackpad and scroll-strip animations,
install tabs. `shared/content.js` holds the long-form sections (platforms,
privacy, comparison, roadmap, FAQ), written from the README, GUIDE and
PLATFORM-PARITY — keep it in step when those change. Every phone is the real client in an iframe, rendered at a
fixed viewport (700×390 landscape, 390×760 portrait) and scaled to fit.

## Viewing

```sh
just mockups
# → http://127.0.0.1:5289/docs/mockups/homepage/b-desk.html
```

The phones show the showcase demo decks (`?demo=home`, `gmail`, `meet`,
`media`, …) defined in `client/src/demo.ts`. `just mockups` serves the pages
over http on :5289 and runs the client's Vite dev server on :5288, which the
pages use automatically when served from localhost. Don't open the HTML files
directly: a `file://` page can't frame localhost in current browsers, so the
phones stay blank.

`?app=<url>` points the phones at another client; elsewhere they fall back to
the public build at `https://jonocodes.github.io/deckd/` (which only has the
showcase decks once this branch is deployed). Add `?eager` to load every phone
up front (for full-page screenshots).
