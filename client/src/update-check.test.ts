import { afterEach, describe, expect, it, vi } from "vitest";

import {
  UPDATE_POLL_MS,
  browserStorage,
  probeForUpdate,
  startUpdateCheck,
  type BuildStorage,
} from "./update-check";

function jsonResponse(body: unknown, ok = true): Response {
  return { ok, json: async () => body } as unknown as Response;
}

function memoryStorage(initial: string | null = null): BuildStorage & { peek(): string | null } {
  let value = initial;
  return {
    get: () => value,
    set: (next: string) => {
      value = next;
    },
    peek: () => value,
  };
}

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("probeForUpdate", () => {
  it("records the first build it sees without reloading", async () => {
    const storage = memoryStorage();
    const reload = vi.fn();
    const result = await probeForUpdate({
      healthUrl: "/health",
      fetchImpl: (async () => jsonResponse({ client_build: "v1" })) as unknown as typeof fetch,
      reload,
      storage,
    });

    expect(result).toBe("recorded");
    expect(storage.peek()).toBe("v1");
    expect(reload).not.toHaveBeenCalled();
  });

  it("leaves an unchanged build alone", async () => {
    const reload = vi.fn();
    const result = await probeForUpdate({
      healthUrl: "/health",
      fetchImpl: (async () => jsonResponse({ client_build: "v1" })) as unknown as typeof fetch,
      reload,
      storage: memoryStorage("v1"),
    });

    expect(result).toBe("unchanged");
    expect(reload).not.toHaveBeenCalled();
  });

  it("records the new build before reloading so a blocked reload can't loop", async () => {
    const storage = memoryStorage("v1");
    const order: string[] = [];
    const result = await probeForUpdate({
      healthUrl: "/health",
      fetchImpl: (async () => jsonResponse({ client_build: "v2" })) as unknown as typeof fetch,
      reload: () => {
        order.push(`reload at ${storage.peek()}`);
      },
      storage: {
        get: storage.get,
        set: (next: string) => {
          order.push(`set ${next}`);
          storage.set(next);
        },
      },
    });

    expect(result).toBe("reloaded");
    expect(order).toEqual(["set v2", "reload at v2"]);
  });

  it("passes cache: no-store so the health check never reads a cached body", async () => {
    const fetchImpl = vi.fn(async (_url: unknown, _init?: RequestInit) => jsonResponse({}));
    await probeForUpdate({
      healthUrl: "/health",
      fetchImpl: fetchImpl as unknown as typeof fetch,
      reload: vi.fn(),
      storage: memoryStorage(),
    });

    expect(fetchImpl).toHaveBeenCalledWith("/health", { cache: "no-store" });
  });

  it("returns unknown for a dev daemon with no client_build field", async () => {
    const storage = memoryStorage();
    const reload = vi.fn();
    const result = await probeForUpdate({
      healthUrl: "/health",
      fetchImpl: (async () => jsonResponse({ ok: true })) as unknown as typeof fetch,
      reload,
      storage,
    });

    expect(result).toBe("unknown");
    expect(storage.peek()).toBeNull();
    expect(reload).not.toHaveBeenCalled();
  });

  it("returns unknown for a non-string fingerprint", async () => {
    const storage = memoryStorage();
    const result = await probeForUpdate({
      healthUrl: "/health",
      fetchImpl: (async () => jsonResponse({ client_build: 42 })) as unknown as typeof fetch,
      reload: vi.fn(),
      storage,
    });

    expect(result).toBe("unknown");
    expect(storage.peek()).toBeNull();
  });

  it("returns unknown for a failed request", async () => {
    const storage = memoryStorage();
    const result = await probeForUpdate({
      healthUrl: "/health",
      fetchImpl: (async () => jsonResponse({}, false)) as unknown as typeof fetch,
      reload: vi.fn(),
      storage,
    });

    expect(result).toBe("unknown");
    expect(storage.peek()).toBeNull();
  });

  it("returns unknown when the daemon is offline", async () => {
    const result = await probeForUpdate({
      healthUrl: "/health",
      fetchImpl: (async () => {
        throw new Error("connection refused");
      }) as unknown as typeof fetch,
      reload: vi.fn(),
      storage: memoryStorage(),
    });

    expect(result).toBe("unknown");
  });
});

describe("startUpdateCheck", () => {
  it("polls on the interval and reloads when the served bundle changes", async () => {
    vi.useFakeTimers();
    let build = "v1";
    const fetchImpl = vi.fn(async () => jsonResponse({ client_build: build }));
    const reload = vi.fn();
    const stop = startUpdateCheck({
      intervalMs: 1000,
      deps: {
        healthUrl: "/health",
        fetchImpl: fetchImpl as unknown as typeof fetch,
        reload,
        storage: memoryStorage(),
      },
    });

    // Immediate check records v1.
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(0);

    await vi.advanceTimersByTimeAsync(1000);
    expect(fetchImpl).toHaveBeenCalledTimes(2);
    expect(reload).not.toHaveBeenCalled();

    build = "v2";
    await vi.advanceTimersByTimeAsync(1000);
    expect(reload).toHaveBeenCalledTimes(1);

    stop();
    await vi.advanceTimersByTimeAsync(5000);
    expect(fetchImpl).toHaveBeenCalledTimes(3);
  });

  it("re-checks when an installed PWA resumes", async () => {
    vi.useFakeTimers();
    const fetchImpl = vi.fn(async () => jsonResponse({ client_build: "v1" }));
    const stop = startUpdateCheck({
      intervalMs: 60_000,
      deps: {
        healthUrl: "/health",
        fetchImpl: fetchImpl as unknown as typeof fetch,
        reload: vi.fn(),
        storage: memoryStorage(),
      },
    });
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(0);

    window.dispatchEvent(new Event("pageshow"));
    await vi.advanceTimersByTimeAsync(0);
    expect(fetchImpl).toHaveBeenCalledTimes(2);

    stop();
    window.dispatchEvent(new Event("pageshow"));
    await vi.advanceTimersByTimeAsync(0);
    expect(fetchImpl).toHaveBeenCalledTimes(2);
  });

  it("defaults the poll interval to 30s", async () => {
    vi.useFakeTimers();
    const fetchImpl = vi.fn(async () => jsonResponse({ client_build: "v1" }));
    const stop = startUpdateCheck({
      deps: {
        healthUrl: "/health",
        fetchImpl: fetchImpl as unknown as typeof fetch,
        reload: vi.fn(),
        storage: memoryStorage(),
      },
    });

    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(UPDATE_POLL_MS - 1);
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(fetchImpl).toHaveBeenCalledTimes(2);
    stop();
  });

  it("falls back to an in-memory store when localStorage throws", () => {
    const spy = vi.spyOn(window.localStorage, "getItem").mockImplementation(() => {
      throw new Error("private mode");
    });
    const storage = browserStorage();
    expect(storage.get()).toBeNull();
    storage.set("v1");
    expect(storage.get()).toBe("v1");
    spy.mockRestore();
  });
});
