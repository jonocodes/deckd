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
    cellSize: 100,
    onCellSizeChange: () => {},
    jogWidth: 1,
    onJogWidthChange: () => {},
    bottomScale: 1,
    onBottomScaleChange: () => {},
    labelScale: 1,
    onLabelScaleChange: () => {},
    largerControls: false,
    onLargerControlsChange: () => {},
    highContrast: false,
    onHighContrastChange: () => {},
    reduceMotion: false,
    onReduceMotionChange: () => {},
    showKeyHints: false,
    onShowKeyHintsChange: () => {},
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

describe("Settings — accessibility toggles", () => {
  afterEach(cleanup);

  it("renders an Accessibility section with three toggles", () => {
    renderSettings();
    expect(screen.getByRole("heading", { name: "Accessibility" })).not.toBeNull();
    expect(screen.getByRole("switch", { name: "Larger controls" })).not.toBeNull();
    expect(screen.getByRole("switch", { name: "High contrast" })).not.toBeNull();
    expect(screen.getByRole("switch", { name: "Reduce motion" })).not.toBeNull();
  });

  it("toggles persist their state", () => {
    const onLargerControls = vi.fn();
    const onHighContrast = vi.fn();
    const onReduceMotion = vi.fn();
    renderSettings({
      largerControls: false,
      onLargerControlsChange: onLargerControls,
      highContrast: false,
      onHighContrastChange: onHighContrast,
      reduceMotion: false,
      onReduceMotionChange: onReduceMotion,
    });
    const larger = screen.getByRole("switch", { name: "Larger controls" });
    fireEvent.click(larger);
    expect(onLargerControls).toHaveBeenCalledWith(true);
  });

  it("toggles show the correct on/off state", () => {
    renderSettings({
      largerControls: true,
      highContrast: true,
      reduceMotion: false,
    });
    expect(screen.getByRole("switch", { name: "Larger controls" }).getAttribute("aria-checked")).toBe("true");
    expect(screen.getByRole("switch", { name: "High contrast" }).getAttribute("aria-checked")).toBe("true");
    expect(screen.getByRole("switch", { name: "Reduce motion" }).getAttribute("aria-checked")).toBe("false");
  });
});
