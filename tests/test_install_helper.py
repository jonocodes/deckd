"""Sandbox tests for packaging/linux/install-system-integration.sh (issue #168).

The helper is a root script, so these run it with ``DECKD_HELPER_TEST_ROOT``:
system paths (/etc/udev, /var/lib/deckd) and the user's home live under a temp
dir, nothing is chown'd, and the system commands it calls (systemctl, udevadm,
gnome-extensions, usermod, gpasswd) are stubs on PATH that record their
arguments. What's left is the helper's own logic: which files it writes, what
they say, what it records, and that uninstall undoes exactly that.
"""
from __future__ import annotations

import getpass
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "linux" or shutil.which("bash") is None,
    reason="the install helper is a Linux bash script",
)

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "packaging" / "linux" / "install-system-integration.sh"
STUBS = ("systemctl", "udevadm", "gnome-extensions", "usermod", "gpasswd")


class Sandbox:
    def __init__(self, base: Path) -> None:
        self.base = base
        self.root = base / "root"
        self.home = self.root / "home"
        self.stubs = base / "stubs"
        self.calls = base / "calls.log"
        self.root.mkdir()
        self.stubs.mkdir()
        for name in STUBS:
            stub = self.stubs / name
            stub.write_text(
                "#!/bin/sh\n"
                f'echo "{name} $*" >> "{self.calls}"\n'
                # Simulate an unreachable user manager (helper run over SSH,
                # no session yet): every systemctl call fails.
                f'[ "{name}" = systemctl ] && [ -n "$STUB_SYSTEMCTL_FAIL" ] && exit 1\n'
                "exit 0\n"
            )
            stub.chmod(0o755)

    # Paths the helper writes.
    @property
    def opt(self) -> Path:
        return self.home / ".local" / "opt" / "deckd"

    @property
    def unit(self) -> Path:
        return self.home / ".config" / "systemd" / "user" / "deckd.service"

    @property
    def wants(self) -> Path:
        return self.unit.parent / "graphical-session.target.wants" / "deckd.service"

    @property
    def menu(self) -> Path:
        return self.home / ".local" / "share" / "applications" / "deckd.desktop"

    @property
    def autostart(self) -> Path:
        return self.home / ".config" / "autostart" / "deckd.desktop"

    @property
    def udev(self) -> Path:
        return self.root / "etc" / "udev" / "rules.d" / "70-deckd-uinput.rules"

    @property
    def state(self) -> Path:
        return self.root / "var" / "lib" / "deckd" / f"system-integration.{getpass.getuser()}.state"

    def calls_log(self) -> str:
        return self.calls.read_text() if self.calls.exists() else ""

    def run(self, script: Path, *args: str, check: bool = True, **env: str):
        full_env = {
            **os.environ,
            "PATH": f"{self.stubs}:{os.environ['PATH']}",
            "DECKD_HELPER_TEST_ROOT": str(self.root),
            **env,
        }
        full_env.pop("XDG_CURRENT_DESKTOP", None)
        proc = subprocess.run(
            ["bash", str(script), "--user", getpass.getuser(), "--desktop", "gnome", *args],
            env=full_env,
            capture_output=True,
            text=True,
        )
        if check and proc.returncode != 0:
            raise AssertionError(f"helper failed ({proc.returncode}):\n{proc.stdout}\n{proc.stderr}")
        return proc


def _integration(dest: Path) -> None:
    (dest / "gnome-shell" / "deckd-focus@local").mkdir(parents=True)
    (dest / "gnome-shell" / "deckd-focus@local" / "extension.js").write_text("// ext\n")
    (dest / "kwin-script" / "deckd-focus" / "contents" / "code").mkdir(parents=True)
    (dest / "kwin-script" / "deckd-focus" / "contents" / "code" / "main.js").write_text("// kwin\n")
    shutil.copy(ROOT / "packaging" / "udev" / "70-deckd-uinput.rules", dest)
    (dest / "deckd.png").write_bytes(b"\x89PNG")
    shutil.copy(HELPER, dest)


def make_tree(base: Path, version: str = "1.0") -> Path:
    """An extracted tarball, laid out like `just build-linux-tarball` makes it."""
    tree = base / f"deckd-{version}-x86_64"
    (tree / "bin" / "_internal").mkdir(parents=True)
    launcher = tree / "bin" / "deckd"
    launcher.write_text("#!/bin/sh\n")
    launcher.chmod(0o755)
    (tree / "bin" / "_internal" / f"marker-{version}").write_text(version)
    _integration(tree / "share" / "deckd" / "integration")
    shutil.copy(HELPER, tree / "install-system-integration.sh")
    return tree


@pytest.fixture
def sb(tmp_path: Path) -> Sandbox:
    return Sandbox(tmp_path)


# --- tarball ----------------------------------------------------------------


def test_tarball_install_from_its_own_directory(sb: Sandbox) -> None:
    tree = make_tree(sb.base / "Downloads")
    out = sb.run(tree / "install-system-integration.sh").stdout

    # The tree is copied to a stable path; the download is left alone.
    exe = sb.opt / "bin" / "deckd"
    assert exe.is_file()
    assert (sb.opt / "install-system-integration.sh").is_file()
    assert tree.is_dir()

    # Autostart is a systemd user service that never opens a browser.
    unit = sb.unit.read_text()
    assert f'ExecStart="{exe}" --no-open' in unit
    assert "WantedBy=graphical-session.target" in unit
    assert sb.wants.is_symlink()
    assert os.readlink(sb.wants) == "../deckd.service"
    assert not sb.autostart.exists()

    # The menu entry opens the surface.
    assert f'Exec="{exe}" --open' in sb.menu.read_text()

    # The root step and the focus watcher.
    assert sb.udev.is_file()
    assert (sb.home / ".local/share/gnome-shell/extensions/deckd-focus@local/extension.js").is_file()

    # Started now (restart so an upgrade picks up the new tree).
    calls = sb.calls_log()
    assert "systemctl --user daemon-reload" in calls
    assert "systemctl --user restart deckd.service" in calls

    state = sb.state.read_text()
    assert "tree=1" in state and "service=1" in state and "autostart=0" in state
    # Uninstall is pointed at the installed copy, not the download.
    assert f"{sb.opt}/install-system-integration.sh --uninstall" in out


