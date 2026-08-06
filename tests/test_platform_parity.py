"""Doc ↔ ``capabilities()`` drift guard (issue #136).

``docs/PLATFORM-PARITY.md`` is the manually reconciled view of what
works where, and it states its own invariant: *if a row disagrees with*
``capabilities()``\\ *, the code wins — and that disagreement is a bug*
(it's how #133 and #135 were found, by a human reading the doc against
the code).

This test automates that read. It treats the doc's ``## Capability
matrix`` as the spec and asserts every backend's ``capabilities()``
advertises a compositor-axis flag **iff** the doc row marks it ✓. A ✓
the code lacks, or a flag the doc marks ✗, fails here — so a capability
change must update the table in the same PR, and dishonest advertisement
(the #133 class) cannot merge.

Scope: only the three compositor-axis capabilities gated by
``capabilities()`` (``watch_active_app`` / ``watch_windows`` /
``raise_window``). The input-injection rows below them are informational
(no capability flag) and are not checked. See the issue's "Scope /
decisions" for why. Live-bus verification of the rows is out of scope
(that's the #129–#131 harness in ``docs/TESTING.md``); this check is
pure and fast.

macOS is enumerated by advertised flags only — ``MacFocusBackend()``
constructs without PyObjC and ``capabilities()`` never touches Quartz —
so this runs on non-Darwin CI unchanged.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from deckd.platform import (
    GnomeShellFocusBackend,
    KdeFocusBackend,
    X11FocusBackend,
)
from deckd.platform_macos import MacFocusBackend

_DOC = Path(__file__).resolve().parents[1] / "docs" / "PLATFORM-PARITY.md"

# The three compositor-axis capabilities the daemon gates on
# ``capabilities()``. Keyed by the substring the doc's leading table
# cell uses to name each row (the ``(`flag`)`` in the "Capability"
# column).
_GATED_CAPABILITIES = ("watch_active_app", "watch_windows", "raise_window")

# Map each matrix column to the backend that column describes. The value
# is a substring that uniquely identifies the column header; the backend
# is constructed with no arguments (the flags are static, so no live
# mechanism — GNOME extension, KWin bus, xdotool, Quartz — is touched).
# NB: the needles must be unambiguous against every header cell — the
# GNOME column is headed "GNOME (Wayland/X11)", so a bare "X11" needle
# would match it before the real "X11 (generic)" column.
_COLUMN_BACKENDS = {
    "GNOME (Wayland": GnomeShellFocusBackend,
    "KDE": KdeFocusBackend,
    "X11 (generic)": X11FocusBackend,
    "macOS": MacFocusBackend,
}


def _matrix_rows() -> list[list[str]]:
    """Return the ``## Capability matrix`` table as a list of cell rows
    (header + separator + data), each already split on ``|`` and
    stripped. Fails loudly if the section or table can't be found so a
    doc reformat surfaces as a test failure rather than a silent skip."""
    text = _DOC.read_text(encoding="utf-8")
    section = re.search(
        r"^## Capability matrix\s*$(.*?)^## ", text, re.MULTILINE | re.DOTALL
    )
    assert section, f"'## Capability matrix' section not found in {_DOC}"
    rows: list[list[str]] = []
    for line in section.group(1).splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        rows.append(cells)
    assert len(rows) >= 3, f"capability matrix table not found in {_DOC}"
    return rows


def _column_index(header: list[str], needle: str) -> int:
    for idx, cell in enumerate(header):
        if needle in cell:
            return idx
    raise AssertionError(f"column {needle!r} not found in matrix header {header!r}")


def _cell_says_supported(cell: str) -> bool:
    """A matrix cell advertises the capability iff it starts with ✓.
    ✗ (not available) and ◑ (partial) are both "not gated on"."""
    assert cell, "empty matrix cell"
    marker = cell[0]
    assert marker in "✓✗◑", f"unexpected cell marker in {cell!r}"
    return marker == "✓"


def _doc_expectations() -> dict[str, dict[str, bool]]:
    """Parse the matrix into ``{column_name: {capability: supported}}``
    for the three gated capabilities."""
    rows = _matrix_rows()
    header = rows[0]
    col_idx = {name: _column_index(header, name) for name in _COLUMN_BACKENDS}
    expectations: dict[str, dict[str, bool]] = {name: {} for name in _COLUMN_BACKENDS}
    for row in rows[2:]:  # skip header + separator
        label = row[0]
        for cap in _GATED_CAPABILITIES:
            if f"`{cap}`" in label:
                for name, idx in col_idx.items():
                    expectations[name][cap] = _cell_says_supported(row[idx])
    for name, caps in expectations.items():
        missing = set(_GATED_CAPABILITIES) - set(caps)
        assert not missing, f"matrix has no row for {sorted(missing)} (column {name})"
    return expectations


_EXPECTATIONS = _doc_expectations()


@pytest.mark.parametrize("column, backend_cls", list(_COLUMN_BACKENDS.items()))
def test_backend_capabilities_match_doc_matrix(column, backend_cls) -> None:
    """Each backend advertises a gated capability iff the doc row is ✓."""
    advertised = backend_cls().capabilities()
    doc = _EXPECTATIONS[column]
    for cap in _GATED_CAPABILITIES:
        expected = doc[cap]
        actual = cap in advertised
        assert actual == expected, (
            f"{backend_cls.__name__} ({column}): doc marks {cap!r} "
            f"{'✓' if expected else '✗'} but capabilities() "
            f"{'advertises' if actual else 'omits'} it. "
            f"Reconcile daemon/deckd/platform*.py with docs/PLATFORM-PARITY.md "
            f"(the code wins — see #133 / #135)."
        )
