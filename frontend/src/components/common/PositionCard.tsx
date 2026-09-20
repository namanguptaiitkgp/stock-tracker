"use client";

import React, { useState } from "react";
import { usePrivacyMode } from "@/lib/privacy-mode";
import { pctStr } from "@/lib/format";
import NarrativeStaleChip from "@/components/ui/NarrativeStaleChip";
import SectionCard, {
  SECTION_VERDICT_STYLE,
  SignalRow,
  MetricRow,
  FootStat,
  newsFreshnessLabel,
} from "./SectionCard";
import {
  IconChartCandle, IconUsersGroup, IconNews,
  IconAlertTriangle, IconTrendingDown, IconInfoCircle,
  IconCircleCheck, IconBuildingFactory2,
  IconArrowRight, IconChevronDown,
} from "@tabler/icons-react";

export interface HoldingAction {
  symbol: string;
  exchange: string;
  quantity: number;
  average_price: number;
  last_price: number;
  pnl: number;
  pnl_pct: number;
  day_pnl: number;
  day_change_pct: number;
  action: "SELL" | "ACCUMULATE" | "WATCHFUL" | "HOLD";
  confidence: number | null;
  reasoning: string;
  analyzed_at: string | null;
  news_sentiment?: string | null;
  news_score?: number | null;
  smart_money_composite?: number | null;
  high_conviction?: boolean;
  market_cap?: number | null;
  signals?: Array<{
    source: "FII" | "DII" | "MF" | "INS" | "PRO" | "RET";
    direction: "accumulating" | "distributing" | "neutral";
    recency?: string | null;
    strength?: number;
    label?: string;
  }>;
  risks?: Array<{ severity: "high" | "med" | "low"; label: string; sublabel?: string | null }>;
  strengths?: Array<{ label: string; sublabel?: string | null }>;
  reviewed_at?: string | null;
  valuation_section?: {
    verdict: string;
    score: number | null;
    signals: Array<{ label: string; direction: string }> | null;
    hard_failed: string[] | null;
    last_run_at?: string | null;
  } | null;
  peer_section?: {
    verdict: string;
    metric_breakdown: Array<{ metric: string; stock_value: number; peer_median: number; status: string }> | null;
    peer_summary: string | null;
    peer_count: number | null;
    peer_set_weak: boolean;
    last_run_at?: string | null;
    peers_generated_at?: string | null;
    peers_top5?: Array<{ symbol: string; name: string | null }> | null;
  } | null;
  news_section?: {
    verdict: string;
    stock_signals: Array<{ label: string; direction: string }> | null;
    source_count: number | null;
    qualitative?: {
      company_overview?: string;
      overall_sentiment?: string;
      bull_case?: string[];
      bear_case?: string[];
      earnings_highlights?: string;
    } | null;
    sector_mood: string | null;
    // Resolved canonical sector name (e.g. "Banking" / "Technology") —
    // used to label the sector-mood chip and as the navigation target
    // when the chip is clicked.
    sector?: string | null;
    last_run_at?: string | null;
    // Newest cached headline pub_date (YYYY-MM-DD). Truthful "this is how
    // fresh the news data is" — drives the freshness label below.
    newest_headline_at?: string | null;
  } | null;
  act_now_score?: number | null;
  summary_line?: string | null;
  // True when the AI verdict contradicts the majority of passed
  // rule-based fundamental strategies. Surfaced in the chip row via a
  // dedicated `STRAT ↯` chip — see plan §D2.5.
  strategies_diverge?: boolean | null;
  // True when the deep-analysis narrative was generated against a
  // fundamentals snapshot more than 24h older than the current one. The
  // rules card next to the narrative will evaluate against the new
  // numbers; flag this so the chip row can warn rather than silently
  // present two conflicting values.
  narrative_stale?: boolean | null;
  narrative_fund_lag_hours?: number | null;
}

type Verdict = "ACT_NOW" | "BUY" | "REVIEW" | "HOLD";

const VERDICT_MAP: Record<HoldingAction["action"], { v: Verdict; icon: string; text: string; cssVar: string; cssBg: string }> = {
  SELL:       { v: "ACT_NOW", icon: "●", text: "ACT NOW", cssVar: "var(--act)",    cssBg: "var(--act-bg)" },
  ACCUMULATE: { v: "BUY",     icon: "▲", text: "BUY",     cssVar: "var(--buy)",    cssBg: "var(--buy-bg)" },
  WATCHFUL:   { v: "REVIEW",  icon: "◆", text: "REVIEW",  cssVar: "var(--review)", cssBg: "var(--review-bg)" },
  HOLD:       { v: "HOLD",    icon: "■", text: "HOLD",    cssVar: "var(--hold)",   cssBg: "var(--hold-bg)" },
};

