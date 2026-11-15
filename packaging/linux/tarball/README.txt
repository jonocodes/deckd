deckd — app-aware touch control surface
=======================================

A self-contained build: no Python, Node, or checkout needed. deckd is a
daemon that serves a web surface; you use it from a browser on this machine
or a phone/tablet on your network.

Runs on any glibc 2.28+ distro: Debian 10+, Ubuntu 20.04+, RHEL/Alma/Rocky
8+, current Fedora and Arch. Not Alpine or other musl distros.

Install (once — installs to ~/.local/opt/deckd and starts it at login):

    sudo ./install-system-integration.sh
    # or, for a desktop password dialog: pkexec "$PWD/install-system-integration.sh"

That copies this directory to ~/.local/opt/deckd, installs the udev rule for
/dev/uinput (the one root step), the focus watcher for GNOME or KDE, an app-menu
entry, and a systemd user service (deckd.service). Afterwards you can delete
this directory.

Open it: pick "deckd" from your app menu (opens the surface in your browser),
or visit http://127.0.0.1:8765/. The password is in ~/.config/deckd/password.

Reach it from a phone: `systemctl --user edit deckd` and add an override
(upgrades rewrite deckd.service but leave this override alone):

    [Service]
    ExecStart=
    ExecStart=%h/.local/opt/deckd/bin/deckd --no-open --bind 0.0.0.0

then `systemctl --user restart deckd`. Only do this on a network you trust.

Upgrade: extract a newer tarball and run its install-system-integration.sh.
Uninstall: sudo ~/.local/opt/deckd/install-system-integration.sh --uninstall
Logs: journalctl --user -u deckd -f   (also ~/.local/share/deckd/deckd.log)

Try it without installing: ./bin/deckd   (localhost only; Ctrl-C to stop)

Docs: https://github.com/jonocodes/deckd/blob/main/docs/GUIDE.md
