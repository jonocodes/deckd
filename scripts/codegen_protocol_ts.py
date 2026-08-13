"""Generate client/src/protocol.generated.ts from daemon/deckd/protocol.py (#76).

The Python module is the single authoritative source for the WebSocket
wire-protocol. This script reads its AST (no runtime imports — the
daemon's deps aren't safe to pull into a plain ``python`` invocation)
and emits a TypeScript file with:

- one ``export type Foo = { ... }`` per Pydantic ``BaseModel`` subclass,
  with the class docstring lifted to JSDoc;
- ``Literal[...]`` Python types translated to literal unions in TS;
- ``X | None`` Python types translated to ``X | null`` in TS;
- ``list[X]`` translated to ``X[]``;
- module-level constants (``WINDOWS_VIEW_ID`` etc.) emitted as
  ``export const``;
- the two ``Annotated[Union[...], Field(discriminator="type")]`` aliases
  (``ServerMessage``, ``ClientMessage``) emitted as discriminated unions.

Run by hand when you change the protocol:

    python scripts/codegen_protocol_ts.py --out client/src/protocol.generated.ts
    just check-protocol    # diffs the generated file against the checked-in one
    just gen-protocol     # regenerates and writes the file in place

The drift guard lives in tests/test_protocol_ts_drift.py.
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_PY = REPO_ROOT / "daemon" / "deckd" / "protocol.py"
DEFAULT_OUT = REPO_ROOT / "client" / "src" / "protocol.ts"


HEADER = """\
/* AUTO-GENERATED from daemon/deckd/protocol.py by
 * scripts/codegen_protocol_ts.py — do not edit by hand.
 *
 * To change the wire protocol, edit daemon/deckd/protocol.py and
 * regenerate via `just check-protocol` (or this script directly).
 * The drift guard fails CI when the two diverge.
 */

