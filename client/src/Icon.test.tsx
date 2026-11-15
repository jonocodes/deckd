import { cleanup, fireEvent, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { Icon } from "./Icon";

describe("Icon — desktop source (issue #187)", () => {
  afterEach(() => {
    cleanup();
    window.history.replaceState(null, "", "/");
  });

  it("renders the daemon-served app icon as an image", () => {
    const { container } = render(
      <Icon icon={{ source: "desktop", name: "com.gexperts.Tilix" }} className="icon" />,
    );
    const img = container.querySelector("img");
    expect(img).not.toBeNull();
    expect(img!.getAttribute("src")).toBe("/desktop-apps/com.gexperts.Tilix/icon");
    expect(img!.getAttribute("data-icon-source")).toBe("desktop");
    expect(img!.className).toBe("icon");
  });

  it("URL-encodes the desktop id", () => {
    const { container } = render(<Icon icon={{ source: "desktop", name: "../x y" }} />);
    expect(container.querySelector("img")!.getAttribute("src")).toBe(
      "/desktop-apps/..%2Fx%20y/icon",
    );
  });

  it("falls back to the missing placeholder when the icon fails to load", () => {
    const { container } = render(
      <Icon icon={{ source: "desktop", name: "not.installed" }} className="icon" />,
    );
    fireEvent.error(container.querySelector("img")!);
    expect(container.querySelector("img")).toBeNull();
    const missing = container.querySelector("[data-icon-missing]");
    expect(missing).not.toBeNull();
    expect(missing!.getAttribute("title")).toBe("unknown icon: desktop:not.installed");
  });

  it("uses bundled fixture icons when there is no daemon (demo mode)", () => {
    window.history.replaceState(null, "", "/?demo=apps");
    const { container } = render(<Icon icon={{ source: "desktop", name: "com.slack.Slack" }} />);
    expect(container.querySelector("img")!.getAttribute("src")).toBe(
      "/demo-app-icons/com.slack.Slack.svg",
    );
  });
});
