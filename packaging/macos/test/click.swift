// Real HID-level input for test-app.sh: the screenshot of the open menu needs
// the status item genuinely clicked (an AXPress fires the item's action but
// doesn't keep the menu on screen long enough to capture it).
//
//   click X Y   left-click at screen point (X, Y)
//   esc         press Escape (closes an open menu)
//
// Posting CGEvents needs Accessibility for the responsible process; the
// GitHub macOS runner image grants it to bash.
import CoreGraphics
import Foundation

func post(_ event: CGEvent?) {
    event?.post(tap: .cghidEventTap)
    usleep(80_000)
}

let args = CommandLine.arguments
guard args.count >= 2 else { exit(2) }

switch args[1] {
case "click" where args.count == 4:
    let point = CGPoint(x: Double(args[2])!, y: Double(args[3])!)
    post(CGEvent(mouseEventSource: nil, mouseType: .mouseMoved, mouseCursorPosition: point, mouseButton: .left))
    post(CGEvent(mouseEventSource: nil, mouseType: .leftMouseDown, mouseCursorPosition: point, mouseButton: .left))
    post(CGEvent(mouseEventSource: nil, mouseType: .leftMouseUp, mouseCursorPosition: point, mouseButton: .left))
case "esc":
    post(CGEvent(keyboardEventSource: nil, virtualKey: 53, keyDown: true))
    post(CGEvent(keyboardEventSource: nil, virtualKey: 53, keyDown: false))
default:
    FileHandle.standardError.write("usage: click X Y | esc\n".data(using: .utf8)!)
    exit(2)
}
