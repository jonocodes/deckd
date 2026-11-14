#!/usr/bin/env bash
# End-to-end test of the deckd.app DMG on a real macOS desktop session:
# install it, drive the real menu-bar item through Accessibility, check each
# item's effect, upgrade in place, then capture the first-run permission
# prompt. Screenshots land in OUT_DIR as evidence.
#
#   test-app.sh [--pregrant] [--yes] DMG [OUT_DIR]
#
#   --pregrant  write deckd's TCC grants (System Events, Accessibility, input)
#               straight into the TCC databases before launch. Needs Full Disk
#               Access for the shell and sudo — true on GitHub's macOS runners,
#               not on a normal Mac (grant by hand there instead). Without the
#               System Events grant, deckd's consent prompt blocks System
#               Events and every menu check below times out.
#   --yes       required outside CI: this replaces /Applications/deckd.app,
#               quits any running deckd, and resets deckd's System Events
#               grant at the end (to capture the prompt).
#
# Runs in CI as the `test-app` job of .github/workflows/release-macos.yml;
# locally via `just test-macos-app`.
set -euo pipefail

PREGRANT=0 YES=0
while [ $# -gt 0 ]; do
    case "$1" in
        --pregrant) PREGRANT=1 ;;
        --yes) YES=1 ;;
        -*) echo "unknown option $1" >&2; exit 2 ;;
        *) break ;;
    esac
    shift
done
DMG="${1:?usage: test-app.sh [--pregrant] [--yes] DMG [OUT_DIR]}"
OUT="${2:-test-app-out}"
HERE="$(cd "$(dirname "$0")" && pwd)"

if [ "${CI:-}" != "true" ] && [ "$YES" != 1 ]; then
    echo "Refusing to run outside CI without --yes: this replaces /Applications/deckd.app" >&2
    echo "and resets deckd's System Events permission at the end." >&2
    exit 2
fi

BID=com.deckd.daemon
APP=/Applications/deckd.app
PORT=8765
LOG="$HOME/Library/Logs/deckd.log"
PASSWORD_FILE="$HOME/.config/deckd/password"
mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd)"

FAILS=0
pass() { echo "  ok   $*"; }
fail() { echo "  FAIL $*"; FAILS=$((FAILS + 1)); }
step() { echo; echo "== $*"; }

# macOS has no GNU timeout.
to() { local s="$1"; shift; perl -e 'alarm shift; exec @ARGV' "$s" "$@"; }

# Run AppleScript lines inside `tell System Events to tell <deckd process>`.
ax() {
    local args=(-e "tell application \"System Events\" to tell (first process whose bundle identifier is \"$BID\")")
    local line
    for line in "$@"; do args+=(-e "$line"); done
    args+=(-e "end tell")
    to 30 osascript "${args[@]}"
}
MENU='menu 1 of menu bar item 1 of menu bar 1'
# A click that quits or restarts the app can drop the AX reply; the checks after
# each click judge the effect, so a non-zero exit here is only noted.
click_item() { ax "click menu item \"$1\" of $MENU" >/dev/null 2>&1 || echo "  note: click on \"$1\" returned non-zero"; }
mark_of() { ax "return value of attribute \"AXMenuItemMarkChar\" of menu item \"$1\" of $MENU"; }

healthy() { curl -fs -m 2 "http://$1:$PORT/health" >/dev/null; }
wait_for() {  # wait_for SECONDS cmd... — poll every 0.5s
    local n=$(($1 * 2)); shift
    for _ in $(seq "$n"); do "$@" && return 0; sleep 0.5; done
    return 1
}
deckd_running() { pgrep -f "$APP/Contents/MacOS/deckd" >/dev/null; }
not_running() { ! deckd_running; }
shot() { screencapture -x "$OUT/$1.png" && echo "  shot $1.png"; }

quit_deckd() {
    osascript -e "tell application id \"$BID\" to quit" >/dev/null 2>&1 || true
    wait_for 10 not_running || pkill -f "$APP/Contents/MacOS/deckd" || true
    wait_for 5 not_running || true
}

