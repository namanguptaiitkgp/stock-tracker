"use client";

/**
 * Full bulk/block deals timeline (addendum §A2d). The current data
 * source is the per-stock /{symbol} endpoint, so this page just
 * pulls the recent universe-level deals from /pulse for now plus
 * lets the user search by symbol. A dedicated /deals endpoint would
 * be cleaner but isn't in scope for this PR — the entry-point and
 * route exist so users can find it.
 */

import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { openStockDetail } from "@/lib/stock-detail";

interface Deal {
  trade_date: string;
  exchange: string;
  symbol: string;
  client_name: string;
  side: "BUY" | "SELL";
  quantity: number;
  avg_price: number | null;
  trade_value_inr: number | null;
  deal_type: string;
  is_known_shark: boolean;
}

function fmtInr(n: number | null): string {
  if (n === null || n === undefined) return "—";
  if (Math.abs(n) >= 1e7) return `Rs ${(n / 1e7).toFixed(2)} Cr`;
  if (Math.abs(n) >= 1e5) return `Rs ${(n / 1e5).toFixed(2)} L`;
  return `Rs ${Math.round(n).toLocaleString("en-IN")}`;
}

export default function DealsPage() {
  const [symbol, setSymbol] = useState("");
  const [deals, setDeals] = useState<Deal[]>([]);
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState(false);

  async function search() {
    if (!symbol.trim()) return;
    setLoading(true);
    setSearched(true);
    try {
      const r = await api.get<{ deals_last_30d: Deal[] }>(
        `/api/smart-money/${encodeURIComponent(symbol.trim().toUpperCase())}`,
      );
      setDeals(r.deals_last_30d || []);
    } catch {
      setDeals([]);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={{ padding: "32px 40px", maxWidth: 1200, margin: "0 auto" }}>
      <div style={{ marginBottom: 16 }}>
        <Link href="/smart-money" style={{ fontSize: 12, color: "var(--system-blue)", textDecoration: "none" }}>
          ← Smart Money
        </Link>
      </div>

      <header style={{ marginBottom: 20 }}>
        <h1 style={{ fontFamily: "var(--font-serif)", fontSize: 28, fontWeight: 600, letterSpacing: "-0.02em", margin: 0 }}>
          Bulk &amp; Block Deals
        </h1>
        <p style={{ fontSize: 13, color: "var(--label-tertiary)", marginTop: 4 }}>
          Search for a stock to see its bulk/block deal history (last 30 days).
          For per-trader timelines use{" "}
          <Link href="/smart-money/traders" style={{ color: "var(--system-blue)" }}>All Active Traders</Link>.
        </p>
      </header>

      <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 16 }}>
        <input
          type="text"
          value={symbol}
          onChange={(e) => setSymbol(e.target.value.toUpperCase())}
          onKeyDown={(e) => e.key === "Enter" && search()}
          placeholder="Symbol (e.g. RELIANCE)"
          style={{
            flex: "0 0 240px",
            padding: "8px 12px",
            borderRadius: 8,
            border: "1px solid var(--separator)",
            background: "var(--bg-primary)",
            color: "var(--label-primary)",
            fontSize: 13,
            fontFamily: "var(--font-mono)",
          }}
        />
        <button
          onClick={search}
          disabled={!symbol.trim() || loading}
          style={{
            padding: "8px 16px",
            borderRadius: 8,
            border: 0,
            background: "var(--label-primary)",
            color: "var(--bg-primary)",
            fontSize: 13,
            fontWeight: 600,
            cursor: symbol.trim() && !loading ? "pointer" : "default",
            opacity: symbol.trim() && !loading ? 1 : 0.4,
          }}
        >
          {loading ? "Searching…" : "Search"}
        </button>
      </div>

      {searched && !loading && deals.length === 0 && (
        <div style={{ fontSize: 12, color: "var(--label-tertiary)", fontStyle: "italic" }}>
          No deals in the last 30 days for {symbol}.
        </div>
      )}

      {deals.length > 0 && (
        <>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "100px 60px 90px 1fr 60px 90px 110px 80px",
              gap: 8,
              padding: "8px 12px",
              fontSize: 10,
              fontWeight: 600,
              color: "var(--label-tertiary)",
              textTransform: "uppercase",
              letterSpacing: "0.05em",
              borderBottom: "1px solid var(--separator-light)",
            }}
          >
            <span>Date</span>
            <span>Exch.</span>
            <span>Type</span>
            <span>Client</span>
            <span>Side</span>
            <span style={{ textAlign: "right" }}>Qty</span>
            <span style={{ textAlign: "right" }}>Value</span>
            <span style={{ textAlign: "right" }}>Price</span>
          </div>
          {deals.map((d, i) => (
            <button
              key={i}
              onClick={() => openStockDetail(d.symbol, d.exchange)}
              style={{
                display: "grid",
                gridTemplateColumns: "100px 60px 90px 1fr 60px 90px 110px 80px",
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
              <span style={{ color: "var(--label-tertiary)", fontFamily: "var(--font-mono)" }}>
                {d.trade_date}
              </span>
              <span style={{ fontSize: 11, color: "var(--label-tertiary)" }}>{d.exchange}</span>
              <span style={{ fontSize: 11, color: "var(--label-tertiary)" }}>{d.deal_type}</span>
              <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: "var(--label-secondary)" }}>
                {d.client_name}
                {d.is_known_shark && (
                  <span
                    style={{
                      marginLeft: 6,
                      fontSize: 9,
                      padding: "1px 5px",
                      borderRadius: 6,
                      background: "color-mix(in srgb, #AF52DE 15%, transparent)",
                      color: "#AF52DE",
                      fontWeight: 700,
                    }}
                  >
                    SHARK
                  </span>
                )}
              </span>
              <span style={{ color: d.side === "BUY" ? "var(--buy)" : "var(--act)", fontWeight: 700 }}>
                {d.side}
              </span>
              <span style={{ textAlign: "right", fontFamily: "var(--font-mono)" }}>
                {d.quantity.toLocaleString("en-IN")}
              </span>
              <span style={{ textAlign: "right", fontFamily: "var(--font-mono)", color: "var(--label-secondary)" }}>
                {fmtInr(d.trade_value_inr)}
              </span>
              <span style={{ textAlign: "right", fontFamily: "var(--font-mono)", color: "var(--label-tertiary)" }}>
                {d.avg_price?.toFixed(2)}
              </span>
            </button>
          ))}
        </>
      )}
    </div>
  );
}
