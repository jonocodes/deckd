"""Tests for the shared-password store (issue #16, daemon/deckd/auth.py)."""
from __future__ import annotations

import os
import stat
import string
from pathlib import Path

import pytest

from deckd import auth


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


# ---------------------------------------------------------------------------
# Generation on first start
# ---------------------------------------------------------------------------


def test_generates_password_file_when_absent(tmp_path: Path) -> None:
    path = tmp_path / "deckd" / "password"
    pw = auth.load_or_create_password(path)

    assert path.is_file()
    assert _mode(path) == 0o640
    # 32 chars from [a-zA-Z0-9], and what we return matches the file.
    assert len(pw) == auth.PASSWORD_LENGTH
    assert all(c in (string.ascii_letters + string.digits) for c in pw)
    assert path.read_text(encoding="utf-8").strip() == pw


def test_generated_password_is_logged_once_at_warning(tmp_path: Path, caplog) -> None:
    path = tmp_path / "password"
    with caplog.at_level("INFO", logger="deckd.auth"):
        pw = auth.load_or_create_password(path)

    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert len(warnings) == 1
    text = warnings[0].getMessage()
    assert pw in text
    assert "won't be shown again" in text


def test_generated_passwords_are_random(tmp_path: Path) -> None:
    a = auth.load_or_create_password(tmp_path / "a")
    b = auth.load_or_create_password(tmp_path / "b")
    assert a != b


# ---------------------------------------------------------------------------
# Pre-existing file is respected verbatim
# ---------------------------------------------------------------------------


def test_preexisting_password_respected_verbatim(tmp_path: Path) -> None:
    path = tmp_path / "password"
    path.write_text("hunter2trailing-newline-stripped\n", encoding="utf-8")
    os.chmod(path, 0o640)

    assert auth.load_or_create_password(path) == "hunter2trailing-newline-stripped"


def test_preexisting_stricter_perms_allowed(tmp_path: Path) -> None:
    """0600 is stricter than 0640 — accepted, not rejected."""
    path = tmp_path / "password"
    path.write_text("secret\n", encoding="utf-8")
    os.chmod(path, 0o600)

    assert auth.load_or_create_password(path) == "secret"


# ---------------------------------------------------------------------------
# Refuse to start on bad files
# ---------------------------------------------------------------------------


def test_refuses_overpermissive_file(tmp_path: Path) -> None:
    path = tmp_path / "password"
    path.write_text("secret\n", encoding="utf-8")
    os.chmod(path, 0o644)  # world-readable

    with pytest.raises(auth.PasswordError) as exc:
        auth.load_or_create_password(path)
    assert str(path) in str(exc.value)
    assert "0o644" in str(exc.value) or "644" in str(exc.value)


def test_refuses_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "password"
    path.write_text("\n", encoding="utf-8")
    os.chmod(path, 0o640)

    with pytest.raises(auth.PasswordError):
        auth.load_or_create_password(path)


@pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0,
    reason="root bypasses file read permissions",
)
def test_refuses_unreadable_file(tmp_path: Path) -> None:
    path = tmp_path / "password"
    path.write_text("secret\n", encoding="utf-8")
    os.chmod(path, 0o000)  # correct-enough perms bits, but we can't read it

    with pytest.raises(auth.PasswordError) as exc:
        auth.load_or_create_password(path)
    assert "read" in str(exc.value).lower() or "permission" in str(exc.value).lower()
