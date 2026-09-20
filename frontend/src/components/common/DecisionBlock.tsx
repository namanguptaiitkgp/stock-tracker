"use client";

import React, { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { fmtRecency } from "./SignalPill";

interface Signal {
  symbol: string;
  as_of: string;
  composite: number | null;
  mf_score: number | null;
  pms_score: number | null;
  aif_score: number | null;
  deals_score: number | null;
  delivery_score: number | null;
  named_sharks: Array<{ name: string; side: string; date: string }> | null;
}

interface SmSignalPayload {
  signal: Signal | null;
}

interface NewsSentiment {
  sentiment: string | null;
  score: number | null;
  analyzed_at?: string | null;
}

interface PcrPayload {
  pcr: number | null;
  available: boolean;
  total_call_oi?: number;
  total_put_oi?: number;
}

interface PeerRow {
  symbol: string;
  pe_ratio: number | null;
  is_self?: boolean;
}

interface PeersPayload {
  peers: PeerRow[];
}

interface TechSignal {
  direction: "accumulating" | "distributing" | "neutral";
  label: string;
  strength: number;
}

export interface Fundamentals {
  pe_ratio?: number | null;
  ttm_pe?: number | null;
  pb_ratio?: number | null;
  debt_to_equity?: number | null;
  net_profit_margin?: number | null;
  roe?: number | null;
  revenue_growth_1y?: number | null;
  promoter_holding?: number | null;
}

type SignalDirection = "accumulating" | "distributing" | "neutral";

export interface SignalRow {
  source: string;        // e.g. "MF", "PRO", "RET", "TECH", "OPT", "VAL"
  label: string;         // "Mutual Fund", "Bulk/Block (Pro)", etc.
  direction: SignalDirection;
  strength: number;       // 0-100
  note: string;           // contextual description for the card
  recency?: string | null;
  dirLabel?: string;     // override default direction text (e.g. "Premium" instead of "SELLING")
}

function dirFromScore(v: number | null | undefined): SignalDirection {
  if (v === null || v === undefined) return "neutral";
  if (v >= 15) return "accumulating";
  if (v <= -15) return "distributing";
  return "neutral";
}

export function useDecisionData(symbol: string, techSignal?: TechSignal | null, peTtm?: number | null) {
  const [sm, setSm] = useState<SmSignalPayload | null>(null);
  const [ns, setNs] = useState<NewsSentiment | null>(null);
  const [pcr, setPcr] = useState<PcrPayload | null>(null);
  const [peers, setPeers] = useState<PeersPayload | null>(null);

  useEffect(() => {
    api.get<SmSignalPayload>(`/api/smart-money/${symbol}`).then(setSm).catch(() => setSm(null));
    // cache_only=true so this hook never triggers a fresh 60-90s Gemini run on mount.
    // Explicit "Refresh news" elsewhere uses force=true.
    api.get<NewsSentiment>(`/api/market-data/sentiment/${symbol}?cache_only=true`).then(setNs).catch(() => setNs(null));
    api.get<PcrPayload>(`/api/market-data/options/${symbol}/pcr`).then(setPcr).catch(() => setPcr(null));
    api.get<PeersPayload>(`/api/market-data/peers/${symbol}?limit=8`).then(setPeers).catch(() => setPeers(null));
  }, [symbol]);

  const composite = sm?.signal?.composite ?? null;

  const signals: SignalRow[] = [];
  if (sm?.signal) {
    const asof = sm.signal.as_of;
    if (sm.signal.mf_score != null)
      signals.push({ source: "MF", label: "Mutual Fund", direction: dirFromScore(sm.signal.mf_score), strength: Math.round(Math.abs(sm.signal.mf_score)), note: `Score ${sm.signal.mf_score.toFixed(0)}`, recency: asof });
    if (sm.signal.deals_score != null)
      signals.push({ source: "PRO", label: "Institutional flow", direction: dirFromScore(sm.signal.deals_score), strength: Math.round(Math.abs(sm.signal.deals_score)), note: `Bulk/block prints score ${sm.signal.deals_score.toFixed(0)}`, recency: asof });
    if (sm.signal.delivery_score != null)
      signals.push({ source: "RET", label: "Retail delivery", direction: dirFromScore(sm.signal.delivery_score), strength: Math.round(Math.abs(sm.signal.delivery_score)), note: `Delivery % score ${sm.signal.delivery_score.toFixed(0)}`, recency: asof });
    if (sm.signal.pms_score != null)
      signals.push({ source: "INS", label: "PMS holdings", direction: dirFromScore(sm.signal.pms_score), strength: Math.round(Math.abs(sm.signal.pms_score)), note: `PMS score ${sm.signal.pms_score.toFixed(0)}`, recency: asof });
    if (sm.signal.aif_score != null)
      signals.push({ source: "DII", label: "AIF activity", direction: dirFromScore(sm.signal.aif_score), strength: Math.round(Math.abs(sm.signal.aif_score)), note: `AIF score ${sm.signal.aif_score.toFixed(0)}`, recency: asof });
  }
  if (ns && ns.score != null) {
    signals.push({
      source: "NEWS",
      label: "News sentiment",
      direction: dirFromScore(ns.score),
      strength: Math.round(Math.abs(ns.score)),
      note: ns.sentiment ? `${ns.sentiment[0].toUpperCase()}${ns.sentiment.slice(1)} coverage` : "Recent coverage",
      recency: ns.analyzed_at,
    });
  }
  if (techSignal) {
    signals.push({
      source: "TECH",
      label: "Technical setup",
      direction: techSignal.direction,
      strength: techSignal.strength,
      note: techSignal.label,
      recency: null,
    });
  }
  if (pcr && pcr.available && pcr.pcr != null) {
    const v = pcr.pcr;
    let direction: SignalDirection = "neutral";
    if (v > 1.2) direction = "distributing";
    else if (v < 0.8) direction = "accumulating";
    const strength = Math.min(100, Math.round(Math.abs(v - 1.0) * 100));
    signals.push({
      source: "OPT",
      label: "Options skew",
      direction,
      strength,
      note: `Put/Call ratio ${v.toFixed(2)}`,
      recency: null,
    });
  }

  if (peTtm != null && peers?.peers) {
    const peerPes = peers.peers
      .filter(p => !p.is_self && p.pe_ratio != null)
      .map(p => p.pe_ratio!)
      .sort((a, b) => a - b);
    const medianPe = peerPes.length ? peerPes[Math.floor(peerPes.length / 2)] : null;
    if (medianPe != null && medianPe > 0) {
      const ratio = peTtm / medianPe;
      let direction: SignalDirection = "neutral";
      let strength = Math.min(100, Math.round(Math.abs(ratio - 1) * 100));
      let dirLabel = "In line";
      if (ratio < 0.7) { direction = "accumulating"; dirLabel = "Discount"; }
      else if (ratio > 1.5) { direction = "distributing"; dirLabel = "Premium"; }
      signals.push({
        source: "VAL",
        label: "Valuation vs peers",
        direction,
        strength,
        note: `P/E ${peTtm.toFixed(0)}× vs peer median ${medianPe.toFixed(0)}×`,
        recency: null,
        dirLabel,
      });
    }
  }

  return { composite, signals };
}

export function ConvictionMeter({ composite }: { composite: number | null }) {
  if (composite === null) return null;
  const valColor = composite < 0 ? "var(--system-red)" : composite > 0 ? "var(--system-green)" : "var(--label-tertiary)";
  const needleColor = composite < 0 ? "var(--system-red)" : composite > 0 ? "var(--system-green)" : "var(--label-secondary)";
  const label =
    composite > 25 ? "Lean Buy"
    : composite < -25 ? "Lean Sell"
    : "Mixed";

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 8 }}>
        <span style={{
          fontSize: 11, fontWeight: 600, color: "var(--label-tertiary)",
          textTransform: "uppercase", letterSpacing: "0.08em",
        }}>
          Signal Conviction
        </span>
        <span style={{
          fontFamily: "var(--font-mono)", fontSize: 13, fontWeight: 700,
          color: valColor,
        }}>
          {label} · {composite > 0 ? "+" : ""}{composite}
        </span>
      </div>
      <div style={{ position: "relative", height: 10, borderRadius: 99, overflow: "hidden", display: "flex" }}>
        <div style={{ flex: 1, background: "var(--system-red)", opacity: 0.15 }} />
        <div style={{ flex: 1, background: "var(--label-quaternary)", opacity: 0.3 }} />
        <div style={{ flex: 1, background: "var(--system-green)", opacity: 0.15 }} />
        <div style={{ position: "absolute", left: "33.33%", top: 0, bottom: 0, width: 1, background: "var(--bg-primary)", opacity: 0.5 }} />
        <div style={{ position: "absolute", left: "66.67%", top: 0, bottom: 0, width: 1, background: "var(--bg-primary)", opacity: 0.5 }} />
        <div style={{
          position: "absolute",
          left: `${Math.max(2, Math.min(98, ((composite ?? 0) + 100) / 200 * 100))}%`,
          top: -1, bottom: -1,
          width: 4, borderRadius: 2,
          background: needleColor,
          transform: "translateX(-50%)",
          boxShadow: "var(--shadow-sm)",
        }} />
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", marginTop: 6, fontSize: 10, fontWeight: 500 }}>
        <span style={{ color: "var(--system-red)" }}>Sell</span>
        <span style={{ color: "var(--label-tertiary)" }}>Neutral</span>
        <span style={{ color: "var(--system-green)" }}>Buy</span>
      </div>
    </div>
  );
}

