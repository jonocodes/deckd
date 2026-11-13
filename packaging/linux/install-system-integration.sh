#!/usr/bin/env bash
# deckd Linux system integration (issues #168, #173).
#
# Neither the AppImage nor the tarball can write /etc/udev/rules.d — that is a
# root action on every channel. This script does the root step (the udev rule)
# *and* the user-level pieces (the desktop focus watcher, the app icon, an
# app-menu entry, and autostart), so one elevated run finishes the install.
#
# On a desktop, run it with `pkexec` for the native password dialog; on a
# headless/SSH box, use `sudo`:
#
#   pkexec ./install-system-integration.sh ./deckd-<version>-x86_64.AppImage
#   sudo   ./install-system-integration.sh ./deckd-<version>-x86_64.AppImage
#
# The tarball carries a copy of this script at its top level; run it from
# there with no arguments and it installs the extracted tree it sits in:
#
#   sudo ./deckd-<version>-x86_64/install-system-integration.sh
#
# Tarball install: the tree is copied to ~/.local/opt/deckd (a stable path, so
# moving or deleting the download breaks nothing; re-running with a newer
# tarball upgrades it) and autostart is a systemd *user* service. AppImage
# install: the AppImage stays where it is and autostart is an XDG entry.
#
# On NixOS, pkexec's sanitised PATH has no system profile: use `sudo`, or
# `pkexec /run/current-system/sw/bin/bash ./install-system-integration.sh ...`.
#
# The udev rule carries TAG+="uaccess", so the *active* session user gets an
# ACL on /dev/uinput and the autostart case needs no relogin. `--add-group`
# additionally adds the user to the `input` group for linger/headless setups
# (that one does need a logout).
#
# It reads its assets from an *extracted* AppImage layout:
#
#   <assets>/70-deckd-uinput.rules
#   <assets>/deckd.png
#   <assets>/gnome-shell/deckd-focus@local/...
#   <assets>/kwin-script/deckd-focus/...
#
# which the AppImage ships under usr/share/deckd/integration. Point it at an
# AppImage and it extracts them; or pass --assets DIR for a pre-extracted tree
# (`just install-system-integration` stages one from a checkout). If the
# AppImage runtime ignores `--appimage-extract` (a binfmt wrapper such as
# NixOS's `programs.appimage` runs the payload directly), it falls back to the
# bundled launcher's `--extract-integration`.
#
# Usage:
#   pkexec ./install-system-integration.sh ./deckd-<version>-x86_64.AppImage
#   sudo   ./install-system-integration.sh ./deckd-<version>-x86_64.AppImage
#   sudo   ./install-system-integration.sh ./deckd-<version>-x86_64   (tarball dir)
#   sudo   ./install-system-integration.sh --assets /path/to/integration
#   sudo   ./install-system-integration.sh --uninstall
#
# Options:
#   --appimage PATH   AppImage to extract assets from, autostart, and add to
#                     the app menu
#   --tree DIR        Extracted tarball (bin/deckd + share/deckd/integration) to
#                     install to ~/.local/opt/deckd. Default when this script
#                     sits at the top of such a tree and nothing else is given.
#   --assets DIR      Use a pre-extracted integration tree instead of an AppImage
#   --user NAME       Target user (default: $SUDO_USER / $PKEXEC_UID, else the
#                     login user)
#   --desktop MODE    auto|gnome|kde|none  (default auto) — focus watcher to install
#   --no-autostart    Do not start deckd with the session (no XDG autostart
#                     entry / systemd user service)
#   --no-menu         Do not write ~/.local/share/applications/deckd.desktop
#   --add-group       Also add the user to the `input` group (for linger /
#                     headless setups; needs a logout). Default: rely on the
#                     rule's uaccess ACL for the active session.
#   --uninstall       Remove what this helper installed (recorded in
#                     /var/lib/deckd/system-integration.<user>.state): the udev
#                     rule, the focus watcher, the app icon, the menu entry,
#                     the autostart entry or user service, the installed
#                     tree, and the user's `input` membership — each only if
#                     this helper created it, so a NixOS/home-manager install
#                     isn't disturbed.
#   -h, --help
#
# Re-running install is safe: assets are replaced, not appended.
#
# Testing: DECKD_HELPER_TEST_ROOT=DIR runs without root against a sandbox —
# system paths live under DIR, the user's home is DIR/home, nothing is chown'd,
# and user commands run as the caller. sudo and pkexec scrub the environment,
# so a real elevated run never sees it (tests/test_install_helper.py).

