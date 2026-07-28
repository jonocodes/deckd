"""Verify links in AGENTS.md and agent-facing docs resolve to existing files."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
DOCS_DIR = REPO_ROOT / "docs"

DOCS_TO_CHECK = [
    REPO_ROOT / "AGENTS.md",
    DOCS_DIR / "ONBOARDING.md",
    DOCS_DIR / "ARCHITECTURE.md",
    DOCS_DIR / "adr" / "README.md",
]

MARKDOWN_LINK = re.compile(r"\]\(([^)]+)\)")


def _resolve(target: str, source_dir: Path) -> Path | None:
    """Resolve a markdown link target relative to its source doc's directory."""
    if "://" in target or target.startswith("mailto:"):
        return None
    if target.startswith("/"):
        resolved = REPO_ROOT / target.lstrip("/")
    else:
        resolved = (source_dir / target).resolve()

    if target.count("#") == 1:
        anchor = target.split("#", 1)[1]
        resolved = (source_dir / target.split("#", 1)[0]).resolve()
    else:
        anchor = None

    if not resolved.exists():
        return resolved

    if anchor is not None and resolved.suffix == ".md":
        try:
            text = resolved.read_text()
        except OSError:
            return resolved
        pattern = re.compile(rf"^(#+)\s+.*{re.escape(anchor)}", re.MULTILINE | re.IGNORECASE)
        if not pattern.search(text):
            return resolved
    return None


@pytest.mark.parametrize("doc_path", DOCS_TO_CHECK)
def test_doc_exists(doc_path: Path) -> None:
    assert doc_path.exists(), f"{doc_path.relative_to(REPO_ROOT)} must exist"


@pytest.mark.parametrize("doc_path", DOCS_TO_CHECK)
def test_links_resolve(doc_path: Path) -> None:
    if not doc_path.exists():
        pytest.skip(f"{doc_path.relative_to(REPO_ROOT)} does not exist")
    source_dir = doc_path.parent
    text = doc_path.read_text()
    broken: list[str] = []
    for match in MARKDOWN_LINK.finditer(text):
        target = match.group(1)
        missing = _resolve(target, source_dir)
        if missing is not None:
            broken.append(f"  {target!r} -> {missing.relative_to(REPO_ROOT)} not found")
    assert not broken, (
        f"Broken links in {doc_path.relative_to(REPO_ROOT)}:\n" + "\n".join(broken)
    )
