"use client";

/**
 * "Who's actually buying" — addendum §A2c.
 *
 * Replaces the old gross-volume "Top active traders" with:
 *   - default-hidden PROP_HFT and BROKER (toggle to show)
 *   - sorted by abs(net_buy) descending
 *   - Net/Total ratio column to spot squaring-off trades at a glance
 */

import Link from "next/link";
import { useState } from "react";

export interface NetTraderRow {
  client_name_norm: string;
  display_name: string;
  client_category: string | null;
  is_known_shark: boolean;
  trades: number;
  stock_count: number;
  buy_value_inr: number;
  sell_value_inr: number;
  net_value_inr: number;
  total_value_inr: number;
  net_to_total_ratio: number;
}

function fmtInr(n: number): string {
  if (Math.abs(n) >= 1e7) return `Rs ${(n / 1e7).toFixed(1)} Cr`;
  if (Math.abs(n) >= 1e5) return `Rs ${(n / 1e5).toFixed(1)} L`;
  return `Rs ${Math.round(n).toLocaleString("en-IN")}`;
}

const CATEGORY_LABEL: Record<string, string> = {
  QUALITY_MF_FPI: "MF / FPI",
  VC_PE: "VC / PE",
  PROMOTER: "Promoter",
  INSIDER_OTHER: "Insider",
  OTHER_FUND: "Fund",
  CORP_OTHER: "Corp.",
  INDIVIDUAL: "Indiv.",
  PROP_HFT: "Prop / HFT",
  BROKER: "Broker",
};

export default function NetTradersTable({
  rows,
  showBrokers,
  onToggleBrokers,
}: {
  rows: NetTraderRow[];
  showBrokers: boolean;
  onToggleBrokers: (v: boolean) => void;
}) {
  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
        <span style={{ fontSize: 12, color: "var(--label-tertiary)" }}>
          {rows.length} traders with directional positions (ratio ≥ 20%)
        </span>
        <label style={{ fontSize: 12, display: "inline-flex", alignItems: "center", gap: 6, cursor: "pointer" }}>
          <input
            type="checkbox"
            checked={showBrokers}
            onChange={(e) => onToggleBrokers(e.target.checked)}
          />
          <span style={{ color: "var(--label-secondary)" }}>Show brokers &amp; prop desks</span>
        </label>
      </div>

      {rows.length === 0 ? (
        <div style={{ fontSize: 12, color: "var(--label-tertiary)", padding: "8px 0", fontStyle: "italic" }}>
          No directional traders in the window.
        </div>
      ) : (
        <>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "1fr 100px 90px 60px 110px 110px 70px",
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
            <span>Client</span>
            <span>Category</span>
            <span style={{ textAlign: "right" }}>Trades</span>
            <span style={{ textAlign: "right" }}>Stocks</span>
            <span style={{ textAlign: "right" }}>Net Buy</span>
            <span style={{ textAlign: "right" }}>Total</span>
            <span style={{ textAlign: "right" }}>Net/Total</span>
          </div>
          {rows.map((c) => (
            <Link
              key={c.client_name_norm}
              href={`/smart-money/shark/${encodeURIComponent(c.display_name)}`}
              style={{
                display: "grid",
                gridTemplateColumns: "1fr 100px 90px 60px 110px 110px 70px",
                gap: 8,
                alignItems: "center",
                padding: "8px 12px",
                fontSize: 12,
                background: "var(--bg-primary)",
                border: "1px solid var(--separator-light)",
                borderRadius: 6,
                marginTop: 4,
                textDecoration: "none",
                color: "var(--label-primary)",
              }}
            >
              <span style={{ display: "flex", alignItems: "center", gap: 6, minWidth: 0 }}>
                <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {c.display_name}
                </span>
                {c.is_known_shark && (
                  <span
                    style={{
                      fontSize: 9,
                      padding: "1px 5px",
                      borderRadius: 6,
                      background: "color-mix(in srgb, #AF52DE 15%, transparent)",
                      color: "#AF52DE",
                      fontWeight: 700,
                      flexShrink: 0,
                    }}
                  >
                    SHARK
                  </span>
                )}
              </span>
              <span style={{ fontSize: 11, color: "var(--label-tertiary)" }}>
                {c.client_category ? CATEGORY_LABEL[c.client_category] || c.client_category : "—"}
              </span>
              <span style={{ textAlign: "right", color: "var(--label-secondary)", fontFamily: "var(--font-mono)" }}>
                {c.trades}
              </span>
              <span style={{ textAlign: "right", color: "var(--label-secondary)", fontFamily: "var(--font-mono)" }}>
                {c.stock_count}
              </span>
              <span
                style={{
                  textAlign: "right",
                  color: c.net_value_inr >= 0 ? "var(--buy)" : "var(--act)",
                  fontWeight: 700,
                  fontFamily: "var(--font-mono)",
                }}
              >
                {c.net_value_inr >= 0 ? "+" : "-"}
                {fmtInr(Math.abs(c.net_value_inr))}
              </span>
              <span style={{ textAlign: "right", color: "var(--label-secondary)", fontFamily: "var(--font-mono)" }}>
                {fmtInr(c.total_value_inr)}
              </span>
              <span
                style={{
                  textAlign: "right",
                  fontFamily: "var(--font-mono)",
                  color: c.net_to_total_ratio >= 0.8
                    ? "var(--buy)"
                    : c.net_to_total_ratio >= 0.5
                      ? "var(--label-primary)"
                      : "var(--label-tertiary)",
                }}
              >
                {Math.round(c.net_to_total_ratio * 100)}%
              </span>
            </Link>
          ))}
        </>
      )}
    </div>
  );
}
