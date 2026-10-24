// Shared homepage scenes. Mount points: <div data-dk="…">, see MOUNTS below.
// Every phone is the real deckd client in an iframe, rendered at a fixed
// viewport and scaled to fit. They're passive: no input reaches the client.
//
// The client comes from ?app=<url> on the page, <html data-app>, or the
// public Pages build. The showcase fixtures (home, gmail, meet, media) need a
// client from this branch: ?app=http://127.0.0.1:5288/ with `vite dev` running.

const APP = new URLSearchParams(location.search).get("app") || document.documentElement.dataset.app || "https://jonocodes.github.io/deckd/";
const LANDSCAPE = [700, 390]; // a 4x2 deck fills this edge to edge
const PORTRAIT = [390, 760];
const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
// ?eager loads every phone up front (for full-page screenshots).
const LOADING = new URLSearchParams(location.search).has("eager") ? "eager" : "lazy";

const h = (html) => { const t = document.createElement("template"); t.innerHTML = html.trim(); return t.content.firstElementChild; };
const clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));
const ease = (u) => (u < .5 ? 4 * u * u * u : 1 - Math.pow(-2 * u + 2, 3) / 2);
const span = (t, a, b) => clamp((t - a) / (b - a));
const on = (t, a, b) => t >= a && t < b;

const CURSOR = '<svg class="dk-cursor" viewBox="0 0 18 22"><path d="M1 1v17l4.5-4.2 3 6.7 3-1.4-3-6.5H15z" fill="#fff" stroke="#000" stroke-width="1.3" stroke-linejoin="round"/></svg>';
const ARROW = (label = "your computer") => `<div class="dk-arrow" aria-hidden="true"><svg viewBox="0 0 28 14"><path d="M0 7h25M19 1l6 6-6 6" fill="none" stroke="currentColor" stroke-width="1.6"/></svg>${label}</div>`;

/** A phone (or any screen) showing the client. ``queries`` may be several:
 * they stack, and ``show(i)`` crossfades between them. */
function phone(queries, { passive = true, size = LANDSCAPE } = {}) {
  queries = [].concat(queries);
  const [w, hgt] = size;
  const el = h(`<div class="dk-phone${hgt > w ? " portrait" : ""}"><div class="dk-screen" style="aspect-ratio:${w}/${hgt}">
    <div class="dk-stage${passive ? " passive" : ""}" style="width:${w}px;height:${hgt}px"><div class="dk-overlay"></div></div></div></div>`);
  const screen = el.querySelector(".dk-screen"), stage = el.querySelector(".dk-stage"), overlay = el.querySelector(".dk-overlay");
  const frames = queries.map((q, i) => {
    const f = h(`<iframe loading="${LOADING}" src="${APP}?${q}" title="deckd client" ${passive ? 'tabindex="-1" aria-hidden="true" inert' : ""}></iframe>`);
    if (queries.length > 1) { f.style.transition = "opacity .3s"; f.style.opacity = i === 0 ? 1 : 0; }
    stage.insertBefore(f, overlay);
    return f;
  });
  new ResizeObserver(([e]) => { stage.style.transform = `scale(${e.contentRect.width / w})`; }).observe(screen);
  return { el, overlay, frames, show: (i) => frames.forEach((f, j) => (f.style.opacity = j === i ? 1 : 0)) };
}

function finger(overlay) {
  const f = h('<div class="dk-finger"></div>');
  overlay.append(f);
  let wasDown = false;
  return {
    set(x, y, visible, down) {
      f.style.left = x + "px"; f.style.top = y + "px";
      f.classList.toggle("on", visible); f.classList.toggle("down", down);
      if (down && !wasDown && visible) { const r = h('<div class="dk-ripple"></div>'); r.style.left = x + "px"; r.style.top = y + "px"; overlay.append(r); setTimeout(() => r.remove(), 520); }
      wasDown = down && visible;
    },
  };
}

// A gentle arc from p to q (quadratic Bézier, control point off to one side).
function arc(p, q, u, bow = .22) {
  const mx = (p[0] + q[0]) / 2, my = (p[1] + q[1]) / 2, dx = q[0] - p[0], dy = q[1] - p[1];
  const c = [mx - dy * bow, my + dx * bow];
  const a = (1 - u) * (1 - u), b = 2 * (1 - u) * u, d = u * u;
  return [a * p[0] + b * c[0] + d * q[0], a * p[1] + b * c[1] + d * q[1]];
}

