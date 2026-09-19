# Seed a writable layouts directory from the package's bundled defaults.
#
# Usage: deckd-seed-layouts SRC_DIR DEST_DIR
#
# Copies each top-level *.yaml from SRC_DIR into DEST_DIR, but never
# overwrites a file that already exists there: a user's edited layouts
# always win, and repeated activations converge. A missing SRC_DIR is a
# no-op, so a stripped package can't fail an activation.
set -euo pipefail

src=${1:?usage: deckd-seed-layouts SRC_DIR DEST_DIR}
dest=${2:?usage: deckd-seed-layouts SRC_DIR DEST_DIR}

[ -d "$src" ] || exit 0

mkdir -p "$dest"

shopt -s nullglob
for f in "$src"/*.yaml; do
  base=${f##*/}
  if [ ! -e "$dest/$base" ]; then
    # install, not cp: the source is a read-only store path, and the
    # editor must be able to write the seeded copy.
    install -m 0644 "$f" "$dest/$base"
  fi
done