set -euo pipefail

# pkexec resets PATH to the distro default; NixOS keeps its tools in the
# system profile instead. Append it when present (a no-op elsewhere, and it
# never shadows the caller's PATH) so an explicitly-interpreted
# `pkexec /run/current-system/sw/bin/bash helper ...` still finds udevadm,
# usermod, grep, ...
if [ -d /run/current-system/sw/bin ]; then
    PATH="$PATH:/run/current-system/sw/bin"
    export PATH
fi

TEST_ROOT="${DECKD_HELPER_TEST_ROOT:-}"
UDEV_DEST="$TEST_ROOT/etc/udev/rules.d/70-deckd-uinput.rules"
STATE_DIR="$TEST_ROOT/var/lib/deckd"
GNOME_UUID="deckd-focus@local"
KWIN_ID="deckd-focus"
SELF_DIR="$(cd "$(dirname "$0")" && pwd)"

die() { echo "error: $*" >&2; exit 1; }
note() { echo "  $*"; }

usage() {
    awk 'NR>1 && /^#/ {sub(/^# ?/, ""); print; next} NR>1 {exit}' "$0"
    exit "${1:-0}"
}

APPIMAGE=""
TREE=""
ASSETS=""
ASSETS_DIR=""
EXEC=""
TARGET_USER=""
DESKTOP="auto"
AUTOSTART=1
MENU=1
ADD_GROUP=0
UNINSTALL=0

while [ $# -gt 0 ]; do
    case "$1" in
        --appimage) APPIMAGE="${2:?--appimage needs a path}"; shift 2 ;;
        --tree)     TREE="${2:?--tree needs a path}"; shift 2 ;;
        --assets)   ASSETS="${2:?--assets needs a path}"; shift 2 ;;
        --user)     TARGET_USER="${2:?--user needs a name}"; shift 2 ;;
        --desktop)  DESKTOP="${2:?--desktop needs a mode}"; shift 2 ;;
        --no-autostart) AUTOSTART=0; shift ;;
        --no-menu) MENU=0; shift ;;
        --add-group) ADD_GROUP=1; shift ;;
        --uninstall) UNINSTALL=1; shift ;;
        -h|--help) usage 0 ;;
        -*) die "unknown option: $1" ;;
        # bare arg: an extracted tarball dir, or the AppImage
        *) if [ -d "$1" ]; then TREE="$1"; else APPIMAGE="$1"; fi; shift ;;
    esac
done

is_tree() { [ -x "$1/bin/deckd" ] && [ -d "$1/share/deckd/integration" ]; }

# Run from the top of an extracted tarball with nothing else to go on: install
# the tree this script sits in.
if [ "$UNINSTALL" -eq 0 ] && [ -z "$TREE$APPIMAGE$ASSETS" ] && is_tree "$SELF_DIR"; then
    TREE="$SELF_DIR"
fi
if [ -n "$TREE" ]; then
    is_tree "$TREE" || die "not a deckd tree (no bin/deckd + share/deckd/integration): $TREE"
    [ -z "$APPIMAGE" ] || die "pass either a tarball tree or an AppImage, not both"
    TREE="$(cd "$TREE" && pwd)"
fi

[ -n "$TEST_ROOT" ] || [ "$(id -u)" -eq 0 ] \
    || die "must run as root: sudo $0 ... (or pkexec $0 ...)"

# How we were elevated, for copy-pasteable follow-up commands. pkexec sets
# PKEXEC_UID; sudo sets SUDO_USER. Neither means a plain root shell.
if [ -n "${PKEXEC_UID:-}" ]; then
    ELEVATE="pkexec"
else
    ELEVATE="sudo"
fi

# The user the desktop belongs to. pkexec reports their uid in PKEXEC_UID;
# sudo in SUDO_USER; otherwise fall back to the owner of the invoking terminal.
if [ -z "$TARGET_USER" ]; then
    if [ -n "${PKEXEC_UID:-}" ]; then
        TARGET_USER="$(getent passwd "$PKEXEC_UID" | cut -d: -f1)"
    else
        TARGET_USER="${SUDO_USER:-$(logname 2>/dev/null || echo "${USER:-}")}"
    fi
