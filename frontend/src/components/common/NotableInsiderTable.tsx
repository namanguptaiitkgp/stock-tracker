"use client";

/**
 * Notable insider disclosures — filtered version that shows only what
 * matters per addendum §A2c. Excludes intra-group transfers, low-value
 * Designated Person trades, and small "Other" sales. Backed by
 * /api/smart-money/notable-insider.
 */

import { openStockDetail } from "@/lib/stock-detail";

export interface NotableInsiderRow {
  id: number;
  symbol: string;
  person_name: string;
  category: string;
  transaction_type: string;
  shares: number;
  value_inr: number | null;
  transaction_date: string | null;
  mode: string | null;
  strength: "strong" | "moderate" | "minor";
}

const STRENGTH_DOT: Record<string, { dot: string; label: string; color: string }> = {
  strong: { dot: "●", label: "Strong", color: "var(--label-primary)" },
  moderate: { dot: "○", label: "Moderate", color: "var(--label-secondary)" },
  minor: { dot: "·", label: "Minor", color: "var(--label-tertiary)" },
};

const TXN_COLOR: Record<string, string> = {
  Buy: "var(--buy)",
  Sale: "var(--act)",
  Pledge: "var(--review)",
  Revoke: "var(--review)",
  Invoke: "var(--act)",
};

export default function NotableInsiderTable({ rows }: { rows: NotableInsiderRow[] }) {
  if (rows.length === 0) {
    return (
      <div style={{ fontSize: 12, color: "var(--label-tertiary)", padding: "8px 0", fontStyle: "italic" }}>
        No notable insider activity in the window.
      </div>
    );
  }

  return (
    <div>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "70px 1fr 110px 70px 110px 90px 90px",
          gap: 8,
          padding: "6px 12px",
          fontSize: 10,
          fontWeight: 600,
          color: "var(--label-tertiary)",
          textTransform: "uppercase",
          letterSpacing: "0.05em",
          borderBottom: "1px solid var(--separator-light)",
        }}
      >
        <span>Symbol</span>
        <span>Who</span>
        <span>Category</span>
        <span>Type</span>
        <span style={{ textAlign: "right" }}>Shares</span>
        <span style={{ textAlign: "right" }}>Date</span>
        <span style={{ textAlign: "center" }}>Strength</span>
      </div>
      {rows.map((r) => {
        const s = STRENGTH_DOT[r.strength] || STRENGTH_DOT.minor;
        // First-initial display for privacy + density. Full name on hover via title.
        const initial = r.person_name?.[0]?.toUpperCase() || "?";
        return (
          <button
            key={r.id}
            onClick={() => openStockDetail(r.symbol, "NSE")}
            title={r.person_name}
            style={{
              display: "grid",
              gridTemplateColumns: "70px 1fr 110px 70px 110px 90px 90px",
              gap: 8,
              alignItems: "center",
              padding: "8px 12px",
              fontSize: 12,
              background: "var(--bg-primary)",
              border: "1px solid var(--separator-light)",
              borderRadius: 6,
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
                color: "var(--label-secondary)",
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}
            >
              <span style={{ fontWeight: 600 }}>{initial}.</span>{" "}
              {r.person_name}
            </span>
            <span style={{ fontSize: 11, color: "var(--label-tertiary)" }}>{r.category}</span>
            <span style={{ color: TXN_COLOR[r.transaction_type] || "var(--label-secondary)", fontWeight: 700 }}>
              {r.transaction_type}
            </span>
            <span style={{ textAlign: "right", fontFamily: "var(--font-mono)", color: "var(--label-primary)" }}>
              {r.shares.toLocaleString("en-IN")}
            </span>
            <span style={{ textAlign: "right", color: "var(--label-tertiary)", fontSize: 11 }}>
              {r.transaction_date}
            </span>
            <span style={{ textAlign: "center", color: s.color, fontSize: 11 }} title={s.label}>
              {s.dot} {s.label}
            </span>
          </button>
        );
      })}
    </div>
  );
}
