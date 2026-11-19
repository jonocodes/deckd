"""Stable code signing for deckd.app (issue #194).

An ad-hoc signature's designated requirement is the build's cdhash, so every
upgrade looks like a new app to TCC and the user's Accessibility / System
Events grants stop applying. Signing with one long-lived self-signed cert makes
the requirement ``identifier "com.deckd.daemon" and certificate leaf = H"…"``,
which doesn't change between builds.

The scripts under ``packaging/macos/signing/`` are tested here:

* ``make-cert.sh`` — needs only ``openssl``, so it runs on Linux too.
* ``check-dr.sh`` / ``sign-app.sh`` / ``import-cert.sh`` — their decision logic
  runs against a stub ``codesign`` on ``PATH``, so it runs anywhere.
* One end-to-end test signs a real (tiny) bundle with a real self-signed cert
  in a throwaway keychain. It briefly adds that keychain to the user's search
  list, so it runs only on macOS CI or with ``DECKD_TEST_CODESIGN=1``.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SIGNING = ROOT / "packaging" / "macos" / "signing"
MAKE_CERT = SIGNING / "make-cert.sh"
CHECK_DR = SIGNING / "check-dr.sh"
SIGN_APP = SIGNING / "sign-app.sh"
IMPORT_CERT = SIGNING / "import-cert.sh"

needs_bash = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
needs_openssl = pytest.mark.skipif(shutil.which("openssl") is None, reason="needs openssl")

STABLE_DR = 'identifier "com.deckd.daemon" and certificate leaf = H"5aed6ad449ed2aea176c7c58e8089b828d2dc0aa"'
ADHOC_DR = 'cdhash H"284b0f27379969d529ec1c582bc758aac0231c30"'


def _run(cmd: list[str], env: dict[str, str] | None = None, **kw) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd, capture_output=True, text=True, env={**os.environ, **(env or {})}, **kw
    )


@pytest.fixture
def stub_codesign(tmp_path: Path):
    """A ``codesign`` on PATH that logs its argv and prints ``$STUB_DR``.

    ``codesign -d -r-`` prints the requirement prefixed ``# `` for an
    implicit (ad-hoc) one; the stub mimics both forms. check-dr.sh merges
    stdout and stderr, so the stream doesn't matter.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "codesign.log"
    stub = bin_dir / "codesign"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        f'echo "$*" >> "{calls}"\n'
        'if [ "$1" = -d ]; then\n'
        '  [ -n "${STUB_DR:-}" ] && echo "${STUB_DR_PREFIX:-}designated => $STUB_DR" >&2\n'
        "  exit 0\n"
        "fi\n"
        'exit "${STUB_RC:-0}"\n'
    )
    stub.chmod(0o755)

    def env(**extra: str) -> dict[str, str]:
        return {"PATH": f"{bin_dir}:{os.environ['PATH']}", **extra}

    def logged() -> list[str]:
        return calls.read_text().splitlines() if calls.exists() else []

    return env, logged


# ---------------------------------------------------------------------------
# make-cert.sh
# ---------------------------------------------------------------------------


@needs_bash
@needs_openssl
def test_make_cert_produces_a_long_lived_code_signing_identity(tmp_path: Path) -> None:
    out = tmp_path / "cert"
    res = _run(["bash", str(MAKE_CERT), str(out)])
    assert res.returncode == 0, res.stderr

    p12 = out / "deckd-codesign.p12"
    password = (out / "deckd-codesign.p12.password").read_text().strip()
    cert = out / "deckd-codesign.cert.pem"
    assert p12.is_file() and cert.is_file() and password

    # The secret files are private to the user.
    assert p12.stat().st_mode & 0o077 == 0
    assert (out / "deckd-codesign.p12.password").stat().st_mode & 0o077 == 0

    text = _run(["openssl", "x509", "-in", str(cert), "-noout", "-text"]).stdout
    assert "Code Signing" in text
    # Long-lived: a new cert means every user re-grants, so it must outlast
    # the project's foreseeable life.
    assert _run(["openssl", "x509", "-in", str(cert), "-noout", "-checkend", str(10 * 365 * 86400)]).returncode == 0

    # The p12 opens with the recorded password (what CI's import does).
    opened = _run(
        ["openssl", "pkcs12", "-in", str(p12), "-nokeys", "-passin", "env:PW"],
        env={"PW": password},
    )
    assert opened.returncode == 0, opened.stderr

    # The printed identity is the cert's SHA-1, the form codesign takes.
    fp = _run(["openssl", "x509", "-in", str(cert), "-noout", "-fingerprint", "-sha1"]).stdout
    sha1 = fp.split("=", 1)[1].strip().replace(":", "")
    assert sha1 in res.stdout


