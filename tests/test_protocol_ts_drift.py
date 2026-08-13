"""Drift guard for the Python -> TypeScript wire-protocol codegen (#76).

The authoritative source for the WebSocket wire types is
``daemon/deckd/protocol.py``. ``scripts/codegen_protocol_ts.py`` reads
it via AST and emits ``client/src/protocol.generated.ts``. This test
runs the codegen, captures the output, and asserts the file on disk
matches byte-for-byte — so a drift in either direction (Python
changed without regen, or someone hand-edited the generated file)
trips CI immediately.

Run by hand:

    just check-protocol

which is wired into ``test-all`` and ``ci.yml``.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "codegen_protocol_ts.py"
GENERATED = REPO_ROOT / "client" / "src" / "protocol.generated.ts"


def _run_codegen() -> str:
    """Run the codegen with no --out (stdout). Tests can read it back
    as the canonical expected output."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
        check=True,
        cwd=REPO_ROOT,
    )
    return result.stdout


def test_generated_file_exists() -> None:
    assert GENERATED.is_file(), (
        f"missing generated file at {GENERATED}.\n"
        "Run: python scripts/codegen_protocol_ts.py "
        "--out client/src/protocol.generated.ts"
    )


def test_generated_file_matches_codegen() -> None:
    """The drift guard: regenerate, compare. A mismatch means someone
    touched one side without the other."""
    on_disk = GENERATED.read_text()
    fresh = _run_codegen()
    if on_disk != fresh:
        # Show the first divergent line so the operator doesn't have to
        # read a wall of diff to find what changed.
        import difflib
        diff = "".join(
            difflib.unified_diff(
                on_disk.splitlines(keepends=True),
                fresh.splitlines(keepends=True),
                fromfile=str(GENERATED),
                tofile="<codegen output>",
                n=3,
            )
        )
        raise AssertionError(
            f"{GENERATED} drifted from daemon/deckd/protocol.py.\n"
            "To fix: python scripts/codegen_protocol_ts.py "
            "--out client/src/protocol.generated.ts\n\n" + diff
        )