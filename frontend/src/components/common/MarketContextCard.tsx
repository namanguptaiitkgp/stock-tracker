"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

interface TrendData {
  direction: string;
  label: string;
  score: number;
  adjusted_score: number;
  breadth: number;
  breadth_up: number;
  breadth_total: number;
  vix: { ltp: number | null; change_pct: number | null } | null;
  components: Array<{ slug: string; name: string; short_name: string; ltp: number | null; change_pct: number }>;
}

interface FiiDiiData {
  date?: string;
  fii?: { buy?: number; sell?: number; net?: number | null };
  dii?: { buy?: number; sell?: number; net?: number | null };
}

function fmtCr(v: number | null | undefined): string {
  if (v == null) return "—";
  const abs = Math.abs(v);
  const formatted = abs >= 1000 ? `${(abs / 1000).toFixed(1)}K Cr` : `${Math.round(abs).toLocaleString("en-IN")} Cr`;
  return `${v >= 0 ? "+" : "−"}₹${formatted}`;
}

export default function MarketContextCard() {
  const [trend, setTrend] = useState<TrendData | null>(null);
  const [fiiDii, setFiiDii] = useState<FiiDiiData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      api.get<TrendData>("/api/indices/trend").catch(() => null),
      api.get<FiiDiiData>("/api/market-data/fii-dii").catch(() => null),
    ]).then(([t, f]) => {
      setTrend(t);
      setFiiDii(f);
    }).finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <section style={{
        background: "var(--bg-primary)", border: "1px solid var(--separator-light)",
        borderRadius: 12, padding: 18, boxShadow: "var(--shadow-card)",
      }}>
        <div style={{ fontSize: 11, fontWeight: 600, letterSpacing: "0.08em", textTransform: "uppercase", color: "var(--label-tertiary)" }}>
          Market Context
        </div>
        <div style={{ marginTop: 12, fontSize: 12, color: "var(--label-tertiary)" }}>Loading…</div>
      </section>
    );
  }

  if (!trend) return null;

  const dirColor = trend.direction === "bullish" ? "var(--system-green, #34C759)"
    : trend.direction === "bearish" ? "var(--system-red, #FF3B30)"
    : "var(--label-secondary)";

  const dirArrow = trend.direction === "bullish" ? "▲" : trend.direction === "bearish" ? "▼" : "—";

  return (
    <section style={{
      background: "var(--bg-primary)", border: "1px solid var(--separator-light)",
      borderRadius: 12, padding: 18, boxShadow: "var(--shadow-card)",
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
        <span style={{
          fontSize: 11, fontWeight: 600, letterSpacing: "0.08em",
          textTransform: "uppercase", color: "var(--label-tertiary)",
        }}>Market Context</span>
        {fiiDii?.date && (
          <span style={{ fontSize: 11, color: "var(--label-quaternary)" }}>{fiiDii.date}</span>
        )}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: 10 }}>
        {/* Market Trend */}
        <div style={{
          padding: "12px 14px", borderRadius: 8,
          background: "var(--bg-secondary)", border: "1px solid var(--separator-light)",
        }}>
          <div style={{ fontSize: 10.5, fontWeight: 600, color: "var(--label-tertiary)", letterSpacing: "0.06em", textTransform: "uppercase", marginBottom: 4 }}>
            Market Trend
          </div>
          <div style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
            <span style={{ fontSize: 18, fontWeight: 600, color: dirColor }}>{dirArrow}</span>
            <span style={{ fontSize: 15, fontWeight: 600, color: dirColor, textTransform: "capitalize" }}>
              {trend.label}
            </span>
          </div>
          <div style={{ fontSize: 11, color: "var(--label-tertiary)", marginTop: 2, fontFamily: "var(--font-mono)" }}>
            score {trend.adjusted_score >= 0 ? "+" : ""}{trend.adjusted_score.toFixed(2)}
          </div>
        </div>

        {/* Breadth */}
        <div style={{
          padding: "12px 14px", borderRadius: 8,
          background: "var(--bg-secondary)", border: "1px solid var(--separator-light)",
        }}>
          <div style={{ fontSize: 10.5, fontWeight: 600, color: "var(--label-tertiary)", letterSpacing: "0.06em", textTransform: "uppercase", marginBottom: 4 }}>
            Breadth
          </div>
          <div style={{ fontSize: 15, fontWeight: 600 }}>
            {trend.breadth_up} of {trend.breadth_total}
            <span style={{ fontSize: 12, fontWeight: 400, color: "var(--label-tertiary)", marginLeft: 4 }}>indices up</span>
          </div>
          <div style={{ fontSize: 11, color: "var(--label-tertiary)", marginTop: 2, fontFamily: "var(--font-mono)" }}>
            {(trend.breadth * 100).toFixed(0)}%
          </div>
        </div>

        {/* VIX */}
        {trend.vix && (
          <div style={{
            padding: "12px 14px", borderRadius: 8,
            background: "var(--bg-secondary)", border: "1px solid var(--separator-light)",
          }}>
            <div style={{ fontSize: 10.5, fontWeight: 600, color: "var(--label-tertiary)", letterSpacing: "0.06em", textTransform: "uppercase", marginBottom: 4 }}>
              India VIX
            </div>
            <div style={{ fontSize: 15, fontWeight: 600, fontFamily: "var(--font-mono)" }}>
              {trend.vix.ltp?.toFixed(1) ?? "—"}
            </div>
            {trend.vix.change_pct != null && (
              <div style={{
                fontSize: 11, marginTop: 2, fontFamily: "var(--font-mono)",
                color: trend.vix.change_pct > 5 ? "var(--system-red)" : trend.vix.change_pct < -5 ? "var(--system-green)" : "var(--label-tertiary)",
              }}>
                {trend.vix.change_pct >= 0 ? "+" : ""}{trend.vix.change_pct.toFixed(1)}%
              </div>
            )}
          </div>
        )}

        {/* FII */}
        {fiiDii && fiiDii.fii?.net != null && (
          <div style={{
            padding: "12px 14px", borderRadius: 8,
            background: "var(--bg-secondary)", border: "1px solid var(--separator-light)",
          }}>
            <div style={{ fontSize: 10.5, fontWeight: 600, color: "var(--label-tertiary)", letterSpacing: "0.06em", textTransform: "uppercase", marginBottom: 4 }}>
              FII (Net)
            </div>
            <div style={{
              fontSize: 15, fontWeight: 600, fontFamily: "var(--font-mono)",
              color: (fiiDii.fii?.net ?? 0) >= 0 ? "var(--system-green)" : "var(--system-red)",
            }}>
              {fmtCr(fiiDii.fii?.net)}
            </div>
          </div>
        )}

        {/* DII */}
        {fiiDii && fiiDii.dii?.net != null && (
          <div style={{
            padding: "12px 14px", borderRadius: 8,
            background: "var(--bg-secondary)", border: "1px solid var(--separator-light)",
          }}>
            <div style={{ fontSize: 10.5, fontWeight: 600, color: "var(--label-tertiary)", letterSpacing: "0.06em", textTransform: "uppercase", marginBottom: 4 }}>
              DII (Net)
            </div>
            <div style={{
              fontSize: 15, fontWeight: 600, fontFamily: "var(--font-mono)",
              color: (fiiDii.dii?.net ?? 0) >= 0 ? "var(--system-green)" : "var(--system-red)",
            }}>
              {fmtCr(fiiDii.dii?.net)}
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
