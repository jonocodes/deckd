"""``scripts/worktree.sh`` port allocation and diagnosis, over real worktrees.

Worktree support is mostly *absence* management: a fresh ``git worktree`` has
no ``.env``, no venv and no node_modules, and every checkout defaults to the
same ports. The allocator is the part with logic worth pinning, so these tests
build actual git worktrees in a tmp dir and drive the script against them.

``adopt`` is always run with ``--no-install`` here: the dependency step is
``just setup`` (uv + npm), which needs network and minutes. What's under test
is the port bookkeeping around it.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
SCRIPT = REPO_ROOT / "scripts" / "worktree.sh"

BASE_DECKD = 8765
BASE_VITE = 5173
BASE_E2E = 8975


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


def _run(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), *args], cwd=cwd, capture_output=True, text=True
    )


def _dotenv(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            out[key.strip()] = value.strip()
    return out


@pytest.fixture
def primary(tmp_path: Path) -> Path:
    """A throwaway repo standing in for the primary checkout."""
    root = tmp_path / "deckd"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "test")
    (root / "README.md").write_text("stub\n")
    _git(root, "add", "README.md")
    _git(root, "commit", "-qm", "init")
    return root


def _add_worktree(primary: Path, name: str) -> Path:
    path = primary.parent / name
    _git(primary, "worktree", "add", "-q", "-b", name, str(path))
    return path


def test_primary_keeps_the_default_ports(primary: Path) -> None:
    """The main checkout must behave exactly as it did before worktree support:
    no .env, no renumbering, :8765/:5173 as always."""
    result = _run(primary, "adopt", "--no-install")
    assert result.returncode == 0, result.stderr
    assert not (primary / ".env").exists()
    assert "primary checkout" in result.stdout


def test_adopt_assigns_the_first_free_offset(primary: Path) -> None:
    wt = _add_worktree(primary, "feature-a")
    assert _run(wt, "adopt", "--no-install").returncode == 0

    env = _dotenv(wt / ".env")
    assert env == {
        "DECKD_PORT": str(BASE_DECKD + 1),
        "VITE_PORT": str(BASE_VITE + 1),
        "DECKD_E2E_PORT": str(BASE_E2E + 1),
    }


def test_siblings_never_collide(primary: Path) -> None:
    """The whole point: three checkouts, three disjoint port sets."""
    worktrees = [_add_worktree(primary, f"feature-{n}") for n in "abc"]
    for wt in worktrees:
        assert _run(wt, "adopt", "--no-install").returncode == 0

    assigned = [_dotenv(wt / ".env")["DECKD_PORT"] for wt in worktrees]
    assert sorted(assigned) == [str(BASE_DECKD + n) for n in (1, 2, 3)]
    # ...and none of them landed on the primary's.
    assert str(BASE_DECKD) not in assigned


def test_adopt_is_idempotent(primary: Path) -> None:
    """Re-adopting must not renumber a worktree — a running daemon, a phone
    bookmarked to the Vite port, and `just kill` all depend on stability."""
    wt = _add_worktree(primary, "feature-a")
    _run(wt, "adopt", "--no-install")
    first = _dotenv(wt / ".env")

    # A sibling appears and takes the next slot; re-adopting must not shuffle.
    other = _add_worktree(primary, "feature-b")
    _run(other, "adopt", "--no-install")
    assert _run(wt, "adopt", "--no-install").returncode == 0

    assert _dotenv(wt / ".env") == first
    assert _dotenv(other / ".env")["DECKD_PORT"] != first["DECKD_PORT"]


def test_force_reassigns(primary: Path) -> None:
    """--force is the repair path for a hand-edited or duplicated .env."""
    wt = _add_worktree(primary, "feature-a")
    _run(wt, "adopt", "--no-install")
    (wt / ".env").write_text(
        f"DECKD_PORT={BASE_DECKD + 9}\nVITE_PORT={BASE_VITE + 9}\n"
        f"DECKD_E2E_PORT={BASE_E2E + 9}\n"
    )
    assert _run(wt, "adopt", "--no-install", "--force").returncode == 0
    assert _dotenv(wt / ".env")["DECKD_PORT"] == str(BASE_DECKD + 1)


def test_ports_reports_without_writing(primary: Path) -> None:
    wt = _add_worktree(primary, "feature-a")
    result = _run(wt, "ports")
    assert result.returncode == 0
    assert f"DECKD_PORT={BASE_DECKD + 1}" in result.stdout
    assert not (wt / ".env").exists()


def test_doctor_flags_an_unadopted_worktree(primary: Path) -> None:
    wt = _add_worktree(primary, "feature-a")
    result = _run(wt, "doctor")
    assert result.returncode == 1
    assert "no .env" in result.stdout
    assert "just worktree-adopt" in result.stdout
    assert "not ready." in result.stdout


def test_doctor_flags_duplicate_offsets(primary: Path) -> None:
    """Two worktrees on the same ports is the failure worktree support exists
    to prevent, so the doctor has to name it rather than just report deps."""
    a, b = (_add_worktree(primary, f"feature-{n}") for n in "ab")
    for wt in (a, b):
        _run(wt, "adopt", "--no-install")
    (b / ".env").write_text((a / ".env").read_text())

    result = _run(b, "doctor")
    assert result.returncode == 1
    assert "also claimed by" in result.stdout
    assert "--force" in result.stdout


def test_list_shows_every_worktree_with_its_state(primary: Path) -> None:
    wt = _add_worktree(primary, "feature-a")
    _run(wt, "adopt", "--no-install")

    result = _run(primary, "list")
    assert result.returncode == 0
    assert "main" in result.stdout
    assert "feature-a" in result.stdout
    assert str(BASE_DECKD + 1) in result.stdout
    # No deps installed anywhere, so nothing claims to be ready.
    assert "ready" not in result.stdout


def test_adopt_copies_gitignored_extras(primary: Path) -> None:
    """TLS certs cost a sudo prompt to provision and are host-wide, so a new
    worktree should inherit the primary's rather than re-minting them."""
    tls = primary / "client" / ".tls"
    tls.mkdir(parents=True)
    (tls / "host.crt").write_text("cert\n")

    wt = _add_worktree(primary, "feature-a")
    assert _run(wt, "adopt", "--no-install").returncode == 0
    assert (wt / "client" / ".tls" / "host.crt").read_text() == "cert\n"


def test_adopt_wires_envrc_to_the_primary_flox_env(primary: Path) -> None:
    """A worktree has no .flox/ of its own; direnv's `use flox` requires one,
    so the generated .envrc resolves the primary's env by path instead."""
    (primary / ".flox").mkdir()
    wt = _add_worktree(primary, "feature-a")
    assert _run(wt, "adopt", "--no-install").returncode == 0

    envrc = (wt / ".envrc").read_text()
    assert f'flox activate -d "{primary}"' in envrc
    assert "use flox" in envrc  # local .flox/ still wins if one appears


def test_adopt_leaves_an_existing_envrc_alone(primary: Path) -> None:
    (primary / ".flox").mkdir()
    wt = _add_worktree(primary, "feature-a")
    (wt / ".envrc").write_text("# hand-rolled\n")
    _run(wt, "adopt", "--no-install")
    assert (wt / ".envrc").read_text() == "# hand-rolled\n"


def test_no_envrc_when_the_primary_does_not_use_direnv(primary: Path) -> None:
    """The repo doesn't prescribe direnv or flox — don't impose them."""
    wt = _add_worktree(primary, "feature-a")
    _run(wt, "adopt", "--no-install")
    assert not (wt / ".envrc").exists()