@needs_bash
@needs_openssl
def test_make_cert_refuses_to_overwrite(tmp_path: Path) -> None:
    """Replacing the cert silently would cost every user a re-grant."""
    out = tmp_path / "cert"
    assert _run(["bash", str(MAKE_CERT), str(out)]).returncode == 0
    before = (out / "deckd-codesign.p12").read_bytes()
    res = _run(["bash", str(MAKE_CERT), str(out)])
    assert res.returncode != 0
    assert (out / "deckd-codesign.p12").read_bytes() == before


# ---------------------------------------------------------------------------
# check-dr.sh
# ---------------------------------------------------------------------------


@needs_bash
def test_check_dr_accepts_a_certificate_requirement(stub_codesign, tmp_path) -> None:
    env, _ = stub_codesign
    res = _run(["bash", str(CHECK_DR), "--expect-signed", str(tmp_path)], env=env(STUB_DR=STABLE_DR))
    assert res.returncode == 0, res.stdout + res.stderr
    assert "certificate leaf" in res.stdout


@needs_bash
def test_check_dr_rejects_cdhash_when_signing_expected(stub_codesign, tmp_path) -> None:
    env, _ = stub_codesign
    res = _run(
        ["bash", str(CHECK_DR), "--expect-signed", str(tmp_path)],
        env=env(STUB_DR=ADHOC_DR, STUB_DR_PREFIX="# "),
    )
    assert res.returncode == 1
    assert "cdhash" in res.stdout


@needs_bash
def test_check_dr_tolerates_cdhash_for_an_ad_hoc_build(stub_codesign, tmp_path) -> None:
    """Local and fork builds have no cert; that's allowed, just noted."""
    env, _ = stub_codesign
    res = _run(["bash", str(CHECK_DR), str(tmp_path)], env=env(STUB_DR=ADHOC_DR, STUB_DR_PREFIX="# "))
    assert res.returncode == 0
    assert "ad-hoc" in res.stdout


@needs_bash
def test_check_dr_rejects_a_foreign_identifier(stub_codesign, tmp_path) -> None:
    env, _ = stub_codesign
    dr = STABLE_DR.replace("com.deckd.daemon", "org.example.other")
    res = _run(["bash", str(CHECK_DR), "--expect-signed", str(tmp_path)], env=env(STUB_DR=dr))
    assert res.returncode == 1


@needs_bash
def test_check_dr_fails_without_a_requirement(stub_codesign, tmp_path) -> None:
    env, _ = stub_codesign
    res = _run(["bash", str(CHECK_DR), str(tmp_path)], env=env())
    assert res.returncode == 1


# ---------------------------------------------------------------------------
# sign-app.sh
# ---------------------------------------------------------------------------


@needs_bash
def test_sign_app_without_identity_keeps_the_ad_hoc_signature(stub_codesign, tmp_path) -> None:
    env, logged = stub_codesign
    res = _run(["bash", str(SIGN_APP), str(tmp_path)], env=env(DECKD_CODESIGN_IDENTITY=""))
    assert res.returncode == 0, res.stderr
    assert "ad-hoc" in res.stdout
    assert logged() == []


@needs_bash
def test_sign_app_signs_verifies_and_checks_the_requirement(stub_codesign, tmp_path) -> None:
    env, logged = stub_codesign
    res = _run(
        ["bash", str(SIGN_APP), str(tmp_path)],
        env=env(DECKD_CODESIGN_IDENTITY="ABC123", STUB_DR=STABLE_DR),
    )
    assert res.returncode == 0, res.stdout + res.stderr
    calls = logged()
    sign = calls[0].split()
    assert "--sign" in sign and sign[sign.index("--sign") + 1] == "ABC123"
    assert "--force" in sign and "--deep" in sign
    # No hardened runtime (library validation would refuse the bundled,
    # differently-signed Python dylibs) and no network timestamp.
    assert not any(a.startswith("--options") for a in sign)
    assert "--timestamp=none" in sign
    assert any(c.startswith("--verify") for c in calls[1:])
    assert any(c.startswith("-d -r-") for c in calls[1:])


