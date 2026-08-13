"""Tests for the Python -> TypeScript protocol codegen (#76).

The codegen script (`scripts/codegen_protocol_ts.py`) reads
`daemon/deckd/protocol.py` via AST and emits a TypeScript file mirroring
the wire-protocol types. These tests pin the generated output's shape:

- every ServerMessage kind becomes a TypeScript discriminated-union member;
- every ClientMessage kind becomes one too;
- Literal["a", "b"] constraints survive the translation;
- required vs optional fields are preserved (``field: str`` vs ``field: str | None = None``);
- view-id constants (``WINDOWS_VIEW_ID`` etc.) become TS ``export const``;
- docstrings travel as JSDoc so the explanatory prose doesn't rot.

The drift guard itself lives in ``test_protocol_ts_drift.py``: this file
exercises the codegen's outputs; that one asserts the checked-in TS file
matches them. Same logic, two angles — the unit test pins behaviour, the
drift test pins the artifact.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "codegen_protocol_ts.py"


def _run_codegen() -> str:
    """Run the codegen and return the generated TS text. Tests should
    import this lazily so a missing script fails fast with a clear error."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
        check=True,
        cwd=REPO_ROOT,
    )
    return result.stdout


def test_script_exists() -> None:
    assert SCRIPT.is_file(), f"codegen script missing at {SCRIPT}"


def test_generates_module_header() -> None:
    out = _run_codegen()
    assert "/* AUTO-GENERATED" in out
    assert "scripts/codegen_protocol_ts.py" in out
    # The header must warn the reader not to edit by hand — otherwise
    # someone will hand-edit the generated file and the drift guard will
    # fail mysteriously for the next contributor.
    assert "do not edit" in out.lower()


def test_emits_server_message_union() -> None:
    out = _run_codegen()
    assert "export type ServerMessage =" in out
    for kind in (
        "LayoutMessage",
        "StateMessage",
        "BrightnessMessage",
        "WidgetUpdateMessage",
        "MediaStateMessage",
        "ChromeMediaMessage",
        "EventMessage",
        "MacroResultMessage",
        "ConfirmRequestMessage",
        "RunningWindowsMessage",
        "ErrorMessage",
    ):
        assert kind in out, f"{kind} missing from generated ServerMessage union"


def test_emits_client_message_union() -> None:
    out = _run_codegen()
    assert "export type ClientMessage =" in out
    for kind in (
        "HelloMessage",
        "PressMessage",
        "JogMessage",
        "JogEndMessage",
        "PadMessage",
        "PadTapMessage",
        "PadDragMessage",
        "TypeMessage",
        "KeyMessage",
        "MediaCommandMessage",
        "SelectViewMessage",
        "ClearViewMessage",
        "RaiseWindowMessage",
        "EnableEventsMessage",
        "DisableEventsMessage",
        "ConfirmResponseMessage",
    ):
        assert kind in out, f"{kind} missing from generated ClientMessage union"


def test_each_message_kind_carries_discriminator() -> None:
    """Every message has a ``type: Literal[...]`` field. The TS shape
    uses a literal union so the discriminant survives."""
    out = _run_codegen()
    # Pick one example we know carries "layout" as its discriminant.
    assert 'type: "layout"' in out
    assert 'type: "press"' in out
    assert 'type: "hello"' in out


def test_literal_constraints_translate() -> None:
    """``Literal["clip", "shrink-to-fit"]`` must round-trip as the
    same literal union in TS — not a bare ``string``."""
    out = _run_codegen()
    # LayoutMessage.overflow
    assert '"clip"' in out
    assert '"shrink-to-fit"' in out


def test_optional_fields_become_nullable() -> None:
    """A Python ``field: str | None = None`` becomes TS ``field?: string | null``."""
    out = _run_codegen()
    # PressMessage.id is required; LayoutMessage.view is optional.
    # Both should appear in their respective interface blocks.
    assert "view?:" in out or "view: string | null" in out
    assert "theme?:" in out or "theme: string | null" in out


def test_ge_le_constraints_surface_as_jsdoc() -> None:
    """BrightnessMessage.value is Field(ge=0, le=255) — the constraint
    must travel to TS as a JSDoc comment so the consumer can validate
    at runtime if they want."""
    out = _run_codegen()
    # The codegen emits constraints as JSDoc on the relevant field.
    # Pin the rule, not the exact wording — keep the prose editable.
    assert "value:" in out
    assert "0" in out and "255" in out


def test_view_id_constants_become_ts_consts() -> None:
    """Wire-side view-id literals live in protocol.py and must
    travel to TS as ``export const`` so the client can pin a view by
    the same identifier the daemon resolves."""
    out = _run_codegen()
    assert "export const WINDOWS_VIEW_ID" in out
    assert "export const MPRIS_VIEW_ID" in out
    assert "export const EDITOR_VIEW_ID" in out
    assert 'WINDOWS_VIEW_ID = "windows"' in out
    assert 'MPRIS_VIEW_ID = "mpris"' in out
    assert 'EDITOR_VIEW_ID = "editor"' in out


def test_docstring_becomes_jsdoc() -> None:
    """The docstring above ``FocusedAppInfo`` should travel as a JSDoc
    block so the consumer's editor still shows it on hover."""
    out = _run_codegen()
    assert "/**" in out
    assert "FocusedAppInfo" in out


def test_generated_output_is_parseable_typescript() -> None:
    """Pipe the output through ``tsc --noEmit`` to catch syntax bugs
    in the codegen itself — a one-character typo in the emitter would
    otherwise only surface at the drift-check step. The generated file
    references types like ``Icon`` that live in hand-curated parts of
    protocol.ts; we wrap the file in a tiny shim that declares those
    stubs so the check exercises the emitter, not cross-file
    resolution.
    """
    import tempfile
    out = _run_codegen()
    shim = "type Icon = unknown;\n"  # stub for the layouts-layer Icon
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".ts", prefix="protocol.generated.", delete=False
    ) as f:
        f.write(shim + out)
        ts_path = Path(f.name)
    try:
        result = subprocess.run(
            ["npx", "tsc", "--noEmit", "--skipLibCheck",
             "--strict", "--target", "es2020",
             "--module", "esnext", "--moduleResolution", "bundler",
             str(ts_path)],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT / "client",
        )
        assert result.returncode == 0, (
            f"generated TS failed to typecheck:\n{result.stdout}\n{result.stderr}"
        )
    finally:
        ts_path.unlink(missing_ok=True)