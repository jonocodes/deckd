#!/usr/bin/env bash
# deckd Linux system integration (issue #168).
#
# The AppImage cannot write /etc/udev/rules.d or add groups — that is a root
# action on every channel. This script does the root step (the udev rule +
# `input` group) *and* the user-level pieces the AppImage can't do by itself
# (the desktop focus watcher and an XDG autostart entry), so one `sudo` run
# finishes the install.
#
# It reads its assets from an *extracted* AppImage layout:
#
#   <assets>/70-deckd-uinput.rules
#   <assets>/gnome-shell/deckd-focus@local/...
#   <assets>/kwin-script/deckd-focus/...
#
# which the AppImage ships under usr/share/deckd/integration. Point it at an
# AppImage and it extracts them; or pass --assets DIR for a pre-extracted tree
# (`just install-system-integration` stages one from a checkout).
#
# Usage:
#   sudo ./install-system-integration.sh ./deckd-<version>-x86_64.AppImage
#   sudo ./install-system-integration.sh --assets /path/to/integration
#   sudo ./install-system-integration.sh --uninstall
#
# Options:
#   --appimage PATH   AppImage to extract assets from and to autostart
#   --assets DIR      Use a pre-extracted integration tree instead of an AppImage
#   --user NAME       Target user (default: $SUDO_USER, else the login user)
#   --desktop MODE    auto|gnome|kde|none  (default auto) — focus watcher to install
#   --no-autostart    Do not write ~/.config/autostart/deckd.desktop
#   --uninstall       Remove the udev rule, focus watcher, autostart entry,
#                     and the user's `input` membership
#   -h, --help
#
# Re-running install is safe: assets are replaced, not appended.

set -euo pipefail

UDEV_DEST="/etc/udev/rules.d/70-deckd-uinput.rules"
GNOME_UUID="deckd-focus@local"
KWIN_ID="deckd-focus"

die() { echo "error: $*" >&2; exit 1; }
note() { echo "  $*"; }

usage() {
    awk 'NR>1 && /^#/ {sub(/^# ?/, ""); print; next} NR>1 {exit}' "$0"
    exit "${1:-0}"
}

APPIMAGE=""
ASSETS=""
ASSETS_DIR=""
TARGET_USER=""
DESKTOP="auto"
AUTOSTART=1
UNINSTALL=0

while [ $# -gt 0 ]; do
    case "$1" in
        --appimage) APPIMAGE="${2:?--appimage needs a path}"; shift 2 ;;
        --assets)   ASSETS="${2:?--assets needs a path}"; shift 2 ;;
        --user)     TARGET_USER="${2:?--user needs a name}"; shift 2 ;;
        --desktop)  DESKTOP="${2:?--desktop needs a mode}"; shift 2 ;;
        --no-autostart) AUTOSTART=0; shift ;;
        --uninstall) UNINSTALL=1; shift ;;
        -h|--help) usage 0 ;;
        -*) die "unknown option: $1" ;;
        *) APPIMAGE="$1"; shift ;;  # bare arg: the AppImage
    esac
done

[ "$(id -u)" -eq 0 ] || die "must run as root: sudo $0 ..."

# The user the desktop belongs to. Under sudo that's SUDO_USER; otherwise fall
# back to the owner of the invoking terminal.
if [ -z "$TARGET_USER" ]; then
    TARGET_USER="${SUDO_USER:-$(logname 2>/dev/null || echo "${USER:-}")}"
fi
[ -n "$TARGET_USER" ] && [ "$TARGET_USER" != "root" ] \
    || die "could not determine the target user; pass --user NAME"
id "$TARGET_USER" >/dev/null 2>&1 || die "no such user: $TARGET_USER"
HOME_DIR="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
PRIMARY_GROUP="$(id -gn "$TARGET_USER")"
[ -n "$HOME_DIR" ] || die "could not resolve home for $TARGET_USER"

