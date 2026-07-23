import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));

export const daemonLogPath = join(__dirname, ".daemon.log");

export function readDaemonLog(): string {
  return existsSync(daemonLogPath) ? readFileSync(daemonLogPath, "utf8") : "";
}

const KEY_LOG_RE = /\[key log\] keycodes=\[([^\]]*)\]/g;

export function keyLogEntries(sinceOffset = 0): number[][] {
  const entries: number[][] = [];
  const log = readDaemonLog();
  const start = sinceOffset > 0 ? log.slice(sinceOffset) : log;
  let m: RegExpExecArray | null;
  while ((m = KEY_LOG_RE.exec(start)) !== null) {
    entries.push(
      m[1]
        .split(",")
        .map((s) => s.trim())
        .filter((s) => s.length > 0)
        .map((s) => Number(s)),
    );
  }
  return entries;
}

export async function waitForKeyLog(
  expected: readonly number[],
  baselineOffset: number,
  options: { timeoutMs?: number; pollMs?: number } = {},
): Promise<number[][]> {
  const timeout = options.timeoutMs ?? 5000;
  const poll = options.pollMs ?? 50;
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    const entries = keyLogEntries(baselineOffset);
    if (entries.some((e) => arraysEqual(e, expected))) return entries;
    await new Promise((r) => setTimeout(r, poll));
  }
  throw new Error(
    `Timed out waiting for [${expected.join(", ")}]; new entries since baseline: ${JSON.stringify(keyLogEntries(baselineOffset))}`,
  );
}

function arraysEqual(a: readonly number[], b: readonly number[]): boolean {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return false;
  return true;
}