install_dmg() {
    local mnt
    mnt="$(mktemp -d)"
    hdiutil attach -quiet -nobrowse -readonly -mountpoint "$mnt" "$DMG"
    rm -rf "$APP"
    ditto "$mnt/deckd.app" "$APP"
    hdiutil detach -quiet "$mnt"
}

launch() {
    open -a "$APP"
    wait_for 60 healthy 127.0.0.1
}

LAN_IP="$(ipconfig getifaddr en0 || ipconfig getifaddr en1 || true)"

# Compile the HID helper up front; a missing toolchain only costs the
# open-menu screenshot.
CLICK=""
if swiftc -O -o "$OUT/.click" "$HERE/click.swift" 2>"$OUT/.click.log"; then
    CLICK="$OUT/.click"
fi

step "Environment"
sw_vers | sed 's/^/  /'
echo "  LAN address: ${LAN_IP:-none}"
echo "  DMG: $DMG"

if [ "$PREGRANT" = 1 ]; then
    step "Pre-grant TCC permissions"
    udb="$HOME/Library/Application Support/com.apple.TCC/TCC.db"
    sdb="/Library/Application Support/com.apple.TCC/TCC.db"
    cols="service, client, client_type, auth_value, auth_reason, auth_version, indirect_object_identifier_type, indirect_object_identifier, flags, last_modified"
    now="$(date +%s)"
    sqlite3 "$udb" "INSERT OR REPLACE INTO access ($cols) VALUES ('kTCCServiceAppleEvents','$BID',0,2,4,1,0,'com.apple.systemevents',0,$now);"
    for svc in kTCCServiceAccessibility kTCCServicePostEvent kTCCServiceListenEvent; do
        sudo sqlite3 "$sdb" "INSERT OR REPLACE INTO access ($cols) VALUES ('$svc','$BID',0,2,4,1,0,'UNUSED',0,$now);"
    done
    pass "granted System Events, Accessibility, PostEvent, ListenEvent to $BID"
fi

step "Install from DMG and launch"
quit_deckd
install_dmg
codesign --verify --deep "$APP" && pass "code signature valid" || fail "code signature invalid"
codesign -d -r- "$APP" 2>&1 | sed -n 's/^# designated => /  designated requirement: /p'
spctl_out="$(spctl --assess --type execute "$APP" 2>&1 || true)"
echo "  Gatekeeper (informational; ad-hoc + not notarized => rejected): ${spctl_out:-accepted}"
if launch; then pass "/health answers on 127.0.0.1:$PORT"; else fail "/health never answered"; fi
if [ -n "$LAN_IP" ] && healthy "$LAN_IP"; then fail "LAN address answers before LAN access is enabled"; else pass "LAN address refused by default"; fi
if grep -q "Accessibility is not granted" "$LOG" 2>/dev/null; then
    echo "  note: deckd reports Accessibility not granted (expected without --pregrant)"
fi

step "Menu structure"
items="$(ax "set out to \"\"" \
    "repeat with mi in menu items of $MENU" \
    "set out to out & (name of mi as text) & linefeed" \
    "end repeat" "return out")" || items=""
expected="Open deckd surface
Open decks folder
Restart server
Allow LAN access
missing value
Quit deckd"
if [ "$(printf '%s' "$items" | sed '/^$/d')" = "$expected" ]; then
    pass "menu items: $(printf '%s' "$items" | sed '/^$/d' | tr '\n' '/' )"
else
    fail "menu items differ; got:"; printf '%s\n' "$items" | sed 's/^/       /'
fi

step "Screenshot: open menu"
if [ -n "$CLICK" ]; then
    pos="$(ax "set {x, y} to position of menu bar item 1 of menu bar 1" \
        "set {w, h} to size of menu bar item 1 of menu bar 1" \
        "return ((x + w / 2) as integer as text) & \" \" & ((y + h / 2) as integer as text)")" || pos=""
    if [ -n "$pos" ]; then
        # shellcheck disable=SC2086
        "$CLICK" click $pos; sleep 1; shot 1-menu-open; "$CLICK" esc; sleep 0.5
    else
        echo "  skipped: couldn't read the status item's position"
    fi
else
    echo "  skipped: swiftc unavailable ($(head -1 "$OUT/.click.log"))"
fi

