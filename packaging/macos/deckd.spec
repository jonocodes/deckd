# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec: freeze the daemon + client into ``deckd.app`` (issue #165).

Build on macOS (a .app needs Apple tooling):

    just build-macos-app
    # or: pyinstaller --noconfirm --clean packaging/macos/deckd.spec

Output: ``dist/deckd.app`` (ad-hoc signed by PyInstaller; not notarized).
The menu-bar entry point is ``packaging/macos/menubar.py``; the client build
and layouts are copied in as data under ``Contents/Frameworks`` (where
``sys._MEIPASS`` points at runtime).
"""
import os
import sys
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parents[1]  # SPECPATH is packaging/macos

# Importable even when the package isn't pip-installed (e.g. a bare
# ``pyinstaller packaging/macos/deckd.spec`` from a checkout).
sys.path.insert(0, str(ROOT / "daemon"))
from deckd.macos_app import (  # noqa: E402
    BUNDLE_ID,
    bundle_info_plist,
    bundle_version,
)

# ``DECKD_VERSION`` (set by the release workflow from the git tag) wins;
# otherwise pyproject's ``version``.
version = bundle_version(ROOT / "pyproject.toml")

# App icon: the committed ``deckd.icns`` (built from client/public/icon.svg by
# ``just icons``). ``DECKD_ICON`` overrides it; otherwise the default
# PyInstaller icon is used when the .icns is missing.
icon = os.environ.get("DECKD_ICON") or str(ROOT / "packaging/macos/deckd.icns")
if not Path(icon).is_file():
    if os.environ.get("DECKD_ICON"):
        raise SystemExit(f"DECKD_ICON set but not found: {icon}")
    icon = None

datas = [
    (str(ROOT / "client/dist"), "web"),
    (str(ROOT / "layouts"), "layouts"),
    # Menu-bar status-item template (monochrome, light/dark aware). Placed at
    # the bundle root so ``resource_root() / "deckd-menubar.png"`` resolves.
    (str(ROOT / "packaging/macos/deckd-menubar.png"), "."),
    (str(ROOT / "packaging/macos/deckd-menubar@2x.png"), "."),
]
if (ROOT / "layouts.macos").is_dir():
    datas.append((str(ROOT / "layouts.macos"), "layouts.macos"))

a = Analysis(
    [str(ROOT / "packaging/macos/menubar.py")],
    pathex=[str(ROOT / "daemon")],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "deckd.macos_app",
        "deckd.platform_macos",
        "objc",
        "AppKit",
        "Foundation",
        "PyObjCTools",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "pytest"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="deckd",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="deckd",
)

app = BUNDLE(
    coll,
    name="deckd.app",
    icon=icon,
    bundle_identifier=BUNDLE_ID,
    info_plist=bundle_info_plist(version),
)
