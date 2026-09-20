"use client";

import React, { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { openStockDetail } from "@/lib/stock-detail";
import Sparkline from "./Sparkline";
import RuleEditorModal, { type WatchRule as EditorRule } from "./RuleEditorModal";
import SectionCard, {
  SignalRow,
  MetricRow,
  FootStat,
  newsFreshnessLabel,
} from "./SectionCard";
import {
  IconChartCandle, IconUsersGroup, IconNews,
  IconAlertTriangle, IconCircleCheck, IconArrowRight,
} from "@tabler/icons-react";

export interface WatchlistStock {
  id: number;
  symbol: string;
  name: string | null;
  exchange: string;
  fundamentals?: {
    cmp?: number | null;
    pe_ratio?: number | null;
    ttm_pe?: number | null;
    pb_ratio?: number | null;
    market_cap?: number | null;
    sector?: string | null;
    industry?: string | null;
  } | null;
  news_sentiment?: string | null;
  news_score?: number | null;
  reason_tag?: string | null;
  // Researching-card fields
  watching_since?: string | null;
  reason?: string | null;
  pe_target?: number | null;
  price_target?: number | null;
  peer_symbols?: string[] | null;
  watch_rules?: Array<{ type: string; value?: string | number; label?: string }> | null;
  lane?: string | null;
  // multi-lane via memberships from /detail
  memberships?: Array<{ name: string; lane: string }> | null;
  // pending review alerts surfaced in /detail
  triggered_alerts?: Array<{
    id: number;
    trigger_type: string;
    trigger_label: string;
    suggested_action: string | null;
    suggested_lane: string | null;
    created_at: string | null;
  }> | null;
  // Latest AI verdict payload — fed straight from InvestmentDecision.result_json
  decision_json?: {
    summary?: string;
    reasoning?: string;
    valuation_view?: string;
    key_risks?: string[];
    action_items?: string[];
    [k: string]: unknown;
  } | null;
  decision_at?: string | null;
  // Rule-based Fundamental Analysis verdict (computed inline by /detail).
  fundamental_analysis?: {
    verdict: "STRONG" | "FAIR" | "WEAK" | "NA";
    score: number | null;
    rules_passed: number;
    rules_failed: number;
    rules_missing: number;
    snapshot_fetched_at: string | null;
  } | null;
  // Latest news sentiment (already plumbed earlier).
  verdict?: string | null;
  verdict_confidence?: number | null;
  // 3-section grid (Price / Peers / News) — emitted by /watchlist/all/detail
  // from stock_analyses + stock_peers. May be null when the symbol hasn't
  // been analyzed yet; the Peers card then renders a "generating peers…"
  // placeholder.
  valuation_section?: {
    verdict: string;
    score: number | null;
    signals: Array<{ label: string; direction?: string }> | null;
    hard_failed: string[] | null;
    last_run_at: string | null;
  } | null;
  peer_section?: {
    verdict: string;
    metric_breakdown: Array<{ metric: string; stock_value: number; peer_median: number; status: string }> | null;
    peer_summary: string | null;
    peer_count: number | null;
    peer_set_weak: boolean;
    last_run_at: string | null;
    peers_generated_at: string | null;
  } | null;
  news_section?: {
    verdict: string;
    stock_signals: Array<{ label: string; direction?: string }> | null;
    source_count: number | null;
    qualitative: Record<string, unknown> | null;
    sector: string | null;
    last_run_at: string | null;
    newest_headline_at: string | null;
  } | null;
}

interface JournalEntry {
  id: number;
  body: string;
  created_at: string | null;
}

interface ChartCandle { time: string; close: number | null }
interface ChartResponse {
  candles: ChartCandle[];
  prev_close: number | null;
  current_price: number | null;
  source?: string;
}

// Module-level semaphore — caps the number of in-flight chart fetches across
// every ResearchingCard on the page. Without this, the Researching tab fans
// out 100+ parallel /chart requests and Kite returns "Too many requests"
// for most of them, leaving cards with empty sparklines.
const CHART_CONCURRENCY = 3;
let _activeChartFetches = 0;
const _chartQueue: Array<() => void> = [];

function acquireChartSlot(): Promise<void> {
  return new Promise((resolve) => {
    if (_activeChartFetches < CHART_CONCURRENCY) {
      _activeChartFetches += 1;
      resolve();
      return;
    }
    _chartQueue.push(() => {
      _activeChartFetches += 1;
      resolve();
    });
  });
}

function releaseChartSlot() {
  _activeChartFetches -= 1;
  const next = _chartQueue.shift();
  if (next) next();
}

import { fmtN, fmtINR, fmtDateShort, fmtRelative, pctStr } from "@/lib/format";

const LANE_META: Record<string, { title: string; color: string; bg: string; edge: string }> = {
  researching:   { title: "Researching",       color: "var(--system-blue)",    bg: "var(--fill-blue)",   edge: "rgba(0,122,255,0.3)" },
  awaiting:      { title: "Awaiting Correction", color: "var(--review)",       bg: "var(--review-bg)",   edge: "var(--review-edge)" },
  exit:          { title: "Exit Watch",        color: "var(--act)",            bg: "var(--act-bg)",      edge: "var(--act-edge)" },
  hold:          { title: "Hold",              color: "var(--hold)",           bg: "var(--hold-bg)",     edge: "var(--hold-edge)" },
  buy:           { title: "Buy",               color: "var(--buy)",            bg: "var(--buy-bg)",      edge: "var(--buy-edge)" },
};

function laneInfo(id: string | null | undefined) {
  return LANE_META[(id || "researching").toLowerCase()] || LANE_META.researching;
}

// ─── Rule chip ─────────────────────────────────────────────────────
function RuleChip({
  rule, status,
}: {
  rule: { type: string; value?: string | number; label?: string };
  status: "armed" | "triggered" | "upcoming";
}) {
  const label = rule.label || `${rule.type} ${rule.value ?? ""}`;
  const icon =
    rule.type.includes("pct") || rule.type.includes("drawdown") || rule.type.includes("peak") ? "▲"
    : rule.type.includes("news") ? "📰"
    : rule.type.includes("pe") ? "💲"
    : "→";
  let style: React.CSSProperties = {};
  if (status === "triggered") {
    style = { background: "var(--act-bg)", borderColor: "var(--act-edge)", color: "var(--act)", fontWeight: 600 };
  } else if (status === "upcoming") {
    style = { background: "var(--review-bg)", borderColor: "var(--review-edge)", color: "var(--review)" };
  } else {
    style = { background: "var(--bg-secondary)", borderColor: "var(--separator-light)", color: "var(--label-secondary)" };
  }
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 6,
      padding: "4px 9px", borderRadius: 99,
      fontSize: 11.5, fontWeight: 500,
      border: "1px solid",
      whiteSpace: "nowrap",
      ...style,
    }}>
      {status === "triggered" && <span className="rule-flame" style={{ fontSize: 8 }}>🔥</span>}
      <span style={{ fontSize: 11, opacity: 0.8 }}>{icon}</span>
      {label}
    </span>
  );
}

