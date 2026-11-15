"""Tests for opening the surface on a GUI launch of the AppImage (issue #168)."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from deckd import open_surface

GUI = {"WAYLAND_DISPLAY": "wayland-0"}


# --- resolve_open -----------------------------------------------------------


def test_gui_launch_opens() -> None:
    assert open_surface.resolve_open([], stdin_isatty=False, environ=GUI) == (True, [])


def test_terminal_launch_does_not_open() -> None:
    assert open_surface.resolve_open([], stdin_isatty=True, environ=GUI) == (False, [])


def test_no_display_does_not_open() -> None:
    # e.g. `ssh host ./deckd.AppImage` — no tty, but nothing to open a browser on.
    assert open_surface.resolve_open([], stdin_isatty=False, environ={}) == (False, [])


def test_x11_display_counts_as_gui() -> None:
    opened, _ = open_surface.resolve_open([], stdin_isatty=False, environ={"DISPLAY": ":0"})
    assert opened is True


def test_explicit_flags_win_and_are_stripped() -> None:
    assert open_surface.resolve_open(
        ["--open", "--bind", "0.0.0.0"], stdin_isatty=True, environ={}
    ) == (True, ["--bind", "0.0.0.0"])
    # Autostart passes --no-open: a login must never pop a browser.
    assert open_surface.resolve_open(["--no-open"], stdin_isatty=False, environ=GUI) == (
        False,
        [],
    )


def test_last_explicit_flag_wins() -> None:
    opened, _ = open_surface.resolve_open(
        ["--no-open", "--open"], stdin_isatty=True, environ={}
    )
    assert opened is True


@pytest.mark.parametrize("flag", ["-h", "--help"])
def test_help_never_opens(flag: str) -> None:
    assert open_surface.resolve_open(["--open", flag], stdin_isatty=False, environ=GUI) == (
        False,
        [flag],
    )


# --- surface_url ------------------------------------------------------------


def test_surface_url_defaults_to_loopback() -> None:
    assert open_surface.surface_url([]) == "http://127.0.0.1:8765/"


def test_surface_url_follows_port() -> None:
    assert open_surface.surface_url(["--port", "9000"]) == "http://127.0.0.1:9000/"


def test_surface_url_wildcard_is_reachable_on_loopback() -> None:
    assert open_surface.surface_url(["--bind", "0.0.0.0"]) == "http://127.0.0.1:8765/"


def test_surface_url_ipv6_only_loopback() -> None:
    assert open_surface.surface_url(["--bind", "::1"]) == "http://[::1]:8765/"


def test_surface_url_none_when_not_on_loopback() -> None:
    assert open_surface.surface_url(["--bind", "192.168.1.5"]) is None
    assert open_surface.surface_url(["--bind", "iface:wlan0"]) is None


def test_surface_url_none_for_kernel_picked_port() -> None:
    assert open_surface.surface_url(["--port", "0"]) is None


# --- probe ------------------------------------------------------------------


def _serve(body: bytes):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(200)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    srv = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/"


def test_probe_recognises_deckd_health() -> None:
    srv, url = _serve(json.dumps({"ok": True, "hostname": "box"}).encode())
    try:
        assert open_surface.probe(url) is True
    finally:
        srv.shutdown()


def test_probe_rejects_some_other_server() -> None:
    srv, url = _serve(b"<html>not deckd</html>")
    try:
        assert open_surface.probe(url) is False
    finally:
        srv.shutdown()


def test_probe_false_when_nothing_listens() -> None:
    srv, url = _serve(b"")
    srv.shutdown()
    srv.server_close()
    assert open_surface.probe(url, timeout=0.5) is False


# --- browser_env ------------------------------------------------------------


def test_browser_env_restores_original_library_path_when_frozen() -> None:
    env = open_surface.browser_env(
        {"LD_LIBRARY_PATH": "/tmp/_MEI/bundle", "LD_LIBRARY_PATH_ORIG": "/usr/local/lib", "X": "1"},
        frozen=True,
    )
    assert env == {"LD_LIBRARY_PATH": "/usr/local/lib", "X": "1"}


def test_browser_env_drops_bundle_library_path_when_frozen() -> None:
    env = open_surface.browser_env({"LD_LIBRARY_PATH": "/tmp/_MEI/bundle"}, frozen=True)
    assert "LD_LIBRARY_PATH" not in env


def test_browser_env_untouched_from_source() -> None:
    src = {"LD_LIBRARY_PATH": "/opt/lib"}
    assert open_surface.browser_env(src, frozen=False) == src


# --- open_url ---------------------------------------------------------------


def test_open_url_runs_xdg_open_detached_with_clean_env() -> None:
    calls = []
    ok = open_surface.open_url(
        "http://127.0.0.1:8765/",
        environ={"LD_LIBRARY_PATH": "/bundle"},
        frozen=True,
        popen=lambda cmd, **kw: calls.append((cmd, kw)),
    )
    assert ok is True
    [(cmd, kw)] = calls
    assert cmd == ["xdg-open", "http://127.0.0.1:8765/"]
    assert kw["start_new_session"] is True
    assert "LD_LIBRARY_PATH" not in kw["env"]


def test_open_url_reports_missing_xdg_open(capsys) -> None:
    def missing(*_a, **_kw):
        raise FileNotFoundError("xdg-open")

    assert open_surface.open_url("http://x/", environ={}, frozen=False, popen=missing) is False
    assert "http://x/" in capsys.readouterr().err


# --- open_when_ready / launch_or_attach -------------------------------------


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, dt: float) -> None:
        self.now += dt


def test_open_when_ready_waits_for_daemon_then_opens_once() -> None:
    clock = FakeClock()
    answers = iter([False, False, True])
    opened = []
    ok = open_surface.open_when_ready(
        "u",
        is_up=lambda _u: next(answers),
        opener=lambda u: opened.append(u) or True,
        sleep=clock.sleep,
        clock=clock,
    )
    assert ok is True
    assert opened == ["u"]


def test_open_when_ready_gives_up_without_opening() -> None:
    clock = FakeClock()
    opened = []
    ok = open_surface.open_when_ready(
        "u",
        is_up=lambda _u: False,
        opener=lambda u: opened.append(u) or True,
        timeout=2.0,
        interval=0.5,
        sleep=clock.sleep,
        clock=clock,
    )
    assert ok is False
    assert opened == []


def test_launch_or_attach_opens_running_daemon_and_exits() -> None:
    opened, spawned = [], []
    done = open_surface.launch_or_attach(
        "u", is_up=lambda _u: True, opener=opened.append, spawn=spawned.append
    )
    assert done is True
    assert opened == ["u"]
    assert spawned == []


def test_launch_or_attach_schedules_open_and_lets_daemon_start() -> None:
    opened, spawned = [], []
    up = iter([False, True])
    done = open_surface.launch_or_attach(
        "u", is_up=lambda _u: next(up), opener=lambda u: opened.append(u) or True,
        spawn=spawned.append,
    )
    assert done is False
    assert opened == []
    [job] = spawned
    job()
    assert opened == ["u"]
