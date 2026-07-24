import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Settings } from "./Settings";

/** Settings has a wide props surface; only the auth-related bits matter here,
 * the rest get inert defaults. */
function renderSettings(overrides: Partial<Parameters<typeof Settings>[0]> = {}) {
  const base = {
    layout: null,
    status: "open" as const,
    scrollScale: 1,
    scrollInvert: false,
    onScrollScaleChange: () => {},
    onScrollInvertChange: () => {},
    trackpadSensitivity: 1,
    onTrackpadSensitivityChange: () => {},
    wakeLockEnabled: false,
    onWakeLockChange: () => {},
    contentScale: 1,
    onContentScaleChange: () => {},
    jogWidth: 1,
    onJogWidthChange: () => {},
    bottomScale: 1,
    onBottomScaleChange: () => {},
    labelScale: 1,
    onLabelScaleChange: () => {},
  };
  return render(<Settings {...base} {...overrides} />);
}

describe("Settings — log out", () => {
  afterEach(cleanup);

  it("hides the log-out button when there is no stored password", () => {
    renderSettings({ canDeauthenticate: false, onDeauthenticate: () => {} });
    expect(screen.queryByRole("button", { name: /log out/i })).toBeNull();
  });

  it("shows the log-out button and fires the callback when a password is stored", () => {
    const onDeauthenticate = vi.fn();
    renderSettings({ canDeauthenticate: true, onDeauthenticate });
    const btn = screen.getByRole("button", { name: /log out/i });
    fireEvent.click(btn);
    expect(onDeauthenticate).toHaveBeenCalledOnce();
  });
});