# Run a command as the target user, with their home. sudo is the common case;
# runuser (util-linux) is the fallback on systems without sudo.
as_user() {
    if command -v sudo >/dev/null 2>&1; then
        sudo -u "$TARGET_USER" -H -- "$@"
    elif command -v runuser >/dev/null 2>&1; then
        runuser -u "$TARGET_USER" -- "$@"
    else
        return 127
    fi
}

# chown a path (and its contents) to the target user.
own() { chown -R "$TARGET_USER:$PRIMARY_GROUP" "$@"; }

# --- assets ----------------------------------------------------------------

extract_dir=""
cleanup() { [ -n "$extract_dir" ] && rm -rf "$extract_dir"; }
trap cleanup EXIT

# Set ASSETS_DIR in the current shell (not a command substitution) so the
# mktemp cleanup trap below still owns extract_dir.
resolve_assets() {
    if [ -n "$ASSETS" ]; then
        ASSETS_DIR="$ASSETS"; return
    fi
    [ -n "$APPIMAGE" ] || die "pass an AppImage path or --assets DIR"
    [ -x "$APPIMAGE" ] || die "AppImage not executable: $APPIMAGE"
    extract_dir="$(mktemp -d)"
    ( cd "$extract_dir" && "$APPIMAGE" --appimage-extract 'usr/share/deckd/integration/*' >/dev/null )
    ASSETS_DIR="$extract_dir/squashfs-root/usr/share/deckd/integration"
}

# --- steps -----------------------------------------------------------------

install_udev() {
    [ -f "$ASSETS_DIR/70-deckd-uinput.rules" ] || die "assets missing the udev rule"
    note "+ installing $UDEV_DEST"
    install -m 0644 "$ASSETS_DIR/70-deckd-uinput.rules" "$UDEV_DEST"
    if command -v udevadm >/dev/null 2>&1; then
        udevadm control --reload-rules
        udevadm trigger --subsystem-match=misc --sysname-match=uinput
    else
        note "udevadm not found; reboot for the rule to take effect"
    fi
    if id -nG "$TARGET_USER" | tr ' ' '\n' | grep -qx input; then
        note "= $TARGET_USER is already in the input group"
    else
        note "+ adding $TARGET_USER to the input group"
        usermod -aG input "$TARGET_USER"
        note "! log out and back in for the group change to apply"
    fi
}

remove_udev() {
    if [ -f "$UDEV_DEST" ]; then
        note "- removing $UDEV_DEST"
        rm -f "$UDEV_DEST"
        command -v udevadm >/dev/null 2>&1 && udevadm control --reload-rules || true
    fi
    if id -nG "$TARGET_USER" | tr ' ' '\n' | grep -qx input; then
        note "- removing $TARGET_USER from the input group"
        gpasswd -d "$TARGET_USER" input >/dev/null
        note "! log out and back in for the group change to apply"
    fi
}

detect_desktop() {
    [ "$DESKTOP" != auto ] && { echo "$DESKTOP"; return; }
    case "${XDG_CURRENT_DESKTOP:-}" in
        *GNOME*) echo gnome; return ;;
        *KDE*|*Plasma*) echo kde; return ;;
    esac
    if pgrep -u "$TARGET_USER" -x gnome-shell >/dev/null 2>&1; then echo gnome; return; fi
    if pgrep -u "$TARGET_USER" -x plasmashell >/dev/null 2>&1 \
        || pgrep -u "$TARGET_USER" -x kwin_wayland >/dev/null 2>&1; then
        echo kde; return
    fi
    echo none
}

