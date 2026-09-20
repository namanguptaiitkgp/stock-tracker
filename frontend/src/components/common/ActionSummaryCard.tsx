"use client";

/**
 * Three-card daily-action summary at the top of /smart-money — what to
 * look at *today*. Accumulation / Distribution / Avoid.
 *
 * One reusable card component, three flavours selected by `kind`. Each
 * card shows up to 5 stocks; the headline + confirm lines come from the
 * /api/smart-money/action-summary endpoint and explain *why* this
 * stock is on the card.
 */

import { openStockDetail } from "@/lib/stock-detail";

export interface ActionSummaryRow {
  symbol: string;
  conviction_score: number | null;
  flow_score: number | null;
  red_flag_score: number | null;
  composite: number | null;
  headline: string;
  confirm: string;
}

export type ActionKind = "accumulation" | "distribution" | "avoid";

const PALETTE: Record<
  ActionKind,
  { tint: string; border: string; accent: string; icon: string; title: string }
> = {
  accumulation: {
    tint: "var(--buy-bg, rgba(48,209,88,0.06))",
    border: "var(--buy-edge, rgba(48,209,88,0.22))",
    accent: "var(--buy)",
    icon: "↗",
    title: "Accumulation",
  },
  distribution: {
    tint: "var(--review-bg, rgba(255,149,0,0.06))",
    border: "var(--review-edge, rgba(255,149,0,0.22))",
    accent: "var(--review)",
    icon: "↘",
    title: "Distribution",
  },
  avoid: {
    tint: "var(--act-bg, rgba(255,59,48,0.05))",
    border: "var(--act-edge, rgba(255,59,48,0.22))",
    accent: "var(--act)",
    icon: "⚠",
    title: "Avoid",
  },
};

const SUBTITLE: Record<ActionKind, string> = {
  accumulation: "Add-to-watchlist candidates — institutional buying",
  distribution: "Review if you hold — institutional selling",
  avoid: "Don't add new positions — red flags active",
};

export default function ActionSummaryCard({
  kind,
  rows,
  loading,
}: {
  kind: ActionKind;
  rows: ActionSummaryRow[];
  loading?: boolean;
}) {
  const p = PALETTE[kind];

  return (
    <section
      style={{
        background: p.tint,
        border: `1px solid ${p.border}`,
        borderRadius: 14,
        padding: 16,
        display: "flex",
        flexDirection: "column",
        minHeight: 220,
      }}
    >
      <header style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 4 }}>
        <span style={{ fontSize: 18, color: p.accent }}>{p.icon}</span>
        <h3
          style={{
            margin: 0,
            fontSize: 13,
            fontWeight: 700,
            textTransform: "uppercase",
            letterSpacing: "0.06em",
            color: p.accent,
          }}
        >
          {p.title}
        </h3>
        <span style={{ marginLeft: "auto", fontSize: 12, color: "var(--label-tertiary)", fontFamily: "var(--font-mono)" }}>
          {loading ? "…" : `${rows.length} stocks`}
        </span>
      </header>
      <p style={{ margin: "0 0 12px", fontSize: 11, color: "var(--label-tertiary)" }}>
        {SUBTITLE[kind]}
      </p>

      {loading && (
        <div style={{ display: "flex", flexDirection: "column", gap: 10, flex: 1 }}>
          {[0, 1, 2].map((i) => (
            <div
              key={i}
              style={{
                height: 38,
                borderRadius: 8,
                background: "color-mix(in srgb, var(--label-quaternary) 8%, transparent)",
              }}
            />
          ))}
        </div>
      )}

      {!loading && rows.length === 0 && (
        <div
          style={{
            flex: 1,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            color: "var(--label-tertiary)",
            fontSize: 12,
            fontStyle: "italic",
          }}
        >
          Nothing in this bucket today.
        </div>
      )}

      {!loading && rows.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 8, flex: 1 }}>
          {rows.map((r) => (
            <ActionRow key={r.symbol} row={r} kind={kind} accent={p.accent} />
          ))}
        </div>
      )}
    </section>
  );
}

function ActionRow({ row, kind, accent }: { row: ActionSummaryRow; kind: ActionKind; accent: string }) {
  // Score the user's eye should land on first
  const primaryScore =
    kind === "avoid" ? row.red_flag_score : kind === "distribution" ? row.conviction_score : row.conviction_score;
  const formatted =
    primaryScore === null
      ? null
      : `${primaryScore >= 0 ? "+" : ""}${Math.round(primaryScore)}`;

  return (
    <button
      onClick={() => openStockDetail(row.symbol, "NSE")}
      style={{
        textAlign: "left",
        background: "var(--bg-primary)",
        border: "1px solid var(--separator-light)",
        borderRadius: 8,
        padding: "8px 12px",
        cursor: "pointer",
        display: "flex",
        flexDirection: "column",
        gap: 2,
      }}
    >
      <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
        <span
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 13,
            fontWeight: 700,
            color: "var(--label-primary)",
            flex: "0 0 auto",
          }}
        >
          {row.symbol}
        </span>
        <span style={{ flex: 1, fontSize: 12, color: "var(--label-secondary)", lineHeight: 1.3 }}>
          {row.headline}
        </span>
        {formatted && (
          <span
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: 13,
              fontWeight: 700,
              color: accent,
              flex: "0 0 auto",
            }}
          >
            {formatted}
          </span>
        )}
      </div>
      {row.confirm && (
        <span style={{ fontSize: 11, color: "var(--label-tertiary)", paddingLeft: 0 }}>
          {row.confirm}
        </span>
      )}
    </button>
  );
}
