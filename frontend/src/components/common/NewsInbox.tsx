"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "@/lib/api";
import { openStockDetail } from "@/lib/stock-detail";
import { fmtRelative } from "@/lib/format";

interface Stock { symbol: string; name?: string }
interface NewsItem {
  title: string;
  url: string;
  source: string;
  published_at: string | null;
  stocks: Stock[];
  sentiment: "tailwind" | "headwind" | "context" | null;
  confidence: "high" | "medium" | "low" | null;
  description: string | null;
}

interface InboxResponse {
  items: NewsItem[];
  total: number;
  sources_available: string[];
  source_counts: Record<string, number>;
  scope: string;
  as_of: string;
}

type Scope = "all" | "mystocks" | "watchlist" | "holdings";

const fmtTime = fmtRelative;

function SentimentPill({ s }: { s: NewsItem["sentiment"] }) {
  if (s === "tailwind") {
    return (
      <span style={{
        display: "inline-flex", alignItems: "center", gap: 4,
        padding: "3px 9px", borderRadius: 99,
        fontSize: 11, fontWeight: 600,
        background: "var(--buy-bg)", color: "var(--buy)",
      }}>
        <span style={{ fontSize: 9 }}>▲</span> tailwind
      </span>
    );
  }
  if (s === "headwind") {
    return (
      <span style={{
        display: "inline-flex", alignItems: "center", gap: 4,
        padding: "3px 9px", borderRadius: 99,
        fontSize: 11, fontWeight: 600,
        background: "var(--act-bg)", color: "var(--act)",
      }}>
        <span style={{ fontSize: 9 }}>▼</span> headwind
      </span>
    );
  }
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 4,
      padding: "3px 9px", borderRadius: 99,
      fontSize: 11, fontWeight: 500,
      background: "var(--bg-secondary)", color: "var(--label-secondary)",
    }}>
      <span style={{ fontSize: 9 }}>○</span> context
    </span>
  );
}

