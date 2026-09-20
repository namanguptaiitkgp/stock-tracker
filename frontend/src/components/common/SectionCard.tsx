"use client";

// Shared SectionCard primitive used by PositionCard (portfolio),
// OpportunityCard, and ResearchingCard (watchlist) for their 3-section
// Price / Peers / News grids. Originally inlined in PositionCard; lifted
// out so the other card types could re-use the same visual language
// without duplicating ~150 LOC of verdict styling + signal rows.
//
// Behaviour is unchanged from the PositionCard version EXCEPT:
//   - new `state` prop ("ready" | "loading" | "empty") for the
//     "generating peers…" placeholder used by opportunity/watchlist
//     cards when stock_peers hasn't been backfilled yet.

import React from "react";
import { IconRefresh } from "@tabler/icons-react";

// ── Verdict styling ────────────────────────────────────────────────
export const SECTION_VERDICT_STYLE: Record<string, { color: string; bg: string; border: string }> = {
  DISCOUNT:    { color: "var(--buy)",    bg: "var(--buy-bg)",    border: "color-mix(in srgb, var(--buy) 25%, transparent)" },
  FAIR:        { color: "var(--label-secondary)", bg: "var(--bg-secondary)", border: "var(--separator-light)" },
  PREMIUM:     { color: "var(--act)",    bg: "var(--act-bg)",    border: "color-mix(in srgb, var(--act) 25%, transparent)" },
  LEADS_PEERS: { color: "var(--buy)",    bg: "var(--buy-bg)",    border: "color-mix(in srgb, var(--buy) 25%, transparent)" },
  IN_LINE:     { color: "var(--label-secondary)", bg: "var(--bg-secondary)", border: "var(--separator-light)" },
  LAGS_PEERS:  { color: "var(--act)",    bg: "var(--act-bg)",    border: "color-mix(in srgb, var(--act) 25%, transparent)" },
  BULLISH:     { color: "var(--buy)",    bg: "var(--buy-bg)",    border: "color-mix(in srgb, var(--buy) 25%, transparent)" },
  NEUTRAL:     { color: "var(--label-secondary)", bg: "var(--bg-secondary)", border: "var(--separator-light)" },
  BEARISH:     { color: "var(--act)",    bg: "var(--act-bg)",    border: "color-mix(in srgb, var(--act) 25%, transparent)" },
  NO_DATA:     { color: "var(--label-quaternary)", bg: "var(--bg-secondary)", border: "var(--separator-light)" },
};

export const SECTION_VERDICT_LABEL: Record<string, string> = {
  DISCOUNT: "DISCOUNT", FAIR: "FAIR", PREMIUM: "PREMIUM",
  LEADS_PEERS: "LEADS", IN_LINE: "IN LINE", LAGS_PEERS: "LAGS",
  BULLISH: "BULLISH", NEUTRAL: "NEUTRAL", BEARISH: "BEARISH",
  NO_DATA: "NO DATA",
};

// ── Atomic rows used inside SectionCard children ───────────────────

export function SignalRow({ label, color, icon }: { label: string; color: string; icon?: React.ReactNode }) {
  return (
    <div style={{
      background: color === "red" ? "var(--act-bg)" : color === "green" ? "var(--buy-bg)" : "var(--bg-secondary)",
      borderRadius: 8, padding: "7px 9px", fontSize: 11.5,
      color: color === "red" ? "var(--act)" : color === "green" ? "var(--buy)" : "var(--label-secondary)",
      lineHeight: 1.35, display: "flex", alignItems: "center",
    }}>
      {icon && <span style={{ marginRight: 4, display: "inline-flex" }}>{icon}</span>}
      {label}
    </div>
  );
}

export function MetricRow({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div style={{
      background: color === "red" ? "var(--act-bg)" : color === "green" ? "var(--buy-bg)" : "var(--bg-secondary)",
      borderRadius: 8, padding: "7px 9px", fontSize: 11.5,
      color: color === "red" ? "var(--act)" : color === "green" ? "var(--buy)" : "var(--label-secondary)",
      lineHeight: 1.35, display: "flex", justifyContent: "space-between",
    }}>
      <span>{label}</span>
      <span style={{ fontWeight: 500 }}>{value}</span>
    </div>
  );
}

export function FootStat({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
      <span style={{
        fontSize: 9, color: "var(--label-tertiary)",
        textTransform: "uppercase", letterSpacing: "0.04em", fontWeight: 500,
      }}>{label}</span>
      <span style={{
        fontFamily: "var(--font-mono)", fontSize: 12, fontWeight: 500,
        color: color || "var(--label-primary)",
      }}>{value}</span>
    </div>
  );
}

// ── Freshness label (news-card-specific helper) ────────────────────

export type FreshnessTone = "fresh" | "recent" | "stale" | "none";

export function freshnessColor(tone: FreshnessTone): string {
  switch (tone) {
    case "fresh":  return "var(--system-green)";
    case "recent": return "var(--label-secondary)";
    case "stale":  return "var(--label-quaternary)";
    case "none":   return "var(--label-quaternary)";
  }
}

/**
 * State-aware "how fresh is this news?" label, derived from the newest cached
 * headline's pub_date. Honest about staleness: if no new headlines arrived
 * today, the label advances day-by-day to "news 1d ago" / "news 2d ago" /
 * "quiet 7d" without any backend write. Replaces the misleading job-runtime
 * "4m" / "10h" timestamps that previously appeared on the news section.
 */
