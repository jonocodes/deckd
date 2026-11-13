// Serve an assembled Pages site the way GitHub Pages does, for `just pages`:
// static files, `dir/` → `dir/index.html`, and the site's 404.html (with a
// 404 status) for anything else — which is what makes app deep links work.
//
// Usage: node scripts/serve_pages.mjs <root> [port]   (default port 5290)
// <root> is the directory holding the site under its base, e.g. _site for
// _site/deckd/.
import { createServer } from "node:http";
import { readFile, stat } from "node:fs/promises";
import { extname, join, normalize, resolve } from "node:path";

const root = resolve(process.argv[2] ?? "_site");
const port = Number(process.argv[3] ?? 5290);
const TYPES = {
  ".html": "text/html; charset=utf-8", ".js": "text/javascript", ".mjs": "text/javascript",
  ".css": "text/css", ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png",
  ".ico": "image/x-icon", ".woff2": "font/woff2", ".map": "application/json", ".txt": "text/plain",
};

async function file(path) {
  try {
    const s = await stat(path);
    return s.isDirectory() ? file(join(path, "index.html")) : path;
  } catch {
    return null;
  }
}

createServer(async (req, res) => {
  const pathname = decodeURIComponent(new URL(req.url, "http://x").pathname);
  const target = normalize(join(root, pathname));
  let path = target.startsWith(root) ? await file(target) : null;
  let status = 200;
  if (!path) {
    // GitHub Pages: the site's top-level 404.html. Our site lives one level
    // down (e.g. deckd/), so look for it under the first path segment.
    status = 404;
    path = await file(join(root, pathname.split("/")[1] ?? "", "404.html"));
  }
  if (!path) return res.writeHead(404).end("not found");
  res.writeHead(status, { "content-type": TYPES[extname(path)] ?? "application/octet-stream" });
  res.end(await readFile(path));
}).listen(port, "127.0.0.1", () => console.log(`serving ${root} on http://127.0.0.1:${port}/`));
