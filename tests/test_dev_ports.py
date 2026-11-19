"""Dev tooling defaults stay off the port an installed deckd uses.

An installed deckd — the NixOS/home-manager service, the macOS app, the Linux
tarball — listens on :8765. Dev daemons from a checkout default to :8865 so a
machine can run both without the checkout getting renumbered or `just dev`
failing on address-in-use. Every place that hard-codes the dev default has to
agree, which is what this pins.
"""
from __future__ import annotations

import re
from pathlib import Path

from deckd import app_bundle, dev

REPO_ROOT = Path(__file__).parent.parent
PROD_PORT = 8765
DEV_PORT = 8865


def test_prod_default_is_unchanged() -> None:
    assert app_bundle.DEFAULT_PORT == PROD_PORT


def test_dev_supervisor_defaults_to_the_dev_port() -> None:
    assert dev.DEFAULT_PORT == DEV_PORT


def test_justfile_defaults_to_the_dev_port() -> None:
    text = (REPO_ROOT / "Justfile").read_text()
    m = re.search(r'DECKD_PORT := env_var_or_default\("DECKD_PORT", "(\d+)"\)', text)
    assert m and int(m.group(1)) == DEV_PORT


def test_worktree_base_is_the_dev_port() -> None:
    text = (REPO_ROOT / "scripts" / "worktree.sh").read_text()
    m = re.search(r"^BASE_DECKD=(\d+)$", text, re.M)
    assert m and int(m.group(1)) == DEV_PORT


def test_vite_proxies_to_the_dev_port_by_default() -> None:
    text = (REPO_ROOT / "client" / "vite.config.ts").read_text()
    m = re.search(r'DECKD_UPSTREAM \?\? "http://127\.0\.0\.1:(\d+)"', text)
    assert m and int(m.group(1)) == DEV_PORT
