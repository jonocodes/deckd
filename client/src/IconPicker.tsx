import { useState, useCallback, useMemo, useRef, useEffect } from "react";
import { icons as lucideIcons } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useVirtualizer } from "@tanstack/react-virtual";
import type { Icon as IconRef } from "./protocol";
import { Icon as IconGlyph } from "./Icon";
import { desktopIconUrl, fetchDesktopApps, loadSimpleIcons } from "./icons";
import type { DesktopApp } from "./icons";

const lucideByName = lucideIcons as Record<string, LucideIcon>;

function toKebab(pascal: string): string {
  return pascal
    .replace(/([a-z])([A-Z])/g, "$1-$2")
    .replace(/([A-Z]+)([A-Z][a-z])/g, "$1-$2")
    .toLowerCase();
}

const lucideEntries = Object.keys(lucideByName).map((pascal) => ({
  pascal,
  kebab: toKebab(pascal),
}));

type SimpleIconEntry = { slug: string; path: string; title: string };

type Tab = "lucide" | "simple-icons" | "desktop";

type Props = {
  value: IconRef | null;
  onChange: (icon: IconRef | null) => void;
  open: boolean;
  onClose: () => void;
  /** Installed host apps for the Apps tab (``source: desktop``, issue #187).
   * Defaults to asking the daemon; injectable for tests. */
  loadDesktopApps?: () => Promise<DesktopApp[]>;
};

const SEARCH_PLACEHOLDER: Record<Tab, string> = {
  lucide: "Search Lucide icons…",
  "simple-icons": "Search brand icons…",
  desktop: "Search installed apps…",
};

const COLS = 5;
const ROW_HEIGHT = 56;

