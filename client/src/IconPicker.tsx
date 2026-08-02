import { useState, useCallback, useMemo, useRef, useEffect } from "react";
import { icons as lucideIcons } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useVirtualizer } from "@tanstack/react-virtual";
import type { Icon as IconRef } from "./protocol";
import { Icon as IconGlyph, loadSimpleIcons } from "./Icon";

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

type Props = {
  value: IconRef | null;
  onChange: (icon: IconRef | null) => void;
  open: boolean;
  onClose: () => void;
};

const COLS = 5;
const ROW_HEIGHT = 56;

export function IconPicker({ value, onChange, open, onClose }: Props) {
  const [activeTab, setActiveTab] = useState<"lucide" | "simple-icons">(
    value?.source === "simple-icons" ? "simple-icons" : "lucide",
  );
  const [search, setSearch] = useState("");
  const [simpleIcons, setSimpleIcons] = useState<SimpleIconEntry[] | null>(null);
  const [loadingBrands, setLoadingBrands] = useState(false);
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

  const filtered = useMemo(() => {
    const q = search.toLowerCase().trim();
    if (activeTab === "lucide") {
      if (!q) return lucideEntries;
      return lucideEntries.filter((e) => e.kebab.includes(q));
    }
    if (!simpleIcons) return [];
    if (!q) return simpleIcons;
    return simpleIcons.filter(
      (e) => e.slug.includes(q) || e.title.toLowerCase().includes(q),
    );
  }, [activeTab, search, simpleIcons]);

  const rowCount = Math.ceil(filtered.length / COLS);

  const virtualizer = useVirtualizer({
    count: rowCount,
    getScrollElement: () => parentRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 3,
  });

  const handleSelect = useCallback(
    (entry: { kebab: string } | SimpleIconEntry) => {
      if ("kebab" in entry) {
        onChange({ source: "lucide", name: entry.kebab });
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
        </div>

        <div className="icon-picker-search">
          <input
            className="icon-picker-search-input"
            type="text"
            placeholder={`Search ${activeTab === "lucide" ? "Lucide" : "brand"} icons…`}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            autoFocus
          />
        </div>

        <div ref={parentRef} className="icon-picker-grid">
          {activeTab === "simple-icons" && !simpleIcons ? (
            <div className="icon-picker-loading">Loading brand icons…</div>
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
                      const name = "kebab" in item ? item.kebab : item.slug;
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
                            {activeTab === "lucide" ? (
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
                            {name}
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