// Run frame(t) on a loop while visible; one static frame under reduced motion.
function loop(root, period, frame, stillAt) {
  if (reduced) { frame(stillAt); return; }
  let start = 0, raf = 0, visible = false;
  const tick = (now) => { if (!start) start = now; frame(((now - start) / 1000) % period); raf = requestAnimationFrame(tick); };
  new IntersectionObserver(([e]) => {
    if (e.isIntersecting && !visible) { visible = true; raf = requestAnimationFrame(tick); }
    else if (!e.isIntersecting && visible) { visible = false; cancelAnimationFrame(raf); }
  }).observe(root);
}

// ---------------------------------------------------------------- cycle
// The hero: the page's own list of "windows" (any [data-q] inside the mount)
// takes focus in turn and the phone follows. Not clickable — it just plays.
function cycle(root) {
  const items = [...root.querySelectorAll("[data-q]")];
  const p = phone(items.map((i) => i.dataset.q));
  (root.querySelector(".dk-cycle-phone") || root).append(p.el);
  const pick = (k) => { items.forEach((it, j) => it.toggleAttribute("aria-current", j === k)); p.show(k); };
  pick(0);
  if (reduced) return;
  let k = 0, timer = 0;
  new IntersectionObserver(([e]) => {
    clearInterval(timer);
    if (e.isIntersecting) timer = setInterval(() => pick((k = (k + 1) % items.length)), 3200);
  }).observe(root);
}

// ---------------------------------------------------------------- trackpad
function trackpad(root) {
  const p = phone("demo=trackpad");
  const desk = h(`<div class="dk-desk"><div class="bar"><i></i><i></i><i></i><span>notes.txt — Text Editor</span></div>
    <div class="body"><div class="dk-tp-save">Save</div><div class="dk-tp-lines"><b style="width:88%"></b><b style="width:72%"></b><b style="width:94%"></b><b style="width:60%"></b></div>
    <div class="dk-tp-file"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/></svg>todo.txt</div>
    <div class="dk-toast">Saved</div>${CURSOR}</div></div>`);
  root.append(h('<div class="dk-scene"></div>'));
  root.firstChild.append(p.el, h(ARROW()), desk);
  const f = finger(p.overlay);
  const body = desk.querySelector(".body"), cur = desk.querySelector(".dk-cursor");
  const save = desk.querySelector(".dk-tp-save"), file = desk.querySelector(".dk-tp-file"), toast = desk.querySelector(".dk-toast");
  const centre = (el) => { const b = body.getBoundingClientRect(), r = el.getBoundingClientRect(); return [r.left - b.left + r.width / 2, r.top - b.top + r.height / 2]; };
  const PA = [170, 268], PB = [480, 150]; // on the trackpad surface (x 10–606, y 114–315)

  loop(root, 7, (t) => {
    const F = centre(file), S = centre(save);
    let fp, fv, fd, c;
    if (t < 2.6) {
      const u = ease(span(t, .3, 1.9));
      fp = t >= 1.9 ? PB : arc(PA, PB, u); c = arc(F, S, u); fv = true;
      fd = t < 1.9 || on(t, 2.3, 2.42);
    } else {
      const u = ease(span(t, 3.7, 5.3));
      fp = arc(PB, PA, u); c = arc(S, F, u); fv = t >= 3.5 && t < 6.0;
      fd = (t >= 3.5 && t < 5.3) || on(t, 5.7, 5.82);
    }
    f.set(fp[0], fp[1], fv, fd);
    cur.style.left = c[0] + "px"; cur.style.top = c[1] + "px";
    save.classList.toggle("hit", on(t, 2.3, 2.45));
    toast.classList.toggle("on", on(t, 2.45, 4.0));
    file.classList.toggle("hit", on(t, 5.7, 6.8));
  }, 2.5);
}