const SOURCE_BADGE_COLORS: Record<string, string> = {
  MF:   "var(--system-teal)",
  PRO:  "var(--system-orange)",
  RET:  "var(--system-yellow)",
  INS:  "var(--system-green)",
  DII:  "var(--system-purple)",
  NEWS: "var(--system-blue)",
  TECH: "var(--system-blue)",
  OPT:  "var(--system-purple)",
  VAL:  "var(--system-teal)",
};

function SignalCard({ s, onClick }: { s: SignalRow; onClick?: () => void }) {
  const dir = s.direction;
  const accent =
    dir === "accumulating" ? "var(--system-green)"
    : dir === "distributing" ? "var(--system-red)"
    : "var(--label-quaternary)";
  const arrow = dir === "accumulating" ? "↑" : dir === "distributing" ? "↓" : "→";
  const dirText = s.dirLabel ?? (dir === "accumulating" ? "BUYING" : dir === "distributing" ? "SELLING" : "NEUTRAL");
  const dirColor =
    dir === "accumulating" ? "var(--system-green)"
    : dir === "distributing" ? "var(--system-red)"
    : "var(--label-tertiary)";
  const badgeColor = SOURCE_BADGE_COLORS[s.source] || "var(--label-secondary)";

  return (
    <div
      onClick={onClick}
      style={{
        borderLeft: `3px solid ${accent}`,
        borderTop: "1px solid var(--separator-light)",
        borderRight: "1px solid var(--separator-light)",
        borderBottom: "1px solid var(--separator-light)",
        borderRadius: 8,
        padding: "10px 12px",
        background: "var(--bg-primary)",
        boxShadow: "var(--shadow-sm)",
        display: "flex",
        flexDirection: "column",
        gap: 4,
        cursor: onClick ? "pointer" : undefined,
      }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span style={{
          fontFamily: "var(--font-mono)",
          fontSize: 10.5, fontWeight: 600,
          letterSpacing: "0.04em",
          color: badgeColor,
          padding: "2px 6px",
          background: "var(--bg-secondary)",
          borderRadius: 4,
        }}>{s.source}</span>
        <span style={{ fontSize: 11, color: "var(--label-tertiary)", fontFamily: "var(--font-mono)" }}>
          {s.recency ? fmtRecency(s.recency) : "—"}
        </span>
      </div>
      <div style={{ fontSize: 13, fontWeight: 600, color: "var(--label-primary)", marginTop: 4 }}>
        {s.label}
      </div>
      <div style={{ display: "flex", gap: 8, alignItems: "baseline", flexWrap: "wrap" }}>
        <span style={{ fontSize: 11, fontWeight: 700, letterSpacing: "0.05em", color: dirColor }}>
          {arrow} {dirText}
        </span>
        <span style={{ fontSize: 11.5, color: "var(--label-secondary)" }}>{s.note}</span>
      </div>
      <div style={{ marginTop: 6, height: 3, background: "var(--bg-secondary)", borderRadius: 99, overflow: "hidden" }}>
        <div style={{ height: "100%", width: `${Math.min(100, s.strength)}%`, background: accent, borderRadius: 99 }} />
      </div>
    </div>
  );
}

export function SignalCards({ signals, onCardClick }: { signals: SignalRow[]; onCardClick?: (source: string) => void }) {
  if (!signals.length) return null;
  return (
    <div>
      <div style={{
        fontSize: 11, fontWeight: 600, color: "var(--label-tertiary)",
        textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 10,
        display: "flex", justifyContent: "space-between", alignItems: "center",
      }}>
        <span>Smart Money Breakdown</span>
        <span style={{ textTransform: "none", letterSpacing: 0, fontSize: 11, fontWeight: 400, color: "var(--label-tertiary)" }}>
          {signals.length} sources
        </span>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
        {signals.map((s, i) => <SignalCard key={`${s.source}-${i}`} s={s} onClick={onCardClick ? () => onCardClick(s.source) : undefined} />)}
      </div>
    </div>
  );
}

export function ValuationCard({ f }: { f: Fundamentals }) {
  const pe = f.pe_ratio ?? f.ttm_pe;
  let pos = 50;
  let tag: { label: string; bg: string; color: string } = {
    label: "Fair", bg: "var(--fill-orange)", color: "var(--system-orange)",
  };
  if (pe == null || pe <= 0) { pos = 92; tag = { label: "Loss / N/A", bg: "var(--fill-red)", color: "var(--system-red)" }; }
  else if (pe < 15) { pos = 18; tag = { label: "Undervalued", bg: "var(--fill-green)", color: "var(--system-green)" }; }
  else if (pe < 25) { pos = 45; tag = { label: "Fair", bg: "var(--fill-orange)", color: "var(--system-orange)" }; }
  else if (pe < 40) { pos = 75; tag = { label: "Overvalued", bg: "var(--fill-red)", color: "var(--system-red)" }; }
  else { pos = 92; tag = { label: "Overvalued", bg: "var(--fill-red)", color: "var(--system-red)" }; }

  const zoneColor = pos < 35 ? "var(--system-green)" : pos < 65 ? "var(--system-orange)" : "var(--system-red)";

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
        <span style={{
          fontSize: 11, fontWeight: 600, color: "var(--label-tertiary)",
          textTransform: "uppercase", letterSpacing: "0.08em",
        }}>Valuation</span>
        <span style={{
          fontSize: 11, fontWeight: 600,
          padding: "3px 9px", borderRadius: 99,
          background: tag.bg, color: tag.color,
        }}>{tag.label}</span>
      </div>
      <div style={{ position: "relative", height: 10, borderRadius: 99, overflow: "hidden" }}>
        <div style={{
          position: "absolute", inset: 0,
          background: "linear-gradient(90deg, var(--system-green) 0%, var(--system-orange) 45%, var(--system-red) 100%)",
          opacity: 0.7,
        }} />
        <div style={{
          position: "absolute", top: -3, left: `${pos}%`, transform: "translateX(-50%)",
          width: 16, height: 16, borderRadius: 99,
          background: "var(--bg-primary)", border: `2.5px solid ${zoneColor}`,
        }} />
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", marginTop: 6, fontSize: 10, fontWeight: 500 }}>
        <span style={{ color: "var(--system-green)" }}>Undervalued</span>
        <span style={{ color: "var(--label-tertiary)" }}>Fair</span>
        <span style={{ color: "var(--system-red)" }}>Overvalued</span>
      </div>
      <div style={{
        display: "flex", gap: 18, marginTop: 12,
        paddingTop: 10, borderTop: "1px solid var(--separator-light)",
      }}>
        <Stat k="PE" v={pe != null && pe > 0 ? pe.toFixed(2) : "—"} />
        <Stat k="PB" v={f.pb_ratio != null ? f.pb_ratio.toFixed(2) : "—"} />
        <Stat k="D/E" v={f.debt_to_equity != null ? f.debt_to_equity.toFixed(2) : "—"} />
        {f.roe != null && <Stat k="ROE" v={`${(f.roe * 100).toFixed(1)}%`} />}
      </div>
    </div>
  );
}

