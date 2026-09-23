# Client freshness: fingerprinted bundle + auto-reload, no offline cache

The daemon serves the built client itself (`--client-dist`), so in a
normal deployment the two ship together. The failure mode this ADR
fixes is the *cached* half of that pair: a phone — especially an
installed PWA — can keep running the old shell against a rebuilt
daemon, and because there is no wire version negotiation (see
"Deliberately not here" below) the stale surface can drive an
incompatible protocol without ever being noticed.

The property we want is narrow and testable: **a running client never
keeps using a bundle different from the one the daemon is serving.**
It is not general protocol compatibility; it is shell freshness.

## Decisions

### No service worker

deckd installs as a PWA with just a manifest and icon: Chrome dropped
the service-worker install requirement, and iOS "Add to Home Screen"
never had one. Shipping no service worker keeps the cache story to a
single layer (HTTP) that the server controls with headers, instead of
two (HTTP + Cache Storage) where the SW's own update lifecycle becomes
the thing that goes stale. Offline operation is not a goal.

### The shell is `no-store`, content-hashed assets are immutable

`__main__._client_cache_headers` applies to the SPA routes and the
static client tree only. `index.html`, `manifest.json`, `icon.svg`,
and any other unhashed file answer `Cache-Control: no-store` — every
navigation re-fetches them. Vite's `/assets/*` files are
content-addressed (a changed byte means a changed filename), so they
keep `public, max-age=31536000, immutable` and the app stays cheap to
load. The middleware skips responses that already carry
`Cache-Control`, so the album-art proxies' own caching is untouched.

### `/health` carries a fingerprint of the served bundle

At startup the daemon hashes every file in the client dist (relative
path + bytes) into a short id and exposes it as `client_build` on
`/health`. Absent when no `--client-dist` was given (dev server,
headless daemon) — the client treats that as "don't check". The
fingerprint covers *all* files, not just `index.html`, so unhashed
edits (`manifest.json`, `icon.svg`) also register.

The id is computed once per daemon start. Rebuilding the dist under a
running daemon does not change it; "new bundle" means "daemon
restarted with a new bundle", which is the actual deploy path
(`just build-client` + restart) and keeps the check free.

### The client reloads itself when the fingerprint moves

`client/src/update-check.ts` remembers the last id it saw in
`localStorage` and re-reads `/health`:

- immediately on load;
- every 30 s;
- on `pageshow`, `visibilitychange` (to visible), and `online` — the
  moments an installed PWA comes back from suspension, when a stale
  shell is most likely to surface.

A changed id is recorded **before** `location.reload()` so a blocked
reload cannot loop. A first-ever sighting is only recorded. Anything
unreadable — offline, demo mode, no `client_build` field — is
`unknown`, and `unknown` never reloads. A slow check doesn't stack:
one request is in flight at a time.

## Deliberately not here

- **Protocol version negotiation / capability handshake.** This ADR
  assumes client and server are version-matched by construction after
  a reload. Making an old client work against a new daemon (or vice
  versa) is a separate, larger decision about additive-only protocol
  evolution, and belongs in its own ADR.
- **Offline mode / service-worker caching.** Explicitly rejected
  above; a surface that works against a down daemon is a different
  product.
- **Per-request fingerprints.** A live dist edit under a running
  daemon serves neither the old bundle consistently nor the new one;
  restart is the contract.
- **A "new version, tap to reload" affordance.** The surface is a
  remote control, mid-session state lives on the daemon, and a reload
  costs well under a second; auto-reload is the simpler contract.

## Consequences

- A daemon restart with a new bundle briefly drops every client's
  WebSocket as the page reloads and reconnects. Acceptable for a
  control surface; the alternative (mixed-version clients) is worse.
- `client/src/main.tsx` starts the check unconditionally; demo and
  gallery entry points don't import it, and demo mode no-ops because
  `/health` is unreachable.
- The client-serving routes moved out of `main()` into
  `_add_client_routes`, so tests boot a throwaway dist without the
  argparse surface (`tests/test_client_serving.py`). The decision
  table in `probeForUpdate` is unit-tested in
  `client/src/update-check.test.ts`.
- `localStorage` holds one key (`deckd.build`). Clearing storage only
  loses the comparison baseline; the next check re-records.
- The reload is only safe if the current URL itself reloads. The SPA
  fallback regex had an anchor bug (`^` inside the named group) that made
  every extension-less path 404 on the daemon-served client — invisible in
  Vite dev, but a hard reload of `/settings`, `/editor`, etc. would have
  failed. The fallback now matches extension-less paths only, leaving
  dotted assets to the static handler; `tests/test_client_serving.py`
  pins both halves.
