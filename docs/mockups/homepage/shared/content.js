// Shared long-form content for the homepage mockups, so the three designs
// differ only in style. Mount points: <div data-dk="platforms|security|compare|roadmap|faq">.
// Facts come from README.md, docs/GUIDE.md and docs/PLATFORM-PARITY.md —
// keep them in step when those change.

const GH = "https://github.com/jonocodes/deckd";
const el = (html) => { const t = document.createElement("template"); t.innerHTML = html.trim(); return t.content.firstElementChild; };
const YES = '<span class="dk-y" aria-label="yes">✓</span>';
const PART = '<span class="dk-p" role="img" aria-label="partly"></span>';
const NO = '<span class="dk-n" aria-label="no">—</span>';

const PLATFORMS = [
  ["Decks follow the focused app", YES, YES, YES, YES],
  ["Website decks (by window title)", YES, YES, YES, YES],
  ["Key presses and shortcuts", YES, YES, YES, PART],
  ["Trackpad and clicks", YES, YES, YES, YES],
  ["Scroll strip with momentum", YES, YES, YES, PART],
  ["Running-windows switcher", YES, YES, NO, YES],
  ["Now playing (every media player)", YES, YES, YES, NO],
  ["Screen-lock awareness", YES, NO, NO, NO],
];
function platforms(root) {
  root.append(el(`<div class="dk-table-wrap"><table class="dk-table dk-platforms">
    <thead><tr><th></th><th>GNOME</th><th>KDE Plasma</th><th>X11</th><th>macOS</th></tr></thead>
    <tbody>${PLATFORMS.map(([f, ...c]) => `<tr><td>${f}</td>${c.map((v) => `<td>${v}</td>`).join("")}</tr>`).join("")}</tbody>
  </table></div>`));
  root.append(el(`<p class="dk-note">GNOME and KDE on Wayland; any X11 desktop. macOS is newer and less tested;
    on a Mac, now playing waits on <a href="${GH}/issues/56">#56</a>. Windows is planned.
    The full matrix is in <a href="${GH}/blob/main/docs/PLATFORM-PARITY.md">PLATFORM-PARITY.md</a>.</p>`));
}

const SECURITY = [
  ["Nothing leaves your network", "No account, no cloud service. Your phone talks straight to the program on your computer."],
  ["Localhost until you say so", "It only listens on your own machine until you open it to your network, or just one interface — say, your Tailscale address."],
  ["A password on every screen", "Each phone or tablet signs in once with a shared password."],
  ["Locked means locked", "While your desktop is locked, presses, typing and the trackpad are refused (GNOME today)."],
];
function security(root) {
  root.append(el(`<dl class="dk-points">${SECURITY.map(([t, d]) => `<div><dt>${t}</dt><dd>${d}</dd></div>`).join("")}</dl>`));
}

const COMPARE = [
  ["Any phone, tablet or laptop as the controller", YES, NO, YES, YES],
  ["Buttons change with the focused app", YES, YES, NO, NO],
  ["Decks for websites", YES, NO, NO, NO],
  ["Trackpad and keyboard", YES, NO, YES, YES],
  ["Media controls", YES, YES, YES, NO],
  ["Open source", YES, PART, YES, YES],
];
function compare(root) {
  root.append(el(`<div class="dk-table-wrap"><table class="dk-table dk-compare">
    <thead><tr><th></th><th class="us">deckd</th><th>Stream Deck</th><th>KDE Connect</th><th>Remote Touchpad</th></tr></thead>
    <tbody>${COMPARE.map(([f, ...c]) => `<tr><td>${f}</td>${c.map((v, i) => `<td${i === 0 ? ' class="us"' : ""}>${v}</td>`).join("")}</tr>`).join("")}</tbody>
  </table></div>`));
  root.append(el(`<p class="dk-note">Stream Deck needs its own hardware; its open-source cousins
    (<a href="https://github.com/nekename/OpenDeck">OpenDeck</a>, Boatswain) drive the same devices.</p>`));
}

const TODAY = [
  "Decks that follow the focused app — and website",
  "Buttons, macros, launchers, live readouts",
  "Trackpad, keyboard and scroll strip",
  "Now playing for every media player",
  "An in-browser deck editor with live reload",
  "Password auth and lock awareness",
  "Linux (GNOME, KDE, X11) and macOS",
];
const NEXT = [
  ["Downloadable app for Linux and macOS", 168],
  ["A browser extension for exact website matching", 90],
  ["Different decks on different devices", null],
  ["Pick between several computers", 25],
  ["Dim with the desktop's screensaver", null],
  ["Soundboard", null],
  ["Windows", null],
];
function roadmap(root) {
  root.append(el(`<div class="dk-roadmap">
    <div><h3>Works today</h3><ul>${TODAY.map((t) => `<li>${t}</li>`).join("")}</ul></div>
    <div><h3>Coming</h3><ul>${NEXT.map(([t, n]) => `<li>${n ? `<a href="${GH}/issues/${n}">${t}</a>` : t}</li>`).join("")}</ul></div>
  </div>`));
  root.append(el(`<p class="dk-note">Pre-alpha, and used every day by the person writing it.</p>`));
}

const FAQ = [
  ["Do I need to install an app on my phone?",
    "No. Open the address in any browser. Add it to your home screen and it runs full screen, and keeps the screen awake while you use it."],
  ["Which websites work?",
    "Any site with keyboard shortcuts. deckd ships decks for YouTube, Netflix, Google Meet and a piano site you play from the deck; adding another is a few buttons in the editor. It matches the browser's window title, so it's best-effort — a browser extension for exact matching is planned."],
  ["Can more than one phone connect?",
    "Yes. Every connected screen shows the deck for the focused app, and edits reach all of them at once. Different decks per device is on the roadmap."],
  ["Does it work away from my Wi-Fi?",
    `Over a private network like Tailscale, yes: point deckd at that interface. With Tailscale's HTTPS certificates, Android will also install it to the home screen — see the <a href="${GH}/blob/main/docs/GUIDE.md#pwa-install-over-https-tailscale">guide</a>.`],
  ["How do I make my own decks?",
    "With the editor in the app: pick widgets, set icons and colours, drag to reorder, save. Every screen updates as you go. Decks are plain text files too, if you'd rather."],
  ["What can a button do?",
    "Press a key combination, run a command, open a URL, start a terminal, call D-Bus — or chain several into a macro."],
  ["Is it free?",
    `Yes — open source under GPL-3.0. Issues and ideas are welcome on <a href="${GH}/issues">GitHub</a>.`],
];
function faq(root) {
  root.append(el(`<div class="dk-faq">${FAQ.map(([q, a]) => `<details><summary>${q}</summary><p>${a}</p></details>`).join("")}</div>`));
}

window.DK_CONTENT = { platforms, security, compare, roadmap, faq };
