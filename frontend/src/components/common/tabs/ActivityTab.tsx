"use client";

import React, { useEffect, useState } from "react";
import { api } from "@/lib/api";
import MarketContextCard from "../MarketContextCard";
import SmartMoneyPanel from "../SmartMoneyPanel";

interface Props {
  symbol: string;
  livePctFrom52wHigh?: number | null;
}

interface ShareholdingRow {
  q: string | null;
  promoter: number | null;
  mf: number | null;
  fii: number | null;
  dii: number | null;
  retail: number | null;
  pledge: number | null;
}

// Backend emits two shapes for the quarter label:
//   - `sp.quarter` free text — typically "Q1-2026"
//   - fallback strftime("%b %Y") — "Mar 2025"
// Render both as a compact 6-char label (Q1'26 / Mar'25). Anything we
// can't recognize is returned trimmed but unmodified, so format changes
// never silently truncate.
function formatQuarterLabel(q: string | null | undefined): string {
  if (!q) return "";
  const trimmed = q.trim();
  // "Mon YYYY" → "Mon'YY"
  const monYear = trimmed.match(/^([A-Za-z]{3})\s+(\d{4})$/);
  if (monYear) return `${monYear[1]}'${monYear[2].slice(-2)}`;
  // "Q1-2026" / "Q1 2026" → "Q1'26"
  const qYear = trimmed.match(/^(Q[1-4])[\s-](\d{4})$/i);
  if (qYear) return `${qYear[1].toUpperCase()}'${qYear[2].slice(-2)}`;
  return trimmed;
}

const MONTH_MAP: Record<string, number> = {
  jan: 0, feb: 1, mar: 2, apr: 3, may: 4, jun: 5,
  jul: 6, aug: 7, sep: 8, oct: 9, nov: 10, dec: 11,
};

// Parse a quarter label ("Jun 2023" / "Q1 2026") to a sortable timestamp.
// Upstream sources (Screener.in, NSE) emit `shareholding_history` in
// inconsistent order — Screener gives oldest-first, NSE gives newest-first.
// Sorting client-side makes both modules robust to either.
function quarterToTs(q: string | null | undefined): number {
  if (!q) return 0;
  const t = q.trim();
  const monYear = t.match(/^([A-Za-z]{3})\s+(\d{4})$/);
  if (monYear) {
    const m = MONTH_MAP[monYear[1].slice(0, 3).toLowerCase()] ?? 0;
    return Date.UTC(parseInt(monYear[2], 10), m, 1);
  }
  const qYear = t.match(/^(Q[1-4])[\s-](\d{4})$/i);
  if (qYear) {
    const qNum = parseInt(qYear[1].slice(1), 10);
    const month = (qNum - 1) * 3;
    return Date.UTC(parseInt(qYear[2], 10), month, 1);
  }
  return 0;
}

// Returns history sorted newest-first (index 0 = latest quarter).
function sortHistoryNewestFirst(history: ShareholdingRow[]): ShareholdingRow[] {
  return [...history].sort((a, b) => quarterToTs(b.q) - quarterToTs(a.q));
}

interface QuoteFundamentals {
  pe_ratio?: number | null;
  ttm_pe?: number | null;
  pb_ratio?: number | null;
  promoter_holding?: number | null;
  shareholding_history?: ShareholdingRow[] | null;
  sector?: string | null;
  name?: string | null;
}

interface QuoteResp {
  fundamentals: QuoteFundamentals | null;
}

interface MfBuySellRow {
  scheme: string;
  weight?: number | null;
  rank?: number | null;
  rank_change?: number | null;
  change_3m?: number | null;
  change?: number | null;
}
interface MfBuySellResp {
  movers?: MfBuySellRow[];
  rows?: MfBuySellRow[];
}

interface Peer {
  symbol: string;
  name: string | null;
  market_cap: number | null;
  pe_ratio: number | null;
  pb_ratio: number | null;
  roe: number | null;
  revenue_growth_1y: number | null;
  net_profit_margin?: number | null;
  pct_from_52w_high: number | null;
  composite_score?: number | null;
  is_self?: boolean;
}
interface PeersResp {
  symbol: string;
  sector: string | null;
  peers: Peer[];
  source?: "stored" | "sector_fallback" | "none";
}

function pctStr(n: number | null | undefined, d = 2): string {
  if (n == null) return "—";
  return `${n >= 0 ? "+" : ""}${n.toFixed(d)}%`;
}

function fmtMcap(v: number | null | undefined): string {
  if (v == null) return "—";
  if (v >= 100_000) return `${(v / 100_000).toFixed(1)}L Cr`;
  if (v >= 1_000) return `${(v / 1_000).toFixed(1)}K Cr`;
  return `${Math.round(v).toLocaleString("en-IN")} Cr`;
}

