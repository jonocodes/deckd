"""Tests for ``Server._is_deckd_window`` exact-match behaviour.

The function decides whether a focus event represents the deckd client
browser gaining focus -- when true, the server holds the current layout
instead of switching away. Two checks:
  1. the daemon's own port appears in the window title
  2. the title is exactly "deckd" (the client's ``<title>``)

The second check used to be ``"deckd" in title.lower()`` which
false-positived on any tab whose title merely contained "deckd" as a
substring (e.g. a GitHub tab for the deckd repo). These tests pin the
new exact-match contract.
"""
from __future__ import annotations

from dataclasses import dataclass

from deckd.platform import AppInfo


@dataclass
class _Stub:
    """Minimal stand-in for Server -- _is_deckd_window only reads self.port."""

    port: int


def _app(*, app_id: str | None = "firefox", title: str | None = None) -> AppInfo:
    """AppInfo with wm_class=None (matches the macOS backend's output
    shape). title / app_id defaults can be overridden per-test."""
    return AppInfo(app_id=app_id, wm_class=None, title=title)


def _is_deckd(server: _Stub, app: AppInfo) -> bool:
    # Late import so test collection doesn't require a fully wired Server.
    from deckd.server import Server

    return Server._is_deckd_window(server, app)


# ---------------------------------------------------------------------------
# Port-in-title branch
# ---------------------------------------------------------------------------


def test_port_in_title_holds() -> None:
    """A title carrying the daemon's own port (some browsers surface the
    URL in the title bar) holds -- the user is looking at the deckd
    client."""
    assert _is_deckd(_Stub(port=8765), _app(title="127.0.0.1:8765"))


def test_other_port_in_title_does_not_hold() -> None:
    """A different port in the title is a different app -- no hold."""
    assert not _is_deckd(
        _Stub(port=8765), _app(title="localhost:8080")
    )


def test_no_title_does_not_hold() -> None:
    """No title, no signal -- resolve the focus event normally."""
    assert not _is_deckd(_Stub(port=8765), _app(title=None))


# ---------------------------------------------------------------------------
# Exact-title branch (the regression magnet)
# ---------------------------------------------------------------------------


def test_exact_deckd_title_holds() -> None:
    """The deckd client's ``<title>deckd</title>`` is an exact match."""
    assert _is_deckd(_Stub(port=8765), _app(title="deckd"))


def test_exact_deckd_title_with_whitespace_holds() -> None:
    """Some terminals / window managers add surrounding whitespace;
    the implementation strips before comparing."""
    assert _is_deckd(
        _Stub(port=8765), _app(title="  deckd  ")
    )


def test_exact_deckd_case_insensitive() -> None:
    """Page titles can vary in case; lower() comparison covers that."""
    assert _is_deckd(_Stub(port=8765), _app(title="DECKD"))


def test_deckd_substring_does_not_hold() -> None:
    """Regression: a tab titled "deckd on GitHub" or "deckd-deckd/issues"
    must NOT hold -- the user is reading something else and the
    previous substring match falsely froze the layout."""
    assert not _is_deckd(
        _Stub(port=8765), _app(title="deckd on GitHub")
    )
    assert not _is_deckd(
        _Stub(port=8765), _app(title="jonocodes/deckd")
    )
    assert not _is_deckd(
        _Stub(port=8765), _app(title="deckded")
    )


def test_empty_title_does_not_hold() -> None:
    """An empty string is not the title 'deckd'."""
    assert not _is_deckd(_Stub(port=8765), _app(title=""))


# ---------------------------------------------------------------------------
# Port-zero edge case (server hasn't bound yet / explicit override)
# ---------------------------------------------------------------------------


def test_port_zero_disables_port_branch() -> None:
    """A non-positive port disables the port-in-title branch (the
    fallback in __main__ uses 0 when the server isn't bound yet). Only
    the exact-title branch can match."""
    assert not _is_deckd(_Stub(port=0), _app(title="1234"))
    # ... but the exact-title branch still works.
    assert _is_deckd(_Stub(port=0), _app(title="deckd"))
