"use client";

/**
 * "Your Holdings" — per-stock smart-money signal table, grouped by
 * actionability.
 *
 * Four groups, each rendered as a collapsible card:
 *   1. Action needed   — REVIEW (red flags) + TRIM (negative conviction)
 *   2. Add candidates  — ADD (positive conviction, no severe flags)
 *   3. Coverage gaps   — NO_SIGNAL (data too thin to score)
 *   4. Stable          — HOLD (no actionable signal either way; collapsed by default)
 *
 * The grouping addresses the user's request: rather than scrolling
 * through 27 holdings to find the few that matter, action-needed
 * stocks land at the top in their own section, stable holdings are
 * collapsed away. Coverage-gap holdings stay expanded so the "smart
 * money isn't producing a signal here" requirement is still visible.
 *
 * Empty groups are omitted entirely.
 */

import { useMemo, useState } from "react";
import { openStockDetail } from "@/lib/stock-detail";

export interface HoldingSignalRow {
  symbol: string;
  direction: "ADD" | "HOLD" | "TRIM" | "REVIEW" | "NO_SIGNAL";
  confidence: "HIGH" | "MEDIUM" | "LOW";
  headline: string;
  drivers: string[];
  conviction_score: number | null;
  flow_score: number | null;
  red_flag_score: number | null;
  coverage_score: number;
  days_held: number | null;
  binding_signal: string | null;
  quantity?: number;
  average_price?: number;
  last_price?: number;
}

interface Props {
  rows: HoldingSignalRow[];
  counts: Record<string, number>;
  loading?: boolean;
}

type Direction = HoldingSignalRow["direction"];

const DIRECTION_PALETTE: Record<Direction, { bg: string; fg: string; edge: string; label: string }> = {
  ADD:        { bg: "var(--buy-bg, rgba(48,209,88,0.10))",  fg: "var(--buy)",     edge: "var(--buy-edge, rgba(48,209,88,0.28))",  label: "ADD" },
  HOLD:       { bg: "var(--bg-secondary)",                  fg: "var(--label-secondary)", edge: "var(--separator-light)",         label: "HOLD" },
  TRIM:       { bg: "var(--review-bg, rgba(255,149,0,0.10))", fg: "var(--review)", edge: "var(--review-edge, rgba(255,149,0,0.30))", label: "TRIM" },
  REVIEW:     { bg: "var(--act-bg, rgba(255,59,48,0.08))",  fg: "var(--act)",     edge: "var(--act-edge, rgba(255,59,48,0.28))",  label: "REVIEW" },
  NO_SIGNAL:  { bg: "color-mix(in srgb, var(--label-quaternary) 8%, transparent)", fg: "var(--label-tertiary)", edge: "var(--separator-light)", label: "NO SIGNAL" },
};

const CONFIDENCE_PALETTE: Record<HoldingSignalRow["confidence"], string> = {
  HIGH:   "var(--buy)",
  MEDIUM: "var(--label-secondary)",
  LOW:    "var(--label-tertiary)",
};


// Group definitions. Order = render order on the page (most actionable first).
type GroupKey = "action" | "add" | "coverage" | "stable";

interface GroupDef {
  key: GroupKey;
  title: string;
  subtitle: string;
  icon: string;
  accent: string;          // colour used for the group header chip + left-border
  defaultOpen: boolean;
  directions: Direction[];
}

const GROUPS: GroupDef[] = [
  {
    key: "action",
    title: "Action needed",
    subtitle: "Red flags or institutional selling — review before adding more",
    icon: "⚠",
    accent: "var(--act)",
    defaultOpen: true,
    directions: ["REVIEW", "TRIM"],
  },
  {
    key: "add",
    title: "Add candidates",
    subtitle: "Smart money accumulating — consider adding to existing positions",
    icon: "↗",
    accent: "var(--buy)",
    defaultOpen: true,
    directions: ["ADD"],
  },
  {
    key: "coverage",
    title: "Coverage gaps",
    subtitle: "Data too thin to produce a reliable signal — investigate manually",
    icon: "○",
    accent: "var(--review)",
    defaultOpen: true,
    directions: ["NO_SIGNAL"],
  },
  {
    key: "stable",
    title: "Stable holdings",
    subtitle: "No actionable signal either way",
    icon: "—",
    accent: "var(--label-tertiary)",
    defaultOpen: false,
    directions: ["HOLD"],
  },
];