export function IconPicker({ value, onChange, open, onClose, loadDesktopApps = fetchDesktopApps }: Props) {
  const [activeTab, setActiveTab] = useState<Tab>(
    value?.source === "simple-icons" || value?.source === "desktop" ? value.source : "lucide",
  );
  const [search, setSearch] = useState("");
  const [simpleIcons, setSimpleIcons] = useState<SimpleIconEntry[] | null>(null);
  const [loadingBrands, setLoadingBrands] = useState(false);
  const [desktopApps, setDesktopApps] = useState<DesktopApp[] | null>(null);
  const [desktopError, setDesktopError] = useState(false);
  const [loadingApps, setLoadingApps] = useState(false);
  const parentRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (activeTab === "simple-icons" && !simpleIcons && !loadingBrands) {
      setLoadingBrands(true);
      loadSimpleIcons().then((bySlug) => {
        const entries: SimpleIconEntry[] = [];
        for (const icon of bySlug.values()) {
          entries.push({ slug: icon.slug, path: icon.path, title: icon.title });
        }
        entries.sort((a, b) => a.slug.localeCompare(b.slug));
        setSimpleIcons(entries);
        setLoadingBrands(false);
      });
    }
  }, [activeTab, simpleIcons, loadingBrands]);

  useEffect(() => {
    if (activeTab === "desktop" && !desktopApps && !loadingApps && !desktopError) {
      setLoadingApps(true);
      loadDesktopApps()
        .then((apps) => setDesktopApps(apps))
        .catch(() => setDesktopError(true))
        .finally(() => setLoadingApps(false));
    }
  }, [activeTab, desktopApps, loadingApps, desktopError, loadDesktopApps]);

  const filtered = useMemo(() => {
    const q = search.toLowerCase().trim();
    if (activeTab === "lucide") {
      if (!q) return lucideEntries;
      return lucideEntries.filter((e) => e.kebab.includes(q));
    }
    if (activeTab === "desktop") {
      if (!desktopApps) return [];
      if (!q) return desktopApps;
      return desktopApps.filter(
        (e) => e.id.toLowerCase().includes(q) || e.name.toLowerCase().includes(q),
      );
    }
    if (!simpleIcons) return [];
    if (!q) return simpleIcons;
    return simpleIcons.filter(
      (e) => e.slug.includes(q) || e.title.toLowerCase().includes(q),
    );
  }, [activeTab, search, simpleIcons, desktopApps]);

  const rowCount = Math.ceil(filtered.length / COLS);

  // TanStack Virtual's API returns non-memoizable functions (the virtualizer
  // exposes .scrollToIndex etc. that capture mutable scroll state). The
  // React Compiler can't memoize the returned object, so disable the lint.
  // eslint-disable-next-line react-hooks/incompatible-library
  const virtualizer = useVirtualizer({
    count: rowCount,
    getScrollElement: () => parentRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 3,
  });

  const handleSelect = useCallback(
    (entry: { kebab: string } | SimpleIconEntry | DesktopApp) => {
      if ("kebab" in entry) {
        onChange({ source: "lucide", name: entry.kebab });
      } else if ("id" in entry) {
        onChange({ source: "desktop", name: entry.id });
      } else {
        onChange({ source: "simple-icons", name: entry.slug });
      }
    },
    [onChange],
  );

  const handleClear = useCallback(() => {
    onChange(null);
  }, [onChange]);

  if (!open) return null;

  return (
    <div className="icon-picker-backdrop" onClick={onClose} data-testid="icon-picker-backdrop">
      <div className="icon-picker" onClick={(e) => e.stopPropagation()}>
        <div className="icon-picker-tabs">
          <button
            className={`icon-picker-tab${activeTab === "lucide" ? " icon-picker-tab-active" : ""}`}
            onClick={() => setActiveTab("lucide")}
          >
            Lucide
          </button>
          <button
            className={`icon-picker-tab${activeTab === "simple-icons" ? " icon-picker-tab-active" : ""}`}
            onClick={() => setActiveTab("simple-icons")}
          >
            Brands
          </button>
          <button
            className={`icon-picker-tab${activeTab === "desktop" ? " icon-picker-tab-active" : ""}`}
            onClick={() => setActiveTab("desktop")}
          >
            Apps
          </button>
        </div>

        <div className="icon-picker-search">
          <input
            className="icon-picker-search-input"
            type="text"
            placeholder={SEARCH_PLACEHOLDER[activeTab]}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            autoFocus
          />
        </div>

        <div ref={parentRef} className="icon-picker-grid">
          {activeTab === "simple-icons" && !simpleIcons ? (
            <div className="icon-picker-loading">Loading brand icons…</div>
          ) : activeTab === "desktop" && desktopError ? (
            <div className="icon-picker-empty">Couldn&apos;t load installed apps from the daemon.</div>
          ) : activeTab === "desktop" && !desktopApps ? (
            <div className="icon-picker-loading">Loading installed apps…</div>
          ) : activeTab === "desktop" && desktopApps?.length === 0 ? (
            <div className="icon-picker-empty">
              No installed apps found. App icons come from the host&apos;s .desktop files (Linux).
            </div>
          ) : filtered.length === 0 ? (
            <div className="icon-picker-empty">No icons match your search.</div>
          ) : (
            <div
              style={{
                height: `${virtualizer.getTotalSize()}px`,
                width: "100%",
                position: "relative",
              }}
            >
              {virtualizer.getVirtualItems().map((virtualRow) => {
                const rowStart = virtualRow.index * COLS;
                const rowItems = filtered.slice(rowStart, rowStart + COLS);
                return (
                  <div
                    key={virtualRow.key}
                    style={{
                      position: "absolute",
                      top: 0,
                      left: 0,
                      width: "100%",
                      height: `${virtualRow.size}px`,
                      transform: `translateY(${virtualRow.start}px)`,
                    }}
                    className="icon-picker-row"
                  >
                    {rowItems.map((item) => {
                      const name =
                        "kebab" in item ? item.kebab : "id" in item ? item.id : item.slug;
                      const source = activeTab;
                      const isSelected =
                        value?.source === source && value?.name === name;
                      return (
                        <button
                          key={name}
                          className={`icon-picker-item${isSelected ? " icon-picker-item-selected" : ""}`}
                          onClick={() => handleSelect(item)}
                          title={name}
                          aria-label={name}
                        >
                          <span className="icon-picker-item-glyph">
                            {"id" in item ? (
                              <img src={desktopIconUrl(item.id)} alt="" loading="lazy" draggable={false} />
                            ) : activeTab === "lucide" ? (
                              (() => {
                                const Glyph =
                                  lucideByName[
                                    (item as { pascal: string }).pascal
                                  ];
                                return Glyph ? <Glyph aria-hidden /> : <span>?</span>;
                              })()
                            ) : (
                              <svg
                                viewBox="0 0 24 24"
                                fill="currentColor"
                                aria-hidden
                              >
                                <path
                                  d={(item as SimpleIconEntry).path}
                                />
                              </svg>
                            )}
                          </span>
                          <span className="icon-picker-item-name">
                            {"id" in item ? item.name : name}
                          </span>
                        </button>
                      );
                    })}
                  </div>
                );
              })}
            </div>
          )}
        </div>

        <div className="icon-picker-footer">
          {value ? (
            <div className="icon-picker-chip">
              <IconGlyph
                icon={value}
                className="icon-picker-chip-glyph"
              />
              <span className="icon-picker-chip-name">
                {value.source}/{value.name}
              </span>
              <button
                type="button"
                className="icon-picker-chip-remove"
                onClick={handleClear}
                aria-label="remove icon"
              >
                &times;
              </button>
            </div>
          ) : (
            <span className="icon-picker-chip-empty">No icon selected</span>
          )}
          <button
            type="button"
            className="icon-picker-close"
            onClick={onClose}
          >
            Done
          </button>
        </div>
      </div>
    </div>
  );
}