// ─── Conviction Scoreboard ─────────────────────────────────────────
function ConvictionScoreboard({
  history, peTtm, peerMedianPe,
}: {
  history: ShareholdingRow[] | null;
  peTtm: number | null;
  peerMedianPe: number | null;
}) {
  // Compare current vs ~3 quarters ago
  const items: Array<{ label: string; verdict: string; tone: "pos" | "neg" | "warn" | "neutral"; detail: string }> = [];

  if (history && history.length >= 1) {
    const latest = history[0];
    const prev = history[Math.min(history.length - 1, 3)];
    const promoterΔ = (latest.promoter ?? 0) - (prev.promoter ?? 0);
    const promoterStrong = (latest.promoter ?? 0) >= 45;
    const promoterStable = Math.abs(promoterΔ) < 0.05;
    items.push({
      label: "Promoter conviction",
      verdict: promoterStrong
        ? promoterStable ? "Stable & high"
        : promoterΔ > 0 ? "Increasing"
        : "Decreasing"
        : "Below 45% threshold",
      tone: promoterStrong ? (promoterΔ >= -0.05 ? "pos" : "neg") : "warn",
      detail: `Holds ${(latest.promoter ?? 0).toFixed(2)}% · pledge ${(latest.pledge ?? 0).toFixed(1)}% · 45% is the conviction floor`,
    });
    const inst = (latest.mf ?? 0) + (latest.fii ?? 0) + (latest.dii ?? 0);
    const instPrev = (prev.mf ?? 0) + (prev.fii ?? 0) + (prev.dii ?? 0);
    const instΔ = inst - instPrev;
    items.push({
      label: "Institutional flow",
      verdict: instΔ > 0.5 ? "Adding" : instΔ < -0.5 ? "Trimming" : "Holding",
      tone: instΔ > 0.5 ? "pos" : instΔ < -0.5 ? "neg" : "neutral",
      detail: `${inst.toFixed(2)}% combined · ${instΔ >= 0 ? "+" : ""}${instΔ.toFixed(2)}% over ${history.length} quarter${history.length === 1 ? "" : "s"}`,
    });
  } else {
    items.push({ label: "Promoter conviction", verdict: "—", tone: "neutral", detail: "History not yet fetched" });
    items.push({ label: "Institutional flow", verdict: "—", tone: "neutral", detail: "History not yet fetched" });
  }

  if (peTtm != null && peerMedianPe != null) {
    const ratio = peTtm / peerMedianPe;
    items.push({
      label: "Valuation vs peers",
      verdict: ratio > 1.5 ? "Premium" : ratio < 0.7 ? "Discount" : "In line",
      tone: ratio > 1.5 ? "warn" : ratio < 0.7 ? "pos" : "neutral",
      detail: `P/E ${peTtm.toFixed(0)}× vs peer median ${peerMedianPe.toFixed(0)}×`,
    });
  } else {
    items.push({ label: "Valuation vs peers", verdict: "—", tone: "neutral", detail: "Peer P/E not available" });
  }

  const accent = (t: string) => t === "pos" ? "var(--system-green)"
    : t === "neg" ? "var(--system-red)"
    : t === "warn" ? "var(--system-orange)"
    : "var(--label-quaternary)";

  // Three-card row at desktop, single-column stack at <md so labels like
  // "INSTITUTIONAL FLOW" stop truncating to "INSTITUTIONA…" and verdicts
  // ("Trimmin…", "Premiur…") fit fully.
  return (
    <div className="at-conviction-grid" style={{
      display: "grid",
      gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
      gap: 12, marginBottom: 16,
    }}>
      <style jsx>{`
        @media (max-width: 720px) {
          .at-conviction-grid {
            grid-template-columns: 1fr !important;
          }
        }
      `}</style>
      {items.map((it, i) => (
        <div key={i} style={{
          background: "var(--bg-primary)",
          border: "1px solid var(--separator-light)",
          borderRadius: 12,
          padding: "14px 16px",
          position: "relative", overflow: "hidden",
          display: "flex", flexDirection: "column", gap: 4,
        }}>
          <span style={{
            position: "absolute", left: 0, top: 0, bottom: 0, width: 3,
            background: accent(it.tone),
          }} />
          <div style={{
            fontSize: 10.5, fontWeight: 600, letterSpacing: "0.08em",
            textTransform: "uppercase", color: "var(--label-tertiary)",
          }}>{it.label}</div>
          <div style={{
            fontFamily: "var(--font-serif)", fontSize: 19, fontWeight: 600,
            letterSpacing: "-0.01em", color: accent(it.tone),
          }}>{it.verdict}</div>
          <div style={{ fontSize: 12, color: "var(--label-tertiary)" }}>{it.detail}</div>
        </div>
      ))}
    </div>
  );
}