"""


def _read_source() -> str:
    return PROTOCOL_PY.read_text()


def _module(tree: ast.Module) -> list[ast.stmt]:
    """Skip the ``from __future__ import annotations`` line — it's
    irrelevant to the generated artifact — and return the rest in
    order. The emitter walks this list top-to-bottom."""
    return [
        stmt
        for stmt in tree.body
        if not (
            isinstance(stmt, ast.ImportFrom)
            and getattr(stmt, "module", "") == "__future__"
        )
    ]


def _docstring(stmt: ast.stmt) -> str | None:
    """Pull the class/module-level docstring. ``ast.get_docstring`` would
    work too, but going through the AST node directly makes the emitter
    explicit about which constructs carry prose."""
    if not isinstance(stmt, (ast.ClassDef, ast.Module)):
        return None
    if not stmt.body:
        return None
    first = stmt.body[0]
    if not isinstance(first, ast.Expr):
        return None
    if not isinstance(first.value, ast.Constant) or not isinstance(first.value.value, str):
        return None
    return first.value.value


def _emit_jsdoc(text: str, indent: str) -> str:
    """Convert a Python docstring to a JSDoc block. Indent applies to
    continuation lines so the block lines up under its anchor."""
    lines = text.splitlines() or [""]
    out = [f"{indent}/**"]
    for line in lines:
        if not line:
            out.append(f"{indent} *")
        else:
            out.append(f"{indent} * {line}")
    out.append(f"{indent} */")
    return "\n".join(out)


def _annotation_to_ts(node: ast.AST | None) -> str:
    """Translate a Python type annotation AST to its TS counterpart.
    Limited to the subset the wire protocol actually uses — Literals,
    Optional/Union, list, dict, builtin scalars. Anything else falls
    back to ``unknown`` so the drift guard trips and a human decides
    how to widen the emitter."""
    if node is None:
        return "unknown"
    if isinstance(node, ast.Name):
        # Bare names are primitive types or self-refs we don't model.
        # ``dict`` shows up as ``list[dict]`` / ``dict`` in the protocol —
        # it's an opaque blob from the wire's perspective. ``Icon`` lives
        # in the layouts layer (ADR-0006: the daemon relays it opaquely);
        # the consumer file (``client/src/protocol.ts``) declares the
        # real shape — the generated file carries the wire types only
        # and treats icon refs as a Record. The consumer redeclares the
        # shape where it matters (Widget, etc.).
        mapping = {
            "str": "string",
            "int": "number",
            "float": "number",
            "bool": "boolean",
            "dict": "Record<string, unknown>",
            "Icon": "Record<string, unknown>",
        }
        return mapping.get(node.id, node.id)
    if isinstance(node, ast.Constant):
        # ``Literal["x"]`` shows up as a bare Constant.
        return json.dumps(node.value)
    if isinstance(node, ast.Subscript):
        # ``list[X]``, ``dict[K, V]``, ``Literal[a, b, ...]``,
        # ``Optional[X]`` (Union[X, None]), ``Union[A, B]``,
        # ``tuple[A, ...]`` (treated as a typed list).
        slc = node.slice
        base = ast.unparse(node.value) if hasattr(ast, "unparse") else _name_fallback(node.value)
        if base == "list":
            return f"{_annotation_to_ts(slc)}[]"
        if base == "dict":
            if isinstance(slc, ast.Tuple) and len(slc.elts) == 2:
                return f"{{ [key: {_annotation_to_ts(slc.elts[0])}]: {_annotation_to_ts(slc.elts[1])} }}"
            return "Record<string, unknown>"
        if base == "Literal":
            if isinstance(slc, ast.Tuple):
                return " | ".join(_annotation_to_ts(elt) for elt in slc.elts)
            return _annotation_to_ts(slc)
        if base == "Optional":
            return f"{_annotation_to_ts(slc)} | null"
        if base == "Union":
            if isinstance(slc, ast.Tuple):
                return " | ".join(_annotation_to_ts(elt) for elt in slc.elts)
            return _annotation_to_ts(slc)
        if base == "tuple":
            return "unknown[]"
        return f"unknown /* unparsed: {base} */"
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        # PEP 604 ``X | Y`` unions.
        return " | ".join(_annotation_to_ts(elt) for elt in [node.left, node.right])
    if isinstance(node, ast.Tuple):
        return " | ".join(_annotation_to_ts(elt) for elt in node.elts)
    return "unknown"


def _name_fallback(node: ast.AST) -> str:
    """Last-resort renderer for ``ast.unparse``-less Python builds."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_name_fallback(node.value)}.{node.attr}"
    return "unknown"





def _field_constraints(field: ast.AnnAssign) -> str:
    """Lift Pydantic ``Field(ge=…, le=…, min_length=…, …)`` keyword
    arguments into a short JSDoc hint so the TS consumer can validate
    at runtime if it wants. We only render the constraints we actually
    use in the protocol — keep the rule narrow."""
    if field.value is None or not isinstance(field.value, ast.Call):
        return ""
    hints: list[str] = []
    for kw in field.value.keywords:
        if kw.arg in {"ge", "le", "gt", "lt", "min_length", "max_length"}:
            val = ast.literal_eval(kw.value) if hasattr(ast, "literal_eval") else _literal(kw.value)
            if val is not None:
                hints.append(f"{kw.arg}={val}")
    return ", ".join(hints)


def _literal(node: ast.AST):
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub) and isinstance(node.operand, ast.Constant):
        return -node.operand.value
    return None


