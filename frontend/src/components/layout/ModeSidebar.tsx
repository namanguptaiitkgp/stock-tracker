"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { api } from "@/lib/api";
import { getTodayBrief } from "@/lib/today-brief";

/**
 * Mode-aware sidebar contents driven by the handoff design.
 *
 * Holdings mode (pathname === /dashboard):
 *   📊 Overview · 📋 All Positions
 *   — FILTERS —
 *   🔴 Act Now [N]
 *   🟡 Review [N]
 *   ✅ Hold   [N]
 *   — quick nav —
 *   📦 F&O · 📜 Orders · ⚙ Settings
 *
 * Discover mode (pathname in /watchlist, /fno, /news, /smart-money):
 *   🔭 Destinations (Watchlist · F&O · In News · Smart Money)
 *   — SORT BY —
 *   🔥 Signal Strength · 📈 Price Change · 🕐 Newest
 *   — SMART MONEY —
 *   ☑ FII/FPI · Mutual Fund · DII · Insurance · Proprietary · Retail
 */

const DISCOVER_PATHS = ["/watchlist", "/fno", "/news", "/smart-money"];

type Mode = "holdings" | "discover";

function modeFor(pathname: string): Mode {
  if (DISCOVER_PATHS.some((p) => pathname === p || pathname.startsWith(p + "/"))) {
    return "discover";
  }
  return "holdings";
}

interface BriefSummary {
  action_counts?: Record<string, number>;
  kite_connected?: boolean;
}

export default function ModeSidebar({ isDark }: { isDark: boolean }) {
  const pathname = usePathname() || "/";
  const mode = modeFor(pathname);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [kiteConnected, setKiteConnected] = useState<boolean | null>(null);

  useEffect(() => {
    if (mode !== "holdings") return;
    getTodayBrief<BriefSummary>()
      .then((d) => {
        setCounts(d.action_counts || {});
        setKiteConnected(Boolean(d.kite_connected));
      })
      .catch(() => {});
  }, [mode]);

  const muted = isDark ? "text-gray-500" : "text-gray-400";
  const labelStyle: React.CSSProperties = {
    padding: "8px 16px 4px",
    fontSize: 10.5,
    fontWeight: 700,
    textTransform: "uppercase",
    letterSpacing: "0.08em",
    color: isDark ? "#6B7280" : "#9CA3AF",
  };
  const itemStyle = (active: boolean): React.CSSProperties => ({
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    padding: "7px 14px",
    margin: "0 8px",
    borderRadius: 6,
    fontSize: 12,
    fontWeight: active ? 600 : 500,
    color: active
      ? isDark
        ? "#FFFFFF"
        : "#2563EB"
      : isDark
      ? "#D1D5DB"
      : "#4B5563",
    background: active ? (isDark ? "#1F2937" : "#EFF6FF") : "transparent",
    textDecoration: "none",
    cursor: "pointer",
  });

  if (mode === "holdings") {
    return (
      <>
        <div style={labelStyle}>OVERVIEW</div>
        <Link href="/dashboard" style={itemStyle(pathname === "/dashboard")}>
          <span>📊 Today&apos;s Brief</span>
        </Link>
        <Link href="/dashboard#portfolio" style={itemStyle(false)}>
          <span>📋 All Positions</span>
        </Link>

        <div style={{ height: 1, background: isDark ? "#1F2937" : "#E4E7EC", margin: "10px 16px" }} />

        <div style={labelStyle}>FILTERS</div>
        <FilterRow href="/dashboard#act-now" icon="🔴" label="Act Now" count={counts["SELL"]} color="#DC2626" bg="#FEF2F2" isDark={isDark} />
        <FilterRow href="/dashboard#review" icon="🟡" label="Review" count={counts["WATCHFUL"]} color="#D97706" bg="#FFFBEB" isDark={isDark} />
        <FilterRow href="/dashboard#hold" icon="✅" label="Hold" count={(counts["HOLD"] || 0) + (counts["ACCUMULATE"] || 0)} color="#16A34A" bg="#F0FDF4" isDark={isDark} />

        <div style={{ height: 1, background: isDark ? "#1F2937" : "#E4E7EC", margin: "10px 16px" }} />

        <Link href="/fno" style={itemStyle(pathname === "/fno")}>
          <span>📦 F&O</span>
        </Link>
        <Link href="/orders" style={itemStyle(pathname === "/orders")}>
          <span>📜 Orders</span>
        </Link>
        <Link href="/strategies" style={itemStyle(pathname === "/strategies")}>
          <span>🎯 Strategies</span>
        </Link>
        <Link href="/paper-trading" style={itemStyle(pathname === "/paper-trading")}>
          <span>🧪 Paper Trading</span>
        </Link>
        <Link href="/settings" style={itemStyle(pathname === "/settings")}>
          <span>⚙ Settings</span>
        </Link>

        {kiteConnected !== null && (
          <div style={{ marginTop: "auto", padding: "12px 16px", fontSize: 10.5, display: "flex", alignItems: "center", gap: 6, color: kiteConnected ? "#10B981" : "#9CA3AF" }}>
            <span style={{ width: 6, height: 6, borderRadius: 99, background: kiteConnected ? "#10B981" : "#9CA3AF" }} />
            {kiteConnected ? "Kite connected" : "Kite disconnected"}
          </div>
        )}
      </>
    );
  }

  // Discover mode
  return <DiscoverSidebar pathname={pathname} isDark={isDark} labelStyle={labelStyle} itemStyle={itemStyle} />;
}

