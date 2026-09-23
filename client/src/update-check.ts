import { resolve_health_url } from "./socket";

/** How often a live client re-reads ``/health`` looking for a new bundle. */
export const UPDATE_POLL_MS = 30_000;

const STORAGE_KEY = "deckd.build";

export type BuildStorage = {
  get(): string | null;
  set(value: string): void;
};

export type UpdateProbeDeps = {
  healthUrl: string;
  fetchImpl: typeof fetch;
  reload: () => void;
  storage: BuildStorage;
};

export type UpdateProbeResult = "reloaded" | "recorded" | "unchanged" | "unknown";

/** One freshness check: read the daemon's client fingerprint, compare it
 * with the last one this browser saw, and reload on a change.
 *
 * Pure in its dependencies (fetch / storage / reload are injected) so the
 * decision table is unit-testable without a daemon or a browser reload.
 * ``unknown`` covers every "can't tell" case — offline, no daemon, a dev
 * server without ``--client-dist`` (no ``client_build`` field) — and always
 * means "leave the page alone". */
export async function probeForUpdate(deps: UpdateProbeDeps): Promise<UpdateProbeResult> {
  let build: string | null = null;
  try {
    const res = await deps.fetchImpl(deps.healthUrl, { cache: "no-store" });
    if (!res.ok) return "unknown";
    const body = (await res.json()) as { client_build?: unknown };
    if (typeof body.client_build === "string" && body.client_build) {
      build = body.client_build;
    }
  } catch {
    return "unknown";
  }
  if (build === null) return "unknown";

  const seen = deps.storage.get();
  if (seen === build) return "unchanged";
  // Record before reloading: if the reload is blocked (browser prompt,
  // interrupted navigation) a later check must not reload again forever.
  deps.storage.set(build);
  if (seen === null) return "recorded";
  deps.reload();
  return "reloaded";
}

/** ``localStorage`` when usable, an in-memory shim when not (Safari private
 * mode and some embedded WebViews throw on access). A shim only loses the
 * cross-session memory; within one page life the check still works. */
export function browserStorage(): BuildStorage {
  try {
    const store = window.localStorage;
    store.getItem(STORAGE_KEY);
    return {
      get: () => store.getItem(STORAGE_KEY),
      set: (value) => store.setItem(STORAGE_KEY, value),
    };
  } catch {
    let memory: string | null = null;
    return {
      get: () => memory,
      set: (value) => {
        memory = value;
      },
    };
  }
}

export type UpdateCheckOptions = {
  intervalMs?: number;
  deps?: Partial<UpdateProbeDeps>;
};

/** Keep the running bundle fresh for the life of the page.
 *
 * Polls on an interval, and also checks the moment an installed PWA comes
 * back from suspension (``pageshow`` / ``visibilitychange``) or regains
 * connectivity — the cases where a phone surfaces a long-cached shell.
 * Returns a teardown function. */
export function startUpdateCheck(options: UpdateCheckOptions = {}): () => void {
  const intervalMs = options.intervalMs ?? UPDATE_POLL_MS;
  const deps: UpdateProbeDeps = {
    healthUrl: options.deps?.healthUrl ?? resolve_health_url(),
    fetchImpl: options.deps?.fetchImpl ?? fetch,
    reload: options.deps?.reload ?? (() => window.location.reload()),
    storage: options.deps?.storage ?? browserStorage(),
  };

  let inFlight = false;
  const checkNow = async () => {
    // A slow /health must not stack requests behind a 30s interval.
    if (inFlight) return;
    inFlight = true;
    try {
      await probeForUpdate(deps);
    } finally {
      inFlight = false;
    }
  };

  const onResume = () => {
    if (!document.hidden) void checkNow();
  };

  const timer = window.setInterval(() => void checkNow(), intervalMs);
  window.addEventListener("pageshow", onResume);
  window.addEventListener("online", onResume);
  document.addEventListener("visibilitychange", onResume);
  void checkNow();

  return () => {
    window.clearInterval(timer);
    window.removeEventListener("pageshow", onResume);
    window.removeEventListener("online", onResume);
    document.removeEventListener("visibilitychange", onResume);
  };
}
