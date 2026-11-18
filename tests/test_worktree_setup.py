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

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
SCRIPT = REPO_ROOT / "scripts" / "worktree.sh"

BASE_DECKD = 8865
# Where an installed (prod) deckd listens. Dev bases deliberately avoid it.
PROD_PORT = 8765
# The dev daemon base before it moved off the prod port; .env files written
# then still say DECKD_PORT=8766 etc. and must keep their offset.
LEGACY_BASE_DECKD = 8765
BASE_VITE = 5173
BASE_E2E = 8975
BASE_SMOKE = 18765


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


def _run(
    cwd: Path, *args: str, busy: str = ""
) -> subprocess.CompletedProcess[str]:
    """Drive the script with a pinned view of which ports are occupied.

    Without ``DECKD_WORKTREE_BUSY_PORTS`` the allocator probes real sockets,
    so results would depend on what happens to be listening on the machine
    running the suite — a developer with a deckd on :8865 would see different
    offsets than CI. Default to "nothing is busy" and let individual tests
    declare otherwise.
    """
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        env={**os.environ, "DECKD_WORKTREE_BUSY_PORTS": busy},
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
    no .env, no renumbering, :8865/:5173 as always."""
    result = _run(primary, "adopt", "--no-install")
    assert result.returncode == 0, result.stderr
    assert not (primary / ".env").exists()
    assert "primary checkout" in result.stdout


def test_primary_ignores_an_installed_deckd_on_the_prod_port(primary: Path) -> None:
    """An installed deckd (NixOS/home-manager service, the macOS app) holds
    :8765. The dev bases sit off that port on purpose, so running prod and dev
    on one machine leaves the primary checkout on its defaults."""
    result = _run(primary, "adopt", "--no-install", busy=str(PROD_PORT))
    assert result.returncode == 0, result.stderr
    assert not (primary / ".env").exists()
    doctor = _run(primary, "doctor", busy=str(PROD_PORT))
    assert "already in use" not in doctor.stdout


def test_primary_moves_off_an_occupied_default_port(primary: Path) -> None:
    """The primary prefers offset 0 but doesn't own it. If something else
    already holds the dev daemon port, the main checkout has to move like
    anyone else — otherwise `just dev` there fails on address-in-use forever."""
    result = _run(primary, "adopt", "--no-install", busy=str(BASE_DECKD))
    assert result.returncode == 0, result.stderr

    assert _dotenv(primary / ".env")["DECKD_PORT"] == str(BASE_DECKD + 1)
    assert "already taken" in result.stdout


def test_primary_offset_leaves_room_for_worktrees(primary: Path) -> None:
    """A displaced primary claims its offset like any other checkout, so
    siblings adopted afterwards must route around it rather than collide."""
    _run(primary, "adopt", "--no-install", busy=str(BASE_DECKD))
    wt = _add_worktree(primary, "feature-a")
    _run(wt, "adopt", "--no-install", busy=str(BASE_DECKD))

    assert _dotenv(primary / ".env")["DECKD_PORT"] == str(BASE_DECKD + 1)
    assert _dotenv(wt / ".env")["DECKD_PORT"] == str(BASE_DECKD + 2)


def test_doctor_flags_a_primary_on_an_occupied_default_port(primary: Path) -> None:
    result = _run(primary, "doctor", busy=str(BASE_DECKD))
    assert result.returncode == 1
    assert "already in use" in result.stdout
    assert "just worktree-adopt" in result.stdout


def test_adopt_skips_offsets_whose_ports_are_taken(primary: Path) -> None:
    """A port can be held by something that isn't a worktree at all — a stray
    daemon, an unrelated dev server. Offsets are only free if all four of
    their ports are."""
    wt = _add_worktree(primary, "feature-a")
    # Offset 1 is blocked by its smoke port alone; offset 2 by its Vite port.
    busy = f"{BASE_SMOKE + 1} {BASE_VITE + 2}"
    assert _run(wt, "adopt", "--no-install", busy=busy).returncode == 0
    assert _dotenv(wt / ".env")["DECKD_PORT"] == str(BASE_DECKD + 3)


def test_adopt_assigns_the_first_free_offset(primary: Path) -> None:
    wt = _add_worktree(primary, "feature-a")
    assert _run(wt, "adopt", "--no-install").returncode == 0

    env = _dotenv(wt / ".env")
    assert env == {
        "DECKD_PORT": str(BASE_DECKD + 1),
        "VITE_PORT": str(BASE_VITE + 1),
        "DECKD_E2E_PORT": str(BASE_E2E + 1),
        "DECKD_SMOKE_PORT": str(BASE_SMOKE + 1),
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


def test_envrc_adds_the_worktree_venv_to_path(primary: Path) -> None:
    """flox's [profile] hook that exports $PWD/.venv/bin only runs for an
    interactive shell, so direnv's non-interactive env dump never carries it.
    Without this the venv's console scripts (deckd-dev, deckctl) are missing
    from an activated worktree and `just dev-daemon` fails."""
    (primary / ".flox").mkdir()
    wt = _add_worktree(primary, "feature-a")
    assert _run(wt, "adopt", "--no-install").returncode == 0

    envrc = (wt / ".envrc").read_text()
    assert "PATH_add .venv/bin" in envrc
    assert 'export VIRTUAL_ENV="$PWD/.venv"' in envrc


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


def test_legacy_env_keeps_its_offset_and_moves_to_the_new_base(primary: Path) -> None:
    """Worktrees adopted before the dev base moved have DECKD_PORT=8766 etc.
    Re-adopting must keep their offset (Vite bookmarks, e2e ports) and only
    move the daemon onto the new base — not decode 8766 as a negative offset."""
    wt = _add_worktree(primary, "feature-a")
    (wt / ".env").write_text(
        f"DECKD_PORT={LEGACY_BASE_DECKD + 2}\nVITE_PORT={BASE_VITE + 2}\n"
        f"DECKD_E2E_PORT={BASE_E2E + 2}\nDECKD_SMOKE_PORT={BASE_SMOKE + 2}\n"
    )
    result = _run(wt, "adopt", "--no-install")
    assert result.returncode == 0, result.stderr
    env = _dotenv(wt / ".env")
    assert env["DECKD_PORT"] == str(BASE_DECKD + 2)
    assert env["VITE_PORT"] == str(BASE_VITE + 2)


def test_legacy_env_still_reserves_its_offset(primary: Path) -> None:
    """A sibling not yet re-adopted still holds its old offset; new worktrees
    must route around it."""
    old = _add_worktree(primary, "feature-old")
    (old / ".env").write_text(
        f"DECKD_PORT={LEGACY_BASE_DECKD + 1}\nVITE_PORT={BASE_VITE + 1}\n"
    )
    new = _add_worktree(primary, "feature-new")
    assert _run(new, "adopt", "--no-install").returncode == 0
    assert _dotenv(new / ".env")["DECKD_PORT"] == str(BASE_DECKD + 2)


def test_doctor_flags_a_legacy_env(primary: Path) -> None:
    wt = _add_worktree(primary, "feature-a")
    (wt / ".env").write_text(
        f"DECKD_PORT={LEGACY_BASE_DECKD + 1}\nVITE_PORT={BASE_VITE + 1}\n"
    )
    result = _run(wt, "doctor")
    assert result.returncode == 1
    assert "prod port range" in result.stdout
    assert "just worktree-adopt" in result.stdout


def test_primary_drops_a_legacy_env_and_reclaims_the_defaults(primary: Path) -> None:
    """A primary displaced to 8766 by an installed deckd (the old behaviour)
    goes back to the bare defaults once dev no longer shares the prod port."""
    (primary / ".env").write_text(
        f"DECKD_PORT={LEGACY_BASE_DECKD + 1}\nVITE_PORT={BASE_VITE + 1}\n"
    )
    result = _run(primary, "adopt", "--no-install", busy=str(PROD_PORT))
    assert result.returncode == 0, result.stderr
    assert not (primary / ".env").exists()
    assert "legacy .env" in result.stdout
