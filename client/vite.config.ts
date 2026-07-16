import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    allowedHosts: ["lute"],
    // WS target is read by the client from VITE_DECKD_WS (see client/.env.development).
    // No proxy needed — the client hits the daemon directly.
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
});