// ─── Promoter Module ───────────────────────────────────────────────
function PromoterModule({ history }: { history: ShareholdingRow[] | null }) {
  if (!history || history.length === 0) {
    return (
      <section style={{
        background: "var(--bg-primary)", border: "1px solid var(--separator-light)",
        borderRadius: 12, padding: 18, boxShadow: "var(--shadow-sm)",
      }}>
        <div style={{
          fontSize: 11, fontWeight: 600, letterSpacing: "0.08em",
          textTransform: "uppercase", color: "var(--label-tertiary)",
        }}>Promoter Holding</div>
        <div style={{ marginTop: 12, fontSize: 13, color: "var(--label-tertiary)" }}>
          Shareholding history not available. Run a fundamentals refresh.
        </div>
      </section>
    );
  }
  // Sort defensively — upstream source order is inconsistent.
  const sorted = sortHistoryNewestFirst(history);  // [0] = latest, [-1] = oldest
  const latest = sorted[0].promoter ?? 0;
  const oldest = sorted[sorted.length - 1].promoter ?? 0;
  const Δ = latest - oldest;
  const tone = Δ > 0.05 ? "pos" : Δ < -0.05 ? "neg" : "neutral";
  const verdict = Δ > 0.05 ? "Promoters adding" : Δ < -0.05 ? "Promoters reducing" : "Holding steady";
  const note = latest >= 60 ? `Strong skin in the game — over 60% promoter ownership.`
    : latest >= 45 ? `Healthy promoter ownership at ${latest.toFixed(2)}%.`
    : `Below 45% — modest promoter conviction.`;
  const pledge = sorted[0].pledge ?? 0;

  // Trend bars: oldest on the left → newest on the right (chronological).
  const chronological = [...sorted].reverse();
  const min = Math.min(...chronological.map(r => r.promoter ?? 0));
  const max = Math.max(...chronological.map(r => r.promoter ?? 0));
  const range = Math.max(0.1, max - min);

  return (
    <section style={{
      background: "var(--bg-primary)", border: "1px solid var(--separator-light)",
      borderRadius: 12, padding: 18, boxShadow: "var(--shadow-sm)",
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
        <span style={{
          fontSize: 11, fontWeight: 600, letterSpacing: "0.08em",
          textTransform: "uppercase", color: "var(--label-tertiary)",
        }}>Promoter Holding</span>
        <span style={{
          fontFamily: "var(--font-mono)", fontSize: 11, fontWeight: 700,
          padding: "3px 10px", borderRadius: 99, letterSpacing: "0.02em",
          background: tone === "pos" ? "var(--buy-bg)" : tone === "neg" ? "var(--act-bg)" : "var(--bg-secondary)",
          color: tone === "pos" ? "var(--buy)" : tone === "neg" ? "var(--act)" : "var(--label-tertiary)",
        }}>
          {tone === "pos" ? "▲" : tone === "neg" ? "▼" : "—"} {verdict}
        </span>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 14, flexWrap: "wrap" }}>
          <div style={{
            fontFamily: "var(--font-mono)", fontSize: 44, fontWeight: 600,
            letterSpacing: "-0.03em", lineHeight: 1,
          }}>
            {latest.toFixed(2)}<span style={{ fontSize: 22, color: "var(--label-tertiary)", marginLeft: 4, fontWeight: 500 }}>%</span>
          </div>
          <div style={{ fontSize: 13, color: "var(--label-secondary)", lineHeight: 1.4, flex: 1, minWidth: 180 }}>
            {note}
          </div>
          <div style={{
            display: "inline-flex", alignItems: "center", gap: 6,
            fontSize: 12, color: "var(--label-tertiary)",
            padding: "8px 12px", background: "var(--bg-secondary)", borderRadius: 8,
            alignSelf: "flex-start",
          }}>
            <span style={{
              width: 6, height: 6, borderRadius: 99,
              background: pledge < 1 ? "var(--system-green)" : pledge < 10 ? "var(--system-orange)" : "var(--system-red)",
            }} />
            Pledge: <strong style={{ color: "var(--label-primary)" }}>{pledge.toFixed(1)}%</strong>
            {pledge < 1 ? " · insignificant" : pledge < 10 ? " · low" : " · concerning"}
          </div>
        </div>

        <div style={{ paddingTop: 12, borderTop: "1px solid var(--separator-light)" }}>
          <div style={{
            fontSize: 10.5, fontWeight: 600, color: "var(--label-tertiary)",
            letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 8,
          }}>Last {chronological.length} quarters</div>
          <div style={{
            display: "grid", gridTemplateColumns: `repeat(${chronological.length}, 1fr)`,
            gap: 6, alignItems: "end",
          }}>
            {chronological.map((row, i) => {
              const v = row.promoter ?? 0;
              const h = 12 + ((v - min) / range) * 36;
              return (
                <div key={i} style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 4 }}>
                  <div style={{
                    width: "100%", maxWidth: 36,
                    background: "linear-gradient(180deg, var(--label-primary), var(--label-secondary))",
                    borderRadius: "3px 3px 0 0",
                    height: `${h}px`,
                  }} />
                  <div style={{ fontFamily: "var(--font-mono)", fontSize: 9.5, color: "var(--label-tertiary)" }}>
                    {formatQuarterLabel(row.q)}
                  </div>
                  <div style={{ fontFamily: "var(--font-mono)", fontSize: 10.5, color: "var(--label-secondary)", fontWeight: 500 }}>
                    {v.toFixed(2)}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </section>
  );
}

// ─── Institutional Module ──────────────────────────────────────────
function InstitutionalModule({ history, movers }: { history: ShareholdingRow[] | null; movers: MfBuySellRow[] }) {
  if (!history || history.length === 0) {
    return (
      <section style={{
        background: "var(--bg-primary)", border: "1px solid var(--separator-light)",
        borderRadius: 12, padding: 18, boxShadow: "var(--shadow-sm)",
      }}>
        <div style={{
          fontSize: 11, fontWeight: 600, letterSpacing: "0.08em",
          textTransform: "uppercase", color: "var(--label-tertiary)",
        }}>Institutional Activity</div>
        <div style={{ marginTop: 12, fontSize: 13, color: "var(--label-tertiary)" }}>
          History not available.
        </div>
      </section>
    );
  }
  // Sort defensively — upstream source order is inconsistent.
  const sorted = sortHistoryNewestFirst(history);
  const latest = sorted[0];
  const prev = sorted[1] || latest;
  const groups = [
    { k: "Mutual Funds", cur: latest.mf ?? 0, prev: prev.mf ?? 0, color: "var(--system-blue)" },
    { k: "FII / FPI", cur: latest.fii ?? 0, prev: prev.fii ?? 0, color: "var(--system-green)" },
    { k: "DII / Insurers", cur: latest.dii ?? 0, prev: prev.dii ?? 0, color: "var(--system-purple)" },
  ];
  const max = Math.max(...groups.map(g => g.cur), 0.1);

  return (
    <section style={{
      background: "var(--bg-primary)", border: "1px solid var(--separator-light)",
      borderRadius: 12, padding: 18, boxShadow: "var(--shadow-sm)",
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
        <span style={{
          fontSize: 11, fontWeight: 600, letterSpacing: "0.08em",
          textTransform: "uppercase", color: "var(--label-tertiary)",
        }}>Institutional Activity</span>
        <span style={{ fontSize: 12, color: "var(--label-tertiary)" }}>
          Quarter-on-quarter ({formatQuarterLabel(latest.q)})
        </span>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 8, margin: "10px 0 16px" }}>
        {groups.map((g, i) => {
          const Δ = g.cur - g.prev;
          const tone = Δ > 0.05 ? "pos" : Δ < -0.05 ? "neg" : "neutral";
          return (
            <div key={i} style={{
              display: "grid", gridTemplateColumns: "140px 1fr 70px",
              gap: 12, alignItems: "center",
            }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
                <span style={{ fontSize: 12.5, color: "var(--label-secondary)", fontWeight: 500 }}>{g.k}</span>
                <span style={{ fontSize: 13, fontWeight: 600, fontFamily: "var(--font-mono)" }}>{g.cur.toFixed(2)}%</span>
              </div>
              <div style={{
                height: 8, background: "var(--bg-secondary)", borderRadius: 99,
                border: "1px solid var(--separator-light)", overflow: "hidden",
              }}>
                <div style={{
                  height: "100%", width: `${(g.cur / max) * 100}%`, background: g.color,
                  borderRadius: 99, transition: "width .4s",
                }} />
              </div>
              <div style={{
                fontSize: 12, fontWeight: 600, textAlign: "right", fontFamily: "var(--font-mono)",
                color: tone === "pos" ? "var(--system-green)" : tone === "neg" ? "var(--system-red)" : "var(--label-tertiary)",
              }}>
                {Δ >= 0 ? "+" : ""}{Δ.toFixed(2)}%
                {tone === "pos" ? " ▲" : tone === "neg" ? " ▼" : ""}
              </div>
            </div>
          );
        })}
      </div>

      {movers.length > 0 && (
        <>
          <div style={{ marginTop: 14, paddingTop: 12, borderTop: "1px solid var(--separator-light)" }}>
            <span style={{
              fontSize: 10.5, fontWeight: 600, color: "var(--label-tertiary)",
              letterSpacing: "0.08em", textTransform: "uppercase",
            }}>Top fund moves · 3-month change</span>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 2, marginTop: 8 }}>
            {movers.slice(0, 5).map((m, i) => {
              const change = m.change_3m ?? m.change ?? 0;
              const tone = change > 0 ? "pos" : change < 0 ? "neg" : "neutral";
              return (
                <div key={i} style={{
                  display: "flex", alignItems: "center", gap: 12,
                  padding: "8px 0", borderBottom: i < movers.length - 1 ? "1px solid var(--separator-light)" : 0,
                }}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 12.5, color: "var(--label-primary)", fontWeight: 500 }}>{m.scheme}</div>
                    <div style={{
                      fontSize: 11, color: "var(--label-tertiary)", marginTop: 2,
                      display: "flex", gap: 4, alignItems: "baseline", flexWrap: "wrap",
                    }}>
                      {m.weight != null && <>weight <span style={{ fontFamily: "var(--font-mono)" }}>{m.weight.toFixed(2)}%</span></>}
                      {m.rank != null && <>
                        <span style={{ color: "var(--label-quaternary)" }}>·</span>
                        rank <span style={{ fontFamily: "var(--font-mono)" }}>{m.rank}</span>
                      </>}
                      {m.rank_change != null && m.rank_change !== 0 && (
                        <span style={{
                          fontFamily: "var(--font-mono)",
                          color: m.rank_change > 0 ? "var(--system-green)" : "var(--system-red)",
                        }}>
                          {m.rank_change > 0 ? `↑${m.rank_change}` : `↓${Math.abs(m.rank_change)}`}
                        </span>
                      )}
                    </div>
                  </div>
                  <div style={{
                    fontSize: 13, fontWeight: 600, fontFamily: "var(--font-mono)",
                    color: tone === "pos" ? "var(--system-green)" : tone === "neg" ? "var(--system-red)" : "var(--label-tertiary)",
                  }}>
                    {change >= 0 ? "+" : ""}{change.toFixed(2)}%
                  </div>
                </div>
              );
            })}
          </div>
        </>
      )}
    </section>
  );
}

