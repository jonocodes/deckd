# Homepage mockups

Three design directions for a GitHub Pages homepage. The content is the same
in each; only the style differs.

| File | Direction |
|---|---|
| `a-notebook.html` | Warm paper, serif text, reads like a project write-up |
| `b-desk.html` | Dark, close to the app; the hero's window list cycles focus |
| `c-press.html` | The page is a deck: each key loads a demo below it |

`shared/scenes.{js,css}` holds the parts all three use: auto-cycling hero,
web-app row, now-playing phone, trackpad and scroll-strip animations,
install tabs. Every phone is the real client in an iframe, rendered at a
fixed viewport (700×390 landscape, 390×760 portrait) and scaled to fit.

## Viewing

The phones show the showcase demo decks (`?demo=home`, `gmail`, `meet`,
`media`, …) defined in `client/src/demo.ts`. Until those are deployed, run a
local client and point the page at it:

```sh
cd client && npx vite dev --port 5288 --host 127.0.0.1
# then open, e.g.
#   file://$PWD/../docs/mockups/homepage/b-desk.html?app=http://127.0.0.1:5288/
```

Without `?app=` the pages use the public build at
`https://jonocodes.github.io/deckd/`.
