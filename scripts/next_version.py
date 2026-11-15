"""Print the next deckd release tag (ADR-0013: CalVer, ``vYYYYMMDD.N``).

    python scripts/next_version.py          # e.g. v20261114.0, then v20261114.1

The date is today's (UTC); N counts releases made that day, starting at 0.
Only final release tags count — a release candidate (``v20261114.0-rc1``)
doesn't use up its number. ``just release`` calls this.
"""
from __future__ import annotations

import re
import subprocess
import sys
from collections.abc import Iterable
from datetime import date, datetime, timezone


def next_tag(today: date, tags: Iterable[str]) -> str:
    """The next ``vYYYYMMDD.N`` tag for ``today``, given existing ``tags``."""
    stamp = today.strftime("%Y%m%d")
    pattern = re.compile(rf"v{stamp}\.(\d+)")
    counts = [int(m.group(1)) for tag in tags if (m := pattern.fullmatch(tag))]
    n = max(counts) + 1 if counts else 0
    return f"v{stamp}.{n}"


def main() -> int:
    tags = subprocess.run(
        ["git", "tag", "--list", "v*"], capture_output=True, text=True, check=True
    ).stdout.split()
    print(next_tag(datetime.now(timezone.utc).date(), tags))
    return 0


if __name__ == "__main__":
    sys.exit(main())
