# Homepage mockups

Three design directions for a GitHub Pages homepage. The content is the same
in each; only the style differs.

| File | Direction |
|---|---|
| `a-notebook.html` | Warm paper, serif text, reads like a project write-up |
| `site/index.html` (was `b-desk.html`) | Dark, close to the app; the hero's window list cycles focus |
| `c-press.html` | The page is a deck: each key loads a demo below it |

**B is the chosen direction** (2026-11-12) and is now the real homepage in
`site/`, deployed to GitHub Pages. A and C are kept here, sharing its content
(`site/shared/`), in case that changes.

`site/shared/scenes.{js,css}` holds the parts all three use: auto-cycling hero,
web-app row, now-playing phone, trackpad and scroll-strip animations,
install tabs. `site/shared/content.js` holds the long-form sections (platforms,
privacy, comparison, roadmap, FAQ), written from the README, GUIDE and
PLATFORM-PARITY — keep it in step when those change. Every phone is the real client in an iframe, rendered at a
fixed viewport (700×390 landscape, 390×760 portrait) and scaled to fit.

## Viewing

```sh
just mockups
# → http://127.0.0.1:5289/docs/mockups/homepage/a-notebook.html (and c-press.html)
# → http://127.0.0.1:5289/site/index.html?app=http://127.0.0.1:5288/  (B, live dev client)
just pages
# → http://127.0.0.1:5290/deckd/  (B exactly as deployed: built site, client at app/)
```

The phones show the showcase demo decks (`?demo=home`, `gmail`, `meet`,
`media`, …) defined in `client/src/demo.ts`. `just mockups` serves the pages
over http on :5289 and runs the client's Vite dev server on :5288, which the
pages use automatically when served from localhost. Don't open the HTML files
directly: a `file://` page can't frame localhost in current browsers, so the
phones stay blank.

`?app=<url>` points the phones at another client. The homepage defaults to the
client beside it (`app/`); A and C fall back to the public build at
`https://jonocodes.github.io/deckd/app/`. Add `?eager` to load every phone
up front (for full-page screenshots).
