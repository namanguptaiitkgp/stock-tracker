"use client";

import Link from "next/link";
import { use, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { openStockDetail } from "@/lib/stock-detail";

interface Deal {
  trade_date: string;
  exchange: string;
  symbol: string;
  security_name: string | null;
  client_name: string;
  side: "BUY" | "SELL";
  quantity: number;
  avg_price: number | null;
  trade_value_inr: number | null;
  deal_type: string;
  is_known_shark: boolean;
}

interface SharkDetail {
  shark: {
    canonical_name: string;
    display_name: string;
    aliases: string[];
  };
  window_days: number;
  deal_count: number;
  deals: Deal[];
}

function fmtInr(n: number | null | undefined): string {
  if (n === null || n === undefined) return "--";
  if (Math.abs(n) >= 1e7) return `Rs ${(n / 1e7).toFixed(2)} Cr`;
  if (Math.abs(n) >= 1e5) return `Rs ${(n / 1e5).toFixed(1)} L`;
  return `Rs ${Math.round(n).toLocaleString("en-IN")}`;
}

function fmtQty(n: number): string {
  if (Math.abs(n) >= 1e7) return `${(n / 1e7).toFixed(2)} Cr`;
  if (Math.abs(n) >= 1e5) return `${(n / 1e5).toFixed(1)} L`;
  if (Math.abs(n) >= 1e3) return `${(n / 1e3).toFixed(1)} K`;
  return n.toLocaleString("en-IN");
}

export default function SharkDetailPage({
  params,
}: {
  params: Promise<{ name: string }>;
}) {
  const { name } = use(params);
  const decoded = decodeURIComponent(name);
  const [data, setData] = useState<SharkDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [window, setWindow] = useState(180);

  useEffect(() => {
    setLoading(true);
    api
      .get<SharkDetail>(`/api/smart-money/shark/${encodeURIComponent(decoded)}?days=${window}`)
      .then((d) => {
        setData(d);
        setLoading(false);
      })
      .catch(() => {
        setData(null);
        setLoading(false);
      });
  }, [decoded, window]);

  return (
    <div style={{ padding: "32px 40px", maxWidth: 1200, margin: "0 auto" }}>
      <div style={{ marginBottom: 12 }}>
        <Link href="/smart-money" style={{ fontSize: 12, color: "#007AFF", textDecoration: "none" }}>
          ← Smart Money
        </Link>
      </div>
      <h1 style={{ fontSize: 24, fontWeight: 700, marginBottom: 4 }}>
        {data?.shark?.display_name || decoded}
      </h1>
      {data?.shark?.aliases && data.shark.aliases.length > 0 && (
        <p style={{ fontSize: 12, color: "#6E6E73", marginBottom: 16 }}>
          Aliases: {data.shark.aliases.join(", ")}
        </p>
      )}

      <div style={{ display: "flex", gap: 8, marginBottom: 20 }}>
        {[30, 90, 180, 365, 1095].map((d) => (
          <button
            key={d}
            onClick={() => setWindow(d)}
            style={{
              padding: "4px 12px",
              borderRadius: 14,
              border: "1px solid #E2E8F0",
              fontSize: 12,
              cursor: "pointer",
              backgroundColor: window === d ? "#1D1D1F" : "white",
              color: window === d ? "white" : "#1D1D1F",
              fontWeight: 500,
            }}
          >
            {d >= 365 ? `${Math.round(d / 365)}y` : `${d}d`}
          </button>
        ))}
      </div>

      {loading && <div style={{ color: "#6E6E73" }}>Loading…</div>}

      {!loading && data && data.deal_count === 0 && (
        <div
          style={{
            padding: 16,
            backgroundColor: "rgba(142,142,147,0.05)",
            border: "1px dashed #E2E8F0",
            borderRadius: 8,
            color: "#6E6E73",
            fontSize: 13,
          }}
        >
          No bulk/block deals recorded for this investor in the last {window} days.
        </div>
      )}

      {!loading && data && data.deal_count > 0 && (
        <div>
          <div style={{ fontSize: 13, color: "#6E6E73", marginBottom: 12 }}>
            {data.deal_count} trade{data.deal_count !== 1 ? "s" : ""} in the last {window} days
          </div>

          <div
            style={{
              display: "grid",
              gridTemplateColumns: "110px 90px 60px 110px 100px 1fr",
              gap: 12,
              padding: "8px 14px",
              fontSize: 11,
              fontWeight: 600,
              color: "#6E6E73",
              textTransform: "uppercase",
              letterSpacing: "0.05em",
              borderBottom: "1px solid #E2E8F0",
              marginBottom: 4,
            }}
          >
            <span>Date</span>
            <span>Symbol</span>
            <span>Side</span>
            <span style={{ textAlign: "right" }}>Qty</span>
            <span style={{ textAlign: "right" }}>Price</span>
            <span style={{ textAlign: "right" }}>Value</span>
          </div>

          {data.deals.map((d, i) => (
            <div
              key={i}
              onClick={() => openStockDetail(d.symbol, d.exchange)}
              style={{
                display: "grid",
                gridTemplateColumns: "110px 90px 60px 110px 100px 1fr",
                gap: 12,
                alignItems: "center",
                padding: "10px 14px",
                fontSize: 13,
                background: "white",
                borderRadius: 6,
                marginBottom: 4,
                cursor: "pointer",
                border: "1px solid #F2F2F7",
              }}
            >
              <span style={{ color: "#48484A" }}>{d.trade_date}</span>
              <span style={{ fontFamily: "monospace", fontWeight: 700 }}>{d.symbol}</span>
              <span
                style={{
                  color: d.side === "BUY" ? "#248A3D" : "#D70015",
                  fontWeight: 700,
                }}
              >
                {d.side}
              </span>
              <span style={{ textAlign: "right" }}>{fmtQty(d.quantity)}</span>
              <span style={{ textAlign: "right" }}>
                {d.avg_price ? `Rs ${d.avg_price.toFixed(2)}` : "--"}
              </span>
              <span style={{ textAlign: "right", fontWeight: 600 }}>
                {fmtInr(d.trade_value_inr)}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
