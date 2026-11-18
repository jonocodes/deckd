#!/usr/bin/env bash
# Assemble the GitHub Pages site: the homepage (site/) at the root, the client
# under app/, Ladle under ladle/. CI (.github/workflows/deploy-pages.yml) and
# `just pages` both run this, so a local preview is exactly what deploys.
#
# Usage: scripts/build_pages.sh [OUT_DIR]    (default: _site)
# Env:   PAGES_BASE  URL path the site is served from (default /deckd/)
#        SKIP_LADLE  set to skip the Ladle build (faster local previews)
# Needs client/node_modules (npm ci in client/).
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
out="$(realpath -m "${1:-$root/_site}")"
base="${PAGES_BASE:-/deckd/}"

rm -rf "$out"
mkdir -p "$out"
# -L: site/deckd-mark.svg is a symlink to assets/; copy the file itself.
cp -rL "$root/site/." "$out/"

cd "$root/client"
# `npm run build` type-checks first, so a type error fails the deploy.
VITE_BASE_PATH="${base}app/" npm run build -- --outDir "$out/app" --emptyOutDir

# Pages serves the site's 404.html for any unknown path. Make it the client,
# so a deep link like app/trackpad boots the app (its asset URLs are
# absolute, so they resolve from any path) instead of a bare 404.
cp "$out/app/index.html" "$out/404.html"

if [ -z "${SKIP_LADLE:-}" ]; then
  # Ladle won't create its outDir, and joins even an absolute --outDir onto
  # the cwd, so hand it a path relative to client/.
  mkdir -p "$out/ladle"
  npm run ladle:build -- --base "${base}ladle/" --outDir "$(realpath --relative-to=. "$out/ladle")"
fi

echo "Pages site assembled in $out (base $base)"