function Stat({ k, v }: { k: string; v: string }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
      <span style={{ fontSize: 10, color: "var(--label-tertiary)", fontWeight: 500, textTransform: "uppercase", letterSpacing: "0.04em" }}>{k}</span>
      <span style={{ fontFamily: "var(--font-mono)", fontSize: 13, fontWeight: 600, color: "var(--label-primary)" }}>{v}</span>
    </div>
  );
}

export function RiskFlags({ fundamentals }: { fundamentals: Fundamentals | null | undefined }) {
  const flags = riskFromFundamentals(fundamentals);
  if (!flags.length) return null;
  return (
    <div>
      <div style={{
        fontSize: 11, fontWeight: 600, color: "var(--label-tertiary)",
        textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 8,
      }}>Risk Flags</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {flags.map((rf, i) => {
          const sev = SEV_COLORS[rf.severity];
          return (
            <div key={i} style={{
              padding: "10px 12px",
              borderRadius: 10,
              background: sev.bg,
              boxShadow: "var(--shadow-sm)",
            }}>
              <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, fontWeight: 600, color: sev.color }}>
                <span style={{ fontSize: 14 }}>{rf.icon}</span>
                {rf.label}
              </div>
              <div style={{ fontSize: 11, color: "var(--label-secondary)", marginTop: 3, lineHeight: 1.4 }}>
                {rf.description}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

const SEV_COLORS: Record<string, { bg: string; color: string }> = {
  red:   { bg: "var(--fill-red)",    color: "var(--system-red)" },
  amber: { bg: "var(--fill-orange)", color: "var(--system-orange)" },
  blue:  { bg: "var(--fill-green)",  color: "var(--system-green)" },
};

function riskFromFundamentals(f: Fundamentals | null | undefined): Array<{
  severity: "red" | "amber" | "blue";
  label: string;
  description: string;
  icon: string;
}> {
  if (!f) return [];
  const flags: Array<{ severity: "red" | "amber" | "blue"; label: string; description: string; icon: string }> = [];
  const pe = f.pe_ratio ?? f.ttm_pe;
  if (f.debt_to_equity != null && f.debt_to_equity > 2)
    flags.push({ severity: "red", label: `High D/E ${f.debt_to_equity.toFixed(1)}x`, icon: "⚠",
      description: `Debt-to-equity of ${f.debt_to_equity.toFixed(1)}x indicates high leverage risk` });
  if (f.net_profit_margin != null && f.net_profit_margin < 0)
    flags.push({ severity: "red", label: "Negative net margin", icon: "⚠",
      description: `Net margin at ${(f.net_profit_margin * 100).toFixed(1)}% — company is loss-making` });
  if (pe != null && pe > 50)
    flags.push({ severity: "amber", label: `Elevated P/E`, icon: "▲",
      description: `P/E of ${pe.toFixed(1)} — significantly above typical market range` });
  if (f.pb_ratio != null && f.pb_ratio > 8)
    flags.push({ severity: "amber", label: `PB ${f.pb_ratio.toFixed(1)}x`, icon: "▲",
      description: `Price-to-book of ${f.pb_ratio.toFixed(1)}x suggests premium valuation` });
  if (pe != null && pe > 0 && pe < 15)
    flags.push({ severity: "blue", label: `Attractive P/E`, icon: "✓",
      description: `P/E of ${pe.toFixed(0)}x indicates potential undervaluation` });
  if (f.roe != null && f.roe > 0.15)
    flags.push({ severity: "blue", label: `Strong ROE ${(f.roe * 100).toFixed(0)}%`, icon: "✓",
      description: `Return on equity of ${(f.roe * 100).toFixed(0)}% shows efficient capital use` });
  if (f.revenue_growth_1y != null && f.revenue_growth_1y > 0.2)
    flags.push({ severity: "blue", label: `Rev growth ${(f.revenue_growth_1y * 100).toFixed(0)}%`, icon: "✓",
      description: `Revenue grew ${(f.revenue_growth_1y * 100).toFixed(0)}% year-over-year` });
  if (f.promoter_holding != null && f.promoter_holding < 25)
    flags.push({ severity: "amber", label: `Low promoter ${f.promoter_holding.toFixed(0)}%`, icon: "▲",
      description: `Promoter holding at ${f.promoter_holding.toFixed(0)}% — low skin in the game` });
  if (f.promoter_holding != null && f.promoter_holding > 60)
    flags.push({ severity: "blue", label: `High promoter ${f.promoter_holding.toFixed(0)}%`, icon: "✓",
      description: `Promoter holding at ${f.promoter_holding.toFixed(0)}% shows strong insider alignment` });
  return flags.slice(0, 5);
}

/**
 * Default DecisionBlock — backwards compatible. Renders all sub-components stacked.
 * Prefer the named exports + `useDecisionData` hook for custom layouts.
 */
export default function DecisionBlock({
  symbol,
  fundamentals,
  techSignal,
}: {
  symbol: string;
  fundamentals?: Fundamentals | null;
  techSignal?: TechSignal | null;
}) {
  const peTtm = fundamentals ? (fundamentals.ttm_pe ?? fundamentals.pe_ratio ?? null) : null;
  const { composite, signals } = useDecisionData(symbol, techSignal, peTtm);
  if (composite === null && signals.length === 0 && !fundamentals) return null;
  return (
    <div style={{ borderTop: "0.5px solid var(--separator-light)", paddingTop: 14, marginTop: 8, display: "flex", flexDirection: "column", gap: 14 }}>
      <ConvictionMeter composite={composite} />
      <SignalCards signals={signals} />
      {fundamentals && <ValuationCard f={fundamentals} />}
      <RiskFlags fundamentals={fundamentals} />
    </div>
  );
}
