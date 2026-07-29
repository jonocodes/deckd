from __future__ import annotations

import fnmatch
import logging
from pathlib import Path
from typing import Literal

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from .platform import AppInfo

# Literal alias for the ``mediabrowser`` widget's ``empty_state`` knob
# (issue #50). Defined here so the daemon's ``Widget`` model — the one
# YAML flows through — has a single source of truth;
# :class:`deckd.mpris.MediaBrowser` imports the same name so the
# dedicated schema can't drift. ``ordering`` was removed in issue #58:
# rows now reflect the session bus's ``ListNames`` order (matching GNOME
# Shell) with no per-layout knob.
MediaBrowserEmptyState = Literal["show", "hide"]

log = logging.getLogger("deckd.layouts")


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
    grid: list[int] = Field(min_length=4, max_length=4)
    # Optional CSS colour string applied as the button's background. Any
    # value the browser accepts is fine ("#1e3a8a", "rebeccapurple",
    # "hsl(...)"). Client trust: layouts are user-owned config, not user
    # input, so no sanitisation is needed.
    color: str | None = None
    action: "Action | None" = None
    macro: "Macro | None" = None
    # ``meter`` widgets bind to a daemon-side :class:`SensorSource` by
    # name (e.g. ``cpu_percent``). The daemon pushes ``WidgetUpdateMessage``
    # frames for every meter widget in the active layout whose source
    # has live readings. ``min`` / ``max`` define the bar's visible
    # range; values outside the range clamp at the ends so a runaway
    # sensor paints the bar at full red rather than overflowing.
    # ``min``/``max`` default to a CPU-friendly 0..100 %; layouts with
    # non-thermal sensors should override.
    source: str | None = None
    min: float | None = None
    max: float | None = None
    # ``stats`` widgets bind to several sensor sources at once and render
    # a compact, bar-less list of "label: value" rows. Each metric names a
    # source the same way a ``meter`` names its single ``source``; the
    # daemon subscribes to every referenced source while a stats widget is
    # in the active layout, exactly as it does for meters.
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
    # ``mediabrowser`` widgets (issue #50) take one knob documented on
    # :class:`deckd.mpris.MediaBrowser`: whether the cell still renders
    # an empty placeholder when no player is discovered (``empty_state``).
    # Row order follows the session bus's ``ListNames`` reply — no
    # per-layout knob (issue #58). Mirrors the existing media-only-field
    # rule: only valid when ``kind == "mediabrowser"``.
    empty_state: MediaBrowserEmptyState | None = None

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
        mediabrowser_fields = {
            "empty_state": self.empty_state,
        }
        if self.kind == "media" and self.controls is None:
            self.controls = ["play", "volume", "position"]
        if self.kind == "mediabrowser":
            # Apply the same default as ``MediaBrowser`` so a widget
            # declared with just ``id`` / ``kind`` / ``grid`` still
            # round-trips through ``model_dump`` with the knob populated —
            # the client needs it to make the empty-placeholder decision,
            # and an absent key would land as ``None`` on the wire.
            if self.empty_state is None:
                self.empty_state = "show"
        if self.kind != "media":
            invalid = sorted(name for name, value in media_fields.items() if value is not None)
            if invalid:
                raise ValueError(f"media-only fields on non-media widget: {', '.join(invalid)}")
        if self.kind != "mediabrowser":
            invalid = sorted(name for name, value in mediabrowser_fields.items() if value is not None)
            if invalid:
                raise ValueError(
                    f"mediabrowser-only fields on non-mediabrowser widget: {', '.join(invalid)}"
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
        return self


class Action(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str | None = None
    shell: str | None = None
    dbus: str | None = None
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


class Layout(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = ""
    match: list[str] = Field(default_factory=list)
    widgets: list[Widget] = Field(default_factory=list)
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

    def matches(self, app: AppInfo) -> bool:
        """True if this layout's ``match`` list covers the given app.

        A match is satisfied when any of the focused app's identifiers
        (``app_id``, ``wm_class``) is in the layout's ``match`` list. The
        special token ``default`` is *not* considered a real match — it is
        only the fallback. Layouts whose ``match`` list is empty never
        match by app identity.

        Web-app prototype (Tier 1): a token of the form ``title:PATTERN`` is
        a case-insensitive glob matched against the focused window's title.
        Because desktop focus backends can only see a browser's window title
        (never the active tab's URL — that needs a browser extension), this
        lets a layout claim a *site* heuristically, e.g.
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
        """True if an ``app_id``/``wm_class`` token covers the focused app."""
        if not self.match or self.match == ["default"]:
            return False
        return any(token in (app.app_id, app.wm_class) for token in self.match)


def load_layout(path: Path) -> Layout:
    data = yaml.safe_load(path.read_text())
    try:
        layout = Layout.model_validate(data)
    except ValidationError as exc:
        raise SystemExit(f"invalid layout YAML at {path}:\n{exc}") from exc
    if layout.match:
        layout.id = layout.match[0]
    return layout


# ---------------------------------------------------------------------------
# Multi-layout directory loader
# ---------------------------------------------------------------------------


DEFAULT_LAYOUT_ID = "default"


class LayoutStore:
    """In-memory collection of all layouts the daemon knows about.

    Layouts are addressable by their primary match token (the first entry
    of ``match``). Layouts with an empty match list (no real app claim)
    are still loaded but only the default fallback is addressable.
    """

    def __init__(self, layouts: list[Layout]) -> None:
        self._layouts = list(layouts)

    @property
    def layouts(self) -> list[Layout]:
        return list(self._layouts)

    def __contains__(self, layout_id: str) -> bool:
        return any(l.id == layout_id for l in self._layouts)

    def __getitem__(self, layout_id: str) -> Layout:
        for layout in self._layouts:
            if layout.id == layout_id:
                return layout
        raise KeyError(layout_id)

    def resolve_id(self, name: str) -> str | None:
        """Map a human-supplied name to a canonical layout id, or None.

        Used by the ``?layout=<name>`` demo pin, where the obvious thing to
        type is a friendly name rather than the primary match token that
        happens to be the id. Tries an exact id match first, then a
        case-insensitive match against each layout's id, its ``display_name``,
        and any of its match tokens — so ``tilix`` resolves the layout whose
        id is ``com.gexperts.Tilix`` (display_name ``Tilix``).
        """
        for layout in self._layouts:
            if layout.id == name:
                return layout.id
        lowered = name.casefold()
        for layout in self._layouts:
            candidates = (layout.id, layout.display_name, *layout.match)
            if any(c and c.casefold() == lowered for c in candidates):
                return layout.id
        return None

    def default(self) -> Layout:
        for layout in self._layouts:
            if "default" in layout.match:
                return layout
        raise KeyError(
            "no default layout loaded (expected a layout with match: [default])"
        )


def resolve_layout(store: LayoutStore, app: AppInfo) -> Layout:
    """Pick the layout for the given focused app.

    A site (``title:``) match is more specific than a plain app-identity
    match, so it wins even if a generic browser layout also claims the app
    and is loaded first. Within each tier it is first-match-wins by load
    order. If nothing matches, the ``default`` layout is returned.
    """
    for layout in store.layouts:
        if layout.matches_title(app):
            return layout
    for layout in store.layouts:
        if layout.matches_identity(app):
            return layout
    return store.default()


def load_layouts(
    layouts_dir: Path, overlay_dir: Path | None = None
) -> LayoutStore:
    """Load every ``*.yaml`` / ``*.yml`` file in ``layouts_dir`` plus an
    optional platform overlay.

    The overlay is loaded first; same-id base entries are then dropped.
    Effect: if the overlay defines a layout with the same id as a base
    layout (typically because both name their file ``<id>.yaml``), the
    overlay wins. The overlay can also add layouts for apps the base
    doesn't cover. A missing ``layouts_dir`` is fatal; a missing overlay
    is fine (no overlay is the most common case).

    Resolution semantics stay first-match-wins within the combined list,
    so loading the overlay first means its entries shadow base entries
    that match the same focused-app identity -- which is the intuitive
    "platform overrides shared" semantic.
    """
    if not layouts_dir.is_dir():
        raise SystemExit(f"layouts directory not found: {layouts_dir}")

    layouts: list[Layout] = []

    if overlay_dir is not None and overlay_dir.is_dir():
        for path in sorted(overlay_dir.glob("*.y*ml")):
            if path.suffix not in {".yaml", ".yml"}:
                continue
            try:
                layout = load_layout(path)
            except SystemExit as exc:
                raise SystemExit(f"{exc}") from None
            layouts.append(layout)

    overlay_ids = {l.id for l in layouts if l.id}
    for path in sorted(layouts_dir.glob("*.y*ml")):
        if path.suffix not in {".yaml", ".yml"}:
            continue
        try:
            layout = load_layout(path)
        except SystemExit as exc:
            raise SystemExit(f"{exc}") from None
        if layout.id and layout.id in overlay_ids:
            log.info("layout %r overridden by overlay %s", layout.id, path)
            continue
        layouts.append(layout)

    return LayoutStore(layouts)


Widget.model_rebuild()
