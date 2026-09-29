"""Menu-bar wrapper for the packaged deckd macOS app (issue #165).

PyInstaller entry point for ``deckd.app``. AppKit owns the main thread (a
status item with a small menu); the deckd server runs on a background thread
via ``deckd.macos_app.ServerRunner``.

Only frozen into the app bundle — the daemon never imports this. Requires the
``[macos]`` extra (PyObjC Cocoa). The platform-independent helpers live in
``deckd.macos_app`` so they can be unit-tested on Linux.
"""
from __future__ import annotations

import logging
import webbrowser
from pathlib import Path

from deckd.macos_app import (
    DEFAULT_PORT,
    ServerRunner,
    app_argv,
    app_support_dir,
    client_dist,
    default_log_file,
    layouts_src,
    menubar_icon_paths,
    overlay_src,
    resource_root,
    seed_layouts,
)

log = logging.getLogger("deckd.menubar")


def _surface_url(port: int = DEFAULT_PORT) -> str:
    return f"http://127.0.0.1:{port}/"


def _menubar_image():
    """The brand mark as a menu-bar template image, or ``None`` if unbundled.

    Loads the bundled 1x/@2x template PNGs into one 18pt NSImage and marks it
    a template, so macOS tints it to match the current menu-bar appearance.
    """
    from AppKit import NSImage, NSImageRep

    paths = menubar_icon_paths(resource_root())
    if paths is None:
        return None
    image = NSImage.alloc().initWithSize_((18.0, 18.0))
    added = False
    for path in paths:
        if not path.is_file():
            continue
        rep = NSImageRep.imageRepWithContentsOfFile_(str(path))
        if rep is None:
            continue
        rep.setSize_((18.0, 18.0))
        image.addRepresentation_(rep)
        added = True
    if not added:
        return None
    image.setTemplate_(True)
    return image


def _prepare() -> tuple[Path, Path, Path]:
    """Seed writable data, returning (layouts_dir, client_dist, log_file)."""
    root = resource_root()
    layouts_dir = app_support_dir() / "layouts"
    if seed_layouts(layouts_src(root), layouts_dir, overlay=overlay_src(root)):
        log.info("seeded bundled layouts into %s", layouts_dir)
    log_file = default_log_file()
    log_file.parent.mkdir(parents=True, exist_ok=True)
    return layouts_dir, client_dist(root), log_file


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    import objc
    from AppKit import (
        NSApp,
        NSApplication,
        NSImage,
        NSMenu,
        NSMenuItem,
        NSStatusBar,
        NSURL,
        NSVariableStatusItemLength,
        NSWorkspace,
    )
    from Foundation import NSObject
    from PyObjCTools import AppHelper

    from deckd.__main__ import parse_args

    layouts_dir, web, log_file = _prepare()

    class MenuTarget(NSObject):
        def initWithLayouts_lan_(self, layouts, lan):
            self = objc.super(MenuTarget, self).init()
            if self is None:
                return None
            self._layouts_dir = layouts
            self._lan = lan
            self._runner = None
            self._start_runner()
            return self

        def _start_runner(self):
            bind = ["0.0.0.0"] if self._lan else None
            argv = app_argv(
                layouts_dir=self._layouts_dir,
                client_dist=web,
                bind=bind,
                log_file=log_file,
            )
            self._runner = ServerRunner(parse_args(argv))
            self._runner.start()

        def openSurface_(self, _sender):
            webbrowser.open(_surface_url())

        def openLayouts_(self, _sender):
            NSWorkspace.sharedWorkspace().openURL_(
                NSURL.fileURLWithPath_(str(self._layouts_dir))
            )

        def restartServer_(self, _sender):
            if self._runner is not None:
                self._runner.stop()
            self._start_runner()

        def toggleLan_(self, sender):
            self._lan = not self._lan
            sender.setState_(1 if self._lan else 0)
            self.restartServer_(sender)

        def quit_(self, _sender):
            if self._runner is not None:
                self._runner.stop()
            NSApp.terminate_(None)

    def add_item(menu, target, title, action, key=""):
        item = menu.addItemWithTitle_action_keyEquivalent_(title, action, key)
        item.setTarget_(target)
        return item

    app = NSApplication.sharedApplication()
    # Accessory: menu-bar only, no Dock icon (also declared via LSUIElement
    # in Info.plist so the Dock icon never appears even for a moment).
    app.setActivationPolicy_(1)

    target = MenuTarget.alloc().initWithLayouts_lan_(layouts_dir, False)

    status_item = NSStatusBar.systemStatusBar().statusItemWithLength_(
        NSVariableStatusItemLength
    )
    # The menu bar wants a monochrome template image, not the full-colour
    # brand mark: the system tints a template for light/dark. Prefer the
    # bundled brand mark, fall back to the matching SF Symbol (macOS 11+,
    # we ship 12+), and finally to the text title.
    button = status_item.button()
    icon = _menubar_image()
    if icon is None:
        icon = NSImage.imageWithSystemSymbolName_accessibilityDescription_(
            "square.grid.2x2", "deckd"
        )
        if icon is not None:
            icon.setTemplate_(True)
    if icon is not None:
        button.setImage_(icon)
    else:
        button.setTitle_("deckd")

    menu = NSMenu.alloc().init()
    add_item(menu, target, "Open deckd surface", "openSurface:")
    add_item(menu, target, "Open layouts folder", "openLayouts:")
    add_item(menu, target, "Restart server", "restartServer:")
    add_item(menu, target, "Allow LAN access", "toggleLan:")
    menu.addItem_(NSMenuItem.separatorItem())
    add_item(menu, target, "Quit deckd", "quit:", "q")
    status_item.setMenu_(menu)

    AppHelper.runEventLoop()


if __name__ == "__main__":
    main()
