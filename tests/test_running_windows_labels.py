"""Tests for the windows-list label/icon helpers (issues #120 / #126).

Seam under test: :func:`deckd.decks.label_for_window` and
:func:`deckd.decks.icon_for_window`. These are pure functions over
the deck store + a :class:`WindowInfo` — no daemon, no D-Bus, no
async. Tests assert:

* Matched deck's ``display_name`` wins on identity match.
* Matched deck's ``icon`` carries through; default-fallback returns
  ``None`` (decision 6 — honest absence, not a generic glyph).
* Title match wins over identity match (same precedence as
  :func:`resolve_deck`).
* Identity fallback chain: ``wm_class`` → ``gtk_application_id`` →
  ``sandboxed_app_id`` → ``title`` → ``"unknown"``.
* A deck reload (store swap) re-derives labels on the next call —
  no cache to invalidate.
"""
from __future__ import annotations

import pytest

from deckd.decks import (
    DeckStore,
    Deck,
    Widget,
    _humanize_identity,
    icon_for_window,
    label_for_window,
    load_decks,
)
from deckd.platform import WindowInfo


def _window(
    *,
    window_id: str = "win1",
    wm_class: str | None = "xterm",
    app_name: str | None = None,
    gtk_application_id: str | None = None,
    sandboxed_app_id: str | None = None,
    title: str | None = "bash",
    workspace: int | None = 0,
    minimized: bool = False,
) -> WindowInfo:
    return WindowInfo(
        window_id=window_id,
        wm_class=wm_class,
        app_name=app_name,
        gtk_application_id=gtk_application_id,
        sandboxed_app_id=sandboxed_app_id,
        title=title,
        workspace=workspace,
        minimized=minimized,
    )


def _deck_store_with(
    *decks: Deck,
) -> DeckStore:
    """Wrap a list of decks in a DeckStore, always including a default.

    ``label_for_window`` calls :func:`resolve_deck` which falls back
    to ``store.default()`` when nothing matches — so the store needs
    at least one deck whose ``match`` contains ``"default"`` for the
    fallback path to be reachable.

    ``load_decks`` populates ``Deck.id`` from ``match[0]``;
    bypassing it in tests means ids stay empty. Set them here so the
    "fall back to id when display_name is None" rule fires.
    """
    has_default = any("default" in l.match for l in decks)
    full: list[Deck] = []
    for deck in decks:
        if not deck.id and deck.match:
            deck.id = deck.match[0]
        full.append(deck)
    if not has_default:
        full.append(
            Deck(
                match=["default"],
                widgets=[Widget(id="noop", kind="blank")],
            )
        )
    return DeckStore(full, source_paths={})


def test_label_for_window_identity_match_uses_display_name() -> None:
    """A window whose ``wm_class`` matches a deck's match token gets
    that deck's ``display_name``. Pure title fallback (the chrome
    title text) is ignored — only the deck name rides."""
    store = _deck_store_with(
        Deck(
            match=["xterm"],
            display_name="Terminal",
            widgets=[Widget(id="noop", kind="blank")],
        )
    )
    win = _window(wm_class="xterm", title="bash")
    assert label_for_window(store, win) == "Terminal"


def test_label_for_window_identity_match_falls_back_to_deck_id() -> None:
    """A deck without ``display_name`` still yields a sensible label
    — the deck id is the canonical name when display_name is absent
    (matches how chrome-badged decks without a display_name work)."""
    store = _deck_store_with(
        Deck(
            match=["xterm"],
            widgets=[Widget(id="noop", kind="blank")],
        )
    )
    win = _window(wm_class="xterm")
    assert label_for_window(store, win) == "Xterm"


@pytest.mark.parametrize(
    ("identity", "expected"),
    [
        ("org.gnome.TextEditor", "Text Editor"),
        ("com.gexperts.Tilix", "Tilix"),
        ("VLC", "VLC"),
        ("VLCMediaPlayer", "VLC Media Player"),
        ("thunderbird", "Thunderbird"),
        ("firefox-esr", "Firefox Esr"),
        ("my_app", "My App"),
        # A trailing packaging suffix is not part of the app's name —
        # ``org.telegram.desktop`` labels ``Telegram``, not ``Desktop``.
        ("org.telegram.desktop", "Telegram"),
    ],
)
def test_humanize_identity(identity: str, expected: str) -> None:
    assert _humanize_identity(identity) == expected