function NewsCard({ item }: { item: NewsItem }) {
  const primaryStock = item.stocks[0];

  return (
    <article style={{
      padding: "14px 18px",
      borderBottom: "1px solid var(--separator-light)",
      transition: "background .12s",
      cursor: item.url ? "pointer" : "default",
    }}
    onMouseEnter={(e) => (e.currentTarget.style.background = "var(--bg-secondary)")}
    onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
    onClick={(e) => {
      // ignore clicks on the symbol pill (handled separately)
      const target = e.target as HTMLElement;
      if (target.closest('[data-stock-pill="1"]')) return;
      if (item.url) window.open(item.url, "_blank", "noopener,noreferrer");
    }}>
      {/* Time + source row */}
      <div style={{
        display: "flex", alignItems: "center", gap: 10,
        fontSize: 11, color: "var(--label-secondary)", marginBottom: 6,
      }}>
        <span style={{ fontFamily: "var(--font-mono)" }}>{fmtTime(item.published_at)}</span>
        <span style={{ fontWeight: 600 }}>{item.source}</span>
      </div>

      {/* Headline */}
      <div style={{
        fontSize: 14, fontWeight: 500, lineHeight: 1.45,
        color: "var(--label-primary)", marginBottom: item.description ? 6 : 10,
      }}>
        {item.title}
      </div>

      {/* Description */}
      {item.description && (
        <div style={{
          fontSize: 12.5, lineHeight: 1.5, color: "var(--label-tertiary)",
          marginBottom: 10,
          display: "-webkit-box",
          WebkitLineClamp: 2,
          WebkitBoxOrient: "vertical" as const,
          overflow: "hidden",
        }}>
          {item.description}
        </div>
      )}

      {/* Stocks + sentiment row */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          {item.stocks.slice(0, 3).map((s) => (
            <button
              key={s.symbol}
              data-stock-pill="1"
              onClick={(e) => { e.stopPropagation(); openStockDetail(s.symbol); }}
              style={{
                padding: "3px 9px", borderRadius: 5,
                fontSize: 11, fontWeight: 600, fontFamily: "var(--font-mono)",
                background: "var(--bg-secondary)",
                color: "var(--label-primary)",
                border: "1px solid var(--separator-light)",
                cursor: "pointer", letterSpacing: "0.02em",
              }}
            >{s.symbol}</button>
          ))}
          {item.stocks.length === 0 && (
            <span style={{ fontSize: 11, color: "var(--label-quaternary)", fontStyle: "italic" }}>—</span>
          )}
        </div>
        <SentimentPill s={item.sentiment} />
      </div>
    </article>
  );
}

interface DropdownProps {
  label: string;
  value: string;
  options: Array<{ value: string; label: string }>;
  onChange: (v: string) => void;
}
function Dropdown({ label, value, options, onChange }: DropdownProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    function onDoc(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    if (open) document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);
  const current = options.find(o => o.value === value);
  return (
    <div ref={ref} style={{ position: "relative" }}>
      <button
        onClick={() => setOpen(o => !o)}
        style={{
          display: "inline-flex", alignItems: "center", gap: 5,
          padding: "6px 10px", borderRadius: 7,
          background: "var(--bg-secondary)", color: "var(--label-primary)",
          border: "1px solid var(--separator-light)",
          fontSize: 12, fontWeight: 500, cursor: "pointer",
        }}
      >
        <span style={{ color: "var(--label-tertiary)", fontWeight: 400 }}>{label}:</span>
        <span>{current?.label || value}</span>
        <span style={{ fontSize: 9, color: "var(--label-tertiary)" }}>▾</span>
      </button>
      {open && (
        <div style={{
          position: "absolute", top: "100%", left: 0, marginTop: 4,
          minWidth: 160, padding: 4,
          background: "var(--bg-primary)",
          border: "1px solid var(--separator-light)",
          borderRadius: 8, boxShadow: "var(--shadow-md)",
          zIndex: 50,
        }}>
          {options.map(o => (
            <button
              key={o.value}
              onClick={() => { onChange(o.value); setOpen(false); }}
              style={{
                display: "block", width: "100%", textAlign: "left",
                padding: "6px 10px", border: 0, background: o.value === value ? "var(--bg-secondary)" : "transparent",
                color: "var(--label-primary)", fontSize: 12.5,
                cursor: "pointer", borderRadius: 5,
              }}
              onMouseEnter={(e) => (e.currentTarget.style.background = "var(--bg-secondary)")}
              onMouseLeave={(e) => (e.currentTarget.style.background = o.value === value ? "var(--bg-secondary)" : "transparent")}
            >{o.label}</button>
          ))}
        </div>
      )}
    </div>
  );
}

interface SourceFilterProps {
  available: string[];
  counts: Record<string, number>;
  selected: string[];          // empty = all
  onChange: (next: string[]) => void;
}
function SourceFilter({ available, counts, selected, onChange }: SourceFilterProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    function onDoc(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    if (open) document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  const allSelected = selected.length === 0;
  const label = allSelected ? "All sources" : `${selected.length} selected`;

  function toggle(src: string) {
    if (allSelected) {
      // start a new selection from "all" by selecting everything else
      onChange(available.filter(s => s !== src));
    } else if (selected.includes(src)) {
      const next = selected.filter(s => s !== src);
      onChange(next.length === available.length || next.length === 0 ? [] : next);
    } else {
      const next = [...selected, src];
      onChange(next.length === available.length ? [] : next);
    }
  }

  return (
    <div ref={ref} style={{ position: "relative" }}>
      <button
        onClick={() => setOpen(o => !o)}
        style={{
          display: "inline-flex", alignItems: "center", gap: 5,
          padding: "6px 10px", borderRadius: 7,
          background: "var(--bg-secondary)", color: "var(--label-primary)",
          border: "1px solid var(--separator-light)",
          fontSize: 12, fontWeight: 500, cursor: "pointer",
        }}
      >
        <span style={{ color: "var(--label-tertiary)", fontWeight: 400 }}>Sources:</span>
        <span>{label}</span>
        <span style={{ fontSize: 9, color: "var(--label-tertiary)" }}>▾</span>
      </button>
      {open && (
        <div style={{
          position: "absolute", top: "100%", right: 0, marginTop: 4,
          minWidth: 220, padding: 4,
          background: "var(--bg-primary)",
          border: "1px solid var(--separator-light)",
          borderRadius: 8, boxShadow: "var(--shadow-md)",
          zIndex: 50,
        }}>
          <button
            onClick={() => onChange([])}
            style={{
              display: "block", width: "100%", textAlign: "left",
              padding: "6px 10px", border: 0,
              background: allSelected ? "var(--bg-secondary)" : "transparent",
              color: "var(--label-primary)", fontSize: 12.5, fontWeight: 600,
              cursor: "pointer", borderRadius: 5,
            }}
          >All sources</button>
          <div style={{ height: 1, background: "var(--separator-light)", margin: "4px 0" }} />
          {available.map((s) => {
            const isOn = allSelected || selected.includes(s);
            return (
              <button
                key={s}
                onClick={() => toggle(s)}
                style={{
                  display: "flex", alignItems: "center", gap: 8, width: "100%",
                  padding: "6px 10px", border: 0,
                  background: isOn ? "var(--bg-secondary)" : "transparent",
                  color: "var(--label-primary)", fontSize: 12.5,
                  cursor: "pointer", borderRadius: 5, textAlign: "left",
                }}
              >
                <span style={{
                  width: 14, height: 14, borderRadius: 3,
                  border: `1.5px solid ${isOn ? "var(--label-primary)" : "var(--separator)"}`,
                  background: isOn ? "var(--label-primary)" : "transparent",
                  display: "grid", placeItems: "center", flexShrink: 0,
                  color: "var(--bg-primary)", fontSize: 9, fontWeight: 700,
                }}>{isOn ? "✓" : ""}</span>
                <span style={{ flex: 1 }}>{s}</span>
                <span style={{ fontFamily: "var(--font-mono)", fontSize: 10.5, color: "var(--label-tertiary)" }}>
                  {counts[s] ?? 0}
                </span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

interface NewsInboxProps {
  variant?: "rail" | "drawer";
  // Lifted up so a parent that renders this inside a tab can show the
  // current count in the tab label. Optional — when omitted the badge
  // still renders internally as before.
  onCountChange?: (n: number) => void;
}

export default function NewsInbox({ variant = "rail", onCountChange }: NewsInboxProps) {
  const [scope, setScope] = useState<Scope>("all");
  const [sentiment, setSentiment] = useState<string>("all");
  const [selectedSources, setSelectedSources] = useState<string[]>([]);
  const [searchInput, setSearchInput] = useState("");
  const [activeQuery, setActiveQuery] = useState<string | null>(null);
  const [items, setItems] = useState<NewsItem[]>([]);
  const [available, setAvailable] = useState<string[]>([]);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(true);
  const [searching, setSearching] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  useEffect(() => { onCountChange?.(items.length); }, [items.length, onCountChange]);

  const loadInbox = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      params.set("scope", scope);
      if (selectedSources.length > 0) params.set("source", selectedSources.join(","));
      if (sentiment !== "all") params.set("sentiment", sentiment);
      params.set("limit", "30");
      const data = await api.get<InboxResponse>(`/api/news/inbox?${params.toString()}`);
      setItems(data.items);
      setAvailable(data.sources_available || []);
      setCounts(data.source_counts || {});
    } catch {
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, [scope, selectedSources, sentiment]);

  const runSearch = useCallback(async (q: string) => {
    setSearching(true);
    setActiveQuery(q);
    try {
      const data = await api.post<InboxResponse>("/api/news/inbox/search", { q, limit: 30 });
      setItems(data.items);
    } catch {
      setItems([]);
    } finally {
      setSearching(false);
    }
  }, []);

  useEffect(() => {
    if (activeQuery) return;
    loadInbox();
  }, [scope, selectedSources, sentiment, loadInbox, activeQuery]);

  useEffect(() => {
    const handler = () => { loadInbox(); };
    window.addEventListener("news-refreshed", handler);
    return () => window.removeEventListener("news-refreshed", handler);
  }, [loadInbox]);

  async function refresh() {
    setRefreshing(true);
    try {
      await api.post("/api/news/inbox/refresh", {});
      if (activeQuery) {
        await runSearch(activeQuery);
      } else {
        await loadInbox();
      }
    } catch { /* ignore */ }
    setRefreshing(false);
  }

  function clearSearch() {
    setSearchInput("");
    setActiveQuery(null);
  }

  function onSearchKey(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter") {
      const q = searchInput.trim();
      if (q) runSearch(q);
    } else if (e.key === "Escape") {
      clearSearch();
    }
  }

  const subtitle = useMemo(() => {
    if (activeQuery) return `Search: "${activeQuery}"`;
    if (scope === "mystocks") return "Holdings + watchlist";
    if (scope === "watchlist") return "Filtered to your watchlist";
    if (scope === "holdings") return "Your holdings";
    return "All news";
  }, [scope, activeQuery]);

  // The `rail` variant fills its parent. The host page is responsible for
  // sticky positioning (so the parent grid cell can drive layout/height).
  // Internally the news list section already scrolls — see the items list
  // below — so users can scroll headlines while the rail itself stays put.
  const containerStyle: React.CSSProperties = variant === "drawer"
    ? { width: "100%", height: "100%", display: "flex", flexDirection: "column" }
    : {
        background: "var(--bg-primary)",
        border: "1px solid var(--separator-light)",
        borderRadius: 12,
        boxShadow: "var(--shadow-sm)",
        height: "100%",
        display: "flex", flexDirection: "column",
        overflow: "hidden",
      };

  return (
    <div style={containerStyle}>
      {/* Header */}
      <div style={{
        padding: "14px 18px 10px",
        borderBottom: "1px solid var(--separator-light)",
        flexShrink: 0,
      }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
            <h3 style={{
              margin: 0, fontFamily: "var(--font-serif)", fontSize: 20, fontWeight: 600,
              letterSpacing: "-0.01em", color: "var(--label-primary)",
            }}>News inbox</h3>
            <span style={{ fontSize: 12, color: "var(--label-secondary)" }}>
              {subtitle}
            </span>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{
              display: "inline-flex", alignItems: "center", justifyContent: "center",
              minWidth: 28, height: 22, padding: "0 8px",
              borderRadius: 99, background: "var(--bg-secondary)",
              border: "1px solid var(--separator-light)",
              fontSize: 11.5, fontWeight: 600, color: "var(--label-secondary)",
              fontFamily: "var(--font-mono)",
            }}>{items.length}</span>
            <button
              onClick={refresh}
              disabled={refreshing}
              title="Refresh"
              style={{
                padding: "4px 8px", borderRadius: 6,
                background: "var(--bg-secondary)", color: "var(--label-secondary)",
                border: "1px solid var(--separator-light)",
                fontSize: 13, cursor: refreshing ? "wait" : "pointer",
                lineHeight: 1,
              }}
            >{refreshing ? "…" : "⟳"}</button>
          </div>
        </div>

        {/* Search + Filters — scrolls horizontally on narrow viewports so
            Sentiment / Sources don't get clipped off-screen. */}
        <div
          className="news-filter-row"
          style={{ display: "flex", gap: 6, alignItems: "center" }}
        >
          <style jsx>{`
            @media (max-width: 720px) {
              .news-filter-row {
                overflow-x: auto;
                flex-wrap: nowrap;
                -webkit-overflow-scrolling: touch;
                scrollbar-width: none;
              }
              .news-filter-row::-webkit-scrollbar { display: none; }
              .news-filter-row > * { flex-shrink: 0; }
            }
          `}</style>
          <div style={{ flex: 1, position: "relative" }}>
            <span style={{
              position: "absolute", left: 10, top: "50%", transform: "translateY(-50%)",
              color: "var(--label-secondary)", fontSize: 13,
            }}>⌕</span>
            <input
              type="text"
              placeholder="Search news…"
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              onKeyDown={onSearchKey}
              style={{
                width: "100%", padding: "7px 32px 7px 30px",
                borderRadius: 8, fontSize: 12.5,
                background: "var(--bg-secondary)",
                border: "1px solid var(--separator-light)",
                color: "var(--label-primary)", outline: "none",
              }}
            />
            {activeQuery && (
              <button
                onClick={clearSearch}
                title="Clear search"
                style={{
                  position: "absolute", right: 6, top: "50%", transform: "translateY(-50%)",
                  width: 22, height: 22, borderRadius: 5,
                  background: "transparent", border: 0,
                  color: "var(--label-secondary)", fontSize: 14,
                  cursor: "pointer", display: "grid", placeItems: "center",
                }}
              >×</button>
            )}
          </div>
          <Dropdown
            label="Scope"
            value={scope}
            onChange={(v) => { setScope(v as Scope); clearSearch(); }}
            options={[
              { value: "all", label: "All" },
              { value: "mystocks", label: "My Stocks" },
              { value: "watchlist", label: "Watchlist" },
              { value: "holdings", label: "Holdings" },
            ]}
          />
          <Dropdown
            label="Sentiment"
            value={sentiment}
            onChange={(v) => { setSentiment(v); clearSearch(); }}
            options={[
              { value: "all", label: "All" },
              { value: "tailwind", label: "▲ Tailwind" },
              { value: "headwind", label: "▼ Headwind" },
              { value: "context", label: "○ Context" },
            ]}
          />
          <SourceFilter
            available={available}
            counts={counts}
            selected={selectedSources}
            onChange={(next) => { setSelectedSources(next); clearSearch(); }}
          />
        </div>
      </div>

      {/* Items — overlay sits outside scroll container so it covers the full viewport */}
      <div style={{ flex: 1, position: "relative", overflow: "hidden" }}>
        {(searching || loading) && items.length > 0 && (
          <div style={{
            position: "absolute", inset: 0, zIndex: 10,
            background: "color-mix(in srgb, var(--bg-primary) 80%, transparent)",
            display: "flex", alignItems: "center", justifyContent: "center",
          }}>
            <div style={{
              padding: "10px 20px", borderRadius: 8,
              background: "var(--bg-secondary)",
              border: "1px solid var(--separator-light)",
              fontSize: 12.5, fontWeight: 500,
              color: "var(--label-primary)",
            }}>
              {searching ? "Searching…" : "Loading…"}
            </div>
          </div>
        )}
        <div style={{ height: "100%", overflowY: "auto" }}>
          {(searching || loading) && items.length === 0 ? (
            <div style={{ padding: 20 }}>
              {[0, 1, 2, 3, 4].map(i => (
                <div key={i} className="animate-pulse" style={{ padding: "14px 0", borderBottom: "1px solid var(--separator-light)" }}>
                  <div style={{ height: 10, width: "40%", background: "var(--fill-gray)", borderRadius: 4, marginBottom: 8 }} />
                  <div style={{ height: 12, width: "90%", background: "var(--fill-gray)", borderRadius: 4, marginBottom: 4 }} />
                  <div style={{ height: 12, width: "60%", background: "var(--fill-gray)", borderRadius: 4 }} />
                </div>
              ))}
            </div>
          ) : items.length === 0 ? (
            <div style={{
              padding: 32, textAlign: "center",
              color: "var(--label-secondary)", fontSize: 13,
            }}>
              {activeQuery
                ? `No news found for "${activeQuery}".`
                : scope === "mystocks" ? "No news for your stocks right now."
                : scope === "watchlist" ? "No watchlist news right now."
                : scope === "holdings" ? "No news for your holdings right now."
                : "No news available — try Refresh."}
            </div>
          ) : (
            items.map((it, i) => <NewsCard key={`${it.url}-${i}`} item={it} />)
          )}
        </div>
      </div>
    </div>
  );
}