const ACTION_LABEL: Record<HoldingAction["action"], string> = {
  SELL:       "Reduce position",
  ACCUMULATE: "Buy on dip",
  WATCHFUL:   "Re-evaluate",
  HOLD:       "View details",
};

function fmtINR(n: number): string {
  const sign = n < 0 ? "-" : "";
  const abs = Math.abs(n);
  if (abs >= 10_000_000) return `${sign}₹${(abs / 10_000_000).toFixed(2)} Cr`;
  if (abs >= 100_000)    return `${sign}₹${(abs / 100_000).toFixed(2)} L`;
  if (abs >= 1000)       return `${sign}₹${(abs / 1000).toFixed(1)}K`;
  return `${sign}₹${abs.toFixed(0)}`;
}

function fmtAge(iso: string | null | undefined): string {
  if (!iso) return "—";
  const t = new Date(iso).getTime();
  if (isNaN(t)) return "—";
  const sec = (Date.now() - t) / 1000;
  if (sec < 60) return "now";
  if (sec < 3600) return `${Math.round(sec / 60)}m`;
  if (sec < 86400) return `${Math.round(sec / 3600)}h`;
  if (sec < 86400 * 14) return `${Math.round(sec / 86400)}d`;
  return `${Math.round(sec / (86400 * 7))}w`;
}

// ---------- VerdictBadge ----------
export function VerdictBadge({ action, score }: { action: HoldingAction["action"]; score: number | null }) {
  const m = VERDICT_MAP[action];
  const urgencyTooltip = score != null
    ? `Urgency score ${score} / 100 — combined signal from fundamentals, price action, and risk flags.`
    : undefined;
  return (
    <div
      title={urgencyTooltip}
      style={{
        display: "inline-flex", alignItems: "center", gap: 0,
        borderRadius: 8, overflow: "hidden",
        border: `1px solid ${m.cssVar}`,
        flexShrink: 0,
        fontWeight: 700, fontSize: 12,
        cursor: urgencyTooltip ? "help" : undefined,
      }}
    >
      <span style={{ padding: "0 8px", fontSize: 10, color: m.cssVar, background: m.cssBg, height: 28, display: "inline-flex", alignItems: "center" }}>
        {m.icon}
      </span>
      <span style={{ padding: "6px 9px", letterSpacing: "0.06em", color: m.cssVar, background: m.cssBg }}>
        {m.text}
      </span>
      {score != null && (
        <span
          aria-label={`Urgency ${score} of 100`}
          style={{
            padding: "6px 10px",
            background: m.cssVar,
            color: "white",
            fontFamily: "var(--font-mono)", fontSize: 11, fontWeight: 600,
            display: "inline-flex", alignItems: "center", gap: 4,
          }}
        >
          <span style={{ opacity: 0.75, fontSize: 9, fontWeight: 500, letterSpacing: "0.04em", textTransform: "uppercase" }}>urg</span>
          {score}
        </span>
      )}
    </div>
  );
}

// ---------- Risk / Strength chips ----------
const RISK_BG: Record<"high" | "med" | "low", { bg: string; color: string }> = {
  high: { bg: "var(--act-bg)",    color: "var(--act)" },
  med:  { bg: "var(--review-bg)", color: "var(--review)" },
  low:  { bg: "var(--bg-secondary)", color: "var(--label-secondary)" },
};

export function RiskChip({ r }: { r: { severity: "high" | "med" | "low"; label: string; sublabel?: string | null } }) {
  const c = RISK_BG[r.severity];
  return (
    <div style={{
      display: "inline-flex", gap: 9, alignItems: "flex-start",
      padding: "9px 12px", borderRadius: 8,
      background: c.bg, color: c.color,
      fontSize: 12.5,
    }}>
      <IconAlertTriangle size={13} style={{ flexShrink: 0, opacity: 0.85, marginTop: 2 }} />
      <div style={{ display: "flex", flexDirection: "column", gap: 2, minWidth: 0 }}>
        <span style={{ fontWeight: 600, lineHeight: 1.35, fontSize: 13 }}>{r.label}</span>
        {r.sublabel && (
          <span title={r.sublabel} style={{ color: c.color, opacity: 0.85, fontSize: 12, lineHeight: 1.35 }}>{r.sublabel}</span>
        )}
      </div>
    </div>
  );
}