fi
[ -n "$TARGET_USER" ] && [ "$TARGET_USER" != "root" ] \
    || die "could not determine the target user; pass --user NAME"
id "$TARGET_USER" >/dev/null 2>&1 || die "no such user: $TARGET_USER"
if [ -n "$TEST_ROOT" ]; then
    HOME_DIR="$TEST_ROOT/home"
else
    HOME_DIR="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
fi
PRIMARY_GROUP="$(id -gn "$TARGET_USER")"
[ -n "$HOME_DIR" ] || die "could not resolve home for $TARGET_USER"
TARGET_UID="$(id -u "$TARGET_USER")"
INSTALL_DIR="$HOME_DIR/.local/opt/deckd"
UNIT_DIR="$HOME_DIR/.config/systemd/user"

# Per-user record of what this helper installed (see "install state" below).
STATE_FILE="$STATE_DIR/system-integration.$TARGET_USER.state"

# Run a command as the target user, with their home. sudo is the common case;
# runuser (util-linux) is the fallback on systems without sudo.
as_user() {
    if [ -n "$TEST_ROOT" ]; then
        env HOME="$HOME_DIR" "$@"
    elif command -v sudo >/dev/null 2>&1; then
        sudo -u "$TARGET_USER" -H -- "$@"
    elif command -v runuser >/dev/null 2>&1; then
        runuser -u "$TARGET_USER" -- env HOME="$HOME_DIR" "$@"
    else
        return 127
    fi
}

# chown a path (and its contents) to the target user.
own() { [ -n "$TEST_ROOT" ] || chown -R "$TARGET_USER:$PRIMARY_GROUP" "$@"; }

# `systemctl --user` for the target user. Reaching their user manager from a
# root shell needs their runtime dir (where the manager's bus lives).
user_systemctl() {
    as_user env XDG_RUNTIME_DIR="/run/user/$TARGET_UID" systemctl --user "$@"
}

# --- install state ---------------------------------------------------------
#
# What a previous run changed, so --uninstall undoes only our own work: a
# machine that already had the input group (NixOS/home-manager) or the GNOME
# extension (a source install) must not lose them.

S_UDEV=0
S_GROUP=0
S_GNOME=0
S_KDE=0
S_ICON=0
S_AUTOSTART=0
S_MENU=0
S_SERVICE=0
S_TREE=0

state_get() {
    [ -f "$STATE_FILE" ] || return 0
    sed -n "s/^$1=//p" "$STATE_FILE" | tail -n1
}

load_state() {
    local v
    v="$(state_get udev)";      [ -n "$v" ] && S_UDEV="$v"
    v="$(state_get group)";     [ -n "$v" ] && S_GROUP="$v"
    v="$(state_get gnome)";     [ -n "$v" ] && S_GNOME="$v"
    v="$(state_get kde)";       [ -n "$v" ] && S_KDE="$v"
    v="$(state_get icon)";      [ -n "$v" ] && S_ICON="$v"
    v="$(state_get autostart)"; [ -n "$v" ] && S_AUTOSTART="$v"
    v="$(state_get menu)";      [ -n "$v" ] && S_MENU="$v"
    v="$(state_get service)";   [ -n "$v" ] && S_SERVICE="$v"
    v="$(state_get tree)";      [ -n "$v" ] && S_TREE="$v"
    return 0
}

write_state() {
    mkdir -p "$STATE_DIR"
    cat > "$STATE_FILE" <<EOF
udev=$S_UDEV
group=$S_GROUP
gnome=$S_GNOME
kde=$S_KDE
icon=$S_ICON
autostart=$S_AUTOSTART
menu=$S_MENU
service=$S_SERVICE
tree=$S_TREE
EOF
    chmod 0644 "$STATE_FILE"
}

# --- assets ----------------------------------------------------------------

extract_dir=""
cleanup() {
    # Must return 0: a failing EXIT trap under `set -e` makes the whole
    # helper exit non-zero even after a successful install (--assets leaves
    # extract_dir empty).
    if [ -n "$extract_dir" ]; then
        rm -rf "$extract_dir"
    fi
}
trap cleanup EXIT

