"""Shared-password auth for remote deckd clients (issue #16).

Every client presents a single shared password (there is no source-address
exemption; see ``Server`` for the check). The password is stored in plaintext
at ``~/.config/deckd/password`` (mode ``0640``).

This module owns exactly one concern: producing that password value at
startup. It either reads a pre-existing file (refusing to start on
unreadable / over-permissive files) or generates one on first run and
logs it once at WARN. The comparison itself lives in ``Server`` so it
can stay next to the request-handling code.
"""
from __future__ import annotations

import logging
import os
import secrets
import stat
import string
from pathlib import Path

log = logging.getLogger("deckd.auth")

# 32 chars from ``[a-zA-Z0-9]`` — matches the issue and the operator's
# override recipe (``pwgen 32``). ~190 bits of entropy; plenty for a
# LAN-facing shared secret.
PASSWORD_ALPHABET = string.ascii_letters + string.digits
PASSWORD_LENGTH = 32

# The one blessed on-disk permission. A generated file gets exactly this;
# a pre-existing file may be this or stricter (e.g. 0600) but nothing more
# permissive — a group- or world-readable secret file is a misconfig we
# refuse to start on.
FILE_MODE = 0o640


class PasswordError(RuntimeError):
    """Raised when a pre-existing password file cannot be trusted or read,
    or a new one cannot be written. The daemon turns this into a refuse-to-
    start at the CLI boundary."""


def default_password_path() -> Path:
    """``$XDG_CONFIG_HOME/deckd/password`` (``~/.config`` fallback)."""
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base else Path.home() / ".config"
    return root / "deckd" / "password"


def generate_password() -> str:
    return "".join(secrets.choice(PASSWORD_ALPHABET) for _ in range(PASSWORD_LENGTH))


def load_or_create_password(path: Path) -> str:
    """Return the shared password, creating the file on first run.

    A pre-existing file is respected verbatim (stripped of trailing
    whitespace only). Raises ``PasswordError`` if it exists but is
    over-permissive, unreadable, or empty — the daemon must refuse to
    start rather than silently fall back to an unknown secret.
    """
    if path.exists():
        return _read_existing(path)
    return _create(path)


def _read_existing(path: Path) -> str:
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except OSError as exc:
        raise PasswordError(f"cannot stat password file {path}: {exc}") from exc

    # Reject anything more permissive than 0640. ``mode & ~FILE_MODE`` is
    # non-zero exactly when a bit outside owner-rw / group-r is set
    # (group-w, any world bit, execute) — i.e. a secret readable or
    # writable by someone it shouldn't be.
    if mode & ~FILE_MODE:
        raise PasswordError(
            f"password file {path} has insecure permissions {oct(mode)}; "
            f"expected {oct(FILE_MODE)} or stricter. Fix with: "
            f"chmod 640 {path}"
        )

    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PasswordError(f"cannot read password file {path}: {exc}") from exc

    value = raw.strip()
    if not value:
        raise PasswordError(f"password file {path} is empty")

    log.info("remote-auth password loaded from %s", path)
    return value


def _create(path: Path) -> str:
    password = generate_password()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # O_EXCL so we never clobber a file that appeared between the
        # exists() check and here; open with the target mode, then chmod
        # to defeat a permissive umask.
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, FILE_MODE)
        try:
            os.write(fd, (password + "\n").encode("utf-8"))
        finally:
            os.close(fd)
        os.chmod(path, FILE_MODE)
    except OSError as exc:
        raise PasswordError(f"cannot create password file {path}: {exc}") from exc

    log.info("generated remote-auth password file %s", path)
    log.warning(
        "\n"
        "==================================================================\n"
        "  deckd generated a remote-access password:\n"
        "\n"
        "      %s\n"
        "\n"
        "  SAVE THIS — it won't be shown again.\n"
        "  Stored (plaintext, mode 0640) at: %s\n"
        "  Local connections (127.0.0.1 / ::1) need no password.\n"
        "==================================================================",
        password,
        path,
    )
    return password
