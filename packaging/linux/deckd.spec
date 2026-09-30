# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec: freeze the daemon + client for the Linux AppImage (#168).

Build on Linux:

    just build-linux-appimage
    # or: pyinstaller --noconfirm --clean packaging/linux/deckd.spec

Output: ``dist/deckd/`` (a PyInstaller onedir tree). The AppImage recipe
copies it into ``deckd.AppDir/usr/bin`` and wraps it with ``appimagetool``.

The entry point is ``packaging/linux/launcher.py``; the built client and
layouts are copied in as data under ``sys._MEIPASS`` (the ``_internal`` dir),
where ``deckd.app_bundle`` looks for them. The udev rule and focus-watcher
sources are *not* frozen in — they are system integration, not runtime, and
the AppImage recipe places them under ``usr/share/deckd/integration`` where
``install-system-integration.sh`` reads them.
"""
import sys
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parents[1]  # SPECPATH is packaging/linux

# Importable even when the package isn't pip-installed (e.g. a bare
# ``pyinstaller packaging/linux/deckd.spec`` from a checkout).
sys.path.insert(0, str(ROOT / "daemon"))

datas = [
    (str(ROOT / "client/dist"), "web"),
    (str(ROOT / "layouts"), "layouts"),
]
# Per-platform overlay, if present. The daemon auto-discovers ``layouts.linux``
# beside the layouts dir (see ``_overlay_dir_for``); app_bundle seeds it.
if (ROOT / "layouts.linux").is_dir():
    datas.append((str(ROOT / "layouts.linux"), "layouts.linux"))

a = Analysis(
    [str(ROOT / "packaging/linux/launcher.py")],
    pathex=[str(ROOT / "daemon")],
    binaries=[],
    datas=datas,
    # evdev and dbus-fast are imported lazily / guarded in the daemon, so name
    # them explicitly: PyInstaller's static walk can miss a conditional import.
    # On aarch64 evdev has no wheel and is source-built before this runs.
    hiddenimports=[
        "deckd.linux_app",
        "evdev",
        "dbus_fast",
        "dbus_fast.aio",
        "dbus_fast.service",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "pytest", "PyQt5", "PySide2", "PySide6"],
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
    console=True,
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
