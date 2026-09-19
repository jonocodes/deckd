# Install (or upgrade) and enable the deckd-focus KWin script for the
# current user, mirroring `just install-focus-kwin`. Idempotent, so it is
# safe to run from a home-manager activation on every switch.
#
# Usage: deckd-install-kwin SCRIPT_PACKAGE_DIR
#
# SCRIPT_PACKAGE_DIR is the directory holding metadata.json and
# contents/code/main.js (the package output of deckd-focus-kwin).
set -euo pipefail

pkg=${1:?usage: deckd-install-kwin SCRIPT_PACKAGE_DIR}
script_id="deckd-focus"
script_path="$HOME/.local/share/kwin/scripts/${script_id}/contents/code/main.js"

# 1. Install the script package into the user's KWin dir. -i fails when
#    it is already installed, so fall back to -u (upgrade) on re-runs.
if ! kpackagetool6 --type=KWin/Script -i "$pkg" 2>/dev/null; then
  kpackagetool6 --type=KWin/Script -u "$pkg"
fi

# 2. Persist enablement across relogins (kwinrc [Plugins] deckd-focusEnabled).
kwriteconfig6 --file kwinrc --group Plugins --key "${script_id}Enabled" true

# 3. Apply the change and hot-start the script. qdbus can fail when no
#    Plasma session is running (e.g. activating over SSH), which must not
#    abort the activation: the persisted flag covers the next login.
qdbus org.kde.KWin /KWin org.kde.KWin.reconfigure >/dev/null 2>&1 || true
qdbus org.kde.KWin /Scripting org.kde.kwin.Scripting.unloadScript "$script_id" >/dev/null 2>&1 || true
qdbus org.kde.KWin /Scripting org.kde.kwin.Scripting.loadScript "$script_path" "$script_id" >/dev/null 2>&1 || true
