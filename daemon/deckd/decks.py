from __future__ import annotations

import fnmatch
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Literal

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from .platform import AppInfo, WindowInfo

# Literal alias for the ``nowplaying`` widget's ``empty_state`` knob
# (issue #50). Defined here so the daemon's ``Widget`` model — the one
# YAML flows through — has a single source of truth;
# :class:`deckd.mpris.NowPlaying` imports the same name so the
# dedicated schema can't drift. ``ordering`` was removed in issue #58:
# rows now reflect the session bus's ``ListNames`` order (matching GNOME
# Shell) with no per-deck knob.
NowPlayingEmptyState = Literal["show", "hide"]

log = logging.getLogger("deckd.decks")


class Icon(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # ``source`` selects a client-side renderer (e.g. "lucide",
    # "simple-icons"); ``name`` is looked up within it. The daemon relays
    # both opaquely (ADR-0006): it validates only that they are non-empty
    # strings and never enumerates the valid sources -- that registry lives
    # in the client, which renders a visible placeholder for an unknown
    # source rather than failing to load.
    source: str = Field(min_length=1)
    name: str = Field(min_length=1)


class MetricSpec(BaseModel):
    """One data point in a ``stats`` widget (issue #40).

    ``source`` names a daemon-side :class:`SensorSource` (same registry
    the single-value ``meter`` widget binds to). ``label`` is the short
    caption shown beside the value; when omitted the client derives one
    from the source name (``cpu_percent`` -> ``CPU``), so a minimal
    ``metrics: [{source: cpu_percent}]`` still reads sensibly. Kept a
    distinct model (rather than a bare string) so more per-metric knobs
    (unit override, min/max, colour) can be added without a breaking
    schema change.
    """

    model_config = ConfigDict(extra="forbid")

    source: str = Field(min_length=1)
    label: str | None = None


MediaControl = Literal["play", "previous", "next", "volume", "position", "speed"]

MacroStepType = Literal["key", "shell", "dbus", "delay", "url", "text"]


class MacroStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: MacroStepType
    value: str = Field(min_length=1)


class Macro(BaseModel):
    model_config = ConfigDict(extra="forbid")

    steps: list[MacroStep] = Field(min_length=1)
    continue_on_error: bool = False


class MediaHttp(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host: str = "127.0.0.1"
    port: int = Field(default=8080, ge=1, le=65535)
    password_ref: str | None = Field(default=None, min_length=1)


class Widget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: str
    label: str | None = None
    icon: Icon | None = None
    # Reflow extent (ADR-0010). ``[w, h]`` is a column/row span; the literal
    # ``"full"`` opts the widget out of the flow to take the whole surface.
    # There is no position — widgets pack in list order, left-to-right,
    # wrapping down against a client-side cell-size band. Absent means a
    # ``[1, 1]`` single cell. The old ``grid: [x, y, w, h]`` coordinate field
    # is gone; migrate by dropping ``x, y`` and keeping ``w, h`` as ``size``.
    size: list[int] | Literal["full"] | None = None
    # Optional CSS colour string applied as the button's background. Any
    # value the browser accepts is fine ("#1e3a8a", "rebeccapurple",
    # "hsl(...)"). Client trust: decks are user-owned config, not user
    # input, so no sanitisation is needed.
    color: str | None = None
    action: "Action | None" = None
    macro: "Macro | None" = None
    # ``meter`` widgets bind to a daemon-side :class:`SensorSource` by
    # name (e.g. ``cpu_percent``). The daemon pushes ``WidgetUpdateMessage``
    # frames for every meter widget in the active deck whose source
    # has live readings. ``min`` / ``max`` define the bar's visible
    # range; values outside the range clamp at the ends so a runaway
    # sensor paints the bar at full red rather than overflowing.
    # ``min``/``max`` default to a CPU-friendly 0..100 %; decks with
    # non-thermal sensors should override.
    source: str | None = None
    min: float | None = None
    max: float | None = None
    # ``stats`` widgets bind to several sensor sources at once and render
    # a compact, bar-less list of "label: value" rows. Each metric names a
    # source the same way a ``meter`` names its single ``source``; the
    # daemon subscribes to every referenced source while a stats widget is
    # in the active deck, exactly as it does for meters.
    metrics: list[MetricSpec] | None = None
    controls: list[MediaControl] | None = None
    media_http: MediaHttp | None = None
    # Ordered art sources for a media widget. ``vlc`` uses VLC's own art
    # (embedded / its cache); ``itunes`` falls back to an online cover-art
    # lookup (sends the track's artist/album/title to Apple's public search
    # API). Defaults to VLC-only; add ``itunes`` to opt into online art.
    art_source: list[str] | None = None
    previous_action: "Action | None" = None
    next_action: "Action | None" = None
    volume_up_action: "Action | None" = None
    volume_down_action: "Action | None" = None
    # ``nowplaying`` widgets (issue #50) take one knob documented on
    # :class:`deckd.mpris.NowPlaying`: whether the cell still renders
    # an empty placeholder when no player is discovered (``empty_state``).
    # Row order follows the session bus's ``ListNames`` reply — no
    # per-deck knob (issue #58). Mirrors the existing media-only-field
    # rule: only valid when ``kind == "nowplaying"``.
    empty_state: NowPlayingEmptyState | None = None
    # Confirmation opt-in (issues #69 / #108). When ``True`` the daemon
    # withholds execution on press, mints a ``confirm_id``, sends a
    # ``confirm_request`` to the client, and only runs the action /
    # macro on a matching ``confirm_response`` with ``decision="confirm"``.
    # The daemon-authoritative handshake is what makes the gate
    # trustworthy (client-only cosmetics can be bypassed); see
    # ``server.py::_dispatch_press`` for the seam. Valid only on a
    # widget with an ``action`` or a ``macro`` — rejected at load by
    # the ``_validate_confirm_invariant`` model validator below
    # (blank / meter / stats / media / nowplaying all reject
    # ``confirm: true``; ``confirm: false``/absent is harmless
    # everywhere and stays the default). Emit-always via plain
    # ``model_dump`` so the client can read ``widget.confirm`` to
    # render a danger affordance before any press happens.
    confirm: bool = False

    @field_validator("kind")
    @classmethod
    def _validate_meter_needs_source(cls, v: str) -> str:
        # Field-level validators on Pydantic v2 don't see sibling fields
        # via ``info.data`` (that dict only contains fields validated
        # *before* this one, not peer fields). The cross-field check
        # (meter requires ``source``, min < max) lives in the
        # ``_validate_meter_invariants`` model validator below where
        # the full model is available.
        return v

    @field_validator("controls")
    @classmethod
    def _validate_media_controls(cls, v: list[MediaControl] | None) -> list[MediaControl] | None:
        if v is None:
            return v
        if not v:
            raise ValueError("media controls must not be empty")
        if len(v) != len(set(v)):
            raise ValueError("media controls must not contain duplicates")
        return v

    @field_validator("size")
    @classmethod
    def _validate_size(cls, v: object) -> object:
        # ``"full"`` and absent are fine; a span must be exactly two positive
        # ints (columns, rows). Guard the shape here so a bad ``size: [0, 2]``
        # or ``size: [1, 2, 3]`` fails at load with a clear message rather than
        # silently producing a zero-span cell in the client.
        if v is None or v == "full":
            return v
        if not isinstance(v, list) or len(v) != 2:
            raise ValueError("size span must be a [columns, rows] pair, or the literal \"full\"")
        if any(not isinstance(n, int) or n < 1 for n in v):
            raise ValueError(f"size span values must be positive integers; got {v!r}")
        return v

    @field_validator("art_source")
    @classmethod
    def _validate_art_source(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        allowed = {"vlc", "itunes"}
        invalid = sorted(set(v) - allowed)
        if invalid:
            raise ValueError(f"unknown art sources: {', '.join(invalid)}")
        return v

    @model_validator(mode="after")
    def _validate_media_invariants(self) -> "Widget":
        media_fields = {
            "controls": self.controls,
            "media_http": self.media_http,
            "art_source": self.art_source,
            "previous_action": self.previous_action,
            "next_action": self.next_action,
            "volume_up_action": self.volume_up_action,
            "volume_down_action": self.volume_down_action,
        }
        nowplaying_fields = {
            "empty_state": self.empty_state,
        }
        if self.kind == "blank":
            # A ``blank`` is a deliberate gap in the reflow (ADR-0010): it
            # only holds space, honouring an optional ``size`` span. Anything
            # that would make it interactive or content-bearing is a mistake,
            # so reject label/icon/color/action and every widget-specific
            # field rather than silently ignoring them.
            forbidden = {
                "label": self.label,
                "icon": self.icon,
                "color": self.color,
                "action": self.action,
                "macro": self.macro,
                "source": self.source,
                "metrics": self.metrics,
                **media_fields,
                **nowplaying_fields,
            }
            invalid = sorted(name for name, value in forbidden.items() if value is not None)
            if invalid:
                raise ValueError(f"blank widgets take only 'size'; got: {', '.join(invalid)}")
            return self
        if self.kind == "media" and self.controls is None:
            self.controls = ["play", "volume", "position"]
        if self.kind == "nowplaying":
            # Apply the same default as ``NowPlaying`` so a widget
            # declared with just ``id`` / ``kind`` / ``size`` still
            # round-trips through ``model_dump`` with the knob populated —
            # the client needs it to make the empty-placeholder decision,
            # and an absent key would land as ``None`` on the wire.
            if self.empty_state is None:
                self.empty_state = "show"
        if self.kind != "media":
            invalid = sorted(name for name, value in media_fields.items() if value is not None)
            if invalid:
                raise ValueError(f"media-only fields on non-media widget: {', '.join(invalid)}")
        if self.kind != "nowplaying":
            invalid = sorted(name for name, value in nowplaying_fields.items() if value is not None)
            if invalid:
                raise ValueError(
                    f"nowplaying-only fields on non-nowplaying widget: {', '.join(invalid)}"
                )
        if self.kind == "meter":
            if not self.source:
                raise ValueError(
                    "meter widgets require a 'source' field naming a "
                    "daemon-side SensorSource (e.g. 'cpu_percent')"
                )
            if self.min is not None and self.max is not None and self.min >= self.max:
                raise ValueError(
                    f"meter widget min ({self.min}) must be strictly "
                    f"less than max ({self.max})"
                )
        if self.kind == "stats" and not self.metrics:
            raise ValueError(
                "stats widgets require a non-empty 'metrics' list, each "
                "naming a 'source' (e.g. metrics: [{source: cpu_percent}])"
            )
        if self.confirm:
            # ``confirm: true`` requires an executable action or macro to
            # gate. A bare label-only button, a non-interactive kind
            # (``blank`` / ``meter`` / ``stats``), or a composite media
            # surface (``media`` / ``nowplaying`` — issue #108's
            # clarification) has nothing to confirm; rejecting at load
            # is clearer than silently ignoring the field.
            forbidden_confirm_kinds = {"blank", "meter", "stats", "media", "nowplaying"}
            if self.kind in forbidden_confirm_kinds:
                raise ValueError(
                    f"confirm: true is not valid on kind={self.kind!r} widgets"
                )
            if self.action is None and self.macro is None:
                raise ValueError(
                    "confirm: true requires an 'action' or 'macro'"
                )
        return self


class Action(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str | None = None
    shell: str | None = None
    dbus: str | None = None
    # ``raise`` activates the most recently focused running window matching
    # the configured application identity. Platform support is backend-specific.
    raise_: str | None = Field(default=None, alias="raise", min_length=1)
    # ``terminal: true`` opens the auto-detected terminal emulator ($TERMINAL,
    # then a candidate list). It intentionally does NOT take a command string:
    # to launch a specific program use ``shell:`` (which is fire-and-forget),
    # so there's exactly one way to launch a named program.
    terminal: bool | None = None
    # ``url`` opens the given URL in the user's default browser. Accepts
    # ``http:``, ``https:``, and ``file:`` schemes; other schemes are
    # rejected at load time with guidance to use ``shell:`` instead.
    url: str | None = None
    # ``text`` injects the given string into the focused window.
    text: str | None = None
    text_mode: Literal["simulate", "paste"] | None = None
    restore_clipboard: bool = True
    restore_clipboard_delay_ms: int = Field(default=1000, ge=0)

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    @field_validator("terminal", mode="before")
    @classmethod
    def _reject_terminal_string(cls, v: object) -> object:
        if isinstance(v, str):
            raise ValueError(
                "the 'terminal' action no longer takes a command string; use "
                "'terminal: true' to open the auto-detected terminal, or "
                f"'shell: \"{v}\"' to launch that program directly"
            )
        return v

    @field_validator("url")
    @classmethod
    def _validate_url_scheme(cls, v: str | None) -> str | None:
        if v is None:
            return v
        allowed = ("http:", "https:", "file:")
        if not any(v.startswith(p) for p in allowed):
            raise ValueError(
                f"url action only accepts http:, https:, and file: schemes; "
                f"got {v!r}. Use shell: for other schemes (e.g. "
                f"shell: \"xdg-open {v}\")"
            )
        return v

    @field_validator("text")
    @classmethod
    def _reject_empty_text(cls, v: str | None) -> str | None:
        if v is not None and v == "":
            raise ValueError("text action must not be empty")
        return v


class Deck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = ""
    match: list[str] = Field(default_factory=list)
    widgets: list[Widget] = Field(default_factory=list)
    # What happens when the deck exceeds what the viewport holds at the
    # client's minimum button size (ADR-0011). ``clip`` (the default) trims
    # trailing widgets so the survivors keep that size; ``shrink-to-fit`` keeps
    # every widget by letting cells fall below the floor. The deck supplies
    # the default and the client may override it per device, so this is the one
    # sizing knob that is both a deck and a device concern.
    overflow: Literal["clip", "shrink-to-fit"] = "clip"
    jogstrip: bool = True
    # Chrome app-identity presentation relayed opaquely to the client
    # (ADR-0007). The client renders these in the always-on bottom strip:
    # ``display_name`` replaces the raw match token, ``theme`` tints the
    # badge (a CSS colour string the browser accepts, exactly like the
    # per-widget ``color``), and ``icon`` is the same ``{source, name}``
    # dispatch widgets use (ADR-0006). All three are optional and default
    # to ``None``; the daemon never interprets them, mirroring the
    # per-widget presentation relay.
    display_name: str | None = None
    theme: str | None = None
    icon: Icon | None = None

    @model_validator(mode="after")
    def _validate_unique_widget_ids(self) -> "Deck":
        """#85 deck-level duplicate widget-id validator.

        Widget ids are how the WS ``widget_update`` pump and the editor's
        reconcile address a widget, so two widgets sharing an id is a
        silent ambiguity rather than a display quirk. Reject at load /
        save-validation time with a model-level error so the editor can
        surface it inline. Runs after the per-widget invariants so a
        malformed widget fails first with its own message.
        """
        seen: set[str] = set()
        for widget in self.widgets:
            if widget.id in seen:
                raise ValueError(f"duplicate widget id: {widget.id!r}")
            seen.add(widget.id)
        return self

    def matches(self, app: AppInfo) -> bool:
        """True if this deck's ``match`` list covers the given app.

        A match is satisfied when any of the focused app's identifiers
        (``app_id``, ``wm_class``) is in the deck's ``match`` list. The
        special token ``default`` is *not* considered a real match — it is
        only the fallback. Decks whose ``match`` list is empty never
        match by app identity.

        Web-app prototype (Tier 1): a token of the form ``title:PATTERN`` is
        a case-insensitive glob matched against the focused window's title.
        Because desktop focus backends can only see a browser's window title
        (never the active tab's URL — that needs a browser extension), this
        lets a deck claim a *site* heuristically, e.g.
        ``match: ["title:*YouTube*"]``. It is best-effort: it breaks whenever
        a site changes how it formats ``<title>``.
        """
        return self.matches_title(app) or self.matches_identity(app)

    def matches_title(self, app: AppInfo) -> bool:
        """True if a ``title:`` glob token covers the focused window title."""
        if not app.title:
            return False
        for token in self.match:
            if token.startswith("title:"):
                pattern = token[len("title:") :]
                if fnmatch.fnmatch(app.title.casefold(), pattern.casefold()):
                    return True
        return False

    def matches_identity(self, app: AppInfo) -> bool:
        """True if an ``app_id``/``wm_class`` token covers the focused app.

        The comparison is case-insensitive (#140). A backend's enumeration
        identity can differ in case from its focus identity — macOS reports
        ``kCGWindowOwnerName`` as ``Firefox`` while the focus path and the
        deck tokens are the lowercase process name ``firefox`` — and an
        exact membership test dropped those windows to the default fallback
        (bare app name, no glyph) even though focus-driven switching matched
        fine. Casefolding both sides fixes every backend at once. The cost
        is that two decks whose tokens differ only in case now collide;
        that has never been a supported distinction (ids slugify to
        lowercase, and ``resolve_id`` already matches case-insensitively).

        Tokens are additionally matched against the *last dotted segment*
        of each identity, so a bare token (``konsole``) covers its
        reverse-DNS form (``org.kde.konsole``) — the shape KDE's
        ``resourceClass`` and GNOME's ``get_wm_class`` report for
        Wayland-native windows (docs/PLATFORM-PARITY.md, KDE backend
        note). A full token (``org.gnome.Console``) still matches the full
        identity exactly; this only widens the exact path, it never
        narrows it.
        """
        if not self.match or self.match == ["default"]:
            return False
        tokens = {token.casefold() for token in self.match}
        identities = [value.casefold() for value in (app.app_id, app.wm_class) if value]
        for identity in identities:
            if identity in tokens:
                return True
            # Reverse-DNS short name: ``org.kde.konsole`` -> ``konsole``.
            short = identity.rsplit(".", 1)[-1]
            if short in tokens:
                return True
        return False


def load_deck(path: Path) -> Deck:
    data = yaml.safe_load(path.read_text())
    try:
        deck = Deck.model_validate(data)
    except ValidationError as exc:
        raise SystemExit(f"invalid deck YAML at {path}:\n{exc}") from exc
    if deck.match:
        deck.id = deck.match[0]
    return deck


# ---------------------------------------------------------------------------
# Multi-deck directory loader
# ---------------------------------------------------------------------------


DEFAULT_DECK_ID = "default"


class DeckStore:
    """In-memory collection of all decks the daemon knows about.

    Decks are addressable by their primary match token (the first entry
    of ``match``). Decks with an empty match list (no real app claim)
    are still loaded but only the default fallback is addressable.
    """

    def __init__(
        self,
        decks: list[Deck],
        *,
        source_paths: dict[str, Path] | None = None,
    ) -> None:
        self._decks = list(decks)
        # Per-deck on-disk source file, keyed by the deck's id
        # (= ``match[0]``). The repo decouples filename from id (e.g.
        # ``tilix.yaml`` holds id ``com.gexperts.Tilix``), so the write API
        # (PUT /decks/{id}, POST /decks) resolves a rewrite target by id
        # rather than by re-deriving ``<id>.yaml``. A loaded-but-synthetic
        # store (tests) leaves this empty and the write endpoints treat a
        # missing path as a 404.
        self._source_paths: dict[str, Path] = dict(source_paths) if source_paths else {}

    @property
    def decks(self) -> list[Deck]:
        return list(self._decks)

    def source_path(self, deck_id: str) -> Path | None:
        """The on-disk YAML file a deck was loaded from, or ``None``."""
        return self._source_paths.get(deck_id)

    def __contains__(self, deck_id: str) -> bool:
        return any(deck.id == deck_id for deck in self._decks)

    def __getitem__(self, deck_id: str) -> Deck:
        for deck in self._decks:
            if deck.id == deck_id:
                return deck
        raise KeyError(deck_id)

    def resolve_id(self, name: str) -> str | None:
        """Map a human-supplied name to a canonical deck id, or None.

        Used by the ``?deck=<name>`` demo pin, where the obvious thing to
        type is a friendly name rather than the primary match token that
        happens to be the id. Tries an exact id match first, then a
        case-insensitive match against each deck's id, its ``display_name``,
        and any of its match tokens — so ``tilix`` resolves the deck whose
        id is ``com.gexperts.Tilix`` (display_name ``Tilix``).
        """
        for deck in self._decks:
            if deck.id == name:
                return deck.id
        lowered = name.casefold()
        for deck in self._decks:
            candidates = (deck.id, deck.display_name, *deck.match)
            if any(c and c.casefold() == lowered for c in candidates):
                return deck.id
        return None

    def default(self) -> Deck:
        for deck in self._decks:
            if "default" in deck.match:
                return deck
        raise KeyError(
            "no default deck loaded (expected a deck with match: [default])"
        )


def resolve_deck(store: DeckStore, app: AppInfo) -> Deck:
    """Pick the deck for the given focused app.

    A site (``title:``) match is more specific than a plain app-identity
    match, so it wins even if a generic browser deck also claims the app
    and is loaded first. Within each tier it is first-match-wins by load
    order. If nothing matches, the ``default`` deck is returned.
    """
    for deck in store.decks:
        if deck.matches_title(app):
            return deck
    for deck in store.decks:
        if deck.matches_identity(app):
            return deck
    return store.default()


def _window_to_app(win: WindowInfo) -> AppInfo:
    """Build an :class:`AppInfo` for one :class:`WindowInfo` so the deck
    matcher can compare the window's three identity keys against the
    match tokens.

    The matcher's identity path compares ``AppInfo.app_id`` /
    ``AppInfo.wm_class`` against each ``match`` token. For a Flatpak /
    Snap window, ``sandboxed_app_id`` is the desktop identity (e.g.
    ``org.flathub.Firefox``); for a GTK app, ``gtk_application_id`` is.
    Mapping ``sandboxed_app_id`` into ``AppInfo.app_id`` keeps the
    matcher's precedence semantics intact without rewriting the
    matcher per-source (#117 / #119). Shared between
    :func:`label_for_window` and :func:`icon_for_window` so the identity
    precedence lives in one place.
    """
    return AppInfo(
        app_id=win.gtk_application_id or win.sandboxed_app_id,
        wm_class=win.wm_class,
        title=win.title,
    )


def _humanize_identity(identity: str) -> str:
    """Turn a machine app identity into a readable window label."""
    # Reverse-DNS ids occasionally carry a packaging-suffix segment
    # (``org.telegram.desktop``) that is not part of the app's name —
    # drop it before taking the last meaningful dotted segment so the
    # label reads ``Telegram``, not ``Desktop``.
    for suffix in (".desktop", ".app"):
        if identity.endswith(suffix):
            identity = identity[: -len(suffix)]
            break
    name = identity.rsplit(".", 1)[-1]
    name = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", name)
    name = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name)
    name = re.sub(r"[-_]", " ", name)
    return " ".join(word if word.isupper() else word.capitalize() for word in name.split())


def label_for_window(store: DeckStore, win: WindowInfo) -> str:
    """Compute a single row label for one enumerated window (issues
    #119 / #120 / #126).

    Mirrors :func:`resolve_deck`'s site-before-identity ordering: a
    ``title:`` match wins even if a generic browser deck also claims
    the window's identity. Match → matched deck's ``display_name``
    (falls back to ``id`` so a deck without an explicit display name
    still renders something meaningful). No match → ``app_name`` when
    supplied, then a humanized identity fallback: ``wm_class``, then
    ``gtk_application_id``, then
    ``sandboxed_app_id``, then ``title`` — the same three-key identity
    the matcher compares against ``match`` tokens (#117 / #118), with
    ``title`` as the last-resort visible string.

    A reload that drops the matched deck naturally re-derives a
    fallback label on the next push — no invalidation logic needed
    because :func:`resolve_deck` walks ``store.decks`` fresh every
    call (issue #120 decision 5: "label per push, no cache"). The
    helper is pure; the matcher is O(n_decks × n_tokens) per call
    and the daemon runs it once per push — adding it to the list tick
    doesn't change the per-tick cost meaningfully.
    """
    deck = resolve_deck(store, _window_to_app(win))
    if deck is not store.default():
        return deck.display_name or _humanize_identity(deck.id) or "unknown"
    identity = win.wm_class or win.gtk_application_id or win.sandboxed_app_id
    return win.app_name or (_humanize_identity(identity) if identity else None) or win.title or "unknown"


def icon_for_window(store: DeckStore, win: WindowInfo) -> "Icon | None":
    """Compute the per-row ``icon`` for one enumerated window (issue #126).

    Returns the matched deck's icon when the window resolves to a
    deck (a Firefox window on a ``firefox.yaml`` deck with
    ``icon: simple-icons firefox`` → row icon is the Simple Icons
    Firefox glyph). Returns ``None`` on the default-fallback path —
    the absence is *honest*, not decorative: a default-fallback row
    having no glyph distinguishes it from identity-matched rows whose
    glyph encodes the brand, and inventing a generic "terminal" Lucide
    icon for every xterm would imply every xterm is the same xterm
    (the list is per-window precisely so they're not — #120 decision
    6).
    """
    deck = resolve_deck(store, _window_to_app(win))
    if deck is store.default():
        return None
    return deck.icon


def load_decks(
    decks_dir: Path, overlay_dir: Path | None = None
) -> DeckStore:
    """Load every ``*.yaml`` / ``*.yml`` file in ``decks_dir`` plus an
    optional platform overlay.

    The overlay is loaded first; same-id base entries are then dropped.
    Effect: if the overlay defines a deck with the same id as a base
    deck (typically because both name their file ``<id>.yaml``), the
    overlay wins. The overlay can also add decks for apps the base
    doesn't cover. A missing ``decks_dir`` is fatal; a missing overlay
    is fine (no overlay is the most common case).

    Resolution semantics stay first-match-wins within the combined list,
    so loading the overlay first means its entries shadow base entries
    that match the same focused-app identity -- which is the intuitive
    "platform overrides shared" semantic.
    """
    if not decks_dir.is_dir():
        raise SystemExit(f"decks directory not found: {decks_dir}")

    decks: list[Deck] = []
    source_paths: dict[str, Path] = {}

    def _record(deck: Deck, path: Path) -> None:
        decks.append(deck)
        if deck.id:
            # Last load wins: the overlay re-records an id it shadows later
            # via the drop path below, so the path always reflects the live
            # file the store actually used.
            source_paths[deck.id] = path

    if overlay_dir is not None and overlay_dir.is_dir():
        for path in sorted(overlay_dir.glob("*.y*ml")):
            if path.suffix not in {".yaml", ".yml"}:
                continue
            try:
                deck = load_deck(path)
            except SystemExit as exc:
                raise SystemExit(f"{exc}") from None
            _record(deck, path)

    overlay_ids = {deck.id for deck in decks if deck.id}
    for path in sorted(decks_dir.glob("*.y*ml")):
        if path.suffix not in {".yaml", ".yml"}:
            continue
        try:
            deck = load_deck(path)
        except SystemExit as exc:
            raise SystemExit(f"{exc}") from None
        if deck.id and deck.id in overlay_ids:
            log.info("deck %r overridden by overlay %s", deck.id, path)
            continue
        _record(deck, path)

    return DeckStore(decks, source_paths=source_paths)


# ---------------------------------------------------------------------------
# Deck write API (issues #99 / #84 / #85)
# ---------------------------------------------------------------------------
#
# These helpers sit below the HTTP write endpoints (``PUT /decks/{id}`` save
# and ``POST /decks`` create). They own three concerns the endpoints share:
#
# * turning a deck's primary ``match`` token into a filesystem-safe filename
#   stem (``slugify_deck_id``);
# * comment-preserving reconcile of a client-supplied full snapshot onto a
#   fresh on-disk YAML re-read, widgets matched by ``id`` and maps recursed,
#   other sequences replaced atomically (``reconcile_and_write_deck``);
# * the atomic temp-write + ``os.replace`` that lets the ``watchfiles`` watcher
#   pick up the edit as a single event.
#
# The daemon never interprets comments; it only carries them along so a deck
# the user hand-authored keeps its prose when the editor saves a one-field
# change. ``ruamel.yaml`` is the round-trip surface; Pydantic validates the
# snapshot before it reaches here so the data is already schema-conformant.


_SLUG_NON_SAFE = re.compile(r"[^a-z0-9._-]+")
_SLUG_DASH_RUN = re.compile(r"-{2,}")


def slugify_deck_id(match_token: str) -> str:
    """Filesystem-safe filename stem for a deck derived from ``match[0]``.

    Lowercases, replaces every run of characters that aren't ``[a-z0-9._-]``
    with a single ``-``, collapses repeated dashes, and strips leading /
    trailing dashes. Dots are kept so reverse-DNS ids (``com.gexperts.Tilix``)
    stay readable. Raises :class:`ValueError` when the token slugifies to the
    empty string (a token made only of sigils, e.g. ``***``) — the caller
    maps that to a ``400`` rather than writing a nameless file.
    """
    slug = match_token.casefold()
    slug = _SLUG_NON_SAFE.sub("-", slug)
    slug = _SLUG_DASH_RUN.sub("-", slug)
    slug = slug.strip("-")
    if not slug:
        raise ValueError(
            f"cannot derive a filename from match[0]={match_token!r}: "
            f"it slugifies to the empty string"
        )
    return slug


def _yaml_round_trip() -> Any:
    """A ruamel YAML round-trip instance tuned to the repo's hand-authored style.

    ``sequence=2, offset=2`` indents block sequences two spaces under their
    mapping key (``match:\n  - firefox``) and the item content two more
    (``    kind: button``), matching every shipping deck. ruamel's default
    is flush-left sequences (``match:\n- firefox``), which is valid YAML but
    inconsistent with the convention the editor writes into — so a freshly
    created file reads identically to a hand-authored one.
    """
    from ruamel.yaml import YAML

    y = YAML()
    y.preserve_quotes = True
    y.default_flow_style = False
    y.indent(mapping=2, sequence=4, offset=2)
    return y


def _to_commented(value: Any) -> Any:
    """Recursively wrap a plain JSON-ish value in ruamel Commented containers.

    New files have no source comments to preserve, but ruamel emits block
    style and keeps key order only when handed its own ``CommentedMap`` /
    ``CommentedSeq`` rather than the plain ``dict`` / ``list`` Pydantic and
    ``json.loads`` produce. This keeps a freshly-created file's field order
    and style identical to one the reconcile path would write.
    """
    from ruamel.yaml.comments import CommentedMap, CommentedSeq

    if isinstance(value, dict):
        out = CommentedMap()
        for key, item in value.items():
            out[key] = _to_commented(item)
        return out
    if isinstance(value, list):
        seq = CommentedSeq()
        for item in value:
            seq.append(_to_commented(item))
        return seq
    return value


# Top-level Deck fields that are maps (recurse) vs. sequences-of-widgets
# (matched by ``id``) vs. everything else (scalar or atomic-sequence).
_WIDGET_ID_KEY = "id"


def _reconcile_map(existing: Any, snapshot: dict) -> Any:
    """Reconcile a ``snapshot`` dict into a ruamel ``CommentedMap``.

    ``existing`` is a ruamel ``CommentedMap`` (possibly empty) carrying the
    on-disk comments and key order. For each snapshot key the value replaces
    the file's, recursing into nested maps; keys present in the file but
    absent from the snapshot are dropped (full-snapshot semantics — the
    editor sends the complete desired state). The special ``widgets`` list
    is reconciled by widget ``id`` (:func:`_reconcile_widgets`) so a widget's
    comments ride along across edits, reorder, add, and delete. Comments
    attached to keys the snapshot keeps are preserved unchanged.
    """
    from ruamel.yaml.comments import CommentedMap

    if not isinstance(existing, CommentedMap):
        out = CommentedMap()
    else:
        out = existing
    snap_keys = list(snapshot.keys())
    # Drop keys the snapshot no longer carries (full-snapshot authoritativeness).
    for key in list(out.keys()):
        if key not in snapshot:
            del out[key]
    for key in snap_keys:
        snap_value = snapshot[key]
        existing = out.get(key)
        # Skip reassignment when the snapshot value is unchanged. ruamel
        # attaches comments to a key's node; reassigning the value (even to
        # an equal one) can drop a leading comment attached to that key and
        # is unnecessary work. The common editor save edits one widget and
        # leaves the rest of the deck byte-identical, so this keeps an
        # unchanged widget's comments and key order intact (issue #85).
        if key == "widgets":
            if existing is None or _widgets_changed(existing, snap_value):
                out[key] = _reconcile_widgets(existing, snap_value)
            continue
        if isinstance(snap_value, dict):
            if not isinstance(existing, CommentedMap) or _plain_dict_changed(existing, snap_value):
                out[key] = _reconcile_map(existing if isinstance(existing, CommentedMap) else None, snap_value)
        elif isinstance(snap_value, list):
            if existing != snap_value:
                out[key] = _to_commented(snap_value)
        else:
            if existing != snap_value:
                out[key] = snap_value
    return out


def _plain_dict_changed(existing: Any, snap: dict) -> bool:
    """True if ``existing`` (a CommentedMap) differs from ``snap`` as a plain dict.

    ruamel ``CommentedMap`` compares by value like a dict, so a cheap
    equality check decides whether to recurse (and risk disturbing
    comments) or leave the subtree untouched.
    """
    try:
        return dict(existing) != snap
    except Exception:
        return True


def _widgets_changed(existing: Any, snap_widgets: list[dict]) -> bool:
    """True if the on-disk widgets sequence differs from the snapshot.

    Compares the plain-dict rendering of each widget in order so a
    byte-identical save (the common case: edit one widget, the rest ride
    along) skips the sequence rewrite and preserves the top-level comment
    ruamel attaches to the ``widgets`` key.
    """
    try:
        existing_list = list(existing)
    except TypeError:
        return True
    if len(existing_list) != len(snap_widgets):
        return True
    for ex, snap in zip(existing_list, snap_widgets):
        if dict(ex) != snap:
            return True
    return False


def _reconcile_widgets(existing: Any, snapshot_widgets: list[dict]) -> Any:
    """Reconcile the ``widgets`` sequence by widget ``id`` (issue #85).

    Existing widgets are matched to snapshot widgets by ``id``; a matched
    pair recurses into the widget's map (so a comment on ``label:` survives
    editing the label), preserving the widget's position in any
    comment-anchored flow. Snapshot widgets with no on-disk counterpart are
    appended; on-disk widgets absent from the snapshot are deleted. The
    final order follows the snapshot, so a reorder in the editor rewrites the
    sequence while a widget's own comments follow it — ruamel attaches list
    item comments to the item node, and copying the existing CommentedSeq
    entry carries them along.
    """
    from ruamel.yaml.comments import CommentedMap, CommentedSeq

    out: CommentedSeq = CommentedSeq()
    if isinstance(existing, CommentedSeq):
        existing_by_id: dict[str, Any] = {}
        for item in existing:
            if isinstance(item, CommentedMap) and _WIDGET_ID_KEY in item:
                existing_by_id[item[_WIDGET_ID_KEY]] = item
    else:
        existing_by_id = {}
    for snap_widget in snapshot_widgets:
        wid = snap_widget.get(_WIDGET_ID_KEY)
        prior = existing_by_id.pop(wid, None) if wid is not None else None
        out.append(_reconcile_map(prior, snap_widget))
    return out


def reconcile_and_write_deck(path: Path, snapshot: dict) -> None:
    """Reconcile ``snapshot`` onto a fresh disk re-read and write atomically.

    ``snapshot`` is the post-:class:`Deck`-validation JSON dict from the
    client (a full-deck snapshot). The deck's ``id`` field is dropped
    before writing — on disk the canonical id is always ``match[0]`` (see
    :func:`load_deck`), never a stored ``id:`` key, so the shipping
    decks (which omit it) and editor-written decks round-trip
    identically.

    On a missing file the snapshot is written fresh. On an existing file the
    reconcile preserves comments and widget ``id`` identity per #85. The
    write is atomic (a temp file in the same directory, then ``os.replace``)
    so the ``watchfiles`` watcher sees one create/modify event instead of a
    half-written file.
    """
    from ruamel.yaml.comments import CommentedMap

    y = _yaml_round_trip()
    if path.exists():
        text = path.read_text()
        loaded = y.load(text)  # type: ignore[assignment]
        if loaded is None:
            loaded = CommentedMap()
    else:
        loaded = CommentedMap()

    writeable = _reconcile_map(loaded, _snapshot_for_disk(snapshot))
    tmp = tempfile.NamedTemporaryFile(
        mode="w",
        delete=False,
        suffix=".yaml.tmp",
        dir=str(path.parent),
        encoding="utf-8",
    )
    try:
        y.dump(writeable, tmp)
        tmp.flush()
        os.replace(tmp.name, path)
    finally:
        try:
            os.unlink(tmp.name)
        except FileNotFoundError:
            pass


def _snapshot_for_disk(snapshot: dict) -> dict:
    """Strip the derived ``id`` field so the file's id is always ``match[0]``.

    The editor echoes whatever it parsed, including ``id``; the on-disk
    convention (every shipping deck) omits ``id:`` and lets
    :func:`load_deck` derive it from ``match[0]``. Dropping it keeps the
    canonical re-read, the watcher's reload, and a hand-authored file
    indistinguishable.
    """
    cleaned = dict(snapshot)
    cleaned.pop("id", None)
    return cleaned


Widget.model_rebuild()