step "Allow LAN access (on)"
click_item "Allow LAN access"
if [ -z "$LAN_IP" ]; then
    echo "  skipped reachability: no LAN address"
elif wait_for 15 healthy "$LAN_IP"; then pass "LAN address $LAN_IP answers"
else fail "LAN address $LAN_IP never answered"; fi
[ "$(mark_of "Allow LAN access")" = "✓" ] && pass "menu shows ✓" || fail "no ✓ on Allow LAN access"

step "Allow LAN access (off)"
click_item "Allow LAN access"
if [ -n "$LAN_IP" ]; then
    sleep 2
    wait_for 15 healthy 127.0.0.1 || true
    if healthy "$LAN_IP"; then fail "LAN address still answers"; else pass "LAN address refused again"; fi
fi
healthy 127.0.0.1 && pass "localhost still answers" || fail "localhost stopped answering"
[ "$(mark_of "Allow LAN access")" != "✓" ] && pass "✓ cleared" || fail "✓ still shown"

step "Restart server"
before="$(grep -c "deckd.server INFO listening on" "$LOG" || true)"
click_item "Restart server"
if wait_for 20 sh -c "[ \$(grep -c 'deckd.server INFO listening on' '$LOG') -gt $before ]"; then
    pass "server restarted (listening line $((before + 1)) in log)"
else
    fail "no new 'listening on' line in $LOG"
fi
wait_for 20 healthy 127.0.0.1 && pass "/health back up" || fail "/health down after restart"

step "Open decks folder"
click_item "Open decks folder"
if wait_for 10 sh -c "osascript -e 'tell application \"System Events\" to get name of every window of process \"Finder\"' | grep -q decks"; then
    pass "Finder window 'decks' opened"
else
    fail "no Finder window named decks"
fi
shot 2-decks-folder
osascript -e 'tell application "System Events" to tell process "Finder" to click button 1 of (first window whose name is "decks")' >/dev/null 2>&1 || true

step "Open deckd surface"
# Python's webbrowser honours $BROWSER, but `open -a` doesn't pass our env, so
# check the effect instead: the default browser comes up on the surface URL.
click_item "Open deckd surface"
browser_up() { osascript -e 'tell application "System Events" to get name of every process whose background only is false' | grep -q -E "Safari|Chrome|Firefox"; }
if wait_for 20 browser_up; then pass "a browser launched"; else fail "no browser launched"; fi
sleep 4
shot 3-surface-in-browser
osascript -e 'tell application "System Events" to tell process "Safari" to get name of every window' 2>/dev/null | sed 's/^/  Safari windows: /' || true
osascript -e 'tell application "Safari" to quit' >/dev/null 2>&1 || true

step "Quit, then upgrade in place"
password_before="$(cat "$PASSWORD_FILE" 2>/dev/null || true)"
click_item "Quit deckd"
if wait_for 10 not_running; then pass "Quit: process gone"; else fail "Quit: still running"; fi
healthy 127.0.0.1 && fail "port still answering after Quit" || pass "port freed"
install_dmg
if launch; then pass "relaunched after reinstall"; else fail "no /health after reinstall"; fi
[ -n "$password_before" ] && [ "$(cat "$PASSWORD_FILE")" = "$password_before" ] \
    && pass "password survived the upgrade" || fail "password changed or missing after upgrade"
[ -d "$HOME/Library/Application Support/deckd/decks" ] && pass "decks folder survived" || fail "decks folder gone"

step "First-run permission prompt"
quit_deckd
# Reset deckd's System Events grant so the next launch asks, as on a fresh Mac.
tccutil reset AppleEvents "$BID" >/dev/null 2>&1 || true
open -a "$APP"
wait_for 60 healthy 127.0.0.1 || true
sleep 8
shot 4-permission-prompt
# The prompt blocks System Events from here on; nothing below may use it.
pkill -f "$APP/Contents/MacOS/deckd" || true

rm -f "$OUT/.click" "$OUT/.click.log"
cp "$LOG" "$OUT/deckd.log" 2>/dev/null || true

echo
if [ "$FAILS" -eq 0 ]; then
    echo "All checks passed. Screenshots: $OUT"
else
    echo "$FAILS check(s) failed. Screenshots and deckd.log: $OUT"
    exit 1
fi