def _emit_class(cls: ast.ClassDef) -> str:
    """Render a Pydantic model as a TS interface. The annotation type
    on each field drives the TS shape; the default value (if any) marks
    the field optional."""
    out: list[str] = []
    doc = _docstring(cls)
    if doc:
        out.append(_emit_jsdoc(doc, ""))
    out.append(f"export type {cls.name} = {{")
    fields = [s for s in cls.body if isinstance(s, ast.AnnAssign) and isinstance(s.target, ast.Name)]
    class_end = getattr(cls, "end_lineno", None)
    for i, stmt in enumerate(fields):
        next_stmt = fields[i + 1] if i + 1 < len(fields) else None
        field_name = stmt.target.id
        ts_type = _annotation_to_ts(stmt.annotation)
        # Pydantic: ``field: Type = "value"`` is a default;
        # ``field: Type = Field(...)`` is a constraint marker that
        # may also carry a default via ``default=`` kwarg. Distinguish
        # by inspecting the AST so:
        #   - ``field: Type = "literal"`` → has default
        #   - ``field: Type = Field(constraint=...)`` → no default (required)
        #   - ``field: Type = Field(default=None, ...)`` → has default (optional)
        has_default = stmt.value is not None
        if isinstance(stmt.value, ast.Call) and isinstance(stmt.value.func, ast.Name) and stmt.value.func.id == "Field":
            has_default = any(
                kw.arg == "default" and kw.value is not None
                for kw in stmt.value.keywords
            )
        # A field with a default value (Python ``= ...``) is optional on
        # the wire — the daemon may omit it. Emit ``?`` regardless of
        # whether the type is nullable; the daemon treats absent and
        # ``None`` interchangeably for nullable fields, so the TS shape
        # accepts both forms.
        optional = has_default
        constraints = _field_constraints(stmt)
        jsdoc = ""
        if constraints:
            jsdoc = _emit_jsdoc(f"constraint: {constraints}", "  ")
        else:
            comment = _trailing_comment(stmt, next_stmt, upper_bound=class_end)
            if comment:
                jsdoc = _emit_jsdoc(comment, "  ")
        marker = "?" if optional else ""
        out.append(jsdoc)
        out.append(f"  {field_name}{marker}: {ts_type};")
    out.append("};")
    return "\n".join(out)


def _trailing_comment(
    stmt: ast.AnnAssign,
    next_stmt: ast.stmt | None = None,
    upper_bound: int | None = None,
) -> str | None:
    """Best-effort: a ``#`` comment between an annotation and the next
    statement in the source. ``ast`` doesn't carry comments, so we re-read
    the source and look at the line range. protocol.py places the prose
    on the lines between the field's annotation and the next field's
    annotation — grab exactly that window.

    ``upper_bound`` is the class body's ``end_lineno`` so the scan
    stops before the closing ``}`` — without it, the LAST field of a
    class borrows the next class's first comment."""
    lines = _source_lines
    if lines is None:
        return None
    end = getattr(stmt, "end_lineno", None)
    if end is None:
        return None
    # The next sibling's ``lineno`` (1-indexed) tells us where its
    # annotation starts. Cap our scan there so we don't borrow the
    # next field's leading comment.
    next_start: int | None = None
    if next_stmt is not None:
        next_start = getattr(next_stmt, "lineno", None)
        if next_start is not None:
            next_start -= 1  # convert to 0-indexed
    if next_start is not None:
        upper = next_start
    elif upper_bound is not None:
        upper = upper_bound
    else:
        upper = min(end + 20, len(lines))
    collected: list[str] = []
    for i in range(end, upper):
        line = lines[i]
        stripped = line.lstrip()
        if not stripped.startswith("#"):
            if collected:
                # Comment block ended; stop walking even if blank lines
                # follow — protocol.py uses comments + a blank separator,
                # so a blank line signals end-of-comment.
                break
            continue
        collected.append(stripped.lstrip("# ").rstrip())
    return "\n".join(collected) if collected else None


# Populated by ``generate()`` so ``_trailing_comment`` can index into
# the source without re-reading it on every call.
_source_lines: list[str] | None = None


def _emit_const(stmt: ast.AnnAssign | ast.Assign) -> str | None:
    """A module-level ``NAME = "value"`` becomes ``export const NAME = "value";``.
    Works for both ``NAME: str = "value"`` (``AnnAssign``) and bare
    ``NAME = "value"`` (``Assign``) — the protocol uses the latter for
    the view-id constants."""
    if not isinstance(stmt, (ast.AnnAssign, ast.Assign)):
        return None
    if isinstance(stmt, ast.Assign):
        if len(stmt.targets) != 1 or not isinstance(stmt.targets[0], ast.Name):
            return None
        target = stmt.targets[0]
        value = stmt.value
    else:
        if not isinstance(stmt.target, ast.Name):
            return None
        target = stmt.target
        value = stmt.value
    if value is None or not isinstance(value, ast.Constant) or not isinstance(value.value, str):
        return None
    return f'export const {target.id} = {json.dumps(value.value)};'


