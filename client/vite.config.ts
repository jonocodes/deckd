import fs from "node:fs";
import path from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

/** Optional HTTPS for the Vite dev server. Set ``DECKD_TLS_DIR`` and
 * ``DECKD_TLS_HOST`` to make Vite serve on ``https://`` using a cert
 * provisioned by ``tailscale cert``. Chrome's PWA install prompt only
 * fires on a secure context, so this is the dev-mode path to installable
 * PWAs while keeping HMR alive. */
function readTlsConfig() {
  const dir = process.env.DECKD_TLS_DIR;
  const host = process.env.DECKD_TLS_HOST;
  if (!dir || !host) return undefined;
  const crt = path.join(dir, `${host}.crt`);
  const key = path.join(dir, `${host}.key`);
  if (!fs.existsSync(crt) || !fs.existsSync(key)) return undefined;
  return { cert: fs.readFileSync(crt), key: fs.readFileSync(key) };
}

const daemonUpstream = process.env.DECKD_UPSTREAM ?? "http://127.0.0.1:8765";
const https = readTlsConfig();

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Match any tailnet hostname so `<host>.<tailnet>.ts.net` isn't rejected.
    allowedHosts: true, // ["lute", "*", ".ts.net"],
    ...(https ? { https } : {}),
    // Same-origin proxy so the client never has to know the daemon's URL:
    // /ws, /health, /reload all appear at the Vite origin and are forwarded
    // to the local daemon.
    proxy: {
      "/ws": {
        target: daemonUpstream.replace(/^http/, "ws"),
        ws: true,
        rewriteWsOrigin: true,
      },
      "/health": daemonUpstream,
      "/reload": daemonUpstream,
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    // Two vendor chunks are intentionally large (ADR-0006): ``lucide`` is
    // the whole UI-glyph set, bundled eagerly (~198 KB gzipped); and
    // ``simple-icons`` is the whole brand-logo set (~2.1 MB gzipped) split
    // into its own *lazy* chunk that is only fetched the first time a layout
    // references a brand logo. Name them so the build output is legible, and
    // lift the size warning above them so it stays meaningful signal rather
    // than a permanent false alarm.
    chunkSizeWarningLimit: 6000,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes("node_modules/simple-icons")) return "simple-icons";
          if (id.includes("node_modules/lucide-react")) return "lucide";
        },
      },
    },
  },
});