function FilterRow({
  href,
  icon,
  label,
  count,
  color,
  bg,
  isDark,
}: {
  href: string;
  icon: string;
  label: string;
  count?: number;
  color: string;
  bg: string;
  isDark: boolean;
}) {
  const n = count ?? 0;
  return (
    <Link
      href={href}
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "6px 14px",
        margin: "0 8px",
        borderRadius: 6,
        fontSize: 11.5,
        fontWeight: 500,
        color: isDark ? "#D1D5DB" : "#4B5563",
        textDecoration: "none",
      }}
    >
      <span>
        <span style={{ marginRight: 6 }}>{icon}</span>
        {label}
      </span>
      {n > 0 && (
        <span
          style={{
            background: bg,
            color,
            borderRadius: 4,
            padding: "1px 6px",
            fontSize: 10,
            fontWeight: 700,
          }}
        >
          {n}
        </span>
      )}
    </Link>
  );
}

const SOURCES: Array<{ key: string; label: string; color: string; bg: string }> = [
  { key: "FII", label: "FII/FPI", color: "#3B82F6", bg: "#EFF6FF" },
  { key: "MF", label: "Mutual Fund", color: "#06B6D4", bg: "#ECFEFF" },
  { key: "DII", label: "DII", color: "#8B5CF6", bg: "#F5F3FF" },
  { key: "INS", label: "Insurance", color: "#10B981", bg: "#ECFDF5" },
  { key: "PRO", label: "Proprietary", color: "#F97316", bg: "#FFF7ED" },
  { key: "RET", label: "Retail", color: "#CA8A04", bg: "#FEFCE8" },
];

const SORT_STORAGE = "algo_trader_discover_sort";
const SOURCE_STORAGE = "algo_trader_discover_sources";
const SOURCE_EVENT = "algo-trader:discover-filters";