# Set ASSETS_DIR in the current shell (not a command substitution) so the
# mktemp cleanup trap below still owns extract_dir.
resolve_assets() {
    if [ -n "$ASSETS" ]; then
        ASSETS_DIR="$ASSETS"; return
    fi
    if [ -n "$TREE" ]; then
        ASSETS_DIR="$TREE/share/deckd/integration"; return
    fi
    [ -n "$APPIMAGE" ] || die "pass an AppImage, an extracted tarball dir, or --assets DIR"
    [ -x "$APPIMAGE" ] || die "AppImage not executable: $APPIMAGE"
    extract_dir="$(mktemp -d)"
    # Preferred: ask the AppImage's own runtime to unpack the integration tree.
    if ( cd "$extract_dir" && "$APPIMAGE" --appimage-extract 'usr/share/deckd/integration/*' >/dev/null 2>&1 ) \
        && [ -d "$extract_dir/squashfs-root/usr/share/deckd/integration" ]; then
        ASSETS_DIR="$extract_dir/squashfs-root/usr/share/deckd/integration"
        return
    fi
    # Some systems intercept AppImages before their runtime sees the flags
    # (NixOS's `programs.appimage` binfmt wrapper, for one), so the extraction
    # above is ignored and the payload runs instead. The frozen launcher can
    # copy the assets out of its own AppDir either way.
    rm -rf "$extract_dir"; extract_dir="$(mktemp -d)"
    "$APPIMAGE" --extract-integration "$extract_dir" >/dev/null 2>&1 \
        || die "could not extract integration assets from $APPIMAGE"
    [ -f "$extract_dir/70-deckd-uinput.rules" ] \
        || die "no integration assets found in $APPIMAGE"
    ASSETS_DIR="$extract_dir"
}

# --- steps -----------------------------------------------------------------

install_udev() {
    [ -f "$ASSETS_DIR/70-deckd-uinput.rules" ] || die "assets missing the udev rule"
    note "+ installing $UDEV_DEST"
    mkdir -p "$(dirname "$UDEV_DEST")"
    install -m 0644 "$ASSETS_DIR/70-deckd-uinput.rules" "$UDEV_DEST"
    S_UDEV=1
    if command -v udevadm >/dev/null 2>&1; then
        udevadm control --reload-rules
        udevadm trigger --subsystem-match=misc --sysname-match=uinput
    else
        note "udevadm not found; reboot for the rule to take effect"
    fi

    local in_group=0
    id -nG "$TARGET_USER" | tr ' ' '\n' | grep -qx input && in_group=1

    if [ "$ADD_GROUP" -eq 1 ] && [ "$in_group" -eq 0 ]; then
        note "+ adding $TARGET_USER to the input group (--add-group)"
        usermod -aG input "$TARGET_USER"
        S_GROUP=1
        note "! log out and back in for the group change to apply"
    elif [ "$in_group" -eq 1 ]; then
        note "= $TARGET_USER is already in the input group"
        # Keep a previous run's record so --uninstall still removes it.
        [ "$S_GROUP" = 1 ] || S_GROUP=0
    else
        note "= /dev/uinput access comes from the rule's uaccess ACL for the"
        note "  active session — no relogin needed. --add-group covers"
        note "  linger/headless setups (that one needs a logout)."
    fi
}

remove_udev_rule() {
    if [ -f "$UDEV_DEST" ]; then
        note "- removing $UDEV_DEST"
        rm -f "$UDEV_DEST"
        command -v udevadm >/dev/null 2>&1 && udevadm control --reload-rules || true
    fi
}