// ─── Notes / Journal thread ────────────────────────────────────────
// Now also hosts the watch-rules block (previously the standalone
// "Watching for" section). Renders the rules + watching_since caption
// + "+ rule" button above the journal entries so all hand-curated notes
// for a stock live in one place.
// Accepts the same WatchRule shape RuleEditorModal/RuleChip use —
// `value: number`, `label?: string | null` — so we can pass `rules`
// straight from useState<EditorRule[]> without re-mapping.
interface NotesRule {
  type: string;
  value?: string | number;
  label?: string | null;
}

function NotesThread({
  notes, expanded, onToggle, onAddNote,
  rules, watchingSince, ruleStatus, onEditRules,
}: {
  notes: JournalEntry[];
  expanded: boolean;
  onToggle: () => void;
  onAddNote: (body: string) => Promise<void>;
  rules?: NotesRule[];
  watchingSince?: string | null;
  ruleStatus?: (rule: NotesRule) => "armed" | "triggered" | "upcoming";
  onEditRules?: () => void;
}) {
  const visible = expanded ? notes : notes.slice(0, 1);
  const [composing, setComposing] = useState(false);
  const [draft, setDraft] = useState("");
  const [posting, setPosting] = useState(false);

  async function submit() {
    const body = draft.trim();
    if (!body) return;
    setPosting(true);
    try {
      await onAddNote(body);
      setDraft("");
      setComposing(false);
    } finally {
      setPosting(false);
    }
  }

  const hasRules = (rules && rules.length > 0) || !!onEditRules;

  return (
    <div style={{ borderTop: "1px solid var(--separator-light)", paddingTop: 12 }}>
      {/* Watch rules subsection — migrated from the removed "Watching for"
          block. Hidden when nothing to show AND no editor wired up. */}
      {hasRules && (
        <div style={{ marginBottom: 14 }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 6, flexWrap: "wrap" }}>
            <span style={{
              fontSize: 11, fontWeight: 600, color: "var(--label-tertiary)",
              textTransform: "uppercase", letterSpacing: "0.08em",
            }}>Watch rules</span>
            {watchingSince && (
              <span style={{
                fontSize: 11, color: "var(--label-quaternary)", fontFamily: "var(--font-mono)",
              }}>· since {fmtDateShort(watchingSince)}</span>
            )}
          </div>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            {(rules || []).map((r, i) => (
              <RuleChip
                key={i}
                rule={{ type: r.type, value: r.value, label: r.label ?? undefined }}
                status={ruleStatus ? ruleStatus(r) : "armed"}
              />
            ))}
            {onEditRules && (
              <button
                onClick={onEditRules}
                style={{
                  background: "transparent", border: "1px dashed var(--separator)",
                  padding: "4px 10px", borderRadius: 99,
                  fontSize: 11.5, color: "var(--label-tertiary)", cursor: "pointer",
                }}
              >+ rule</button>
            )}
          </div>
        </div>
      )}

      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
        <span style={{
          fontSize: 11, fontWeight: 600, color: "var(--label-tertiary)",
          textTransform: "uppercase", letterSpacing: "0.08em",
        }}>Journal</span>
        <span style={{
          fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--label-tertiary)",
          padding: "2px 7px", background: "var(--bg-secondary)", borderRadius: 99,
        }}>
          {notes.length} {notes.length === 1 ? "entry" : "entries"}
        </span>
        <button
          onClick={() => setComposing((c) => !c)}
          style={{
            marginLeft: "auto", background: "transparent",
            border: "1px dashed var(--separator)",
            padding: "3px 10px", borderRadius: 99,
            fontSize: 11.5, color: "var(--label-tertiary)", cursor: "pointer",
          }}
          aria-expanded={composing}
        >+ note</button>
        {notes.length > 1 && (
          <button
            onClick={onToggle}
            style={{
              background: "transparent", border: 0,
              fontSize: 12, color: "var(--label-tertiary)", cursor: "pointer",
              padding: "2px 6px", borderRadius: 4,
            }}
          >{expanded ? "Show less" : "Show all"}</button>
        )}
      </div>
      {composing && (
        <div style={{
          display: "flex", flexDirection: "column", gap: 6,
          marginBottom: 10, padding: 10,
          background: "var(--bg-secondary)", borderRadius: 8,
          border: "1px solid var(--separator-light)",
        }}>
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="What's the update on this stock?"
            rows={3}
            autoFocus
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                e.preventDefault();
                submit();
              }
            }}
            style={{
              border: "1px solid var(--separator)", borderRadius: 6,
              padding: "8px 10px", fontSize: 13, lineHeight: 1.5,
              background: "var(--bg-primary)", color: "var(--label-primary)",
              fontFamily: "inherit", resize: "vertical",
              outline: "none",
            }}
          />
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <span style={{ fontSize: 11, color: "var(--label-quaternary)" }}>
              ⌘/Ctrl+Enter to save
            </span>
            <div style={{ flex: 1 }} />
            <button
              onClick={() => { setComposing(false); setDraft(""); }}
              style={{
                padding: "5px 10px", borderRadius: 6, fontSize: 12, fontWeight: 500,
                background: "transparent", color: "var(--label-tertiary)",
                border: "1px solid var(--separator)", cursor: "pointer",
              }}
            >Cancel</button>
            <button
              onClick={submit}
              disabled={posting || !draft.trim()}
              style={{
                padding: "5px 12px", borderRadius: 6, fontSize: 12, fontWeight: 600,
                background: "var(--label-primary)", color: "var(--bg-primary)",
                border: 0, cursor: posting ? "wait" : "pointer",
                opacity: !draft.trim() ? 0.4 : 1,
              }}
            >{posting ? "Saving…" : "Save note"}</button>
          </div>
        </div>
      )}
      {notes.length === 0 ? (
        <div style={{ fontSize: 12, color: "var(--label-tertiary)", fontStyle: "italic" }}>
          No journal entries yet — add one above, or click <strong>Run analysis</strong> to evaluate this stock.
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {visible.map((n) => (
            <div key={n.id} style={{ display: "grid", gridTemplateColumns: "12px 1fr", gap: 10 }}>
              <div style={{ position: "relative", width: 2, margin: "0 auto", background: "var(--separator)", borderRadius: 2 }}>
                <span style={{
                  position: "absolute", left: -3, top: 4, width: 8, height: 8, borderRadius: 99,
                  background: "var(--label-quaternary)", border: "2px solid var(--bg-primary)",
                }} />
              </div>
              <div style={{ padding: "2px 0" }}>
                <div style={{
                  fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--label-tertiary)",
                  marginBottom: 3, fontWeight: 500,
                }}>
                  {fmtRelative(n.created_at)}
                </div>
                <div style={{ fontSize: 13.5, lineHeight: 1.5, color: "var(--label-secondary)", whiteSpace: "pre-wrap" }}>
                  {n.body}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── ResearchingCard ───────────────────────────────────────────────
interface CardProps {
  stock: WatchlistStock;
  onMoveLane?: (newLane: string) => void;
  onStop?: () => void;
  onEditRules?: () => void;
  onAnalysisComplete?: () => void;
  selectMode?: boolean;
  selected?: boolean;
  onToggleSelect?: () => void;
  bulkStatus?: "queued" | "running" | "done" | "error" | null;
}

export default function ResearchingCard({ stock, onMoveLane, onStop, onEditRules, onAnalysisComplete, selectMode, selected, onToggleSelect, bulkStatus }: CardProps) {
  const f = stock.fundamentals || {};
  const fundCmp = f.cmp ?? null;
  const pe = f.pe_ratio ?? f.ttm_pe ?? null;
  const sector = f.sector || f.industry || null;
  const triggered = stock.triggered_alerts ?? [];
  const hasAlerts = triggered.length > 0;

  const [chart, setChart] = useState<number[] | null>(null);
  const [livePrice, setLivePrice] = useState<number | null>(null);
  const [livePrevClose, setLivePrevClose] = useState<number | null>(null);
  const [journal, setJournal] = useState<JournalEntry[]>([]);
  const [expanded, setExpanded] = useState(false);
  const [researching, setResearching] = useState(false);
  const [editorOpen, setEditorOpen] = useState(false);
  const [laneDropdownOpen, setLaneDropdownOpen] = useState(false);
  const [localLane, setLocalLane] = useState<string>(stock.lane || "researching");
  // Local rule list — initialized from props, mutated on save so the chips
  // re-render without a full /detail refetch.
  const [rules, setRules] = useState<EditorRule[]>(
    () =>
      ((stock.watch_rules || []) as EditorRule[]).map((r) => ({
        type: r.type,
        value: typeof r.value === "string" ? Number(r.value) : (r.value as number),
        operator: (r.operator ?? null) as EditorRule["operator"],
        label: r.label ?? null,
        check_frequency: (r.check_frequency ?? null) as EditorRule["check_frequency"],
      })),
  );

  useEffect(() => {
    let cancelled = false;
    (async () => {
      await acquireChartSlot();
      if (cancelled) {
        releaseChartSlot();
        return;
      }
      try {
        const d = await api.get<ChartResponse>(
          `/api/market-data/chart/${stock.symbol}?range=1M&exchange=${stock.exchange}`,
        );
        if (cancelled) return;
        setChart(
          d.candles
            .map((c) => c.close)
            .filter((v): v is number => v != null),
        );
        setLivePrice(d.current_price ?? null);
        setLivePrevClose(d.prev_close ?? null);
      } catch {
        if (!cancelled) setChart(null);
      } finally {
        releaseChartSlot();
      }
    })();
    api
      .get<{ entries: JournalEntry[]; count: number }>(
        `/api/watchlists/items/${stock.id}/journal`,
      )
      .then((d) => {
        if (!cancelled) setJournal(d.entries);
      })
      .catch(() => {
        if (!cancelled) setJournal([]);
      });
    return () => {
      cancelled = true;
    };
  }, [stock.id, stock.symbol, stock.exchange]);

  // Prefer live quote price (from chart endpoint) over the cached
  // fundamentals.cmp — it's always populated when the chart succeeds and
  // covers the case where fundamentals haven't been fetched yet.
  const cmp = livePrice ?? fundCmp;

  // Day change %: prefer (live - prevClose) when both are present; otherwise
  // fall back to last-two-points of the chart series.
  let dayChangePct: number | null = null;
  if (livePrice != null && livePrevClose != null && livePrevClose !== 0) {
    dayChangePct = ((livePrice - livePrevClose) / livePrevClose) * 100;
  } else if (chart && chart.length >= 2) {
    const last = chart[chart.length - 1];
    const prev = chart[chart.length - 2];
    dayChangePct = prev ? ((last - prev) / prev) * 100 : null;
  }
  const isUp = (dayChangePct ?? 0) >= 0;

  // Memberships → distinct lanes (for multi-lane tags)
  const lanes: string[] = [];
  for (const m of stock.memberships || []) {
    const id = (m.lane || "researching").toLowerCase();
    if (!lanes.includes(id)) lanes.push(id);
  }
  if (lanes.length === 0) lanes.push((stock.lane || "researching").toLowerCase());
  const primaryLane = laneInfo(lanes[0]);

  // Rules — augment with trigger status (matched against triggered alerts of type "rule")
  const ruleStatus = (rule: { type: string }): "armed" | "triggered" | "upcoming" => {
    const fired = triggered.find(a => a.trigger_type === "rule");
    if (fired && (fired.trigger_label || "").toLowerCase().includes(rule.type.toLowerCase())) return "triggered";
    return "armed";
  };

  async function runResearch() {
    setResearching(true);
    try {
      // Run the same comprehensive analysis as the stock detail panel:
      // fundamentals + news sentiment + MF activity + smart money + AI verdict.
      type AnalyzeResp = {
        investment_decision?: {
          verdict?: string | null;
          confidence?: number | null;
          reasoning?: string | null;
        } | null;
        news_sentiment?: { sentiment?: string | null; score?: number | null } | null;
      };
      const res = await api.post<AnalyzeResp>(
        `/api/stocks/${stock.symbol}/analyze?exchange=${stock.exchange || "NSE"}`,
        {},
      );

      // Append a one-line verdict snapshot to the journal so the timeline still
      // captures each analysis run.
      const verdict = res.investment_decision?.verdict ?? null;
      const conf = res.investment_decision?.confidence ?? null;
      const reasoning = (res.investment_decision?.reasoning ?? "").trim();
      const newsSent = res.news_sentiment?.sentiment ?? null;
      const newsScore = res.news_sentiment?.score ?? null;
      const parts: string[] = [];
      if (verdict) parts.push(`AI: ${verdict}${conf != null ? ` ${conf}%` : ""}`);
      if (newsSent) parts.push(`News: ${newsSent}${newsScore != null ? ` ${newsScore > 0 ? "+" : ""}${newsScore}` : ""}`);
      const headerLine = parts.length ? parts.join(" · ") : "Analysis complete";
      const body = reasoning ? `${headerLine}\n${reasoning.slice(0, 600)}` : headerLine;
      try {
        await api.post(`/api/watchlists/items/${stock.id}/journal`, { body });
      } catch { /* journal entry is best-effort */ }

      // Refresh local journal + bubble up so parent re-fetches detail and the
      // Signal Pills (News / Fundamentals / AI) update on the card.
      const j = await api.get<{ entries: JournalEntry[] }>(`/api/watchlists/items/${stock.id}/journal`);
      setJournal(j.entries);
      onAnalysisComplete?.();
    } catch { /* ignore */ }
    setResearching(false);
  }

  return (
    <article
      id={`pcard-${stock.symbol}`}
      onClick={selectMode && onToggleSelect ? onToggleSelect : undefined}
      style={{
        background: "var(--bg-primary)",
        border: `1px solid ${selected ? "var(--system-blue, #007AFF)" : hasAlerts ? "var(--act-edge)" : "var(--separator-light)"}`,
        borderRadius: 16,
        padding: "18px 20px",
        boxShadow: selected
          ? "var(--shadow-sm), 0 0 0 2px rgba(0,122,255,0.15)"
          : hasAlerts
          ? "var(--shadow-sm), 0 0 0 1px color-mix(in srgb, var(--act) 12%, transparent)"
          : "var(--shadow-sm)",
        display: "flex", flexDirection: "column", gap: 14,
        marginBottom: 14,
        cursor: selectMode ? "pointer" : "default",
        position: "relative",
      }}
    >
      {/* Bulk-run status badge (top-right) */}
      {bulkStatus && (
        <div style={{
          position: "absolute", top: 12, right: 12, zIndex: 1,
          padding: "3px 9px", borderRadius: 12, fontSize: 11, fontWeight: 600,
          background:
            bulkStatus === "done" ? "#D1FAE5" :
            bulkStatus === "error" ? "#FEE2E2" :
            bulkStatus === "running" ? "#DBEAFE" :
            "var(--bg-secondary)",
          color:
            bulkStatus === "done" ? "#065F46" :
            bulkStatus === "error" ? "#991B1B" :
            bulkStatus === "running" ? "#1E40AF" :
            "var(--label-tertiary)",
        }}>
          {bulkStatus === "queued" && "Queued"}
          {bulkStatus === "running" && "Analyzing…"}
          {bulkStatus === "done" && "✓ Done"}
          {bulkStatus === "error" && "✕ Failed"}
        </div>
      )}
      {/* Header row */}
      <header className="rcard-header" style={{
        display: "grid", gridTemplateColumns: "1fr auto auto",
        alignItems: "center", gap: 16,
      }}>
        <div style={{ display: "flex", gap: 12, alignItems: "center", minWidth: 0 }}>
          {selectMode && (
            <input
              type="checkbox"
              checked={!!selected}
              onChange={onToggleSelect}
              onClick={(e) => e.stopPropagation()}
              aria-label={`Select ${stock.symbol}`}
              style={{
                width: 18, height: 18, cursor: "pointer", flexShrink: 0,
                accentColor: "var(--system-blue, #007AFF)",
              }}
            />
          )}
          <div style={{
            width: 40, height: 40, borderRadius: 9,
            display: "grid", placeItems: "center",
            fontFamily: "var(--font-mono)", fontWeight: 600, fontSize: 12,
            background: primaryLane.bg, color: primaryLane.color, border: `1px solid ${primaryLane.edge}`,
            flexShrink: 0, letterSpacing: 0,
          }}>
            {stock.symbol.slice(0, 2)}
          </div>
          <div style={{ minWidth: 0, flex: 1 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
              <button
                onClick={() => openStockDetail(stock.symbol, stock.exchange)}
                style={{
                  fontFamily: "var(--font-mono)", fontWeight: 600, fontSize: 15,
                  color: "var(--label-primary)", background: "transparent",
                  border: 0, padding: 0, cursor: "pointer",
                }}
              >{stock.symbol}</button>
              <div style={{ display: "inline-flex", gap: 4, flexWrap: "wrap" }}>
                {lanes.map((id, idx) => {
                  const l = laneInfo(idx === 0 ? localLane : id);
                  const displayId = idx === 0 ? localLane : id;
                  const isPrimary = idx === 0;
                  return (
                    <span key={id} style={{ position: "relative" }}>
                      <button
                        onClick={(e) => {
                          if (!isPrimary) return;
                          e.stopPropagation();
                          setLaneDropdownOpen((o) => !o);
                        }}
                        style={{
                          fontSize: 10.5, fontWeight: 600,
                          padding: "2px 7px", borderRadius: 99,
                          border: `1px solid ${l.edge}`,
                          background: l.bg, color: l.color,
                          whiteSpace: "nowrap",
                          cursor: isPrimary ? "pointer" : "default",
                          fontFamily: "inherit",
                          display: "inline-flex", alignItems: "center", gap: 3,
                        }}
                      >
                        {laneInfo(displayId).title}
                        {isPrimary && <span style={{ fontSize: 8, opacity: 0.7 }}>▾</span>}
                      </button>
                      {isPrimary && laneDropdownOpen && (
                        <LaneDropdown
                          currentLane={localLane}
                          itemId={stock.id}
                          onSelect={(newLane) => {
                            setLocalLane(newLane);
                            setLaneDropdownOpen(false);
                            onMoveLane?.(newLane);
                          }}
                          onClose={() => setLaneDropdownOpen(false)}
                        />
                      )}
                    </span>
                  );
                })}
                {/* Watchlist-membership chips. Distinct names so a stock
                    in two lanes of the same watchlist only renders once. */}
                {Array.from(
                  new Set((stock.memberships || []).map((m) => m.name).filter(Boolean)),
                ).map((wlName) => (
                  <span
                    key={`wl-${wlName}`}
                    title={`In watchlist: ${wlName}`}
                    style={{
                      fontSize: 10.5, fontWeight: 500,
                      padding: "2px 7px", borderRadius: 99,
                      border: "1px solid var(--separator)",
                      background: "var(--bg-secondary)",
                      color: "var(--label-secondary)",
                      whiteSpace: "nowrap",
                    }}
                  >{wlName}</span>
                ))}
              </div>
            </div>
            <div style={{
              fontSize: 13, color: "var(--label-tertiary)", marginTop: 2,
              whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
            }}>
              {stock.name || "—"}{sector && <span style={{ color: "var(--label-quaternary)" }}> · {sector}</span>}
            </div>
            {stock.reason && (
              <div
                title={stock.reason}
                style={{
                  fontSize: 11, color: "var(--label-quaternary)", marginTop: 2,
                  display: "-webkit-box",
                  WebkitLineClamp: 2,
                  WebkitBoxOrient: "vertical",
                  overflow: "hidden",
                  lineHeight: 1.35,
                  wordBreak: "break-word",
                }}
              >
                {stock.reason}
              </div>
            )}
          </div>
        </div>

        <div className="rcard-chart" style={{ padding: "0 6px" }}>
          {chart && chart.length > 1 ? (
            <Sparkline data={chart} width={96} height={32} showGrid={false} />
          ) : (
            <div style={{ width: 96, height: 32, background: "var(--fill-gray)", borderRadius: 4 }} />
          )}
        </div>

        <div className="rcard-price" style={{ textAlign: "right", minWidth: 110 }}>
          <div style={{ fontFamily: "var(--font-mono)", fontSize: 18, fontWeight: 600, lineHeight: 1.1 }}>
            {cmp != null ? `₹${fmtN(cmp)}` : "—"}
          </div>
          <div style={{
            fontFamily: "var(--font-mono)", fontSize: 12, marginTop: 3, fontWeight: 500,
            color: dayChangePct == null ? "var(--label-tertiary)" : isUp ? "var(--buy)" : "var(--act)",
          }}>
            {dayChangePct != null ? `${pctStr(dayChangePct)} today` : "—"}
          </div>
        </div>
      </header>

      {/* Triggered alerts strip — surfaced standalone now that the "Today"
          two-column block is gone. Only renders when there are pending
          alerts; otherwise hidden entirely. */}
      {hasAlerts && (
        <div style={{
          padding: "10px 12px", borderRadius: 8,
          background: "var(--act-bg)",
          border: "1px solid var(--act-edge)",
        }}>
          <div style={{
            fontSize: 11, color: "var(--act)",
            textTransform: "uppercase", letterSpacing: "0.08em",
            fontWeight: 600, marginBottom: 8,
          }}>Alerts</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {triggered.map((t, i) => (
              <div key={i} className="rcard-alert-row" style={{
                display: "grid", gridTemplateColumns: "auto auto 1fr",
                gap: 8, alignItems: "baseline",
                fontSize: 12.5, color: "var(--label-secondary)", lineHeight: 1.45,
              }}>
                <span style={{ width: 6, height: 6, borderRadius: 99, background: "var(--act)", transform: "translateY(2px)" }} />
                <span style={{
                  fontFamily: "var(--font-mono)", fontSize: 11,
                  color: "var(--act)", fontWeight: 600, whiteSpace: "nowrap",
                }}>{fmtRelative(t.created_at)}</span>
                <span style={{ color: "var(--label-primary)" }}>{t.trigger_label}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Fundamentals (AI verdict) — summary + key risks + action items */}
      <Fundamentals decision={stock.decision_json} decisionAt={stock.decision_at} />

      {/* 3-section grid (Price · Peers · News) — same shape as portfolio
          PositionCard. Backend emits these from stock_analyses; Peers
          shows a "generating peers…" placeholder when not yet computed. */}
      <ResearchingSectionGrid
        stock={stock}
        onReadSources={() => {
          // The NewsAccordion sits below — scroll to it. Hosting both
          // (verdict in SectionCard, headlines in accordion) is by
          // design: section is a glance, accordion is a deep-dive.
          const el = document.querySelector(`#news-accordion-${stock.symbol}`);
          if (el) el.scrollIntoView({ behavior: "smooth", block: "nearest" });
        }}
      />

      {/* Meta grid — only renders when the user has set Entry target or
          P/E target. "Watching since" moved inline with Watching For
          above; the free-text "Reason" was removed (no editor wired up,
          and Fundamentals already carries the AI thesis). */}
      {(stock.price_target != null || (stock.pe_target != null && pe != null)) && (
        <div style={{
          display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
          gap: "12px 24px", padding: "12px 14px",
          background: "var(--bg-secondary)", borderRadius: 8,
          border: "1px solid var(--separator-light)",
        }}>
          {stock.price_target != null && (
            <MetaRow k="Entry target" v={`₹${fmtINR(stock.price_target)}`} mono />
          )}
          {(stock.pe_target != null && pe != null) && (
            <MetaRow k="P/E target" v={`${pe.toFixed(0)}× → ${stock.pe_target.toFixed(0)}×`} mono />
          )}
        </div>
      )}

      {/* Journal + watch rules — Notes hosts both since the "Watching for"
          standalone block was removed. Rules and "+ rule" button are
          rendered inside NotesThread when `rules` is passed. */}
      <NotesThread
        notes={journal}
        expanded={expanded}
        onToggle={() => setExpanded((e) => !e)}
        onAddNote={async (body) => {
          await api.post(`/api/watchlists/items/${stock.id}/journal`, { body });
          const j = await api.get<{ entries: JournalEntry[] }>(
            `/api/watchlists/items/${stock.id}/journal`,
          );
          setJournal(j.entries);
          setExpanded(true);
        }}
        rules={rules}
        watchingSince={stock.watching_since ?? null}
        ruleStatus={ruleStatus}
        onEditRules={() => setEditorOpen(true)}
      />

      {/* News — collapsible, hidden by default. Loads /api/news/inbox?scope=symbol:X on first open. */}
      <div id={`news-accordion-${stock.symbol}`}>
        <NewsAccordion symbol={stock.symbol} />
      </div>

      <style jsx>{`
        @media (max-width: 720px) {
          .rcard-header { grid-template-columns: 1fr !important; gap: 10px !important; }
          .rcard-chart { display: none !important; }
          .rcard-price { min-width: auto !important; text-align: left !important; }
          /* Triggered-alerts row: stop trying to align timestamp + dot
             + label across 3 columns. Long trigger labels wrap and break
             alignment. Stack vertically instead. */
          .rcard-alert-row {
            grid-template-columns: auto 1fr !important;
            grid-template-rows: auto auto !important;
            row-gap: 2px !important;
          }
          .rcard-alert-row > :nth-child(3) {
            grid-column: 1 / -1 !important;
          }
        }
      `}</style>

      {/* Footer */}
      <footer style={{
        display: "flex", alignItems: "center", gap: 12,
        borderTop: "1px solid var(--separator-light)", paddingTop: 12,
      }}>
        <button
          onClick={runResearch}
          disabled={researching}
          style={{
            background: "var(--label-primary)", color: "var(--bg-primary)",
            border: 0, padding: "8px 14px", borderRadius: 7,
            fontSize: 12.5, fontWeight: 600, cursor: researching ? "wait" : "pointer",
            display: "inline-flex", alignItems: "center", gap: 6,
          }}
        >
          {researching ? "Analyzing…" : "Run analysis"} <span>→</span>
        </button>
        <div style={{ marginLeft: "auto", display: "flex", gap: 4 }}>
          <FootLink onClick={() => setEditorOpen(true)}>Edit rules</FootLink>
          <FootLink onClick={onStop} danger>Stop watching</FootLink>
        </div>
      </footer>

      {editorOpen && (
        <RuleEditorModal
          itemId={stock.id}
          symbol={stock.symbol}
          rules={rules}
          onClose={() => setEditorOpen(false)}
          onSaved={(next) => setRules(next)}
        />
      )}
    </article>
  );
}

function LaneDropdown({
  currentLane,
  itemId,
  onSelect,
  onClose,
}: {
  currentLane: string;
  itemId: number;
  onSelect: (lane: string) => void;
  onClose: () => void;
}) {
  const ref = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [onClose]);

  async function pick(lane: string) {
    if (lane === currentLane) { onClose(); return; }
    try {
      await api.patch(`/api/watchlists/items/${itemId}`, { lane });
      onSelect(lane);
    } catch { onClose(); }
  }

  const allLanes = ["researching", "awaiting", "buy", "hold", "exit"] as const;
  return (
    <div
      ref={ref}
      style={{
        position: "absolute", top: "calc(100% + 4px)", left: 0, zIndex: 20,
        background: "var(--bg-primary)",
        border: "1px solid var(--separator)",
        borderRadius: 10, padding: 4,
        boxShadow: "var(--shadow-md)",
        minWidth: 170,
      }}
    >
      {allLanes.map((id) => {
        const l = LANE_META[id];
        const active = id === currentLane;
        return (
          <button
            key={id}
            onClick={(e) => { e.stopPropagation(); pick(id); }}
            style={{
              display: "flex", alignItems: "center", gap: 8,
              width: "100%", padding: "7px 10px", borderRadius: 7,
              border: 0, cursor: "pointer",
              background: active ? l.bg : "transparent",
              fontFamily: "inherit", fontSize: 12.5,
              fontWeight: active ? 600 : 500,
              color: active ? l.color : "var(--label-secondary)",
            }}
          >
            <span style={{
              width: 8, height: 8, borderRadius: 99,
              background: l.color, flexShrink: 0,
            }} />
            {l.title}
            {active && <span style={{ marginLeft: "auto", fontSize: 11, opacity: 0.6 }}>✓</span>}
          </button>
        );
      })}
    </div>
  );
}

function MetaRow({ k, v, mono, italic }: { k: string; v: string; mono?: boolean; italic?: boolean }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 2, minWidth: 0 }}>
      <span style={{
        fontSize: 10.5, fontWeight: 600, color: "var(--label-tertiary)",
        textTransform: "uppercase", letterSpacing: "0.08em",
      }}>{k}</span>
      <span style={{
        fontSize: 13, color: italic ? "var(--label-secondary)" : "var(--label-primary)",
        fontWeight: italic ? 400 : 500,
        fontFamily: mono ? "var(--font-mono)" : "inherit",
        fontStyle: italic ? "italic" : "normal",
      }}>{v}</span>
    </div>
  );
}

function FootLink({ children, onClick, danger }: {
  children: React.ReactNode; onClick?: () => void; danger?: boolean;
}) {
  const [hover, setHover] = useState(false);
  return (
    <button
      onClick={onClick}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        background: hover ? (danger ? "var(--act-bg)" : "var(--bg-secondary)") : "transparent",
        border: 0, padding: "6px 10px", borderRadius: 5,
        fontSize: 12,
        color: danger
          ? hover ? "var(--act)" : "var(--system-red)"
          : hover ? "var(--label-primary)" : "var(--label-tertiary)",
        cursor: "pointer", fontFamily: "inherit",
      }}
    >
      {children}
    </button>
  );
}


// ─── Fundamentals (AI verdict snapshot) ─────────────────────────────
// Shows a serif quote-style summary from the latest InvestmentDecision,
// then two grids: red-tinted "key risks" and green-tinted "action items".
// All three fields are optional — render nothing if the verdict is empty.
function Fundamentals({
  decision,
  decisionAt,
}: {
  decision?: WatchlistStock["decision_json"];
  decisionAt?: string | null;
}) {
  if (!decision) return null;
  const summary = (decision.summary as string) || (decision.reasoning as string) || "";
  const risks: string[] = Array.isArray(decision.key_risks)
    ? (decision.key_risks as string[]).filter(Boolean).slice(0, 6)
    : [];
  const actions: string[] = Array.isArray(decision.action_items)
    ? (decision.action_items as string[]).filter(Boolean).slice(0, 6)
    : [];
  if (!summary && risks.length === 0 && actions.length === 0) return null;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      {summary && (
        <div style={{
          borderLeft: "3px solid var(--act)",
          paddingLeft: 14,
          fontFamily: "var(--font-serif)",
          fontSize: 16,
          fontWeight: 500,
          lineHeight: 1.4,
          color: "var(--label-primary)",
        }}>
          {summary}
        </div>
      )}
      {(risks.length > 0 || actions.length > 0) && (
        <div style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
          gap: 8,
        }}>
          {risks.map((r, i) => (
            <div key={`r${i}`} title={r} style={pillStyle(true)}>
              <span style={{ marginRight: 6, flexShrink: 0 }}>⚠</span>
              <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r}</span>
            </div>
          ))}
          {actions.map((a, i) => (
            <div key={`a${i}`} title={a} style={pillStyle(false)}>
              <span style={{ marginRight: 6, flexShrink: 0 }}>✓</span>
              <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{a}</span>
            </div>
          ))}
        </div>
      )}
      {decisionAt && (
        <div style={{
          fontSize: 11, color: "var(--label-tertiary)",
          fontFamily: "var(--font-mono)", textAlign: "right",
        }}>
          AI verdict · {fmtRelative(decisionAt)}
        </div>
      )}
    </div>
  );
}

