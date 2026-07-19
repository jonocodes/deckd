import { useEffect, useState } from "react";
import { icons as lucideIcons } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { Icon as IconRef } from "./protocol";

/** Renders a widget ``{source, name}`` icon reference by dispatching on
 * ``source`` to a bundled icon set (ADR-0006). The registry of known
 * sources lives here, in the client; an unknown source or an unresolved
 * name renders a visible placeholder rather than failing.
 *
 * Bundle strategy: Lucide (UI glyphs, on most buttons) is bundled whole so
 * it renders synchronously. Simple Icons (brand logos, ~3450 icons, only
 * occasionally used) is loaded lazily as a single on-demand chunk the first
 * time a layout references one — so its weight is never paid unless a brand
 * logo is actually used. */

const lucideByName = lucideIcons as Record<string, LucideIcon>;

/** kebab-case (``arrow-left``) -> Lucide's PascalCase map key (``ArrowLeft``). */
function toPascal(name: string): string {
  return name
    .split("-")
    .filter(Boolean)
    .map((w) => w[0].toUpperCase() + w.slice(1))
    .join("");
}

type SimpleIcon = { slug: string; path: string; title: string };

// Lazily import the whole Simple Icons set exactly once, indexed by slug.
let simpleIconsPromise: Promise<Map<string, SimpleIcon>> | null = null;
function loadSimpleIcons(): Promise<Map<string, SimpleIcon>> {
  if (!simpleIconsPromise) {
    simpleIconsPromise = import("simple-icons").then((mod) => {
      const m = new Map<string, SimpleIcon>();
      for (const value of Object.values(mod)) {
        if (value && typeof value === "object" && "slug" in value && "path" in value) {
          const icon = value as SimpleIcon;
          m.set(icon.slug, icon);
        }
      }
      return m;
    });
  }
  return simpleIconsPromise;
}

function MissingIcon({ icon, className }: { icon: IconRef; className?: string }) {
  return (
    <span
      className={className}
      data-icon-missing=""
      title={`unknown icon: ${icon.source}:${icon.name}`}
    >
      ⬚
    </span>
  );
}

/** Brand-logo path rendered from the lazily-loaded Simple Icons set. Shows an
 * empty box while the chunk loads, and the miss placeholder if the slug is
 * unknown once loaded. */
function SimpleBrandIcon({ icon, className }: { icon: IconRef; className?: string }) {
  // Resolution is keyed by the name it was resolved for, so a name change is
  // detectable as "not yet resolved" without a synchronous reset in the
  // effect (which would trigger a cascading render). ``path: null`` once
  // resolved means the slug is unknown.
  const [resolved, setResolved] = useState<{ name: string; path: string | null } | null>(null);

  useEffect(() => {
    let alive = true;
    loadSimpleIcons().then((bySlug) => {
      if (!alive) return;
      const si = bySlug.get(icon.name);
      setResolved({ name: icon.name, path: si ? si.path : null });
    });
    return () => {
      alive = false;
    };
  }, [icon.name]);

  // Loading, or resolving a newly-changed name: reserve the slot without a
  // flash of the previous logo or the placeholder.
  if (!resolved || resolved.name !== icon.name) {
    return <span className={className} aria-hidden />;
  }
  if (resolved.path) {
    return (
      <svg className={className} viewBox="0 0 24 24" fill="currentColor" aria-hidden>
        <path d={resolved.path} />
      </svg>
    );
  }
  return <MissingIcon icon={icon} className={className} />;
}

export function Icon({ icon, className }: { icon: IconRef; className?: string }) {
  if (icon.source === "lucide") {
    const Glyph = lucideByName[toPascal(icon.name)];
    if (Glyph) return <Glyph className={className} aria-hidden />;
    return <MissingIcon icon={icon} className={className} />;
  }
  if (icon.source === "simple-icons") {
    return <SimpleBrandIcon icon={icon} className={className} />;
  }
  return <MissingIcon icon={icon} className={className} />;
}
