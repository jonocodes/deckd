"""Drift guard: the CI ladder and the local ladder must be the same ladder (#77).

`just test-all` is documented as the one-command reproduction of CI
(docs/ONBOARDING.md, "Verification ladder"). That promise only holds while the
ubuntu `test` job in `.github/workflows/ci.yml` and the `test-all` recipe stay
in lockstep: same steps, same order, same numbering. This test reads both
sources and fails on structural drift — a step added, removed, reordered, or
renumbered on one side only.

It checks the ordered *subsystem keys* (below), not the full human-readable
labels or the commands they run, so rewording a description doesn't trip it.
CI's macOS / Nix / 3.12 jobs have no local twin and are deliberately out of
scope.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import NamedTuple

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
JUSTFILE = REPO_ROOT / "Justfile"

# Canonical subsystem keys, in ladder order. Each must appear (as a substring)
# in the corresponding step label on both sides. Add one here only when adding
# the same step to both `ci.yml`'s `test` job and the `test-all` recipe.
LADDER_KEYS = [
    "pyright",
    "pytest",
    "focus-wire",
    "tsc",
    "vitest",
    "playwright",
    "smoke",
    "eslint",
]

CI_STEP_RE = re.compile(r"^\[(\d+)/(\d+)\]\s+(.*)$")
JUST_STEP_RE = re.compile(r'STEP="(\d+)/(\d+)\s+(.*?)"')


class Step(NamedTuple):
    number: int
    total: int
    label: str


def _ci_steps() -> list[Step]:
    workflow = yaml.safe_load(CI_WORKFLOW.read_text())
    steps = []
    for step in workflow["jobs"]["test"]["steps"]:
        match = CI_STEP_RE.match(step.get("name", ""))
        if match:
            steps.append(Step(int(match.group(1)), int(match.group(2)), match.group(3)))
    return sorted(steps)


def _just_steps() -> list[Step]:
    return [
        Step(int(m.group(1)), int(m.group(2)), m.group(3))
        for m in JUST_STEP_RE.finditer(JUSTFILE.read_text())
    ]


def test_ci_and_local_ladder_step_for_step() -> None:
    ci = _ci_steps()
    just = _just_steps()

    assert len(ci) == len(LADDER_KEYS), f"CI ladder drifted: {[s.label for s in ci]}"
    assert len(just) == len(LADDER_KEYS), (
        f"local ladder drifted: {[s.label for s in just]}"
    )

    for index, (ci_step, just_step, key) in enumerate(
        zip(ci, just, LADDER_KEYS), start=1
    ):
        assert ci_step.number == just_step.number == index, f"numbering drift at {key}"
        assert ci_step.total == just_step.total == len(LADDER_KEYS), (
            f"step count drift at {key}"
        )
        assert key in ci_step.label, f"CI step {ci_step.label!r} does not name {key!r}"
        assert key in just_step.label, (
            f"local step {just_step.label!r} does not name {key!r}"
        )
