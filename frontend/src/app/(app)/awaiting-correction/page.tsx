"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { openStockDetail } from "@/lib/stock-detail";
import { fmtN, pctStr } from "@/lib/format";

interface Watchlist {
  id: number;
  name: string;
  description?: string | null;
  stock_count?: number;
}

interface WatchlistStock {
  id: number;
  symbol: string;
  name: string | null;
  exchange: string;
  cmp?: number | null;
  pe_ratio?: number | null;
  pb_ratio?: number | null;
  roe?: number | null;
  market_cap?: number | null;
  pct_from_52w_high?: number | null;
  fundamentals?: {
    cmp?: number | null;
    pe_ratio?: number | null;
    pb_ratio?: number | null;
    roe?: number | null;
    market_cap?: number | null;
  };
  news_sentiment?: string | null;
  news_score?: number | null;
}

interface WatchlistDetail extends Watchlist {
  stocks: WatchlistStock[];
}

const NAME_PATTERN = /awaiting|correction|dip/i;

export default function AwaitingCorrectionPage() {
  const [watchlists, setWatchlists] = useState<Watchlist[]>([]);
  const [detail, setDetail] = useState<WatchlistDetail | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    api.get<Watchlist[]>("/api/watchlists/")
      .then(async (lists) => {
        setWatchlists(lists);
        const match = lists.find((w) => NAME_PATTERN.test(w.name));
        if (match) {
          try {
            const d = await api.get<WatchlistDetail>(`/api/watchlists/${match.id}/detail`);
            setDetail(d);
          } catch {
            setDetail(null);
          }
        }
      })
      .catch(() => setWatchlists([]))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div style={{ maxWidth: 900, margin: "0 auto", padding: 40, textAlign: "center", color: "var(--label-tertiary)" }}>
        Loading…
      </div>
    );
  }

  if (!detail) {
    return (
      <div style={{ maxWidth: 700, margin: "0 auto", padding: "60px 20px" }}>
        <h1 style={{
          fontFamily: "var(--font-serif)", fontSize: 28, fontWeight: 600,
          letterSpacing: "-0.02em", marginBottom: 14,
        }}>Awaiting Correction</h1>
        <p style={{ color: "var(--label-secondary)", lineHeight: 1.6, marginBottom: 18 }}>
          This tab shows stocks you&apos;re convinced about and waiting to buy at a better price.
          Create a watchlist named <strong>&quot;Awaiting Correction&quot;</strong> and add the candidates to it.
        </p>
        {watchlists.length > 0 && (() => {
          // Detect duplicate names — same name across two watchlists almost
          // always means an accidental import or sync; surface it so the
          // user can clean up rather than silently dedup the list.
          const counts = watchlists.reduce<Record<string, number>>((acc, w) => {
            acc[w.name] = (acc[w.name] ?? 0) + 1;
            return acc;
          }, {});
          const seen = new Set<string>();
          const rendered: string[] = [];
          for (const w of watchlists) {
            if (seen.has(w.name)) continue;
            seen.add(w.name);
            const n = counts[w.name];
            rendered.push(n > 1 ? `${w.name} (${n} watchlists with this name — possible duplicate)` : w.name);
          }
          return (
            <p style={{ color: "var(--label-tertiary)", fontSize: 13, marginBottom: 18 }}>
              Existing watchlists: {rendered.join(", ") || "—"}.{" "}
              Create a watchlist with <strong>awaiting</strong>, <strong>correction</strong>, or <strong>dip</strong> in the name to populate this tab.
            </p>
          );
        })()}
        <Link
          href="/watchlist"
          style={{
            display: "inline-flex", alignItems: "center", gap: 6,
            padding: "10px 16px", borderRadius: 9,
            background: "var(--label-primary)", color: "var(--bg-primary)",
            fontSize: 14, fontWeight: 600, textDecoration: "none",
          }}
        >
          Open Watchlists →
        </Link>
      </div>
    );
  }

  return (
    <div style={{ maxWidth: 1200, margin: "0 auto" }}>
      <div style={{ marginBottom: 20 }}>
        <h1 style={{
          fontFamily: "var(--font-serif)", fontSize: 28, fontWeight: 600,
          letterSpacing: "-0.02em", marginBottom: 6,
        }}>Awaiting Correction</h1>
        <p style={{ color: "var(--label-tertiary)", fontSize: 14 }}>
          {detail.stocks.length} stock{detail.stocks.length !== 1 ? "s" : ""} from <strong style={{ color: "var(--label-secondary)" }}>{detail.name}</strong> · waiting for the right price
        </p>
      </div>

      {detail.stocks.length === 0 ? (
        <div style={{
          padding: 40, textAlign: "center",
          background: "var(--bg-primary)", border: "1px dashed var(--separator)",
          borderRadius: 12, color: "var(--label-tertiary)",
        }}>
          No stocks in this watchlist yet.{" "}
          <Link href="/watchlist" style={{ color: "var(--system-blue)" }}>Add some →</Link>
        </div>
      ) : (
        <div style={{
          background: "var(--bg-primary)",
          border: "1px solid var(--separator-light)",
          borderRadius: 12, overflow: "hidden",
        }}>
          {/* Header */}
          <div style={{
            display: "grid",
            gridTemplateColumns: "minmax(180px, 1.6fr) 100px 90px 80px 80px 100px",
            alignItems: "center", padding: "0 16px", height: 42, gap: 8,
            background: "var(--bg-secondary)",
            borderBottom: "1px solid var(--separator-light)",
            fontSize: 11, fontWeight: 600, color: "var(--label-tertiary)",
            textTransform: "uppercase", letterSpacing: "0.06em",
          }}>
            <div>Stock</div>
            <div style={{ textAlign: "right" }}>CMP</div>
            <div style={{ textAlign: "right" }}>From 52WH</div>
            <div style={{ textAlign: "right" }}>P/E</div>
            <div style={{ textAlign: "right" }}>ROE</div>
            <div style={{ textAlign: "right" }}>Sentiment</div>
          </div>
          {detail.stocks.map((s) => {
            const f = s.fundamentals || s;
            const cmp = (f as { cmp?: number | null }).cmp ?? s.cmp ?? null;
            const pe = (f as { pe_ratio?: number | null }).pe_ratio ?? s.pe_ratio ?? null;
            const roe = (f as { roe?: number | null }).roe ?? s.roe ?? null;
            const fromHigh = s.pct_from_52w_high ?? null;
            return (
              <div
                key={s.id}
                onClick={() => openStockDetail(s.symbol, s.exchange)}
                style={{
                  display: "grid",
                  gridTemplateColumns: "minmax(180px, 1.6fr) 100px 90px 80px 80px 100px",
                  alignItems: "center", padding: "0 16px", height: 56, gap: 8,
                  borderBottom: "1px solid var(--separator-light)",
                  cursor: "pointer", transition: "background .12s",
                  fontSize: 13.5,
                }}
                onMouseEnter={(e) => (e.currentTarget.style.background = "var(--bg-secondary)")}
                onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
              >
                <div>
                  <div style={{ fontWeight: 600, fontFamily: "var(--font-mono)" }}>{s.symbol}</div>
                  {s.name && (
                    <div style={{ fontSize: 11, color: "var(--label-tertiary)", marginTop: 2 }}>{s.name}</div>
                  )}
                </div>
                <div style={{ textAlign: "right", fontFamily: "var(--font-mono)" }}>{fmtN(cmp)}</div>
                <div style={{
                  textAlign: "right", fontFamily: "var(--font-mono)",
                  color: fromHigh != null && fromHigh < 0 ? "var(--system-red)" : "var(--label-primary)",
                }}>
                  {fromHigh != null ? `${fromHigh >= 0 ? "+" : ""}${fromHigh.toFixed(1)}%` : "—"}
                </div>
                <div style={{ textAlign: "right", fontFamily: "var(--font-mono)" }}>{pe != null ? pe.toFixed(1) : "—"}</div>
                <div style={{ textAlign: "right", fontFamily: "var(--font-mono)" }}>
                  {roe != null ? `${(roe * 100).toFixed(0)}%` : "—"}
                </div>
                <div style={{ textAlign: "right" }}>
                  {s.news_sentiment ? (
                    <span style={{
                      fontSize: 11, fontWeight: 600,
                      padding: "2px 7px", borderRadius: 99,
                      background: s.news_sentiment === "bullish" ? "var(--buy-bg)"
                        : s.news_sentiment === "bearish" ? "var(--act-bg)"
                        : "var(--bg-secondary)",
                      color: s.news_sentiment === "bullish" ? "var(--buy)"
                        : s.news_sentiment === "bearish" ? "var(--act)"
                        : "var(--label-tertiary)",
                    }}>{s.news_sentiment}</span>
                  ) : (
                    <span style={{ color: "var(--label-quaternary)" }}>—</span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
