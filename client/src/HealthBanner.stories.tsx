import type { Story } from "@ladle/react";
import { HealthBanner } from "./HealthBanner";
import type { HealthIssue } from "./protocol";

export default { title: "HealthBanner" };

/** The macOS Accessibility issue, worded like the daemon's
 * (``deckd.platform_macos._accessibility_missing_issue``) for the packaged
 * app. A hand copy for layout review; the daemon's text is the source. */
const AX: HealthIssue = {
  id: "accessibility_missing",
  severity: "error",
  title: "Accessibility permission missing",
  detail:
    "macOS isn't letting deckd.app control the mouse and keyboard. Buttons that open apps still work.",
  fix_steps: [
    "On the Mac, open System Settings → Privacy & Security → Accessibility.",
    "Turn on deckd.app. If it is already listed and on, run `tccutil reset Accessibility com.deckd.daemon` in Terminal, then add deckd.app again with +.",
    "This warning clears by itself a few seconds after the grant. If buttons still do nothing after that, quit and reopen deckd.app.",
  ],
  affects: ["pointer", "scroll", "key", "raise_window"],
};

const frame = { width: 420 };

/** Phone-width: the banner sits above the grid. */
export const AccessibilityMissing: Story = () => (
  <div style={frame}>
    <HealthBanner issues={[AX]} dismissed={new Set()} onDismiss={() => {}} />
  </div>
);

/** A lower-severity issue renders in amber. */
export const Warning: Story = () => (
  <div style={frame}>
    <HealthBanner
      issues={[{ ...AX, id: "example_warning", severity: "warning", title: "Example warning", affects: ["key"] }]}
      dismissed={new Set()}
      onDismiss={() => {}}
    />
  </div>
);

/** The macOS Automation issue (#196), worded like
 * ``deckd.platform_macos._automation_missing_issue`` for the packaged app. */
const AUTOMATION: HealthIssue = {
  id: "automation_system_events_missing",
  severity: "error",
  title: "Automation permission missing",
  detail:
    "macOS isn't letting deckd.app control System Events, so key buttons do nothing and the deck may not follow the app in front.",
  fix_steps: [
    "On the Mac, open System Settings → Privacy & Security → Automation.",
    "Under deckd.app, turn on System Events.",
    "If deckd.app isn't listed, or System Events is already on, run `tccutil reset AppleEvents com.deckd.daemon` in Terminal, then click OK when macOS asks to let it control System Events.",
    "This warning clears by itself a few seconds after the grant.",
  ],
  affects: ["key", "focus"],
};

/** Both grants missing: one banner each, Accessibility first. */
export const BothMissing: Story = () => (
  <div style={frame}>
    <HealthBanner issues={[AX, AUTOMATION]} dismissed={new Set()} onDismiss={() => {}} />
  </div>
);