export default function HoldingsSignalTable({ rows, counts, loading }: Props) {
  // Bucket the rows by group up-front so we can skip empty groups + show counts.
  const groupedRows = useMemo(() => {
    const out: Record<GroupKey, HoldingSignalRow[]> = {
      action: [], add: [], coverage: [], stable: [],
    };
    for (const r of rows) {
      for (const g of GROUPS) {
        if (g.directions.includes(r.direction)) {
          out[g.key].push(r);
          break;
        }
      }
    }
    return out;
  }, [rows]);

  // Per-group expanded state. Stable's default is collapsed; others open.
  const [openGroups, setOpenGroups] = useState<Record<GroupKey, boolean>>(() => {
    const init = {} as Record<GroupKey, boolean>;
    for (const g of GROUPS) init[g.key] = g.defaultOpen;
    return init;
  });

  if (loading) {
    return <div style={{ color: "var(--label-tertiary)", fontSize: 13 }}>Loading holdings signals…</div>;
  }
  if (!rows || rows.length === 0) {
    return (
      <div style={{ color: "var(--label-tertiary)", fontSize: 13 }}>
        No holdings to score. Connect Kite (Settings → Connections) to see your holdings here.
      </div>
    );
  }

  return (
    <div>
      {/* Counts summary — same chips as before, gives an at-a-glance overview */}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 14 }}>
        {(["ADD", "TRIM", "REVIEW", "HOLD", "NO_SIGNAL"] as const).map((d) => {
          const n = counts[d] || 0;
          if (n === 0) return null;
          const p = DIRECTION_PALETTE[d];
          return (
            <span
              key={d}
              style={{
                fontSize: 11,
                fontWeight: 600,
                padding: "3px 9px",
                borderRadius: 99,
                background: p.bg,
                color: p.fg,
                border: `1px solid ${p.edge}`,
              }}
            >
              {n} {p.label.toLowerCase()}
            </span>
          );
        })}
      </div>

      {/* Grouped sections */}
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {GROUPS.map((g) => {
          const groupRows = groupedRows[g.key];
          if (groupRows.length === 0) return null;
          const open = openGroups[g.key];
          return (
            <section
              key={g.key}
              style={{
                border: "1px solid var(--separator-light)",
                borderRadius: 10,
                overflow: "hidden",
                background: "var(--bg-primary)",
              }}
            >
              <button
                onClick={() => setOpenGroups({ ...openGroups, [g.key]: !open })}
                style={{
                  width: "100%",
                  padding: "12px 16px",
                  background: "transparent",
                  border: 0,
                  borderLeft: `4px solid ${g.accent}`,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  gap: 12,
                  cursor: "pointer",
                  textAlign: "left",
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: 10, minWidth: 0 }}>
                  <span style={{ fontSize: 16, color: g.accent, flexShrink: 0 }}>{g.icon}</span>
                  <div style={{ minWidth: 0 }}>
                    <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
                      <span style={{ fontSize: 14, fontWeight: 600, color: "var(--label-primary)" }}>
                        {g.title}
                      </span>
                      <span
                        style={{
                          fontSize: 11,
                          fontWeight: 600,
                          padding: "2px 8px",
                          borderRadius: 99,
                          background: "var(--bg-secondary)",
                          color: g.accent,
                          fontFamily: "var(--font-mono)",
                        }}
                      >
                        {groupRows.length}
                      </span>
                    </div>
                    <div style={{ fontSize: 11, color: "var(--label-tertiary)", marginTop: 1 }}>
                      {g.subtitle}
                    </div>
                  </div>
                </div>
                <span style={{ color: "var(--label-tertiary)", fontFamily: "var(--font-mono)", flexShrink: 0 }}>
                  {open ? "▴" : "▾"}
                </span>
              </button>
              {open && (
                <div style={{ padding: "8px 12px 12px", borderTop: "1px solid var(--separator-light)" }}>
                  <GroupHeader />
                  {groupRows.map((r) => <SignalRow key={r.symbol} row={r} />)}
                </div>
              )}
            </section>
          );
        })}
      </div>
    </div>
  );
}


function GroupHeader() {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "100px 100px 80px 1fr 80px",
        gap: 8,
        padding: "6px 12px",
        fontSize: 10,
        fontWeight: 600,
        textTransform: "uppercase",
        letterSpacing: "0.06em",
        color: "var(--label-tertiary)",
        borderBottom: "1px solid var(--separator-light)",
        marginBottom: 4,
      }}
    >
      <span>Symbol</span>
      <span>Direction</span>
      <span>Confidence</span>
      <span>Headline</span>
      <span style={{ textAlign: "right" }}>Coverage</span>
    </div>
  );
}


function SignalRow({ row: r }: { row: HoldingSignalRow }) {
  const p = DIRECTION_PALETTE[r.direction];
  return (
    <button
      onClick={() => openStockDetail(r.symbol, "NSE")}
      title={r.drivers.length ? r.drivers.join(" · ") : undefined}
      style={{
        display: "grid",
        gridTemplateColumns: "100px 100px 80px 1fr 80px",
        gap: 8,
        alignItems: "center",
        padding: "10px 12px",
        fontSize: 12,
        background: "var(--bg-primary)",
        border: `1px solid ${p.edge}`,
        borderLeft: `4px solid ${p.fg}`,
        borderRadius: 8,
        marginTop: 4,
        cursor: "pointer",
        textAlign: "left",
        width: "100%",
      }}
    >
      <span style={{ fontFamily: "var(--font-mono)", fontWeight: 700, color: "var(--label-primary)" }}>
        {r.symbol}
      </span>
      <span
        style={{
          fontSize: 11,
          fontWeight: 700,
          padding: "3px 9px",
          borderRadius: 6,
          background: p.bg,
          color: p.fg,
          border: `1px solid ${p.edge}`,
          textAlign: "center",
          width: "fit-content",
        }}
      >
        {p.label}
      </span>
      <span
        style={{
          fontSize: 10,
          fontWeight: 600,
          color: CONFIDENCE_PALETTE[r.confidence],
          textTransform: "uppercase",
          letterSpacing: "0.05em",
        }}
        title="Confidence is a function of coverage + signal magnitude"
      >
        {r.confidence}
      </span>
      <span
        style={{
          color: "var(--label-secondary)",
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
        }}
      >
        {r.headline}
        {r.days_held && r.days_held > 0 && (
          <span style={{ marginLeft: 8, color: "var(--label-tertiary)", fontSize: 11 }}>
            · held {r.days_held}d
          </span>
        )}
      </span>
      <span
        style={{
          textAlign: "right",
          fontFamily: "var(--font-mono)",
          fontSize: 11,
          color:
            r.coverage_score >= 70
              ? "var(--buy)"
              : r.coverage_score >= 50
                ? "var(--label-secondary)"
                : r.coverage_score >= 30
                  ? "var(--review)"
                  : "var(--act)",
          fontWeight: 600,
        }}
      >
        {r.coverage_score}%
      </span>
    </button>
  );
}
