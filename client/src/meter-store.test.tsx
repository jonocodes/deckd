import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { useMeterStore } from "./meter-store";

const IDS = new Set<string>(["cpu_percent"]);

beforeEach(() => window.localStorage.clear());
afterEach(() => window.localStorage.clear());

describe("useMeterStore identity stability", () => {
  // Regression guard (issue #40): App feeds widget_update frames to
  // ``meter.onUpdate`` and puts it in the socket effect's dependency array.
  // If ``onUpdate`` got a fresh identity per render — or per readings push —
  // the socket would tear down and reconnect in a tight loop, never staying
  // open long enough to authenticate, so the password gate never appeared.
  it("keeps onUpdate referentially stable across renders", () => {
    const { result, rerender } = renderHook(() => useMeterStore(IDS));
    const first = result.current.onUpdate;
    rerender();
    rerender();
    expect(result.current.onUpdate).toBe(first);
  });

  it("keeps onUpdate stable even after a readings push re-renders the hook", () => {
    const { result } = renderHook(() => useMeterStore(IDS));
    const before = result.current.onUpdate;
    act(() => {
      result.current.onUpdate({
        type: "widget_update",
        id: "cpu_percent",
        source: "cpu_percent",
        value: 42,
        unit: "%",
        stale: false,
      });
    });
    // The push changes ``readings`` (so the memoised store object legitimately
    // gets a new identity), but ``onUpdate`` itself must not change — that is
    // what the socket effect depends on.
    expect(result.current.readings.cpu_percent?.value).toBe(42);
    expect(result.current.onUpdate).toBe(before);
  });
});
