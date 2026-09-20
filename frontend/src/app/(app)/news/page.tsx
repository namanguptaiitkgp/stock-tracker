"use client";

import React, { useCallback, useEffect, useState } from "react";
import NewsInbox from "@/components/common/NewsInbox";
import OpportunitiesPanel from "@/components/common/OpportunitiesPanel";
import { usePageActions } from "@/lib/page-actions";
import { usePipelineStatus } from "@/lib/use-pipeline-status";

function formatRelative(iso: string | null | undefined): string {
  if (!iso) return "never";
  const t = new Date(iso).getTime();
  if (isNaN(t)) return "unknown";
  const diff = (Date.now() - t) / 1000;
  if (diff < 60) return `${Math.max(1, Math.round(diff))}s ago`;
  if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.round(diff / 3600)}h ago`;
  return `${Math.round(diff / 86400)}d ago`;
}

function NewsHeaderActions({ pipeline, onRefresh, refreshing }: {
  pipeline: ReturnType<typeof usePipelineStatus>;
  onRefresh: () => void;
  refreshing: boolean;
}) {
  const disabled = refreshing || pipeline.running;
  const buttonLabel = pipeline.running
    ? `${pipeline.active?.source === "morning_pipeline" ? "Pipeline" : pipeline.active?.source === "brief_refresh" ? "Refresh" : "News scan"}… since ${formatRelative(pipeline.active?.started_at)}`
    : refreshing
      ? "Scanning…"
      : "Refresh News";

  const node = (
    <div style={{ display: "inline-flex", alignItems: "center", gap: 10 }}>
      <button
        onClick={onRefresh}
        disabled={disabled}
        style={{
          padding: "5px 12px", borderRadius: 7,
          background: disabled ? "var(--label-quaternary)" : "var(--label-primary)",
          color: "var(--bg-primary)", border: "none",
          fontSize: 12, fontWeight: 600,
          cursor: disabled ? "not-allowed" : "pointer",
          whiteSpace: "nowrap",
          maxWidth: pipeline.running ? 280 : undefined,
          overflow: "hidden", textOverflow: "ellipsis",
        }}
      >
        {buttonLabel}
      </button>
    </div>
  );
  usePageActions(node, [refreshing, pipeline.running, pipeline.active]);
  return null;
}

// ── Segmented pill toggle ────────────────────────────────────────
type TabKey = "news" | "opps";

function SegmentedTab({ active, onClick, dot, label, count }: {
  active: boolean;
  onClick: () => void;
  dot?: boolean;
  label: string;
  count: number | null;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      role="tab"
      aria-selected={active}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 8,
        height: 32,
        padding: "0 14px",
        borderRadius: 9999,
        border: active ? "1px solid var(--label-primary)" : "1px solid var(--separator-non-opaque)",
        background: active ? "var(--label-primary)" : "transparent",
        color: active ? "var(--bg-primary)" : "var(--label-secondary)",
        fontSize: 13,
        fontWeight: 600,
        cursor: "pointer",
        transition: "background 180ms ease, color 180ms ease, border-color 180ms ease",
        whiteSpace: "nowrap",
      }}
      onMouseEnter={(e) => {
        if (!active) e.currentTarget.style.borderColor = "var(--separator-opaque)";
      }}
      onMouseLeave={(e) => {
        if (!active) e.currentTarget.style.borderColor = "var(--separator-non-opaque)";
      }}
    >
      {dot && (
        <span
          aria-hidden
          style={{
            width: 6, height: 6, borderRadius: 9999,
            background: active ? "var(--bg-primary)" : "var(--label-tertiary)",
            opacity: active ? 0.9 : 0.6,
          }}
        />
      )}
      <span>{label}</span>
      {count != null && (
        <span
          style={{
            fontVariantNumeric: "tabular-nums",
            fontSize: 12,
            fontWeight: 500,
            opacity: active ? 0.75 : 1,
            color: active ? "var(--bg-primary)" : "var(--label-tertiary)",
          }}
        >
          · {count}
        </span>
      )}
    </button>
  );
}

const TAB_STORAGE_KEY = "news-active-tab";

function readStoredTab(): TabKey {
  if (typeof window === "undefined") return "news";
  try {
    const v = window.localStorage.getItem(TAB_STORAGE_KEY);
    return v === "opps" ? "opps" : "news";
  } catch {
    return "news";
  }
}

export default function NewsPage() {
  const [refreshing, setRefreshing] = useState(false);
  const pipeline = usePipelineStatus();

  const [tab, setTabRaw] = useState<TabKey>("news");
  const [newsCount, setNewsCount] = useState<number | null>(null);
  const [oppsCount, setOppsCount] = useState<number | null>(null);

  // Hydrate the persisted tab on mount (avoids server/client mismatch).
  useEffect(() => { setTabRaw(readStoredTab()); }, []);

  const setTab = useCallback((next: TabKey) => {
    setTabRaw(next);
    try { window.localStorage.setItem(TAB_STORAGE_KEY, next); } catch { /* ignore */ }
  }, []);

  const handleRefreshNews = useCallback(async () => {
    setRefreshing(true);
    try {
      await pipeline.dispatch("news");
    } catch { /* toast handled by hook or silently */ }
    finally { setRefreshing(false); }
  }, [pipeline]);

  // Keyboard ← / → to switch tabs (ignored when typing in inputs).
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const target = e.target as Element | null;
      if (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement) return;
      if (target && (target as HTMLElement).isContentEditable) return;
      if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
        setTab(tab === "news" ? "opps" : "news");
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [tab, setTab]);

  return (
    <div style={{ maxWidth: 1400, margin: "0 auto", padding: "0 8px" }}>
      <NewsHeaderActions pipeline={pipeline} onRefresh={handleRefreshNews} refreshing={refreshing} />

      {/* Segmented pill row */}
      <div
        role="tablist"
        aria-label="News view"
        style={{
          display: "flex",
          gap: 8,
          alignItems: "center",
          flexWrap: "wrap",
          paddingBottom: 14,
        }}
      >
        <SegmentedTab
          active={tab === "news"}
          onClick={() => setTab("news")}
          dot
          label="News inbox"
          count={newsCount}
        />
        <SegmentedTab
          active={tab === "opps"}
          onClick={() => setTab("opps")}
          label="New opportunities"
          count={oppsCount}
        />
      </div>

      {/* Both children stay mounted; inactive hidden via display:none to
          preserve scroll position and avoid re-fetching on every switch. */}
      <div
        style={{
          display: tab === "news" ? "flex" : "none",
          flexDirection: "column",
          minWidth: 0,
          height: "calc(100vh - 170px)",
        }}
      >
        <NewsInbox variant="drawer" onCountChange={setNewsCount} />
      </div>

      <div
        style={{
          display: tab === "opps" ? "flex" : "none",
          flexDirection: "column",
          minWidth: 0,
          height: "calc(100vh - 170px)",
          overflowY: "auto",
        }}
      >
        <OpportunitiesPanel onCountChange={setOppsCount} />
      </div>
    </div>
  );
}