function DiscoverSidebar({
  pathname,
  isDark,
  labelStyle,
  itemStyle,
}: {
  pathname: string;
  isDark: boolean;
  labelStyle: React.CSSProperties;
  itemStyle: (active: boolean) => React.CSSProperties;
}) {
  const [sort, setSort] = useState<string>("signal");
  const [enabledSources, setEnabledSources] = useState<Record<string, boolean>>(
    SOURCES.reduce((acc, s) => ({ ...acc, [s.key]: true }), {}),
  );

  useEffect(() => {
    try {
      const s = localStorage.getItem(SORT_STORAGE);
      if (s) setSort(s);
      const raw = localStorage.getItem(SOURCE_STORAGE);
      if (raw) setEnabledSources(JSON.parse(raw));
    } catch {}
  }, []);

  const writeSort = useCallback((v: string) => {
    setSort(v);
    try {
      localStorage.setItem(SORT_STORAGE, v);
    } catch {}
    window.dispatchEvent(new CustomEvent(SOURCE_EVENT, { detail: { sort: v } }));
  }, []);

  const toggleSource = useCallback(
    (key: string) => {
      setEnabledSources((prev) => {
        const next = { ...prev, [key]: !prev[key] };
        try {
          localStorage.setItem(SOURCE_STORAGE, JSON.stringify(next));
        } catch {}
        window.dispatchEvent(new CustomEvent(SOURCE_EVENT, { detail: { sources: next } }));
        return next;
      });
    },
    [],
  );

  return (
    <>
      <div style={labelStyle}>DESTINATIONS</div>
      <Link href="/watchlist" style={itemStyle(pathname === "/watchlist" || pathname.startsWith("/watchlist/"))}>
        <span>📋 Watchlist</span>
      </Link>
      <Link href="/fno" style={itemStyle(pathname === "/fno" || pathname.startsWith("/fno/"))}>
        <span>📦 F&O Universe</span>
      </Link>
      <Link href="/news" style={itemStyle(pathname === "/news" || pathname.startsWith("/news/"))}>
        <span>📰 In News</span>
      </Link>
      <Link href="/smart-money" style={itemStyle(pathname === "/smart-money" || pathname.startsWith("/smart-money/"))}>
        <span>💰 Smart Money</span>
      </Link>

      <div style={{ height: 1, background: isDark ? "#1F2937" : "#E4E7EC", margin: "10px 16px" }} />

      <div style={labelStyle}>SORT BY</div>
      {[
        { k: "signal", label: "🔥 Signal Strength" },
        { k: "price", label: "📈 Price Change" },
        { k: "recency", label: "🕐 Newest Signal" },
      ].map((s) => (
        <button
          key={s.k}
          onClick={() => writeSort(s.k)}
          style={{
            ...itemStyle(sort === s.k),
            background: sort === s.k ? (isDark ? "#1F2937" : "#EFF6FF") : "transparent",
            border: "none",
            textAlign: "left",
            width: "calc(100% - 16px)",
            cursor: "pointer",
          }}
        >
          <span>{s.label}</span>
        </button>
      ))}

      <div style={{ height: 1, background: isDark ? "#1F2937" : "#E4E7EC", margin: "10px 16px" }} />

      <div style={labelStyle}>SMART MONEY</div>
      {SOURCES.map((s) => {
        const on = !!enabledSources[s.key];
        return (
          <button
            key={s.key}
            onClick={() => toggleSource(s.key)}
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              padding: "6px 14px",
              margin: "0 8px",
              borderRadius: 6,
              fontSize: 11.5,
              fontWeight: 500,
              color: isDark ? "#D1D5DB" : "#4B5563",
              textDecoration: "none",
              background: "transparent",
              border: "none",
              textAlign: "left",
              width: "calc(100% - 16px)",
              cursor: "pointer",
            }}
          >
            <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span
                style={{
                  width: 13,
                  height: 13,
                  borderRadius: 3,
                  border: `1.5px solid ${on ? s.color : "#D1D5DB"}`,
                  background: on ? s.color : "transparent",
                  display: "inline-flex",
                  alignItems: "center",
                  justifyContent: "center",
                  color: "white",
                  fontSize: 9,
                }}
              >
                {on && "✓"}
              </span>
              {s.label}
            </span>
            <span
              style={{
                fontSize: 9.5,
                padding: "1px 6px",
                borderRadius: 4,
                background: s.bg,
                color: s.color,
                fontFamily: '"DM Mono", monospace',
                fontWeight: 600,
              }}
            >
              {s.key}
            </span>
          </button>
        );
      })}
    </>
  );
}

/** Exposed helpers for Discover pages that want to apply the sidebar filters. */
export function useDiscoverFilters() {
  const [sort, setSort] = useState<string>("signal");
  const [sources, setSources] = useState<Record<string, boolean>>(
    SOURCES.reduce((acc, s) => ({ ...acc, [s.key]: true }), {}),
  );

  useEffect(() => {
    try {
      const s = localStorage.getItem(SORT_STORAGE);
      if (s) setSort(s);
      const raw = localStorage.getItem(SOURCE_STORAGE);
      if (raw) setSources(JSON.parse(raw));
    } catch {}
    const onUpdate = (e: Event) => {
      const ce = e as CustomEvent<{ sort?: string; sources?: Record<string, boolean> }>;
      if (ce.detail.sort) setSort(ce.detail.sort);
      if (ce.detail.sources) setSources(ce.detail.sources);
    };
    window.addEventListener(SOURCE_EVENT, onUpdate);
    return () => window.removeEventListener(SOURCE_EVENT, onUpdate);
  }, []);

  return { sort, sources };
}