export function newsFreshnessLabel(
  newest: string | null | undefined,
): { text: string; tone: FreshnessTone } {
  if (!newest) return { text: "no news", tone: "none" };
  const newestDay = newest.slice(0, 10);
  const today = new Date().toISOString().slice(0, 10);
  const ms = Date.parse(today) - Date.parse(newestDay);
  const days = Math.max(0, Math.round(ms / 86_400_000));
  if (days === 0) return { text: "news today", tone: "fresh" };
  if (days === 1) return { text: "news 1d ago", tone: "recent" };
  if (days <= 6) return { text: `news ${days}d ago`, tone: "recent" };
  return { text: `quiet ${days}d`, tone: "stale" };
}

// ── SectionCard ────────────────────────────────────────────────────

export type SectionState = "ready" | "loading" | "empty";

export interface SectionCardProps {
  icon: React.ReactNode;
  title: string;
  verdict: string;
  age?: string | null;
  freshness?: { text: string; tone: FreshnessTone } | null;
  onRefresh?: () => void;
  refreshing?: boolean;
  children?: React.ReactNode;
  footer?: React.ReactNode;
  // When `state="loading"` the body is replaced by a thin placeholder
  // (used for the "generating peers…" state). When `state="empty"` the
  // card still renders but the body shows the children verbatim (often
  // a "No data" line) — caller controls that.
  state?: SectionState;
  loadingLabel?: string;
}

export default function SectionCard({
  icon, title, verdict, age, freshness, onRefresh, refreshing,
  children, footer, state = "ready", loadingLabel,
}: SectionCardProps) {
  const vs = SECTION_VERDICT_STYLE[verdict] || SECTION_VERDICT_STYLE.NEUTRAL;
  // `freshness` (state label) takes precedence over `age` (timestamp).
  // The state label says "news today" / "quiet 3d" — meaningful to a glance.
  // `age` stays as a fallback for sections that don't yet provide freshness.
  const headerText = freshness?.text ?? age ?? null;
  const headerColor = freshness ? freshnessColor(freshness.tone) : "var(--label-quaternary)";

  return (
    <div style={{
      background: "var(--bg-primary)", border: `1px solid ${vs.border}`,
      borderRadius: 12, padding: 12, display: "flex", flexDirection: "column",
      minWidth: 0,
    }}>
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        marginBottom: 10,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6, minWidth: 0 }}>
          <span style={{ display: "inline-flex", color: vs.color }}>{icon}</span>
          <span style={{ fontSize: 13, fontWeight: 500, color: "var(--label-primary)" }}>{title}</span>
          <span style={{
            background: vs.bg, color: vs.color,
            fontSize: 10, fontWeight: 500, padding: "2px 7px", borderRadius: 999,
          }}>{SECTION_VERDICT_LABEL[verdict] || verdict}</span>
        </div>
        {headerText && state !== "loading" && (
          <button
            onClick={onRefresh}
            disabled={!onRefresh || refreshing}
            title="Refresh this section"
            style={{
              background: "none", border: "none",
              cursor: onRefresh && !refreshing ? "pointer" : "default",
              color: headerColor,
              display: "inline-flex", alignItems: "center", gap: 4,
              fontSize: 10, padding: "2px 4px", borderRadius: 4,
              opacity: !onRefresh ? 0.5 : 1,
            }}
          >
            <span>{headerText}</span>
            <IconRefresh size={12} className={refreshing ? "pcard-spin" : ""} />
          </button>
        )}
      </div>

      {state === "loading" ? (
        <div style={{
          display: "flex", alignItems: "center", justifyContent: "center",
          minHeight: 64, gap: 6,
          color: "var(--label-tertiary)", fontSize: 11.5,
        }}>
          <IconRefresh size={12} className="pcard-spin" />
          <span>{loadingLabel || "generating…"}</span>
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 6, flex: 1 }}>
          {children}
        </div>
      )}

      {footer && state !== "loading" && (
        <div style={{
          borderTop: "1px dashed var(--separator-light)",
          marginTop: 10, paddingTop: 8,
        }}>
          {footer}
        </div>
      )}

      {/* Global rules live here so any caller of SectionCard — PositionCard,
          OpportunityCard, ResearchingCard — gets the same responsive
          stacking behaviour and refresh-icon spin animation without
          duplicating CSS. */}
      <style jsx global>{`
        @keyframes pcard-spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
        .pcard-spin { animation: pcard-spin 1s linear infinite; }

        /* 3-section grid stacks vertically on mobile. Same rule used to
           live in PositionCard's inline <style> block, but since we
           re-use the class on OpportunityCard and ResearchingCard the
           rule has to be available wherever any SectionCard renders. */
        @media (max-width: 720px) {
          .pcard-section-grid {
            grid-template-columns: 1fr !important;
          }
        }
        /* Price footer (3 FootStats in a row) drops to 2 columns at
           very narrow widths so the labels don't clip. The third stat
           wraps onto a second row. */
        @media (max-width: 480px) {
          .section-card-footer-3col {
            grid-template-columns: repeat(2, 1fr) !important;
          }
        }
      `}</style>
    </div>
  );
}
