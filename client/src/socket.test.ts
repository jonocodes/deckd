/** Reconnect telemetry on the socket hook (issue #64).
 *
 * The App renders the reconnecting overlay from facts the hook owns:
 * the attempt counter, the last error, and whether the user cancelled the
 * auto-retry loop. These tests drive a stub WebSocket so those facts can
 * be asserted without a daemon.
 */
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useDeckdSocket } from "./socket";

class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  static OPEN = 1;
  url: string;
  readyState = 0;
  sent: string[] = [];
  onopen: (() => void) | null = null;
  onclose: ((ev: { code: number; reason: string }) => void) | null = null;
  onmessage: ((ev: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }
  send(data: string) {
    this.sent.push(data);
  }
  close() {
    this.readyState = 3;
  }
  open() {
    this.readyState = FakeWebSocket.OPEN;
    this.onopen?.();
  }
  fail(code: number, reason = "") {
    this.readyState = 3;
    this.onclose?.({ code, reason });
  }
}

const noop = () => {};

function hookArgs() {
  // Stable identities: a fresh callback per render would re-run the hook's
  // connect effect and spin up a feedback loop of sockets.
  return [noop, noop, noop] as const;
}

describe("useDeckdSocket — reconnect feedback (issue #64)", () => {
  beforeEach(() => {
    FakeWebSocket.instances = [];
    vi.stubGlobal("WebSocket", FakeWebSocket);
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(new Response(null, { status: 200 }))),
    );
    window.history.replaceState(null, "", "/");
  });
  afterEach(() => {
    // Vitest globals are off, so RTL's auto-cleanup can't register itself;
    // unmount explicitly or a pending retry timer leaks into the next test.
    cleanup();
    vi.unstubAllGlobals();
  });

  it("resets attempt on open and records the last error on close", async () => {
    const { result } = renderHook(() => useDeckdSocket(...hookArgs()));
    await waitFor(() => expect(FakeWebSocket.instances.length).toBe(1));
    act(() => FakeWebSocket.instances[0].open());
    expect(result.current.status).toBe("open");
    expect(result.current.attempt).toBe(0);
    expect(result.current.lastError).toBe("");

    act(() => FakeWebSocket.instances[0].fail(1006));
    expect(result.current.status).toBe("closed");
    expect(result.current.lastError).toBe("daemon not reachable");
  });

  it("counts attempts as the retry loop runs", async () => {
    const { result } = renderHook(() => useDeckdSocket(...hookArgs()));
    await waitFor(() => expect(FakeWebSocket.instances.length).toBe(1));
    act(() => FakeWebSocket.instances[0].open());
    act(() => FakeWebSocket.instances[0].fail(1006));

    // The 500 ms backoff fires and opens a second socket.
    await waitFor(
      () => expect(FakeWebSocket.instances.length).toBe(2),
      { timeout: 2000 },
    );
    await waitFor(
      () => expect(result.current.attempt).toBe(1),
      { timeout: 2000 },
    );
  });

  it("cancel stops the retry loop; retry resumes it", async () => {
    const { result } = renderHook(() => useDeckdSocket(...hookArgs()));
    await waitFor(() => expect(FakeWebSocket.instances.length).toBe(1));
    act(() => FakeWebSocket.instances[0].open());
    act(() => FakeWebSocket.instances[0].fail(1006));

    act(() => result.current.cancelReconnect());
    expect(result.current.cancelled).toBe(true);

    // No new socket while cancelled, even after the backoff window.
    await new Promise((resolve) => setTimeout(resolve, 700));
    expect(FakeWebSocket.instances.length).toBe(1);

    act(() => result.current.retryNow());
    await waitFor(
      () => expect(FakeWebSocket.instances.length).toBe(2),
      { timeout: 2000 },
    );
    expect(result.current.cancelled).toBe(false);
  });
});
