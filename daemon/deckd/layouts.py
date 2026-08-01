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
    # Reflow extent (ADR-0010). ``[w, h]`` is a column/row span; the literal
    # ``"full"`` opts the widget out of the flow to take the whole surface.
    # There is no position — widgets pack in list order, left-to-right,
    # wrapping down against a client-side cell-size band. Absent means a
    # ``[1, 1]`` single cell. The old ``grid: [x, y, w, h]`` coordinate field
    # is gone; migrate by dropping ``x, y`` and keeping ``w, h`` as ``size``.
    size: list[int] | Literal["full"] | None = None
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
        mediabrowser_fields = {
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
                **mediabrowser_fields,
            }
            invalid = sorted(name for name, value in forbidden.items() if value is not None)
            if invalid:
                raise ValueError(f"blank widgets take only 'size'; got: {', '.join(invalid)}")
            return self
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
    # What happens when the widgets exceed the capacity the client's cell-size
    # band yields at the current viewport (ADR-0010). ``clip`` leaves trailing
    # widgets off-surface; ``shrink-to-fit`` lets cells drop below the band's
    # floor so all widgets fit. The one genuinely per-layout sizing knob —
    # every other cell-size concern is a client-side device preference.
    overflow: Literal["clip", "shrink-to-fit"] = "shrink-to-fit"
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
    def _validate_unique_widget_ids(self) -> "Layout":
        """#85 layout-level duplicate widget-id validator.

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

    def __init__(
        self,
        layouts: list[Layout],
        *,
        source_paths: dict[str, Path] | None = None,
    ) -> None:
        self._layouts = list(layouts)
        # Per-layout on-disk source file, keyed by the layout's id
        # (= ``match[0]``). The repo decouples filename from id (e.g.
        # ``tilix.yaml`` holds id ``com.gexperts.Tilix``), so the write API
        # (PUT /layouts/{id}, POST /layouts) resolves a rewrite target by id
        # rather than by re-deriving ``<id>.yaml``. A loaded-but-synthetic
        # store (tests) leaves this empty and the write endpoints treat a
        # missing path as a 404.
        self._source_paths: dict[str, Path] = dict(source_paths) if source_paths else {}

    @property
    def layouts(self) -> list[Layout]:
        return list(self._layouts)

    def source_path(self, layout_id: str) -> Path | None:
        """The on-disk YAML file a layout was loaded from, or ``None``."""
        return self._source_paths.get(layout_id)

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
    source_paths: dict[str, Path] = {}

    def _record(layout: Layout, path: Path) -> None:
        layouts.append(layout)
        if layout.id:
            # Last load wins: the overlay re-records an id it shadows later
            # via the drop path below, so the path always reflects the live
            # file the store actually used.
            source_paths[layout.id] = path

    if overlay_dir is not None and overlay_dir.is_dir():
        for path in sorted(overlay_dir.glob("*.y*ml")):
            if path.suffix not in {".yaml", ".yml"}:
                continue
            try:
                layout = load_layout(path)
            except SystemExit as exc:
                raise SystemExit(f"{exc}") from None
            _record(layout, path)

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
        _record(layout, path)

    return LayoutStore(layouts, source_paths=source_paths)


# ---------------------------------------------------------------------------
# Layout write API (issues #99 / #84 / #85)
# ---------------------------------------------------------------------------
#
# These helpers sit below the HTTP write endpoints (``PUT /layouts/{id}`` save
# and ``POST /layouts`` create). They own three concerns the endpoints share:
#
# * turning a layout's primary ``match`` token into a filesystem-safe filename
#   stem (``slugify_layout_id``);
# * comment-preserving reconcile of a client-supplied full snapshot onto a
#   fresh on-disk YAML re-read, widgets matched by ``id`` and maps recursed,
#   other sequences replaced atomically (``reconcile_and_write_layout``);
# * the atomic temp-write + ``os.replace`` that lets the ``watchfiles`` watcher
#   pick up the edit as a single event.
#
# The daemon never interprets comments; it only carries them along so a layout
# the user hand-authored keeps its prose when the editor saves a one-field
# change. ``ruamel.yaml`` is the round-trip surface; Pydantic validates the
# snapshot before it reaches here so the data is already schema-conformant.


_SLUG_NON_SAFE = re.compile(r"[^a-z0-9._-]+")
_SLUG_DASH_RUN = re.compile(r"-{2,}")


def slugify_layout_id(match_token: str) -> str:
    """Filesystem-safe filename stem for a layout derived from ``match[0]``.

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
    (``    kind: button``), matching every shipping layout. ruamel's default
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


# Top-level Layout fields that are maps (recurse) vs. sequences-of-widgets
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
        # leaves the rest of the layout byte-identical, so this keeps an
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


def reconcile_and_write_layout(path: Path, snapshot: dict) -> None:
    """Reconcile ``snapshot`` onto a fresh disk re-read and write atomically.

    ``snapshot`` is the post-:class:`Layout`-validation JSON dict from the
    client (a full-layout snapshot). The layout's ``id`` field is dropped
    before writing — on disk the canonical id is always ``match[0]`` (see
    :func:`load_layout`), never a stored ``id:`` key, so the shipping
    layouts (which omit it) and editor-written layouts round-trip
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
    convention (every shipping layout) omits ``id:`` and lets
    :func:`load_layout` derive it from ``match[0]``. Dropping it keeps the
    canonical re-read, the watcher's reload, and a hand-authored file
    indistinguishable.
    """
    cleaned = dict(snapshot)
    cleaned.pop("id", None)
    return cleaned


Widget.model_rebuild()