def test_label_for_window_app_name_wins_over_identity_fallback() -> None:
    store = _deck_store_with(Deck(match=["firefox"], widgets=[Widget(id="noop", kind="blank")]))
    win = _window(wm_class="org.gnome.TextEditor", app_name="Text Editor")
    assert label_for_window(store, win) == "Text Editor"


def test_label_for_window_title_match_wins_over_identity() -> None:
    """A ``title:`` token matches beats a plain identity match — same
    precedence as ``resolve_deck``. Title matches are site-specific
    and the more specific signal."""
    store = _deck_store_with(
        Deck(
            match=["xterm"],
            display_name="Terminal",
            widgets=[Widget(id="noop", kind="blank")],
        ),
        Deck(
            match=["title:*YouTube*"],
            display_name="YouTube",
            widgets=[Widget(id="noop", kind="blank")],
        ),
    )
    win = _window(wm_class="xterm", title="YouTube — Watch")
    assert label_for_window(store, win) == "YouTube"


def test_label_for_window_default_fallback_returns_wm_class() -> None:
    """When no deck matches, the raw ``wm_class`` is the label —
    primary identity string the matcher compared against."""
    store = _deck_store_with(
        Deck(
            match=["firefox"],
            display_name="Firefox",
            widgets=[Widget(id="noop", kind="blank")],
        ),
    )
    win = _window(wm_class="xterm")
    assert label_for_window(store, win) == "Xterm"


def test_label_for_window_falls_back_to_gtk_app_id() -> None:
    """No ``wm_class`` but a ``gtk_application_id`` — the GTK id is the
    next fallback (matches the ``AppInfo`` precedence for resolution)."""
    store = _deck_store_with(
        Deck(
            match=["firefox"],
            display_name="Firefox",
            widgets=[Widget(id="noop", kind="blank")],
        ),
    )
    win = _window(wm_class=None, gtk_application_id="com.gexperts.Tilix")
    assert label_for_window(store, win) == "Tilix"


def test_label_for_window_falls_back_to_sandboxed_app_id() -> None:
    """Flatpak-style windows with a sandboxed app id but no GTK id —
    the sandboxed id is the third fallback. Mirrors ``AppInfo.app_id``
    precedence on the resolution path."""
    store = _deck_store_with(
        Deck(
            match=["firefox"],
            display_name="Firefox",
            widgets=[Widget(id="noop", kind="blank")],
        ),
    )
    win = _window(
        wm_class=None,
        gtk_application_id=None,
        sandboxed_app_id="org.flathub.Firefox",
    )
    assert label_for_window(store, win) == "Firefox"


def test_label_for_window_falls_back_to_title() -> None:
    """No identity strings at all — the title is the last resort before
    the ``"unknown"`` sentinel. Matches the decision-3 fallback chain
    (wm_class → app_id → title) the spec spells out for default-fallback
    rows."""
    store = _deck_store_with(
        Deck(
            match=["firefox"],
            display_name="Firefox",
            widgets=[Widget(id="noop", kind="blank")],
        ),
    )
    win = _window(wm_class=None, gtk_application_id=None, sandboxed_app_id=None, title="some-window")
    assert label_for_window(store, win) == "some-window"


def test_label_for_window_returns_unknown_when_all_blank() -> None:
    """All identity fields are ``None`` and the title is also ``None``
    — the function never raises; the sentinel string keeps the chrome
    list rendering something visible rather than an empty row."""
    store = _deck_store_with(
        Deck(
            match=["firefox"],
            display_name="Firefox",
            widgets=[Widget(id="noop", kind="blank")],
        ),
    )
    win = _window(wm_class=None, gtk_application_id=None, sandboxed_app_id=None, title=None)
    assert label_for_window(store, win) == "unknown"


def test_icon_for_window_carries_matched_deck_icon() -> None:
    """A matched deck's ``icon`` rides onto the row — Firefox window
    on a firefox deck with ``icon: simple-icons firefox`` → row
    icon is the Simple Icons Firefox glyph. Mirrors the chrome-badge
    icon relay rule (ADR-0006 / ADR-0007)."""
    store = _deck_store_with(
        Deck(
            match=["firefox"],
            display_name="Firefox",
            icon={"source": "simple-icons", "name": "firefox"},
            widgets=[Widget(id="noop", kind="blank")],
        ),
    )
    win = _window(wm_class="firefox")
    icon = icon_for_window(store, win)
    assert icon is not None
    assert icon.source == "simple-icons"
    assert icon.name == "firefox"


