"""Tests for scripts/next_version.py — the next CalVer release tag (ADR-0013)."""
from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("next_version", ROOT / "scripts" / "next_version.py")
assert _spec and _spec.loader
next_version = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(next_version)

NOV = date(2026, 11, 14)


def test_first_release_of_the_month_is_micro_zero() -> None:
    assert next_version.next_tag(NOV, []) == "v2026.11.0"


def test_counts_up_within_the_month() -> None:
    assert next_version.next_tag(NOV, ["v2026.11.0", "v2026.11.1"]) == "v2026.11.2"


def test_takes_the_highest_not_the_last() -> None:
    assert next_version.next_tag(NOV, ["v2026.11.9", "v2026.11.10", "v2026.11.2"]) == "v2026.11.11"


def test_new_month_restarts_at_zero() -> None:
    assert next_version.next_tag(date(2026, 12, 1), ["v2026.11.0", "v2026.11.1"]) == "v2026.12.0"


def test_month_is_not_zero_padded() -> None:
    # v2027.1.0, not v2027.01.0: leading zeros aren't valid in SemVer-shaped
    # tooling and PEP 440 would normalise them away, so the tag and the
    # package version would disagree.
    assert next_version.next_tag(date(2027, 1, 5), []) == "v2027.1.0"


def test_ignores_release_candidates_and_other_tags() -> None:
    tags = [
        "v2026.11.0-rc1",  # an rc doesn't use up the number
        "v0.0.0-rc3",  # pre-CalVer rehearsal tags
        "v0.0.0-test-115",
        "verify/61-touch-targets",
        "v2026.10.4",  # last month
        "v2025.11.7",  # same month, last year
    ]
    assert next_version.next_tag(NOV, tags) == "v2026.11.0"