def _emit_union_alias(stmt: ast.AnnAssign | ast.Assign) -> str | None:
    """``ServerMessage`` and ``ClientMessage`` are
    ``Annotated[Union[...], Field(discriminator="type")]`` (with
    ``from __future__ import annotations``) or, in plain-``ast`` form,
    a bare ``Assign`` whose value is the Annotated expression.
    Render the inner Union as a TS union of the member types — the
    discriminant is implicit (``type`` field on each)."""
    if isinstance(stmt, ast.Assign):
        if len(stmt.targets) != 1 or not isinstance(stmt.targets[0], ast.Name):
            return None
        target = stmt.targets[0]
        ann = stmt.value
    else:
        if not isinstance(stmt.target, ast.Name):
            return None
        target = stmt.target
        ann = stmt.annotation
    if not isinstance(ann, ast.Subscript):
        return None
    inner = _unwrap_annotated(ann)
    if not isinstance(inner, ast.Subscript):
        return None
    base_name = ast.unparse(inner.value) if hasattr(ast, "unparse") else _name_fallback(inner.value)
    if base_name != "Union":
        return None
    if not isinstance(inner.slice, ast.Tuple):
        return None
    members = " | ".join(ast.unparse(elt) for elt in inner.slice.elts)
    return f"export type {target.id} = {members};"


def _unwrap_annotated(node: ast.Subscript) -> ast.AST:
    """``Annotated[X, Y]`` arrives as a Subscript whose value is the
    Name ``Annotated`` and whose slice is a Tuple ``(X, Y)``. Return
    the first element (the inner annotation)."""
    if not isinstance(node.slice, ast.Tuple):
        return node
    return node.slice.elts[0]


def generate() -> str:
    global _source_lines
    src = _read_source()
    _source_lines = src.splitlines()
    tree = ast.parse(src)

    chunks: list[str] = [HEADER]
    for stmt in _module(tree):
        if isinstance(stmt, ast.ClassDef):
            chunks.append(_emit_class(stmt))
            chunks.append("")
            continue
        if isinstance(stmt, (ast.AnnAssign, ast.Assign)):
            const = _emit_const(stmt)
            if const:
                chunks.append(const)
                continue
            union = _emit_union_alias(stmt)
            if union:
                chunks.append(union)
                chunks.append("")
                continue
        # Ignore imports, the Annotated type alias, and bare
        # ``MprisCommandRequest`` is a BaseModel subclass so it falls
        # into the class branch above.
    return "\n".join(chunks).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Path to write the generated TS file. Default: stdout for piping.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit 1 if the generated output differs from --out (drift guard).",
    )
    args = parser.parse_args()

    out = generate()
    if args.check:
        if not args.out.exists():
            print(f"check-protocol: {args.out} missing — run the codegen first.", file=sys.stderr)
            return 2
        existing = args.out.read_text()
        if existing == out:
            return 0
        # Compute a unified diff so the operator sees exactly what drifted.
        import difflib
        diff = difflib.unified_diff(
            existing.splitlines(keepends=True),
            out.splitlines(keepends=True),
            fromfile=str(args.out),
            tofile="<generated>",
        )
        sys.stdout.writelines(diff)
        print(
            f"\ncheck-protocol: {args.out} drifted from daemon/deckd/protocol.py.\n"
            "Regenerate with: python scripts/codegen_protocol_ts.py --out client/src/protocol.ts",
            file=sys.stderr,
        )
        return 1
    if args.out:
        args.out.write_text(out)
    else:
        sys.stdout.write(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())