// ─── Peer comparison table ─────────────────────────────────────────
function PeerComparisonTable({ peers, sector, symbol, source, onRegenerate, livePctFrom52wHigh, isLoading }: {
  peers: Peer[];
  sector: string | null;
  symbol: string;
  source?: string;
  onRegenerate: () => void;
  livePctFrom52wHigh?: number | null;
  isLoading?: boolean;
}) {
  const [generating, setGenerating] = useState(false);

  async function handleGenerate() {
    setGenerating(true);
    try {
      await api.post(`/api/market-data/peers/${symbol}/generate`, {});
      onRegenerate();
    } catch {
      // silently fail — user can try again
    } finally {
      setGenerating(false);
    }
  }

  const showGenerateButton = source !== "stored";

  // Loading skeleton — show while fetch is in flight so we never display
  // "No peers found" as a misleading empty state for stocks that DO have peers.
  if (isLoading && (!peers || peers.length === 0)) {
    return (
      <section style={{
        background: "var(--bg-primary)", border: "1px solid var(--separator-light)",
        borderRadius: 12, padding: 18, boxShadow: "var(--shadow-sm)",
      }}>
        <div style={{
          fontSize: 11, fontWeight: 600, letterSpacing: "0.08em",
          textTransform: "uppercase", color: "var(--label-tertiary)", marginBottom: 12,
        }}>Peer Comparison</div>
        {[0, 1, 2].map(i => (
          <div
            key={i}
            className="animate-pulse"
            style={{
              height: 28, marginBottom: 8, borderRadius: 6,
              background: "var(--fill-gray)",
            }}
          />
        ))}
      </section>
    );
  }

  if (!peers || peers.length === 0) {
    return (
      <section style={{
        background: "var(--bg-primary)", border: "1px solid var(--separator-light)",
        borderRadius: 12, padding: 18, boxShadow: "var(--shadow-sm)",
      }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div style={{
            fontSize: 11, fontWeight: 600, letterSpacing: "0.08em",
            textTransform: "uppercase", color: "var(--label-tertiary)",
          }}>Peer Comparison</div>
          <button
            onClick={handleGenerate}
            disabled={generating}
            style={{
              padding: "5px 12px", borderRadius: 6, border: "none", cursor: generating ? "not-allowed" : "pointer",
              fontSize: 11, fontWeight: 600, backgroundColor: "var(--label-primary)", color: "var(--bg-primary)",
              opacity: generating ? 0.5 : 1,
            }}
          >
            {generating ? "Generating…" : "Generate Smart Peers"}
          </button>
        </div>
        <div style={{ marginTop: 12, fontSize: 13, color: "var(--label-tertiary)" }}>
          No peers found. Click "Generate Smart Peers" to discover relevant comparables.
        </div>
      </section>
    );
  }

  const peVals = peers.map(p => p.pe_ratio).filter((v): v is number => v != null);
  const pbVals = peers.map(p => p.pb_ratio).filter((v): v is number => v != null);
  const roeVals = peers.map(p => p.roe).filter((v): v is number => v != null);
  const revVals = peers.map(p => p.revenue_growth_1y).filter((v): v is number => v != null);
  const fromHVals = peers.map(p => p.pct_from_52w_high).filter((v): v is number => v != null);

  const bestPE = Math.min(...peVals, Infinity);
  const worstPE = Math.max(...peVals, -Infinity);
  const bestPB = Math.min(...pbVals, Infinity);
  const worstPB = Math.max(...pbVals, -Infinity);
  const bestROE = Math.max(...roeVals, -Infinity);
  const bestRev = Math.max(...revVals, -Infinity);
  const bestFromH = Math.max(...fromHVals, -Infinity);
  const worstFromH = Math.min(...fromHVals, Infinity);

  const tone = (v: number | null, best: number, worst: number, lowerBetter: boolean) => {
    if (v == null) return "neutral";
    if (lowerBetter) {
      if (v === best) return "pos";
      if (v === worst) return "neg";
    } else {
      if (v === best) return "pos";
      if (v === worst) return "neg";
    }
    return "neutral";
  };
  const toneClass = (t: string) =>
    t === "pos" ? "var(--system-green)" : t === "neg" ? "var(--system-red)" : "var(--label-primary)";

  return (
    <section style={{
      background: "var(--bg-primary)", border: "1px solid var(--separator-light)",
      borderRadius: 12, padding: 18, boxShadow: "var(--shadow-sm)",
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
        <span style={{
          fontSize: 11, fontWeight: 600, letterSpacing: "0.08em",
          textTransform: "uppercase", color: "var(--label-tertiary)",
        }}>Peer Comparison</span>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 12, color: "var(--label-tertiary)" }}>
            {source === "stored" ? "AI-matched" : "Sector"} · {sector || "—"} · {peers.length}
          </span>
          {showGenerateButton && (
            <button
              onClick={handleGenerate}
              disabled={generating}
              style={{
                padding: "4px 10px", borderRadius: 6, border: "none", cursor: generating ? "not-allowed" : "pointer",
                fontSize: 10.5, fontWeight: 600, backgroundColor: "var(--label-primary)", color: "var(--bg-primary)",
                opacity: generating ? 0.5 : 1,
              }}
            >
              {generating ? "…" : "Generate Smart Peers"}
            </button>
          )}
          {source === "stored" && (
            <button
              onClick={handleGenerate}
              disabled={generating}
              title="Regenerate peers via AI"
              style={{
                padding: "4px 8px", borderRadius: 6, border: "1px solid var(--separator-light)", cursor: generating ? "not-allowed" : "pointer",
                fontSize: 11, backgroundColor: "transparent", color: "var(--label-tertiary)",
                opacity: generating ? 0.5 : 1,
              }}
            >
              {generating ? "…" : "↻"}
            </button>
          )}
        </div>
      </div>
      <div style={{ fontSize: 12.5, color: "var(--label-secondary)", margin: "8px 0 12px" }}>
        How this stock stands vs sector peers — context for the valuation.
      </div>
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
          <thead>
            <tr style={{ borderBottom: "1px solid var(--separator-light)" }}>
              <th style={{ textAlign: "left", padding: "8px 12px", fontSize: 10.5, fontWeight: 600, color: "var(--label-tertiary)", letterSpacing: "0.08em", textTransform: "uppercase" }}>Company</th>
              <th style={{ textAlign: "right", padding: "8px 12px", fontSize: 10.5, fontWeight: 600, color: "var(--label-tertiary)", letterSpacing: "0.08em", textTransform: "uppercase" }} title="Composite score: cheaper + higher quality vs cohort. 50 = at peer median.">Score</th>
              <th style={{ textAlign: "right", padding: "8px 12px", fontSize: 10.5, fontWeight: 600, color: "var(--label-tertiary)", letterSpacing: "0.08em", textTransform: "uppercase" }}>M-Cap</th>
              <th style={{ textAlign: "right", padding: "8px 12px", fontSize: 10.5, fontWeight: 600, color: "var(--label-tertiary)", letterSpacing: "0.08em", textTransform: "uppercase" }}>P/E</th>
              <th style={{ textAlign: "right", padding: "8px 12px", fontSize: 10.5, fontWeight: 600, color: "var(--label-tertiary)", letterSpacing: "0.08em", textTransform: "uppercase" }}>P/B</th>
              <th style={{ textAlign: "right", padding: "8px 12px", fontSize: 10.5, fontWeight: 600, color: "var(--label-tertiary)", letterSpacing: "0.08em", textTransform: "uppercase" }}>ROE</th>
              <th style={{ textAlign: "right", padding: "8px 12px", fontSize: 10.5, fontWeight: 600, color: "var(--label-tertiary)", letterSpacing: "0.08em", textTransform: "uppercase" }}>Rev 1Y</th>
              <th style={{ textAlign: "right", padding: "8px 12px", fontSize: 10.5, fontWeight: 600, color: "var(--label-tertiary)", letterSpacing: "0.08em", textTransform: "uppercase" }}>From 52WH</th>
            </tr>
          </thead>
          <tbody>
            {[...peers].sort((a, b) => {
              // Self always at top, then by composite_score DESC
              if (a.is_self && !b.is_self) return -1;
              if (!a.is_self && b.is_self) return 1;
              const sa = a.composite_score ?? -1;
              const sb = b.composite_score ?? -1;
              return sb - sa;
            }).map(p => {
              const isSelf = !!p.is_self;
              const fromH = isSelf && livePctFrom52wHigh != null ? livePctFrom52wHigh : p.pct_from_52w_high;
              const tPE = tone(p.pe_ratio, bestPE, worstPE, true);
              const tPB = tone(p.pb_ratio, bestPB, worstPB, true);
              const tROE = tone(p.roe, bestROE, -Infinity, false);
              const tRev = tone(p.revenue_growth_1y, bestRev, -Infinity, false);
              const tFromH = tone(fromH, bestFromH, worstFromH, false);
              const cellStyle = (color: string): React.CSSProperties => ({
                padding: 12, textAlign: "right",
                fontFamily: "var(--font-mono)",
                color, fontWeight: 500,
                borderBottom: "1px solid var(--separator-light)",
              });
              return (
                <tr key={p.symbol} style={{
                  background: isSelf ? "var(--bg-secondary)" : "transparent",
                  fontWeight: isSelf ? 600 : 400,
                }}>
                  <td style={{
                    padding: 12, borderBottom: "1px solid var(--separator-light)",
                    borderLeft: isSelf ? "3px solid var(--label-primary)" : "0",
                    paddingLeft: isSelf ? 9 : 12,
                  }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <span style={{ fontFamily: "var(--font-mono)", fontWeight: 600, fontSize: 13 }}>{p.symbol}</span>
                      {isSelf && (
                        <span style={{
                          fontFamily: "var(--font-mono)", fontSize: 9.5, fontWeight: 700,
                          background: "var(--label-primary)", color: "var(--bg-primary)",
                          padding: "2px 6px", borderRadius: 3, letterSpacing: "0.04em",
                        }}>THIS</span>
                      )}
                    </div>
                    {p.name && (
                      <div style={{ fontSize: 11.5, color: "var(--label-tertiary)", marginTop: 2 }}>{p.name}</div>
                    )}
                  </td>
                  <td style={cellStyle(
                    p.composite_score == null
                      ? "var(--label-tertiary)"
                      : p.composite_score >= 60
                        ? "var(--buy)"
                        : p.composite_score <= 40
                          ? "var(--act)"
                          : "var(--label-primary)"
                  )}>
                    {p.composite_score != null ? p.composite_score.toFixed(0) : "—"}
                  </td>
                  <td style={cellStyle("var(--label-primary)")}>{fmtMcap(p.market_cap)}</td>
                  <td style={cellStyle(toneClass(tPE))}>{p.pe_ratio != null ? `${p.pe_ratio.toFixed(1)}×` : "—"}</td>
                  <td style={cellStyle(toneClass(tPB))}>{p.pb_ratio != null ? `${p.pb_ratio.toFixed(1)}×` : "—"}</td>
                  <td style={cellStyle(toneClass(tROE))}>{p.roe != null ? `${(p.roe * 100).toFixed(1)}%` : "—"}</td>
                  <td style={cellStyle(toneClass(tRev))}>{p.revenue_growth_1y != null ? pctStr(p.revenue_growth_1y * 100) : "—"}</td>
                  <td style={cellStyle(toneClass(tFromH))}>{fromH != null ? `${fromH.toFixed(1)}%` : "—"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

// ─── Top-level ActivityTab ─────────────────────────────────────────
export default function ActivityTab({ symbol, livePctFrom52wHigh }: Props) {
  const [fundamentals, setFundamentals] = useState<QuoteFundamentals | null>(null);
  const [movers, setMovers] = useState<MfBuySellRow[]>([]);
  const [peersData, setPeersData] = useState<PeersResp | null>(null);
  // Per-section loading flags so a slow fetch (sentiment, mf-buysell) doesn't
  // block render of a fast one (peers ~43ms). Each section updates state
  // independently as soon as its own fetch resolves.
  const [quoteLoading, setQuoteLoading] = useState(true);
  const [moversLoading, setMoversLoading] = useState(true);
  const [peersLoading, setPeersLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setQuoteLoading(true);
    setMoversLoading(true);
    setPeersLoading(true);

    api.get<QuoteResp>(`/api/market-data/quote/${symbol}`)
      .then(q => { if (!cancelled) setFundamentals(q?.fundamentals ?? null); })
      .catch(() => { if (!cancelled) setFundamentals(null); })
      .finally(() => { if (!cancelled) setQuoteLoading(false); });

    api.get<MfBuySellResp>(`/api/market-data/mf-buysell/${symbol}`)
      .then(m => { if (!cancelled) setMovers((m?.movers ?? m?.rows ?? []) as MfBuySellRow[]); })
      .catch(() => { if (!cancelled) setMovers([]); })
      .finally(() => { if (!cancelled) setMoversLoading(false); });

    api.get<PeersResp>(`/api/market-data/peers/${symbol}?limit=8`)
      .then(p => { if (!cancelled) setPeersData(p); })
      .catch(() => { if (!cancelled) setPeersData(null); })
      .finally(() => { if (!cancelled) setPeersLoading(false); });

    return () => { cancelled = true; };
  }, [symbol]);

  const loading = quoteLoading || moversLoading || peersLoading;

  const history = fundamentals?.shareholding_history ?? null;
  const peTtm = fundamentals?.ttm_pe ?? fundamentals?.pe_ratio ?? null;
  const peerPes = (peersData?.peers ?? [])
    .filter(p => !p.is_self && p.pe_ratio != null)
    .map(p => p.pe_ratio!)
    .sort((a, b) => a - b);
  const peerMedianPe = peerPes.length ? peerPes[Math.floor(peerPes.length / 2)] : null;

  function refetchPeers() {
    api.get<PeersResp>(`/api/market-data/peers/${symbol}?limit=8`)
      .then((p) => setPeersData(p))
      .catch(() => {});
  }

  return (
    <section style={{ paddingTop: 8 }}>
      <header style={{ marginBottom: 18 }}>
        <h2 style={{
          fontFamily: "var(--font-serif)", fontSize: 26, fontWeight: 600,
          letterSpacing: "-0.015em", margin: 0,
        }}>Vote of confidence</h2>
        <p style={{ fontSize: 13.5, color: "var(--label-secondary)", margin: "4px 0 0" }}>
          Who owns it, who&apos;s adding, and how it stacks up against peers.
        </p>
      </header>

      <div style={{ marginBottom: 14 }}>
        <MarketContextCard />
      </div>

      <ConvictionScoreboard history={history} peTtm={peTtm} peerMedianPe={peerMedianPe} />

      <div style={{ marginBottom: 14 }}>
        <SmartMoneyPanel symbol={symbol} />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14, marginBottom: 14 }}>
        <PromoterModule history={history} />
        <InstitutionalModule history={history} movers={movers} />
      </div>

      <PeerComparisonTable
        peers={peersData?.peers ?? []}
        sector={peersData?.sector ?? fundamentals?.sector ?? null}
        symbol={symbol}
        source={peersData?.source}
        onRegenerate={refetchPeers}
        livePctFrom52wHigh={livePctFrom52wHigh}
        isLoading={peersLoading}
      />

      {(quoteLoading || moversLoading) && (
        <div style={{ marginTop: 12, textAlign: "center", fontSize: 12, color: "var(--label-tertiary)" }}>
          Loading…
        </div>
      )}
    </section>
  );
}