remove_input_group() {
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
            S_GNOME=1
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
            S_KDE=1
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

remove_gnome_extension() {
    local ext="$HOME_DIR/.local/share/gnome-shell/extensions/$GNOME_UUID"
    [ -d "$ext" ] && { note "- removing GNOME extension $GNOME_UUID"; rm -rf "$ext"; } || true
}

remove_kwin_script() {
    local kw="$HOME_DIR/.local/share/kwin/scripts/$KWIN_ID"
    [ -d "$kw" ] && { note "- removing KWin script $KWIN_ID"; rm -rf "$kw"; } || true
}

install_icon() {
    [ -f "$ASSETS_DIR/deckd.png" ] || { note "! no icon in assets; skipping"; return 0; }
    local dest="$HOME_DIR/.local/share/icons/hicolor/512x512/apps/deckd.png"
    note "+ installing app icon $dest"
    mkdir -p "$(dirname "$dest")"
    cp "$ASSETS_DIR/deckd.png" "$dest"
    S_ICON=1
    own "$(dirname "$dest")"
}

remove_icon() {
    local dest="$HOME_DIR/.local/share/icons/hicolor/512x512/apps/deckd.png"
    [ -f "$dest" ] && { note "- removing app icon $dest"; rm -f "$dest"; } || true
}

# Copy an extracted tarball to a stable per-user path. The service, menu entry
# and uninstall all point at the installed copy, so the download can be moved
# or deleted. Re-running with a newer tarball swaps the tree in place.
install_tree() {
    [ -n "$TREE" ] || return 0
    if [ "$TREE" = "$INSTALL_DIR" ]; then
        note "= running from $INSTALL_DIR; keeping the installed tree"
    else
        note "+ installing deckd to $INSTALL_DIR"
        mkdir -p "$(dirname "$INSTALL_DIR")"
        rm -rf "$INSTALL_DIR.new"
        cp -R "$TREE" "$INSTALL_DIR.new"
        rm -rf "$INSTALL_DIR"
        mv "$INSTALL_DIR.new" "$INSTALL_DIR"
        own "$INSTALL_DIR"
    fi
    S_TREE=1
}

remove_tree() {
    [ -d "$INSTALL_DIR" ] && { note "- removing $INSTALL_DIR"; rm -rf "$INSTALL_DIR"; } || true
}

# What the menu entry and autostart launch.
resolve_exec() {
    if [ -n "$TREE" ]; then
        EXEC="$INSTALL_DIR/bin/deckd"
    elif [ -n "$APPIMAGE" ]; then
        EXEC="$(readlink -f "$APPIMAGE")"
    fi
}

# AppImage autostart: an XDG entry (the AppImage has no fixed install path to
# hang a unit on, and stays wherever the user keeps it).
install_xdg_autostart() {
    local dest="$HOME_DIR/.config/autostart/deckd.desktop"
    note "+ writing $dest"
    mkdir -p "$(dirname "$dest")"
    cat > "$dest" <<EOF
[Desktop Entry]
Type=Application
Name=deckd
Comment=App-aware touch control surface
Icon=deckd
Exec="$EXEC" --no-open
Terminal=false
X-GNOME-Autostart-enabled=true
EOF
    own "$dest" "$(dirname "$dest")"
    S_AUTOSTART=1
    note "! autostart points at $EXEC; keep the AppImage there or re-run"
}

remove_autostart() {
    local dest="$HOME_DIR/.config/autostart/deckd.desktop"
    [ -f "$dest" ] && { note "- removing $dest"; rm -f "$dest"; } || true
}

# Tarball autostart: a systemd user service, ordered on the graphical session
# and restarted on failure. Enabled by writing the wants/ link directly (what
# `systemctl --user enable` does), so it works even when the user manager
# can't be reached from here; then started now if it can.
install_service() {
    local unit="$UNIT_DIR/deckd.service"
    local wants="$UNIT_DIR/graphical-session.target.wants"
    note "+ writing $unit"
    mkdir -p "$wants"
    cat > "$unit" <<EOF
# Installed by deckd's install-system-integration.sh. Re-run it to update;
# '--uninstall' removes it. --no-open: starting at login never opens a browser.
[Unit]
Description=deckd — app-aware touch control surface
After=graphical-session.target
PartOf=graphical-session.target

[Service]
Type=simple
ExecStart="$EXEC" --no-open
Restart=on-failure
RestartSec=2

[Install]
WantedBy=graphical-session.target
EOF
    ln -sfn ../deckd.service "$wants/deckd.service"
    own "$HOME_DIR/.config/systemd"
    S_SERVICE=1
    # restart, not start: an upgrade must pick up the new tree.
    if user_systemctl daemon-reload >/dev/null 2>&1 \
        && user_systemctl restart deckd.service >/dev/null 2>&1; then
        note "= deckd.service started (logs: journalctl --user -u deckd -f)"
    else
        note "! could not reach your user session; deckd.service starts at next login"
    fi
}

remove_service() {
    local unit="$UNIT_DIR/deckd.service"
    [ -f "$unit" ] || return 0
    user_systemctl stop deckd.service >/dev/null 2>&1 || true
    note "- removing $unit"
    rm -f "$unit" "$UNIT_DIR/graphical-session.target.wants/deckd.service"
    user_systemctl daemon-reload >/dev/null 2>&1 || true
}

install_autostart() {
    [ "$AUTOSTART" -eq 1 ] || return 0
    [ -n "$EXEC" ] || { note "! no AppImage or tarball given; skipping autostart"; return 0; }
    # One autostart mechanism at a time: switching channels must not leave
    # the other one racing for the port at login.
    if [ -n "$TREE" ]; then
        [ "$S_AUTOSTART" = 1 ] && { remove_autostart; S_AUTOSTART=0; }
        install_service
    else
        [ "$S_SERVICE" = 1 ] && { remove_service; S_SERVICE=0; }
        install_xdg_autostart
    fi
}

install_menu_entry() {
    [ "$MENU" -eq 1 ] || return 0
    [ -n "$EXEC" ] || { note "! no AppImage or tarball given; skipping app-menu entry"; return 0; }
    local dest="$HOME_DIR/.local/share/applications/deckd.desktop"
    note "+ writing $dest"
    mkdir -p "$(dirname "$dest")"
    # --open: clicking it opens the surface in the browser, starting the
    # daemon first if it isn't already running.
    cat > "$dest" <<EOF
[Desktop Entry]
Type=Application
Name=deckd
Comment=App-aware touch control surface
Icon=deckd
Exec="$EXEC" --open
Terminal=false
Categories=Utility;
EOF
    own "$dest" "$(dirname "$dest")"
    S_MENU=1
}

remove_menu_entry() {
    local dest="$HOME_DIR/.local/share/applications/deckd.desktop"
    [ -f "$dest" ] && { note "- removing $dest"; rm -f "$dest"; } || true
}

# --- main ------------------------------------------------------------------

if [ "$UNINSTALL" -eq 1 ]; then
    echo "Uninstalling deckd system integration for $TARGET_USER"
    if [ ! -f "$STATE_FILE" ]; then
        echo "  no install recorded by this helper ($STATE_FILE is missing)."
        echo "  Nothing to remove."
        exit 0
    fi
    load_state
    # Stop the service before its tree goes away.
    [ "$S_SERVICE" = 1 ] && remove_service || true
    [ "$S_AUTOSTART" = 1 ] && remove_autostart || true
    [ "$S_MENU" = 1 ] && remove_menu_entry || true
    [ "$S_TREE" = 1 ] && remove_tree || true
    [ "$S_GNOME" = 1 ] && remove_gnome_extension || true
    [ "$S_KDE" = 1 ] && remove_kwin_script || true
    [ "$S_ICON" = 1 ] && remove_icon || true
    [ "$S_UDEV" = 1 ] && remove_udev_rule || true
    [ "$S_GROUP" = 1 ] && remove_input_group || true
    rm -f "$STATE_FILE"
    rmdir "$STATE_DIR" 2>/dev/null || true
    if [ "$S_GROUP" = 1 ]; then
        echo "Done. Log out and back in to apply the group change."
    else
        echo "Done."
    fi
    exit 0
fi

load_state
resolve_assets
[ -d "$ASSETS_DIR" ] || die "assets dir not found: $ASSETS_DIR"
resolve_exec

echo "Installing deckd system integration for $TARGET_USER"
install_tree
install_focus_watcher
install_icon
# Before autostart: a service started without the rule would fall back to
# logging-only input until its next restart.
install_udev
install_menu_entry
install_autostart
write_state
echo
echo "Done."
echo "  - Open deckd from the app menu (it opens the surface in your browser)."
if [ "$S_GROUP" = 1 ]; then
    echo "  - Log out and back in so the input-group change takes effect."
fi
if [ -n "$TREE" ]; then
    echo "  - Upgrade: re-run this with a newer tarball."
    echo "  - Uninstall: $ELEVATE $INSTALL_DIR/install-system-integration.sh --uninstall"
else
    echo "  - Uninstall: $ELEVATE $0 --uninstall"
fi