// ---------------------------------------------------------------- scroll strip
function scroll(root) {
  const p = phone("demo=firefox");
  const lines = (n) => Array.from({ length: n }, (_, i) => `<b style="width:${70 + ((i * 37) % 29)}%"></b>`).join("");
  const desk = h(`<div class="dk-desk"><div class="bar"><i></i><i></i><i></i><span>A long read — Firefox</span></div>
    <div class="body"><div class="dk-article"><h4>Why every room needs a jog wheel</h4>${lines(6)}
    <div class="img" style="background:#c7d2fe"></div>${lines(8)}<div class="img" style="background:#fed7aa"></div>${lines(9)}
    <div class="img" style="background:#bbf7d0"></div>${lines(10)}</div><div class="dk-scrollbar"></div></div></div>`);
  root.append(h('<div class="dk-scene"></div>'));
  root.firstChild.append(p.el, h(ARROW()), desk);
  const f = finger(p.overlay);
  const glow = h('<div class="dk-glow" style="left:616px;top:8px;width:76px;height:309px"></div>');
  p.overlay.append(glow);
  const art = desk.querySelector(".dk-article"), bar = desk.querySelector(".dk-scrollbar");
  const SWIPES = [[.4, 1], [1.9, 1], [3.6, -1], [5.1, -1]]; // [start, +1 = flick up]
  const DRAG = .32, D1 = 90, D2 = 150, TAU = .35;

  loop(root, 6.8, (t) => {
    let off = 0, fv = false, fd = false, fy = 0;
    for (const [s, d] of SWIPES) {
      if (t < s) continue;
      const u = span(t, s, s + DRAG);
      off += d * D1 * ease(u);
      if (t > s + DRAG) off += d * D2 * (1 - Math.exp(-(t - s - DRAG) / TAU));
      if (t < s + DRAG + .15) { fv = true; fd = t < s + DRAG; fy = d > 0 ? 270 - 190 * ease(u) : 80 + 190 * ease(u); }
    }
    f.set(654, fy, fv, fd);
    glow.classList.toggle("on", fd);
    art.style.transform = `translateY(${-off}px)`;
    bar.style.top = 30 + off * .22 + "px";
  }, 2.5);
}

// ---------------------------------------------------------------- focus follows
// Click a window on a fake desktop; the phone crossfades to that app's deck.
const WINS = [
  { q: "demo=firefox", name: "Firefox", c: "#ff7139", box: [3, 4, 56, 52], hit: [12, 14] },
  { q: "demo=gmail", name: "Inbox (3) - Gmail", c: "#d93025", box: [41, 12, 56, 52], hit: [88, 22] },
  { q: "demo=meet", name: "Weekly sync - Google Meet", c: "#00897b", box: [20, 44, 58, 52], hit: [48, 90] },
];
function focus(root) {
  const p = phone(WINS.map((w) => w.q));
  const desk = h(`<div class="dk-desk dk-wall"><div class="bar"><span>your desktop</span></div><div class="body">${WINS.map((w) =>
    `<div class="dk-win" style="left:${w.box[0]}%;top:${w.box[1]}%;width:${w.box[2]}%;height:${w.box[3]}%;--c:${w.c}"><div class="t">${w.name}</div><b></b><b></b><b></b></div>`).join("")}${CURSOR}</div></div>`);
  root.append(h('<div class="dk-scene"></div>'));
  root.firstChild.append(p.el, h(ARROW("focus")), desk);
  const wins = [...desk.querySelectorAll(".dk-win")], cur = desk.querySelector(".dk-cursor"), body = desk.querySelector(".body");
  loop(root, 9, (t) => {
    const k = Math.floor(t / 3), u = t % 3, prev = (k + 2) % 3;
    const bw = body.clientWidth / 100, bh = body.clientHeight / 100;
    const a = [WINS[prev].hit[0] * bw, WINS[prev].hit[1] * bh], b = [WINS[k].hit[0] * bw, WINS[k].hit[1] * bh];
    const c = arc(a, b, ease(span(u, .2, 1.0)), .15);
    cur.style.left = c[0] + "px"; cur.style.top = c[1] + "px";
    cur.style.transform = on(u, 1.05, 1.2) ? "scale(.85)" : "";
    const active = u >= 1.1 ? k : prev;
    wins.forEach((w, i) => { w.style.zIndex = i === active ? 3 : i === (active + 2) % 3 ? 2 : 1; w.classList.toggle("on", i === active); });
    p.show(active);
  }, 1.5);
}

// ---------------------------------------------------------------- web apps
// Each deck in the orientation it looks best in.
const WEBAPPS = [
  ["demo=gmail", "Gmail", "compose, reply, archive, next", LANDSCAPE],
  ["demo=youtube", "YouTube", "play, skip 10s, captions", PORTRAIT],
  ["demo=meet", "Google Meet", "mic, camera, raise hand", LANDSCAPE],
];
function webapps(root) {
  const g = h('<div class="dk-row"></div>');
  for (const [q, name, what, size] of WEBAPPS) {
    const fig = h(`<figure${size === PORTRAIT ? ' class="tall"' : ""}><figcaption><b>${name}</b> ${what}</figcaption></figure>`);
    fig.prepend(phone(q, { size }).el);
    g.append(fig);
  }
  root.append(g);
}