function pillStyle(risk: boolean): React.CSSProperties {
  return {
    display: "flex",
    alignItems: "center",
    minWidth: 0,
    padding: "10px 12px",
    borderRadius: 8,
    background: risk ? "var(--fill-red, rgba(255,59,48,0.06))" : "var(--fill-green, rgba(48,209,88,0.06))",
    border: `1px solid ${risk ? "var(--act-edge)" : "rgba(48,209,88,0.25)"}`,
    color: risk ? "var(--act)" : "var(--buy)",
    fontSize: 13,
    fontWeight: 500,
    lineHeight: 1.4,
    cursor: "default",
  };
}


// ─── 3-section grid (Price · Peers · News) ─────────────────────────
// Mirrors the portfolio PositionCard layout. Each section reads from
// stock_analyses via the /watchlist/all/detail backend response.
function ResearchingSectionGrid({ stock, onReadSources }: {
  stock: WatchlistStock;
  onReadSources: () => void;
}) {
  const v = stock.valuation_section ?? null;
  const p = stock.peer_section ?? null;
  const n = stock.news_section ?? null;

  if (!v && !p && !n) {
    // No analysis row at all — still surface the peers placeholder so
    // the user knows generation is in flight.
    return (
      <SectionCard
        icon={<IconUsersGroup size={14} />}
        title="Peers"
        verdict="NO_DATA"
        state="loading"
        loadingLabel="generating peers…"
      />
    );
  }

  const cols = [v, p, n].filter(Boolean).length;
  const fmtMetricVal = (val: number, metric: string) => {
    if (metric.includes("margin") || metric.includes("roe") || metric.includes("growth") || metric.includes("yield"))
      return `${Math.round(val * 100)}%`;
    return val.toFixed(1);
  };

  // Watchlist-context Price footer: show P/E now, the user's P/E target,
  // and the watching-since date instead of portfolio's QTY/AVG/LTP/DAY.
  const pe = stock.fundamentals?.pe_ratio ?? stock.fundamentals?.ttm_pe ?? null;
  const peTarget = stock.pe_target ?? null;
  const priceTarget = stock.price_target ?? null;
  const cmp = stock.fundamentals?.cmp ?? null;

  return (
    <div className="pcard-section-grid" style={{
      display: "grid",
      gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))`,
      gap: 10,
    }}>
      {v && (
        <SectionCard
          icon={<IconChartCandle size={14} />}
          title="Price"
          verdict={v.verdict}
          footer={
            <div className="section-card-footer-3col" style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 4 }}>
              <FootStat label="P/E" value={pe != null ? `${pe.toFixed(1)}×` : "—"} />
              <FootStat label="P/E TGT" value={peTarget != null ? `${peTarget.toFixed(0)}×` : "—"} />
              <FootStat
                label="PX TGT"
                value={priceTarget != null
                  ? `₹${Math.round(priceTarget)}`
                  : "—"}
                color={cmp && priceTarget && cmp <= priceTarget ? "var(--buy)" : undefined}
              />
            </div>
          }
        >
          {(v.signals || []).slice(0, 3).map((s, i) => (
            <SignalRow key={i} label={s.label}
              color={s.direction === "negative" || s.direction === "red" ? "red" : s.direction === "positive" || s.direction === "green" ? "green" : "neutral"}
              icon={<IconAlertTriangle size={11} />} />
          ))}
          {(!v.signals || v.signals.length === 0) && (
            <div style={{ fontSize: 12, color: "var(--label-tertiary)", padding: "7px 0" }}>No signals</div>
          )}
        </SectionCard>
      )}

      {p ? (
        p.verdict === "NO_DATA" || !p.peer_count ? (
          <SectionCard
            icon={<IconUsersGroup size={14} />}
            title="Peers"
            verdict="NO_DATA"
            state="loading"
            loadingLabel="generating peers…"
          />
        ) : (
          <SectionCard
            icon={<IconUsersGroup size={14} />}
            title="Peers"
            verdict={p.verdict}
            footer={
              <div style={{ fontSize: 10, color: "var(--label-quaternary)" }}>
                {(() => {
                  const breakdown = p.metric_breakdown || [];
                  const lagCount = breakdown.filter((mb) => mb.status === "lag").length;
                  return lagCount > 0
                    ? `Behind on ${lagCount} of ${breakdown.length}`
                    : `${p.peer_count || 0} peers matched`;
                })()}
              </div>
            }
          >
            {p.peer_count != null && p.peer_count > 0 && !p.peer_set_weak && (
              <div style={{
                display: "inline-flex", alignSelf: "flex-start", alignItems: "center", gap: 5,
                background: "var(--buy-bg)", borderRadius: 999, padding: "2px 8px",
                fontSize: 10, color: "var(--buy)", marginBottom: 2,
              }}>
                <IconCircleCheck size={11} /> {p.peer_count} peers matched
              </div>
            )}
            {(p.metric_breakdown || []).slice(0, 4).map((mb, i) => (
              <MetricRow
                key={i}
                label={mb.metric.replace(/_/g, " ").replace(/\b1y\b/, "growth").replace(/revenue growth/, "Rev growth").replace(/net profit margin/, "Net margin")}
                value={`${fmtMetricVal(mb.stock_value, mb.metric)} vs ${fmtMetricVal(mb.peer_median, mb.metric)}`}
                color={mb.status === "lag" ? "red" : mb.status === "lead" ? "green" : "neutral"}
              />
            ))}
            {(!p.metric_breakdown || p.metric_breakdown.length === 0) && (
              <div style={{ fontSize: 12, color: "var(--label-tertiary)", padding: "7px 0" }}>No metric data</div>
            )}
          </SectionCard>
        )
      ) : (
        <SectionCard
          icon={<IconUsersGroup size={14} />}
          title="Peers"
          verdict="NO_DATA"
          state="loading"
          loadingLabel="generating peers…"
        />
      )}

      {n && (
        <SectionCard
          icon={<IconNews size={14} />}
          title="News"
          verdict={n.verdict}
          freshness={newsFreshnessLabel(n.newest_headline_at)}
          footer={
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <span style={{ fontSize: 10, color: "var(--label-quaternary)" }}>
                {(n.source_count || 0)} source{(n.source_count || 0) === 1 ? "" : "s"}
              </span>
              <button onClick={onReadSources}
                style={{
                  background: "none", border: "none", padding: 0,
                  color: "var(--label-secondary)", cursor: "pointer",
                  fontSize: 11, fontWeight: 500,
                  display: "inline-flex", alignItems: "center", gap: 3,
                }}>
                Read sources <IconArrowRight size={11} />
              </button>
            </div>
          }
        >
          {n.sector && (
            <div style={{
              display: "inline-flex", alignSelf: "flex-start", alignItems: "center", gap: 5,
              background: "var(--bg-secondary)", border: "1px solid var(--separator-light)",
              borderRadius: 999, padding: "2px 8px",
              fontSize: 10, color: "var(--label-secondary)", marginBottom: 2,
            }}>
              {n.sector}
            </div>
          )}
          {(n.stock_signals || []).slice(0, 3).map((s, i) => (
            <SignalRow key={i} label={s.label}
              color={s.direction === "negative" || s.direction === "red" ? "red" : s.direction === "positive" || s.direction === "green" ? "green" : "neutral"} />
          ))}
          {(!n.stock_signals || n.stock_signals.length === 0) && (
            <div style={{ fontSize: 12, color: "var(--label-tertiary)", padding: "7px 0" }}>No news signals</div>
          )}
        </SectionCard>
      )}
    </div>
  );
}



// ─── News accordion (per-symbol) ────────────────────────────────────
// Mirrors the Journal's collapsed-by-default pattern. On first expand,
// fetches /api/news/inbox?scope=symbol:<X>&limit=20 and renders the
// headlines as a vertical thread. Cached in component state — re-opens
// don't re-fetch unless the user clicks Refresh.
interface NewsItem {
  title: string;
  url?: string | null;
  source?: string | null;
  published_at?: string | null;
}

interface InboxMeta {
  fetched_at?: string | null;
  next_refresh_at?: string | null;
}

// Compact "1h ago" / "in 1h 20m" formatter for cache hints. Returns null
// when the input is null so callers can render nothing.
function fmtAgo(iso?: string | null): string | null {
  if (!iso) return null;
  const t = new Date(iso).getTime();
  if (!Number.isFinite(t)) return null;
  const sec = Math.round((Date.now() - t) / 1000);
  if (sec < 30) return "just now";
  if (sec < 60) return `${sec}s ago`;
  if (sec < 3600) return `${Math.round(sec / 60)}m ago`;
  if (sec < 86400) {
    const h = Math.floor(sec / 3600);
    const m = Math.round((sec % 3600) / 60);
    return m > 0 ? `${h}h ${m}m ago` : `${h}h ago`;
  }
  return `${Math.round(sec / 86400)}d ago`;
}

function fmtIn(iso?: string | null): string | null {
  if (!iso) return null;
  const t = new Date(iso).getTime();
  if (!Number.isFinite(t)) return null;
  const sec = Math.round((t - Date.now()) / 1000);
  if (sec <= 0) return "due now";
  if (sec < 60) return `in ${sec}s`;
  if (sec < 3600) return `in ${Math.round(sec / 60)}m`;
  const h = Math.floor(sec / 3600);
  const m = Math.round((sec % 3600) / 60);
  return m > 0 ? `in ${h}h ${m}m` : `in ${h}h`;
}

// Module-level meta cache. The RSS aggregator's freshness is shared
// across symbols (it's the SAME 2h-cached RSS pool), so all News chips
// show the same "last checked / next refresh in" — fetch once on
// first card mount and let every subsequent card read from this state.
let _sharedInboxMeta: InboxMeta | null = null;
let _sharedInboxMetaInflight: Promise<InboxMeta> | null = null;

async function fetchSharedInboxMeta(): Promise<InboxMeta> {
  if (_sharedInboxMeta) return _sharedInboxMeta;
  if (_sharedInboxMetaInflight) return _sharedInboxMetaInflight;
  _sharedInboxMetaInflight = api
    .get<InboxMeta>("/api/news/inbox?limit=1")
    .then((r) => {
      _sharedInboxMeta = { fetched_at: r.fetched_at, next_refresh_at: r.next_refresh_at };
      return _sharedInboxMeta;
    })
    .catch(() => ({} as InboxMeta))
    .finally(() => {
      _sharedInboxMetaInflight = null;
    });
  return _sharedInboxMetaInflight;
}

function NewsAccordion({ symbol }: { symbol: string }) {
  const [open, setOpen] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [items, setItems] = useState<NewsItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [meta, setMeta] = useState<InboxMeta>(() => _sharedInboxMeta ?? {});

  // Bootstrap the shared meta on mount so the chip can render before the
  // user opens the section. Updates again from the per-symbol response on
  // expand (in case that response carries fresher cache info).
  useEffect(() => {
    if (_sharedInboxMeta) {
      setMeta(_sharedInboxMeta);
      return;
    }
    let cancelled = false;
    fetchSharedInboxMeta().then((m) => {
      if (!cancelled) setMeta(m);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  async function fetchNews(force = false) {
    if (loaded && !force) return;
    setLoading(true);
    try {
      const r = await api.get<{ items: NewsItem[] } & InboxMeta>(
        `/api/news/inbox?scope=symbol:${encodeURIComponent(symbol)}&limit=20`,
      );
      setItems(r.items || []);
      setMeta({ fetched_at: r.fetched_at, next_refresh_at: r.next_refresh_at });
      setLoaded(true);
    } catch {
      setItems([]);
      setLoaded(true);
    } finally {
      setLoading(false);
    }
  }

  function toggle() {
    const next = !open;
    setOpen(next);
    if (next && !loaded) fetchNews(false);
  }

  const checked = fmtAgo(meta.fetched_at);
  const refreshIn = fmtIn(meta.next_refresh_at);

  return (
    <div>
      <button
        onClick={toggle}
        aria-expanded={open}
        style={{
          background: "transparent", border: 0, padding: 0,
          cursor: "pointer", display: "inline-flex", alignItems: "center", gap: 8,
          fontFamily: "inherit", width: "100%",
        }}
      >
        <span style={{
          fontSize: 11.5, fontWeight: 600, color: "var(--label-tertiary)",
          textTransform: "uppercase", letterSpacing: "0.08em",
        }}>News</span>
        {loaded && (
          <span style={{
            fontFamily: "var(--font-mono)", fontSize: 11,
            color: "var(--label-quaternary)",
          }}>{items.length} item{items.length === 1 ? "" : "s"}</span>
        )}
        {checked && (
          <span style={{ fontSize: 11, color: "var(--label-tertiary)" }}>
            · last checked <span style={{ color: "var(--label-secondary)" }}>{checked}</span>
            {refreshIn && <> · next refresh <span style={{ color: "var(--label-secondary)" }}>{refreshIn}</span></>}
          </span>
        )}
        <span style={{ marginLeft: "auto", fontSize: 11, color: "var(--label-tertiary)" }}>
          {open ? "Hide" : "Show all"}
        </span>
      </button>

      {open && (
        <div style={{ marginTop: 10, paddingLeft: 4, borderLeft: "1px solid var(--separator-light)" }}>
          {loading && <div style={{ padding: "8px 12px", fontSize: 12, color: "var(--label-tertiary)" }}>Loading…</div>}
          {!loading && items.length === 0 && (
            <div style={{ padding: "8px 12px", fontSize: 12, color: "var(--label-tertiary)" }}>
              No recent headlines for {symbol}.
            </div>
          )}
          {!loading && items.map((n, i) => (
            <div key={i} style={{
              padding: "8px 12px",
              display: "grid", gridTemplateColumns: "auto 1fr",
              gap: 10, alignItems: "baseline",
              fontSize: 13, lineHeight: 1.45,
              borderBottom: "1px solid var(--separator-light)",
            }}>
              <span style={{
                fontFamily: "var(--font-mono)", fontSize: 11,
                color: "var(--label-tertiary)", whiteSpace: "nowrap",
              }}>{fmtRelative(n.published_at)}</span>
              <div style={{ minWidth: 0 }}>
                {n.url ? (
                  <a href={n.url} target="_blank" rel="noopener noreferrer" style={{
                    color: "var(--label-primary)", textDecoration: "none",
                  }}>{n.title}</a>
                ) : (
                  <span style={{ color: "var(--label-primary)" }}>{n.title}</span>
                )}
                {n.source && (
                  <span style={{ marginLeft: 8, fontSize: 11, color: "var(--label-tertiary)" }}>
                    · {n.source}
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