@needs_bash
def test_sign_app_fails_when_the_result_is_still_cdhash(stub_codesign, tmp_path) -> None:
    env, _ = stub_codesign
    res = _run(
        ["bash", str(SIGN_APP), str(tmp_path)],
        env=env(DECKD_CODESIGN_IDENTITY="ABC123", STUB_DR=ADHOC_DR, STUB_DR_PREFIX="# "),
    )
    assert res.returncode != 0


# ---------------------------------------------------------------------------
# import-cert.sh
# ---------------------------------------------------------------------------


@needs_bash
def test_import_cert_without_a_secret_falls_back_to_ad_hoc(tmp_path) -> None:
    """Fork CI has no secrets: the build must still run, unsigned."""
    gh_out = tmp_path / "out"
    gh_env = tmp_path / "env"
    res = _run(
        ["bash", str(IMPORT_CERT)],
        env={
            "DECKD_CODESIGN_P12_BASE64": "",
            "GITHUB_OUTPUT": str(gh_out),
            "GITHUB_ENV": str(gh_env),
        },
    )
    assert res.returncode == 0, res.stderr
    assert "signed=false" in gh_out.read_text()
    assert not gh_env.exists() or "DECKD_CODESIGN_IDENTITY" not in gh_env.read_text()


# ---------------------------------------------------------------------------
# End to end on a real Mac
# ---------------------------------------------------------------------------


_E2E = sys.platform == "darwin" and (
    os.environ.get("DECKD_TEST_CODESIGN") == "1" or os.environ.get("CI") == "true"
)


@pytest.mark.skipif(not _E2E, reason="macOS only; set DECKD_TEST_CODESIGN=1 (touches the keychain search list)")
def test_real_self_signed_bundle_has_a_stable_requirement(tmp_path: Path) -> None:
    import base64

    out = tmp_path / "cert"
    made = _run(["bash", str(MAKE_CERT), str(out)])
    assert made.returncode == 0, made.stderr

    # A minimal bundle: Info.plist + one Mach-O executable.
    app = tmp_path / "deckd.app"
    (app / "Contents" / "MacOS").mkdir(parents=True)
    (app / "Contents" / "Info.plist").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0"><dict>'
        "<key>CFBundleIdentifier</key><string>com.deckd.daemon</string>"
        "<key>CFBundleExecutable</key><string>deckd</string>"
        "<key>CFBundlePackageType</key><string>APPL</string>"
        "</dict></plist>\n"
    )
    shutil.copy("/bin/echo", app / "Contents" / "MacOS" / "deckd")

    keychain = tmp_path / "signing.keychain-db"
    gh_env = tmp_path / "gh.env"
    gh_out = tmp_path / "gh.out"
    try:
        imported = _run(
            ["bash", str(IMPORT_CERT)],
            env={
                "DECKD_CODESIGN_P12_BASE64": base64.b64encode((out / "deckd-codesign.p12").read_bytes()).decode(),
                "DECKD_CODESIGN_P12_PASSWORD": (out / "deckd-codesign.p12.password").read_text().strip(),
                "DECKD_SIGNING_KEYCHAIN": str(keychain),
                "GITHUB_ENV": str(gh_env),
                "GITHUB_OUTPUT": str(gh_out),
            },
        )
        assert imported.returncode == 0, imported.stdout + imported.stderr
        assert "signed=true" in gh_out.read_text()
        identity = gh_env.read_text().split("DECKD_CODESIGN_IDENTITY=", 1)[1].strip()

        signed = _run(["bash", str(SIGN_APP), str(app)], env={"DECKD_CODESIGN_IDENTITY": identity})
        assert signed.returncode == 0, signed.stdout + signed.stderr

        shown = _run(["codesign", "-d", "-r-", str(app)])
        dr = shown.stdout + shown.stderr
        assert "cdhash" not in dr
        assert 'identifier "com.deckd.daemon"' in dr
        assert f'certificate leaf = H"{identity.lower()}"' in dr
    finally:
        # Also drops it from the search list.
        subprocess.run(["security", "delete-keychain", str(keychain)], capture_output=True)
