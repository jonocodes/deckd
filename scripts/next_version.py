"""Print the next deckd release tag (ADR-0013: CalVer, ``vYYYY.M.MICRO``).

    python scripts/next_version.py          # e.g. v2026.11.0, then v2026.11.1

The year and month are today's (UTC); MICRO counts releases within that
month, starting at 0. Only final release tags count — a release candidate
(``v2026.11.0-rc1``) doesn't use up its number. ``just release`` calls this.
"""
from __future__ import annotations

import re
import subprocess
import sys
from collections.abc import Iterable
from datetime import date, datetime, timezone


def next_tag(today: date, tags: Iterable[str]) -> str:
    """The next ``vYYYY.M.MICRO`` tag for ``today``, given existing ``tags``."""
    pattern = re.compile(rf"v{today.year}\.{today.month}\.(\d+)")
    micros = [int(m.group(1)) for tag in tags if (m := pattern.fullmatch(tag))]
    micro = max(micros) + 1 if micros else 0
    return f"v{today.year}.{today.month}.{micro}"


def main() -> int:
    tags = subprocess.run(
        ["git", "tag", "--list", "v*"], capture_output=True, text=True, check=True
    ).stdout.split()
    print(next_tag(datetime.now(timezone.utc).date(), tags))
    return 0


if __name__ == "__main__":
    sys.exit(main())