install_focus_watcher() {
    local mode; mode="$(detect_desktop)"
    case "$mode" in
        gnome)
            local dest="$HOME_DIR/.local/share/gnome-shell/extensions/$GNOME_UUID"
            [ -d "$ASSETS_DIR/gnome-shell/$GNOME_UUID" ] || die "assets missing the GNOME extension"
            note "+ installing GNOME Shell extension $GNOME_UUID"
            rm -rf "$dest"
            mkdir -p "$(dirname "$dest")"
            cp -R "$ASSETS_DIR/gnome-shell/$GNOME_UUID" "$dest"
            own "$(dirname "$dest")"
            if as_user gnome-extensions enable "$GNOME_UUID" >/dev/null 2>&1; then
                note "= extension enabled"
            else
                note "! log out and back in, then: gnome-extensions enable $GNOME_UUID"
            fi
            ;;
        kde)
            local dest="$HOME_DIR/.local/share/kwin/scripts/$KWIN_ID"
            [ -d "$ASSETS_DIR/kwin-script/$KWIN_ID" ] || die "assets missing the KWin script"
            note "+ installing KWin script $KWIN_ID"
            rm -rf "$dest"
            mkdir -p "$(dirname "$dest")"
            cp -R "$ASSETS_DIR/kwin-script/$KWIN_ID" "$dest"
            own "$(dirname "$dest")"
            as_user kwriteconfig6 --file kwinrc --group Plugins \
                --key "${KWIN_ID}Enabled" true 2>/dev/null || true
            as_user qdbus org.kde.KWin /KWin org.kde.KWin.reconfigure >/dev/null 2>&1 || true
            as_user qdbus org.kde.KWin /Scripting org.kde.kwin.Scripting.loadScript \
                "$dest/contents/code/main.js" "$KWIN_ID" >/dev/null 2>&1 || true
            note "= KWin script installed; log out/in if focus does not track"
            ;;
        *)
            note "! no GNOME/KDE session detected; skipping the focus watcher."
            note "  Re-run with --desktop gnome|kde once your desktop is up,"
            note "  or install it from your checkout: 'just install-focus-extension' / 'just install-focus-kwin'."
            ;;
    esac
}

remove_focus_watcher() {
    local ext="$HOME_DIR/.local/share/gnome-shell/extensions/$GNOME_UUID"
    local kw="$HOME_DIR/.local/share/kwin/scripts/$KWIN_ID"
    [ -d "$ext" ] && { note "- removing GNOME extension $GNOME_UUID"; rm -rf "$ext"; } || true
    [ -d "$kw" ] && { note "- removing KWin script $KWIN_ID"; rm -rf "$kw"; } || true
}

install_autostart() {
    [ "$AUTOSTART" -eq 1 ] || return 0
    [ -n "$APPIMAGE" ] || { note "! no AppImage path given; skipping autostart"; return 0; }
    local abs; abs="$(readlink -f "$APPIMAGE")"
    local dest="$HOME_DIR/.config/autostart/deckd.desktop"
    note "+ writing $dest"
    mkdir -p "$(dirname "$dest")"
    cat > "$dest" <<EOF
[Desktop Entry]
Type=Application
Name=deckd
Comment=App-aware touch control surface
Exec="$abs"
Terminal=false
X-GNOME-Autostart-enabled=true
EOF
    own "$dest" "$(dirname "$dest")"
    note "! autostart points at $abs; keep the AppImage there or re-run"
}

remove_autostart() {
    local dest="$HOME_DIR/.config/autostart/deckd.desktop"
    [ -f "$dest" ] && { note "- removing $dest"; rm -f "$dest"; } || true
}

# --- main ------------------------------------------------------------------

if [ "$UNINSTALL" -eq 1 ]; then
    echo "Uninstalling deckd system integration for $TARGET_USER"
    remove_autostart
    remove_focus_watcher
    remove_udev
    echo "Done. Log out and back in to apply the group change."
    exit 0
fi

resolve_assets
[ -d "$ASSETS_DIR" ] || die "assets dir not found: $ASSETS_DIR"

echo "Installing deckd system integration for $TARGET_USER"
install_focus_watcher
install_autostart
install_udev
echo
echo "Done."
echo "  - Run the AppImage (or log out/in for the autostart entry)."
echo "  - Log out and back in so the input-group change takes effect."
echo "  - Uninstall: sudo $0 --uninstall"