// ---------------------------------------------------------------- now playing
function nowplaying(root) { root.append(phone("demo=media", { size: PORTRAIT }).el); }

// A single passive phone: <div data-dk="phone" data-q="demo=youtube">.
function single(root) { root.append(phone(root.dataset.q).el); }

// ---------------------------------------------------------------- install
const REL = "https://github.com/jonocodes/deckd/releases/latest";
const INSTALL = {
  Linux: `<ol>
    <li><a class="dl" href="${REL}">Download the AppImage</a><span class="note">x86_64 or aarch64</span></li>
    <li>Run it:<pre>chmod +x deckd-*.AppImage
./deckd-*.AppImage --bind 0.0.0.0</pre></li>
    <li>Once, so it can send keys and see the focused window (asks for your password):<pre>pkexec ./deckd-install-system-integration.sh ./deckd-*.AppImage</pre></li>
    <li>Open the printed address on your phone. The password is in <code>~/.config/deckd/password</code>.</li></ol>
    <p class="note">GNOME and KDE on Wayland, or any X11 desktop.</p>`,
  macOS: `<ol>
    <li><a class="dl" href="${REL}">Download the DMG</a><span class="note">Apple Silicon</span></li>
    <li>Drag deckd to Applications. It isn't notarized yet, so open it the first time with right-click → Open.</li>
    <li>Allow Accessibility when asked, then pick <b>Allow LAN access</b> from the menu-bar icon.</li>
    <li>Open the address on your phone.</li></ol>
    <p class="note">Now playing and D-Bus actions are Linux-only for now.</p>`,
  "From source": `<pre>git clone https://github.com/jonocodes/deckd && cd deckd
uv venv --python 3.11 && uv pip install -e ".[uinput,dbus]"
(cd client && npm install) && just build-client
just run-daemon</pre><p class="note">Python 3.11+, Node 18+. Per-platform setup is in the <a href="https://github.com/jonocodes/deckd/blob/main/docs/GUIDE.md#running-deckd">guide</a>.</p>`,
  Nix: `<pre>nix run github:jonocodes/deckd -- --bind 0.0.0.0</pre><p class="note">NixOS and home-manager modules are in the flake — see the <a href="https://github.com/jonocodes/deckd#nix">README</a>.</p>`,
};
function install(root) {
  const guess = /Mac/.test(navigator.platform) ? "macOS" : "Linux";
  const tabs = h('<div role="tablist" aria-label="Install deckd"></div>');
  const panel = h('<div role="tabpanel"></div>');
  const pick = (n) => {
    tabs.querySelectorAll("button").forEach((b) => b.setAttribute("aria-selected", b.textContent === n));
    panel.innerHTML = INSTALL[n];
  };
  for (const n of Object.keys(INSTALL)) { const b = h(`<button role="tab">${n}</button>`); b.onclick = () => pick(n); tabs.append(b); }
  root.classList.add("dk-install");
  root.append(tabs, panel);
  pick(guess);
}

// Embedded clients that open in a chrome view (trackpad, now playing) focus
// their first control on load, and the browser scrolls this page to that
// iframe — inert doesn't stop a cross-origin frame doing it. Fixed in the
// client (focus({ preventScroll: true })); until that's deployed, undo a
// scroll that lands together with focus moving into a passive embed.
let lastY = scrollY, lastActive = document.activeElement;
// A focus change between scrolls (an embed loading out of view) is fine; the
// visitor's next input makes it the new baseline.
const baseline = () => (lastActive = document.activeElement);
for (const ev of ["wheel", "touchstart", "keydown", "pointerdown"]) addEventListener(ev, baseline, { passive: true, capture: true });
window.dkScrollIntent = baseline; // for scripted scrolls (screenshots, recordings)
addEventListener("scroll", () => {
  const a = document.activeElement;
  if (a !== lastActive && a?.tagName === "IFRAME" && a.inert) { lastActive = a; scrollTo(0, lastY); return; }
  lastActive = a; lastY = scrollY;
}, { passive: true });

const MOUNTS = { cycle, trackpad, scroll, focus, webapps, nowplaying, install, phone: single, ...(window.DK_CONTENT || {}) };
document.querySelectorAll("[data-dk]").forEach((el) => MOUNTS[el.dataset.dk]?.(el));

// For pages that mount scenes on demand (design C's readout).
window.dkMount = (el) => MOUNTS[el.dataset.dk]?.(el);
