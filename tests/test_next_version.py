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

DAY = date(2026, 11, 14)


def test_first_release_of_the_day_is_zero() -> None:
    assert next_version.next_tag(DAY, []) == "v20261114.0"


def test_counts_up_within_the_day() -> None:
    assert next_version.next_tag(DAY, ["v20261114.0", "v20261114.1"]) == "v20261114.2"


def test_takes_the_highest_not_the_last() -> None:
    assert next_version.next_tag(DAY, ["v20261114.9", "v20261114.10", "v20261114.2"]) == "v20261114.11"


def test_a_new_day_restarts_at_zero() -> None:
    assert next_version.next_tag(date(2026, 11, 15), ["v20261114.0", "v20261114.1"]) == "v20261115.0"


def test_month_and_day_are_zero_padded() -> None:
    # One integer, so the padding is part of the number and tags sort by date.
    assert next_version.next_tag(date(2027, 1, 5), []) == "v20270105.0"


def test_ignores_release_candidates_and_other_tags() -> None:
    tags = [
        "v20261114.0-rc1",  # an rc doesn't use up the number
        "v2026.11.0",  # the short-lived YYYY.M.MICRO format
        "v0.0.0-rc3",  # pre-CalVer rehearsal tags
        "verify/61-touch-targets",
        "v20261113.4",  # yesterday
        "v20251114.7",  # same day, last year
    ]
    assert next_version.next_tag(DAY, tags) == "v20261114.0"