def test_tarball_dir_as_bare_argument(sb: Sandbox) -> None:
    tree = make_tree(sb.base / "Downloads")
    sb.run(HELPER, str(tree))
    assert (sb.opt / "bin" / "deckd").is_file()
    assert sb.unit.is_file()


def test_tarball_upgrade_replaces_the_tree(sb: Sandbox) -> None:
    v1 = make_tree(sb.base / "v1", "1.0")
    v2 = make_tree(sb.base / "v2", "2.0")
    sb.run(v1 / "install-system-integration.sh")
    sb.run(v2 / "install-system-integration.sh")

    internal = sb.opt / "bin" / "_internal"
    assert (internal / "marker-2.0").is_file()
    assert not (internal / "marker-1.0").exists(), "stale files from the old version survived"
    assert sb.calls_log().count("systemctl --user restart deckd.service") == 2


def test_rerun_from_the_installed_copy_keeps_the_tree(sb: Sandbox) -> None:
    sb.run(make_tree(sb.base / "dl") / "install-system-integration.sh")
    out = sb.run(sb.opt / "install-system-integration.sh").stdout
    assert "keeping the installed tree" in out
    assert (sb.opt / "bin" / "deckd").is_file()


def test_unreachable_user_session_still_enables_the_service(sb: Sandbox) -> None:
    tree = make_tree(sb.base / "dl")
    out = sb.run(tree / "install-system-integration.sh", STUB_SYSTEMCTL_FAIL="1").stdout
    assert sb.unit.is_file()
    assert sb.wants.is_symlink()
    assert "starts at next login" in out


def test_no_autostart_skips_the_service(sb: Sandbox) -> None:
    sb.run(make_tree(sb.base / "dl") / "install-system-integration.sh", "--no-autostart")
    assert not sb.unit.exists()
    assert sb.menu.is_file()


def test_uninstall_removes_everything_it_installed(sb: Sandbox) -> None:
    sb.run(make_tree(sb.base / "dl") / "install-system-integration.sh")
    sb.run(sb.opt / "install-system-integration.sh", "--uninstall")

    for path in (sb.opt, sb.unit, sb.menu, sb.udev, sb.state):
        assert not path.exists(), f"{path} survived uninstall"
    assert not sb.wants.is_symlink()
    assert not (sb.home / ".local/share/gnome-shell/extensions/deckd-focus@local").exists()
    assert "systemctl --user stop deckd.service" in sb.calls_log()


def test_rejects_a_directory_that_is_not_a_tree(sb: Sandbox) -> None:
    junk = sb.base / "junk"
    junk.mkdir()
    proc = sb.run(HELPER, str(junk), check=False)
    assert proc.returncode != 0
    assert "not a deckd tree" in proc.stderr


# --- AppImage ---------------------------------------------------------------


def _appimage(sb: Sandbox) -> tuple[Path, Path]:
    app = sb.base / "deckd-1.0-x86_64.AppImage"
    app.write_text("#!/bin/sh\n")
    app.chmod(0o755)
    assets = sb.base / "assets"
    _integration(assets)
    return app, assets


def test_appimage_install_uses_xdg_autostart(sb: Sandbox) -> None:
    app, assets = _appimage(sb)
    sb.run(HELPER, "--assets", str(assets), "--appimage", str(app))

    assert f'Exec="{app}" --no-open' in sb.autostart.read_text()
    assert f'Exec="{app}" --open' in sb.menu.read_text()
    assert not sb.unit.exists()
    assert not sb.opt.exists()


def test_switching_appimage_to_tarball_drops_the_xdg_autostart(sb: Sandbox) -> None:
    app, assets = _appimage(sb)
    sb.run(HELPER, "--assets", str(assets), "--appimage", str(app))
    sb.run(make_tree(sb.base / "dl") / "install-system-integration.sh")

    assert not sb.autostart.exists(), "two autostarts would race for the port"
    assert sb.unit.is_file()
    assert "autostart=0" in sb.state.read_text()


def test_switching_tarball_to_appimage_drops_the_service(sb: Sandbox) -> None:
    sb.run(make_tree(sb.base / "dl") / "install-system-integration.sh")
    app, assets = _appimage(sb)
    sb.run(HELPER, "--assets", str(assets), "--appimage", str(app))

    assert not sb.unit.exists()
    assert not sb.wants.is_symlink()
    assert sb.autostart.is_file()
    assert "service=0" in sb.state.read_text()


# --- guard ------------------------------------------------------------------


@pytest.mark.skipif(os.geteuid() == 0, reason="running as root")
def test_refuses_to_run_unelevated_outside_the_sandbox(tmp_path: Path) -> None:
    env = {k: v for k, v in os.environ.items() if k != "DECKD_HELPER_TEST_ROOT"}
    proc = subprocess.run(
        ["bash", str(HELPER), "--uninstall"], env=env, capture_output=True, text=True
    )
    assert proc.returncode != 0
    assert "must run as root" in proc.stderr
