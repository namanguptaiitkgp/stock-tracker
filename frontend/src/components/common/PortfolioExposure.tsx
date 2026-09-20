"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { usePrivacyMode } from "@/lib/privacy-mode";
import { fmtINR } from "@/lib/format";

interface SectorBucket { sector: string; value: number; pct: number }
interface CapBucket { bucket: string; value: number; pct: number }
interface TopPosition { symbol: string; value: number; pct: number }
interface Exposure {
  total_value: number;
  position_count: number;
  by_sector: SectorBucket[];
  by_cap_bucket: CapBucket[];
  top_n: TopPosition[];
  // Legacy: sum of squared per-position weights. New backend returns both
  // herfindahl_sectors (intuitive concentration metric) and
  // herfindahl_positions (the older value) — display sector HHI by default.
  herfindahl?: number;
  herfindahl_sectors?: number;
  herfindahl_positions?: number;
}

const CAP_LABELS: Record<string, string> = {
  large: "Large", mid: "Mid", small: "Small", unknown: "Other",
};
const CAP_COLORS: Record<string, string> = {
  large: "oklch(60% 0.13 250)",
  mid: "oklch(65% 0.14 180)",
  small: "oklch(72% 0.15 80)",
  unknown: "oklch(60% 0.05 280)",
};

export default function PortfolioExposure() {
  const [data, setData] = useState<Exposure | null>(null);
  const [loading, setLoading] = useState(true);
  const mask = usePrivacyMode();

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await api.get<Exposure>("/api/portfolio/exposure");
        if (!cancelled) setData(res);
      } catch {
        if (!cancelled) setData(null);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  if (loading || !data || data.position_count === 0) return null;

  // Prefer sector-level HHI (matches analyst intuition); fall back to the
  // legacy per-position value when the backend hasn't been redeployed.
  const sectorHhi = data.herfindahl_sectors ?? data.herfindahl ?? 0;
  const positionHhi = data.herfindahl_positions ?? data.herfindahl ?? 0;

  const concentrationLabel =
    sectorHhi > 2500 ? "Highly concentrated"
      : sectorHhi > 1500 ? "Concentrated"
        : sectorHhi > 800 ? "Balanced"
          : "Diversified";

  const concentrationColor =
    sectorHhi > 2500 ? "var(--act)"
      : sectorHhi > 1500 ? "var(--review)"
        : "var(--buy)";

  const hhiTooltip =
    `Sector-level Herfindahl–Hirschman Index. Scale 0–10,000; ` +
    `>2,500 highly concentrated, 1,500–2,500 concentrated, ` +
    `800–1,500 balanced, <800 diversified. ` +
    `Position-level HHI: ${positionHhi.toFixed(0)}.`;

  return (
    <section style={{
      background: "var(--bg-primary)",
      border: "1px solid var(--separator-light)",
      borderRadius: 12,
      padding: 18,
      marginBottom: 22,
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", marginBottom: 14 }}>
        <div>
          <h3 style={{
            margin: 0, fontFamily: "var(--font-serif)", fontSize: 18,
            fontWeight: 600, letterSpacing: "-0.01em",
          }}>Exposure</h3>
          <p style={{ margin: "4px 0 0", fontSize: 12, color: "var(--label-tertiary)" }}>
            {data.position_count} positions · {mask ? "••••" : fmtINR(data.total_value)}
          </p>
        </div>
        <div
          title={hhiTooltip}
          style={{
            display: "inline-flex", alignItems: "center", gap: 6,
            fontSize: 11.5, fontWeight: 600,
            padding: "3px 8px", borderRadius: 99,
            color: concentrationColor,
            background: "color-mix(in srgb, currentColor 10%, transparent)",
            cursor: "help",
          }}
        >
          {concentrationLabel} · Sector HHI {sectorHhi.toFixed(0)}
        </div>
      </div>

      <div style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
        gap: 14,
      }}>
        {/* Sector mix */}
        <div>
          <div style={{ fontSize: 10.5, fontWeight: 600, color: "var(--label-tertiary)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 8 }}>
            By sector
          </div>
          {data.by_sector.slice(0, 5).map(s => (
            <div key={s.sector} style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 5 }}>
              <span style={{ fontSize: 12, color: "var(--label-secondary)", minWidth: 80, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {s.sector}
              </span>
              <span style={{ flex: 1, height: 6, background: "var(--bg-secondary)", borderRadius: 3, overflow: "hidden" }}>
                <span style={{ display: "block", height: "100%", width: `${s.pct}%`, background: "oklch(60% 0.13 250)" }} />
              </span>
              <span style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--label-tertiary)", minWidth: 36, textAlign: "right" }}>
                {s.pct.toFixed(0)}%
              </span>
            </div>
          ))}
        </div>

        {/* Cap mix */}
        <div>
          <div style={{ fontSize: 10.5, fontWeight: 600, color: "var(--label-tertiary)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 8 }}>
            By cap
          </div>
          {data.by_cap_bucket.map(b => (
            <div key={b.bucket} style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 5 }}>
              <span style={{ fontSize: 12, color: "var(--label-secondary)", minWidth: 80 }}>
                {CAP_LABELS[b.bucket] || b.bucket}
              </span>
              <span style={{ flex: 1, height: 6, background: "var(--bg-secondary)", borderRadius: 3, overflow: "hidden" }}>
                <span style={{ display: "block", height: "100%", width: `${b.pct}%`, background: CAP_COLORS[b.bucket] || "oklch(60% 0.05 280)" }} />
              </span>
              <span style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--label-tertiary)", minWidth: 36, textAlign: "right" }}>
                {b.pct.toFixed(0)}%
              </span>
            </div>
          ))}
        </div>

        {/* Top positions */}
        <div>
          <div style={{ fontSize: 10.5, fontWeight: 600, color: "var(--label-tertiary)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 8 }}>
            Top 5 positions
          </div>
          {data.top_n.map(p => (
            <div key={p.symbol} style={{ display: "flex", justifyContent: "space-between", marginBottom: 5 }}>
              <span style={{ fontFamily: "var(--font-mono)", fontSize: 12, fontWeight: 600 }}>{p.symbol}</span>
              <span style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--label-tertiary)" }}>
                {p.pct.toFixed(1)}%
              </span>
            </div>
          ))}
          <div style={{ fontSize: 10.5, color: "var(--label-quaternary)", marginTop: 6 }}>
            Top 5 = {data.top_n.reduce((s, p) => s + p.pct, 0).toFixed(0)}% of portfolio
          </div>
        </div>
      </div>
    </section>
  );
}