def test_row_matches_deck_when_enumeration_identity_differs_only_in_case() -> None:
    """A row whose enumeration identity differs only in case from the
    deck token (macOS ``Firefox`` vs the ``firefox`` token, #140) still
    carries the matched deck's ``display_name`` and ``icon`` — it used
    to drop to the default fallback (bare app name, no glyph)."""
    store = _deck_store_with(
        Deck(
            match=["firefox"],
            display_name="Firefox",
            icon={"source": "simple-icons", "name": "firefox"},
            widgets=[Widget(id="noop", kind="blank")],
        ),
    )
    win = _window(wm_class="Firefox", app_name="Firefox")
    assert label_for_window(store, win) == "Firefox"
    icon = icon_for_window(store, win)
    assert icon is not None
    assert (icon.source, icon.name) == ("simple-icons", "firefox")


def test_icon_for_window_returns_none_on_default_fallback() -> None:
    """Default-fallback row carries no icon — honest absence, not a
    decorative generic glyph (decision 6). Inventing a generic
    "terminal" Lucide icon for every xterm would imply every xterm is
    the same xterm; the list is per-window precisely so they're not."""
    store = _deck_store_with(
        Deck(
            match=["firefox"],
            display_name="Firefox",
            icon={"source": "simple-icons", "name": "firefox"},
            widgets=[Widget(id="noop", kind="blank")],
        ),
    )
    win = _window(wm_class="xterm")
    assert icon_for_window(store, win) is None


def test_label_for_window_re_derives_after_deck_reload(tmp_path) -> None:
    """A deck reload re-derives the label on the next call — no cache
    to invalidate (decision 5: "label per push, no cache"). A user
    editing their deck YAML gets a fresh label as soon as the
    daemon reloads."""
    store_path = tmp_path / "decks"
    store_path.mkdir()
    (store_path / "default.yaml").write_text(
        "match: [default]\nwidgets:\n  - id: x\n    kind: blank\n"
    )
    (store_path / "xterm.yaml").write_text(
        'match: [xterm]\ndisplay_name: Old Terminal\nwidgets:\n  - id: x\n    kind: blank\n'
    )
    store = load_decks(store_path)
    win = _window(wm_class="xterm")
    assert label_for_window(store, win) == "Old Terminal"

    # Reload: deck YAML now names the deck differently.
    (store_path / "xterm.yaml").write_text(
        'match: [xterm]\ndisplay_name: New Terminal\nwidgets:\n  - id: x\n    kind: blank\n'
    )
    store = load_decks(store_path)
    assert label_for_window(store, win) == "New Terminal"


def test_icon_for_window_re_derives_after_deck_reload(tmp_path) -> None:
    """Same reload semantics for icon — adding an icon to a previously
    iconless deck lights up the row on the next push, removing it
    goes back to ``None``."""
    store_path = tmp_path / "decks"
    store_path.mkdir()
    (store_path / "default.yaml").write_text(
        "match: [default]\nwidgets:\n  - id: x\n    kind: blank\n"
    )
    (store_path / "xterm.yaml").write_text(
        'match: [xterm]\nwidgets:\n  - id: x\n    kind: blank\n'
    )
    store = load_decks(store_path)
    win = _window(wm_class="xterm")
    assert icon_for_window(store, win) is None

    # Reload with an icon: the next call sees it.
    (store_path / "xterm.yaml").write_text(
        'match: [xterm]\n'
        'icon:\n'
        '  source: lucide\n'
        '  name: terminal\n'
        'widgets:\n  - id: x\n    kind: blank\n'
    )
    store = load_decks(store_path)
    icon = icon_for_window(store, win)
    assert icon is not None
    assert icon.source == "lucide"
    assert icon.name == "terminal"


@pytest.mark.parametrize(
    "kwargs,expected",
    [
        ({"wm_class": "firefox"}, "Firefox"),  # identity match wins
        ({"wm_class": "unknown-app"}, "Unknown App"),  # default fallback
        ({"title": "YouTube — Watch", "wm_class": "firefox"}, "Firefox"),  # identity vs no-title deck
    ],
)
def test_label_for_window_parametrized(kwargs, expected) -> None:
    """Spot-check the precedence on a few common shapes — keeps the
    helper's behaviour pinned for the daemon integration test to lean
    on without re-deriving every rule."""
    store = _deck_store_with(
        Deck(
            match=["firefox"],
            display_name="Firefox",
            widgets=[Widget(id="noop", kind="blank")],
        ),
    )
    win = _window(**kwargs)
    assert label_for_window(store, win) == expected
