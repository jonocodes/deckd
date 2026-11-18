import type { Story } from "@ladle/react";
import { HealthBanner } from "./HealthBanner";
import type { HealthIssue } from "./protocol";

export default { title: "HealthBanner" };

/** The macOS Accessibility issue exactly as the daemon words it for the
 * packaged app (``deckd.platform_macos._accessibility_missing_issue``). */
const AX: HealthIssue = {
  id: "accessibility_missing",
  severity: "error",
  title: "Accessibility permission missing",
  detail:
    "macOS isn't letting deckd.app control the mouse and keyboard. Buttons that open apps still work.",
  fix_steps: [
    "On the Mac, open System Settings → Privacy & Security → Accessibility.",
    "Turn on deckd.app. If it is already listed and on, select it, remove it with the − button, then add it again with +.",
    "This warning clears by itself a few seconds after the grant. If buttons still do nothing after that, quit and reopen deckd.app.",
  ],
  affects: ["pointer", "scroll", "key", "raise_window"],
};

const frame = { width: 420 };

/** Phone-width: the banner sits above the grid. */
export const AccessibilityMissing: Story = () => (
  <div style={frame}>
    <HealthBanner issues={[AX]} />
  </div>
);

/** A lower-severity issue renders in amber. */
export const Warning: Story = () => (
  <div style={frame}>
    <HealthBanner
      issues={[{ ...AX, id: "example_warning", severity: "warning", title: "Example warning", affects: ["key"] }]}
    />
  </div>
);