export function StrengthChip({ s }: { s: { label: string; sublabel?: string | null } }) {
  return (
    <div style={{
      display: "inline-flex", gap: 9, alignItems: "flex-start",
      padding: "9px 12px", borderRadius: 8,
      background: "var(--buy-bg)", color: "var(--buy)",
      fontSize: 12.5,
    }}>
      <IconCircleCheck size={13} style={{ flexShrink: 0, opacity: 0.85, marginTop: 2 }} />
      <div style={{ display: "flex", flexDirection: "column", gap: 2, minWidth: 0 }}>
        <span style={{ fontWeight: 600, lineHeight: 1.35, fontSize: 13 }}>{s.label}</span>
        {s.sublabel && (
          <span title={s.sublabel} style={{ color: "var(--buy)", opacity: 0.85, fontSize: 12, lineHeight: 1.35 }}>{s.sublabel}</span>
        )}
      </div>
    </div>
  );
}

// ---------- SignalDot ----------
export function SignalDot({ src, direction, recency }: { src: string; direction: "accumulating" | "distributing" | "neutral"; recency?: string | null }) {
  const arrow = direction === "accumulating" ? "↑" : direction === "distributing" ? "↓" : "→";
  const color =
    direction === "accumulating" ? "var(--buy)"
    : direction === "distributing" ? "var(--act)"
    : "var(--label-secondary)";

  // `recency` carries one of two encodings:
  //   - YYYY-MM-DD (date only) — used by NEWS chips, render as state label
  //     ("today" / "3d" / "stale") so we don't pretend a 24h-old article is "4h ago".
  //   - Full ISO timestamp — used by SM/FII/MF chips, render relative ago via fmtAge.
  const isDateOnly = typeof recency === "string" && /^\d{4}-\d{2}-\d{2}$/.test(recency);
  let recencyText: string;
  if (isDateOnly) {
    const label = newsFreshnessLabel(recency);
    // Strip the "news " / "quiet " prefix — chip context already says NEWS.
    recencyText = label.text.replace(/^news\s/, "").replace(/^quiet\s/, "quiet ");
  } else {
    recencyText = fmtAge(recency);
  }
  return (
    <div style={{
      display: "inline-flex", alignItems: "center", gap: 6,
      padding: "5px 10px", borderRadius: 6,
      background: "var(--bg-secondary)",
      border: "1px solid var(--separator-light)",
      fontSize: 12,
    }} title={`${src}: ${direction} (${recencyText})`}>
      <span style={{ fontFamily: "var(--font-mono)", fontWeight: 600, color: "var(--label-tertiary)", fontSize: 11, letterSpacing: "0.05em" }}>{src}</span>
      <span style={{ color, fontWeight: 700, fontSize: 13 }}>{arrow}</span>
      <span style={{ fontFamily: "var(--font-mono)", color: "var(--label-tertiary)", fontSize: 11.5 }}>{recencyText}</span>
    </div>
  );
}

// ---------- Strategy-divergence chip ----------
// Surfaced when `holding.strategies_diverge === true`. Amber/REVIEW
// colour family + lightning glyph signal "AI verdict disagrees with
// rule-based strategies". Same visual weight as a SignalDot so it sits
// naturally in the existing chip row. See plan §D2.5.
function StratDivergeChip() {
  return (
    <div
      style={{
        display: "inline-flex", alignItems: "center", gap: 6,
        padding: "5px 10px", borderRadius: 6,
        background: "var(--review-bg)",
        border: "1px solid color-mix(in srgb, var(--review) 35%, transparent)",
        fontSize: 12,
      }}
      title="AI verdict diverges from rule-based strategies"
    >
      <span style={{ fontFamily: "var(--font-mono)", fontWeight: 600, color: "var(--review)", fontSize: 11, letterSpacing: "0.05em" }}>STRAT</span>
      <span style={{ color: "var(--review)", fontWeight: 700, fontSize: 13 }}>↯</span>
      <span style={{ fontFamily: "var(--font-mono)", color: "var(--review)", fontSize: 11.5 }}>diverge</span>
    </div>
  );
}

