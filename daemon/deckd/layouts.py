from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .platform import AppInfo


class Widget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: str
    label: str | None = None
    icon: str | None = None
    grid: list[int] = Field(min_length=4, max_length=4)
    # Optional CSS colour string applied as the button's background. Any
    # value the browser accepts is fine ("#1e3a8a", "rebeccapurple",
    # "hsl(...)"). Client trust: layouts are user-owned config, not user
    # input, so no sanitisation is needed.
    color: str | None = None
    action: "Action | None" = None


class Action(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str | None = None
    shell: str | None = None
    dbus: str | None = None
    terminal: bool | str | None = None


class Layout(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = ""
    match: list[str] = Field(default_factory=list)
    widgets: list[Widget] = Field(default_factory=list)
    jogstrip: bool = True

    def matches(self, app: AppInfo) -> bool:
        """True if this layout's ``match`` list covers the given app.

        A match is satisfied when any of the focused app's identifiers
        (``app_id``, ``wm_class``) is in the layout's ``match`` list. The
        special token ``default`` is *not* considered a real match — it is
        only the fallback. Layouts whose ``match`` list is empty never
        match by app identity.
        """
        if not self.match or self.match == ["default"]:
            return False
        return (app.app_id in self.match) or (app.wm_class in self.match)


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

    def default(self) -> Layout:
        for layout in self._layouts:
            if "default" in layout.match:
                return layout
        raise KeyError(
            "no default layout loaded (expected a layout with match: [default])"
        )


def resolve_layout(store: LayoutStore, app: AppInfo) -> Layout:
    """Pick the layout for the given focused app.

    First layout whose ``match`` list contains the app's ``app_id`` or
    ``wm_class`` wins. If nothing matches, the layout with ``default`` in
    its match list is returned.
    """
    for layout in store.layouts:
        if layout.matches(app):
            return layout
    return store.default()


def load_layouts(layouts_dir: Path) -> LayoutStore:
    """Load every ``*.yaml`` / ``*.yml`` file in ``layouts_dir``.

    A missing directory is a fatal startup error (matches the existing
    single-file behavior: bad config = ``SystemExit``). Non-yaml files in
    the directory are ignored.
    """
    if not layouts_dir.is_dir():
        raise SystemExit(f"layouts directory not found: {layouts_dir}")

    layouts: list[Layout] = []
    for path in sorted(layouts_dir.glob("*.y*ml")):
        if path.suffix not in {".yaml", ".yml"}:
            continue
        try:
            layout = load_layout(path)
        except SystemExit as exc:
            raise SystemExit(f"{exc}") from None
        layouts.append(layout)
    return LayoutStore(layouts)


Widget.model_rebuild()