// NarrativeStaleChip lives in @/components/ui/NarrativeStaleChip — extracted
// so the StockDetailPanel tabs can reuse it without duplicating the
// component definition.
//
// SectionCard + SignalRow + MetricRow + FootStat + SECTION_VERDICT_STYLE
// + newsFreshnessLabel now live in ./SectionCard so OpportunityCard and
// ResearchingCard can reuse the same primitives.

// ---------- PositionCard ----------
interface CardProps {
  h: HoldingAction;
  companyName?: string;
  onClickAction?: (h: HoldingAction) => void;
  onClickSymbol?: (h: HoldingAction) => void;
  onReview?: (h: HoldingAction) => void;
  onRefreshSections?: (h: HoldingAction) => void;
  sectionRefreshing?: boolean;
  pipelineRunning?: boolean;
  onComparePeers?: (h: HoldingAction) => void;
  onReadSources?: (h: HoldingAction) => void;
}

export default function PositionCard({
  h, companyName, onClickAction, onClickSymbol, onReview,
  onRefreshSections, sectionRefreshing, pipelineRunning,
  onComparePeers, onReadSources,
}: CardProps) {
  const [expanded, setExpanded] = useState(false);
  const isUrgent = h.action === "SELL";
  const mask = usePrivacyMode();
  const masked = (v: string) => (mask ? "••••" : v);
  const m = VERDICT_MAP[h.action];

  const reasoning = h.reasoning || "";
  const firstSentence = reasoning.split(/(?<=[.!?])\s/)[0] || reasoning;
  const headline = firstSentence.length > 0 ? firstSentence : "Awaiting analysis";

  const isPlPositive = h.pnl >= 0;

  const sectionRefresh = pipelineRunning ? undefined : () => onRefreshSections?.(h);

  return (
    <article
      id={`pcard-${h.symbol}`}
      style={{
        background: isUrgent
          ? "linear-gradient(180deg, var(--act-bg) 0%, var(--bg-primary) 30%)"
          : "var(--bg-primary)",
        border: `1px solid ${isUrgent ? "var(--act-edge)" : "var(--separator-light)"}`,
        borderRadius: 12,
        padding: 24,
        marginBottom: 14,
        boxShadow: isUrgent
          ? "var(--shadow-md), 0 0 0 4px color-mix(in srgb, var(--act) 8%, transparent)"
          : "var(--shadow-sm)",
        transition: "border-color .15s, box-shadow .15s, opacity .2s",
        opacity: h.reviewed_at ? 0.55 : 1,
      }}
    >
      {/* Header row */}
      <header className="pcard-header" style={{
        display: "flex", justifyContent: "space-between", alignItems: "flex-start",
        gap: 16, flexWrap: "wrap",
      }}>
        <div style={{ display: "flex", gap: 16, alignItems: "flex-start", flexWrap: "wrap" }}>
          <VerdictBadge action={h.action} score={h.act_now_score ?? h.confidence} />
          <div
            style={{ display: "flex", flexDirection: "column", cursor: onClickSymbol ? "pointer" : "default" }}
            onClick={() => onClickSymbol?.(h)}
          >
            <div style={{
              fontFamily: "var(--font-serif)", fontSize: 22, fontWeight: 700,
              letterSpacing: "-0.015em", lineHeight: 1.1, color: "var(--label-primary)",
            }}>
              {h.symbol}
            </div>
            {companyName && (
              <div style={{ fontSize: 13, color: "var(--label-tertiary)", marginTop: 3 }}>
                {companyName}
              </div>
            )}
          </div>
        </div>

        <div className="pcard-actions" style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <div style={{ textAlign: "right", lineHeight: 1.2 }}>
            <div style={{
              fontFamily: "var(--font-mono)", fontSize: 15, fontWeight: 500,
              color: isPlPositive ? "var(--buy)" : "var(--act)",
            }}>
              {pctStr(h.pnl_pct)}
            </div>
            <div style={{
              fontFamily: "var(--font-mono)", fontSize: 12,
              color: isPlPositive ? "var(--buy)" : "var(--act)",
            }}>
              {masked(`${h.pnl >= 0 ? "+" : ""}${fmtINR(h.pnl)}`)}
            </div>
          </div>
          {onReview && (
            <button
              onClick={() => onReview(h)}
              title={h.reviewed_at ? "Mark as unreviewed" : "Mark as reviewed"}
              style={{
                display: "inline-flex", alignItems: "center", gap: 5,
                background: h.reviewed_at ? "var(--buy-bg)" : "var(--bg-primary)",
                color: h.reviewed_at ? "var(--buy)" : "var(--label-tertiary)",
                border: `1px solid ${h.reviewed_at ? "var(--buy)" : "var(--separator-light)"}`,
                borderRadius: 999, padding: "6px 11px",
                fontSize: 11, cursor: "pointer", flexShrink: 0, whiteSpace: "nowrap",
              }}
            >
              <IconCircleCheck size={13} />
              {h.reviewed_at ? "Reviewed" : "Mark reviewed"}
            </button>
          )}
          <button
            onClick={() => onClickAction?.(h)}
            style={{
              background: isUrgent ? "var(--act)" : "var(--label-primary)",
              color: "white",
              border: 0,
              padding: "8px 14px", borderRadius: 10,
              fontSize: 13, fontWeight: 500, cursor: "pointer",
              display: "inline-flex", alignItems: "center", gap: 6,
              boxShadow: isUrgent
                ? `0 1px 0 color-mix(in srgb, var(--act) 70%, black), 0 4px 12px color-mix(in srgb, var(--act) 30%, transparent)`
                : "none",
            }}
          >
            {ACTION_LABEL[h.action]} <IconArrowRight size={14} />
          </button>
        </div>
      </header>

      {/* Headline (serif, with quote-style left border) */}
      <div style={{
        marginTop: 16,
        fontFamily: "var(--font-serif)", fontSize: 15, lineHeight: 1.45,
        color: "var(--label-primary)", fontWeight: 500,
        paddingLeft: 12, padding: "2px 0 2px 12px",
        borderLeft: `3px solid ${isUrgent ? "var(--act)" : "var(--label-quaternary)"}`,
      }}>
        {h.reasoning || h.summary_line || headline}
      </div>

      {/* Three-column section grid */}
      {(h.valuation_section || (h.peer_section && h.peer_section.verdict !== "NO_DATA") || h.news_section) && (
        <div className="pcard-section-grid" style={{
          display: "grid",
          gridTemplateColumns: `repeat(${[h.valuation_section, h.peer_section && h.peer_section.verdict !== "NO_DATA", h.news_section].filter(Boolean).length}, minmax(0, 1fr))`,
          gap: 10, marginTop: 16,
        }}>
          {/* Price section */}
          {h.valuation_section && (
            <SectionCard
              icon={<IconChartCandle size={14} />}
              title="Price"
              verdict={h.valuation_section.verdict}
              age={fmtAge(h.valuation_section.last_run_at || h.analyzed_at)}
              onRefresh={sectionRefresh}
              refreshing={sectionRefreshing}
              footer={
                <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 4 }}>
                  <FootStat label="QTY" value={mask ? "••" : String(h.quantity)} />
                  <FootStat label="AVG" value={masked(Math.round(h.average_price).toString())} />
                  <FootStat label="LTP" value={masked(h.last_price.toFixed(1))} />
                  <FootStat label="DAY" value={pctStr(h.day_change_pct)} color={h.day_change_pct >= 0 ? "var(--buy)" : "var(--act)"} />
                </div>
              }
            >
              {(h.valuation_section.signals || []).slice(0, 3).map((s, i) => (
                <SignalRow key={i} label={s.label} color={s.direction === "negative" || s.direction === "red" ? "red" : s.direction === "positive" || s.direction === "green" ? "green" : "neutral"} icon={<IconAlertTriangle size={11} />} />
              ))}
              {(h.risks || []).slice(0, 2).map((r, i) => (
                <SignalRow key={`r${i}`} label={r.label} color={r.severity === "high" ? "red" : r.severity === "med" ? "neutral" : "green"} icon={<IconAlertTriangle size={11} />} />
              ))}
              {!(h.valuation_section.signals?.length) && !(h.risks?.length) && (
                <div style={{ fontSize: 12, color: "var(--label-tertiary)", padding: "7px 0" }}>No signals</div>
              )}
            </SectionCard>
          )}

          {/* Peers section */}
          {h.peer_section && h.peer_section.verdict !== "NO_DATA" && (
            <SectionCard
              icon={<IconUsersGroup size={14} />}
              title="Peers"
              verdict={h.peer_section.verdict}
              age={fmtAge(h.peer_section.last_run_at || h.analyzed_at)}
              onRefresh={sectionRefresh}
              refreshing={sectionRefreshing}
              footer={
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                  <span style={{ fontSize: 10, color: "var(--label-quaternary)" }}>
                    {(() => {
                      const breakdown = h.peer_section!.metric_breakdown || [];
                      const lagCount = breakdown.filter(mb => mb.status === "lag").length;
                      const base = lagCount > 0 ? `Behind on ${lagCount} of ${breakdown.length}` : `${h.peer_section!.peer_count || 0} peers matched`;
                      // Append "peers Nd old" hint when stale (>60d).
                      const genAt = h.peer_section!.peers_generated_at;
                      if (genAt) {
                        const ageDays = Math.floor((Date.now() - new Date(genAt).getTime()) / 86400000);
                        if (ageDays >= 60) return `${base} · peers ${ageDays}d old`;
                      }
                      return base;
                    })()}
                  </span>
                  {onComparePeers && (
                    <button onClick={() => onComparePeers(h)} style={{
                      background: "none", border: "none",
                      color: (SECTION_VERDICT_STYLE[h.peer_section.verdict] || SECTION_VERDICT_STYLE.NEUTRAL).color,
                      fontSize: 11, fontWeight: 500, cursor: "pointer",
                      display: "inline-flex", alignItems: "center", gap: 3, padding: 0,
                    }}>
                      Compare all <IconArrowRight size={11} />
                    </button>
                  )}
                </div>
              }
            >
              {h.peer_section.peer_count != null && h.peer_section.peer_count > 0 && !h.peer_section.peer_set_weak && (
                <div style={{
                  display: "inline-flex", alignSelf: "flex-start", alignItems: "center", gap: 5,
                  background: "var(--buy-bg)", borderRadius: 999, padding: "2px 8px",
                  fontSize: 10, color: "var(--buy)", marginBottom: 2,
                }}>
                  <IconCircleCheck size={11} /> {h.peer_section.peer_count} peers matched
                </div>
              )}
              {(h.peer_section.metric_breakdown || []).slice(0, 4).map((mb, i) => {
                const fmtVal = (v: number, metric: string) => {
                  if (metric.includes("margin") || metric.includes("roe") || metric.includes("growth") || metric.includes("yield"))
                    return `${Math.round(v * 100)}%`;
                  return v.toFixed(1);
                };
                return (
                  <MetricRow
                    key={i}
                    label={mb.metric.replace(/_/g, " ").replace(/\b1y\b/, "growth").replace(/revenue growth/, "Rev growth").replace(/net profit margin/, "Net margin").replace(/dividend yield/, "Div yield")}
                    value={`${fmtVal(mb.stock_value, mb.metric)} vs ${fmtVal(mb.peer_median, mb.metric)}`}
                    color={mb.status === "lag" ? "red" : mb.status === "lead" ? "green" : "neutral"}
                  />
                );
              })}
              {!(h.peer_section.metric_breakdown?.length) && (
                h.peer_section.peers_top5 && h.peer_section.peers_top5.length > 0 ? (
                  <div style={{ fontSize: 12, color: "var(--label-secondary)", padding: "7px 0", lineHeight: 1.5 }}>
                    <span style={{ color: "var(--label-tertiary)", fontSize: 11 }}>vs.&nbsp;</span>
                    {h.peer_section.peers_top5.slice(0, 4).map((p, i, arr) => (
                      <span key={p.symbol}>
                        <span style={{ fontWeight: 500, color: "var(--label-primary)" }}>{p.symbol}</span>
                        {i < arr.length - 1 ? ", " : ""}
                      </span>
                    ))}
                    {h.peer_section.peers_top5.length > 4 && (
                      <span style={{ color: "var(--label-tertiary)" }}> +{h.peer_section.peers_top5.length - 4}</span>
                    )}
                  </div>
                ) : (
                  <div style={{ fontSize: 12, color: "var(--label-tertiary)", padding: "7px 0" }}>No peer data</div>
                )
              )}
            </SectionCard>
          )}

          {/* News section */}
          {h.news_section && (
            <SectionCard
              icon={<IconNews size={14} />}
              title="News"
              verdict={h.news_section.verdict}
              freshness={newsFreshnessLabel(h.news_section.newest_headline_at)}
              onRefresh={sectionRefresh}
              refreshing={sectionRefreshing}
              footer={
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                  <span style={{ fontSize: 10, color: "var(--label-quaternary)" }}>
                    {h.news_section.source_count || 0} sources · {newsFreshnessLabel(h.news_section.newest_headline_at).text}
                  </span>
                  {onReadSources && (
                    <button onClick={() => onReadSources(h)} style={{
                      background: "none", border: "none",
                      color: (SECTION_VERDICT_STYLE[h.news_section.verdict] || SECTION_VERDICT_STYLE.NEUTRAL).color,
                      fontSize: 11, fontWeight: 500, cursor: "pointer",
                      display: "inline-flex", alignItems: "center", gap: 3, padding: 0,
                    }}>
                      Read sources <IconChevronDown size={11} />
                    </button>
                  )}
                </div>
              }
            >
              {h.news_section.sector_mood && (() => {
                const sectorName = h.news_section.sector;
                const moodMatchesBg: Record<string, { bg: string; fg: string }> = {
                  BULLISH: { bg: "color-mix(in srgb, var(--system-green) 10%, transparent)", fg: "var(--system-green)" },
                  BEARISH: { bg: "color-mix(in srgb, var(--system-red) 10%, transparent)", fg: "var(--system-red)" },
                  NEUTRAL: { bg: "var(--bg-secondary)", fg: "var(--label-secondary)" },
                };
                const moodStyle = moodMatchesBg[h.news_section.sector_mood] || moodMatchesBg.NEUTRAL;
                const openInBrief = () => {
                  if (!sectorName) return;
                  window.dispatchEvent(new CustomEvent("market-brief:open", {
                    detail: { sector: sectorName },
                  }));
                };
                return (
                  <button
                    type="button"
                    onClick={sectorName ? openInBrief : undefined}
                    disabled={!sectorName}
                    title={sectorName ? `Open ${sectorName} in Market Brief` : undefined}
                    style={{
                      all: "unset",
                      cursor: sectorName ? "pointer" : "default",
                      display: "inline-flex", alignSelf: "flex-start", alignItems: "center", gap: 6,
                      background: moodStyle.bg, borderRadius: 999, padding: "3px 10px",
                      fontSize: 11, color: moodStyle.fg, marginBottom: 2,
                      fontWeight: 500,
                      transition: "background .12s ease",
                    }}
                    onMouseEnter={(e) => {
                      if (sectorName) e.currentTarget.style.background = "color-mix(in srgb, currentColor 14%, transparent)";
                    }}
                    onMouseLeave={(e) => { e.currentTarget.style.background = moodStyle.bg; }}
                  >
                    <IconBuildingFactory2 size={11} />
                    {sectorName ? <strong style={{ fontWeight: 600 }}>{sectorName}</strong> : null}
                    {sectorName ? <span style={{ opacity: 0.6 }}>·</span> : null}
                    Sector mood: {h.news_section.sector_mood}
                    {sectorName && <span style={{ opacity: 0.6, fontSize: 12, lineHeight: 1 }}>→</span>}
                  </button>
                );
              })()}
              {h.news_section.qualitative?.overall_sentiment && (
                <div style={{
                  fontSize: 12, color: "var(--label-secondary)", lineHeight: 1.4,
                  padding: "4px 0 6px", fontStyle: "italic",
                }}>
                  {h.news_section.qualitative.overall_sentiment.length > 140
                    ? h.news_section.qualitative.overall_sentiment.slice(0, 140) + "…"
                    : h.news_section.qualitative.overall_sentiment}
                </div>
              )}
              {(h.news_section.stock_signals || []).slice(0, 3).map((s, i) => (
                <SignalRow
                  key={i}
                  label={s.label}
                  color={s.direction === "negative" || s.direction === "red" ? "red" : s.direction === "positive" || s.direction === "green" ? "green" : "neutral"}
                  icon={
                    s.direction === "negative" || s.direction === "red"
                      ? <IconTrendingDown size={11} />
                      : s.direction === "positive" || s.direction === "green"
                        ? <IconCircleCheck size={11} />
                        : <IconInfoCircle size={11} />
                  }
                />
              ))}
              {!(h.news_section.stock_signals?.length) && (
                <div style={{ fontSize: 12, color: "var(--label-tertiary)", padding: "7px 0" }}>No news signals</div>
              )}
            </SectionCard>
          )}
        </div>
      )}

      {/* Signal dots + expand toggle */}
      <footer style={{
        display: "flex", justifyContent: "space-between", alignItems: "center", gap: 16,
        marginTop: 12, flexWrap: "wrap",
      }}>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          {(h.signals || []).slice(0, 3).map((s, i) => (
            <SignalDot key={`${s.source}-${i}`} src={s.label || s.source} direction={s.direction} recency={s.recency} />
          ))}
          {h.strategies_diverge === true && <StratDivergeChip />}
          {h.narrative_stale === true && <NarrativeStaleChip lagHours={h.narrative_fund_lag_hours} />}
        </div>
        <button
          onClick={() => setExpanded(e => !e)}
          aria-expanded={expanded}
          style={{
            background: "transparent", border: 0, color: "var(--label-tertiary)",
            cursor: "pointer", fontSize: 13, fontWeight: 500,
            display: "inline-flex", alignItems: "center", gap: 6, padding: "4px 0",
            textDecoration: "underline", textDecorationColor: "var(--label-quaternary)",
            textUnderlineOffset: 4,
          }}
        >
          {expanded ? "Hide details" : "Details"}
          <span style={{ display: "inline-block", transform: expanded ? "rotate(180deg)" : "rotate(0deg)", transition: "transform .15s", fontSize: 10 }}>▾</span>
        </button>
      </footer>

      {expanded && (
        <div style={{
          marginTop: 10, padding: 14,
          background: "var(--bg-secondary)", borderRadius: 8,
          display: "flex", flexDirection: "column", gap: 12,
        }}>
          {h.peer_section?.peer_summary && (
            <div>
              <div style={{ fontSize: 11, fontWeight: 600, color: "var(--label-tertiary)", letterSpacing: "0.05em", marginBottom: 4 }}>PEER COMPARISON</div>
              <p style={{ margin: 0, fontSize: 13.5, color: "var(--label-secondary)", lineHeight: 1.55 }}>{h.peer_section.peer_summary}</p>
            </div>
          )}
          {h.news_section?.qualitative?.bull_case?.length ? (
            <div>
              <div style={{ fontSize: 11, fontWeight: 600, color: "var(--buy)", letterSpacing: "0.05em", marginBottom: 4 }}>BULL CASE</div>
              {h.news_section.qualitative.bull_case.map((b, i) => (
                <p key={i} style={{ margin: "0 0 4px 0", fontSize: 13.5, color: "var(--label-secondary)", lineHeight: 1.55, paddingLeft: 12, borderLeft: "2px solid var(--buy)" }}>
                  {b}
                </p>
              ))}
            </div>
          ) : null}
          {h.news_section?.qualitative?.bear_case?.length ? (
            <div>
              <div style={{ fontSize: 11, fontWeight: 600, color: "var(--act)", letterSpacing: "0.05em", marginBottom: 4 }}>BEAR CASE</div>
              {h.news_section.qualitative.bear_case.map((b, i) => (
                <p key={i} style={{ margin: "0 0 4px 0", fontSize: 13.5, color: "var(--label-secondary)", lineHeight: 1.55, paddingLeft: 12, borderLeft: "2px solid var(--act)" }}>
                  {b}
                </p>
              ))}
            </div>
          ) : null}
          {h.news_section?.qualitative?.earnings_highlights && (
            <div>
              <div style={{ fontSize: 11, fontWeight: 600, color: "var(--label-tertiary)", letterSpacing: "0.05em", marginBottom: 4 }}>EARNINGS</div>
              <p style={{ margin: 0, fontSize: 13.5, color: "var(--label-secondary)", lineHeight: 1.55 }}>{h.news_section.qualitative.earnings_highlights}</p>
            </div>
          )}
          {((h.risks?.length || 0) + (h.strengths?.length || 0) > 0) && (
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
              {(h.risks || []).map((r, i) => <RiskChip key={`r${i}`} r={r} />)}
              {(h.strengths || []).map((s, i) => <StrengthChip key={`s${i}`} s={s} />)}
            </div>
          )}
          <p style={{ margin: 0, fontSize: 14, color: "var(--label-secondary)", lineHeight: 1.6 }}>
            {h.reasoning || "No detailed reasoning available."}
          </p>
        </div>
      )}

      {/* Responsive (`.pcard-section-grid` + `.pcard-spin` live in
          SectionCard.tsx global). The `.pcard-header` / `.pcard-actions`
          rules are PositionCard-specific (no other card uses them). */}
      <style>{`
        @media (max-width: 720px) {
          .pcard-header { flex-direction: column !important; align-items: flex-start !important; }
          .pcard-actions { width: 100% !important; justify-content: space-between !important; flex-wrap: wrap !important; }
        }
      `}</style>
    </article>
  );
}
