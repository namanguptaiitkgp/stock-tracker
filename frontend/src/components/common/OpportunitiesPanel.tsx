"use client";

import React, { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { openStockDetail } from "@/lib/stock-detail";
import { fmtRelative, fmtN, pctStr } from "@/lib/format";
import Sparkline from "./Sparkline";
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

// ── Section payload shapes (mirror today.py /brief portfolio holding items) ──
interface ValuationSection {
  verdict: string;
  score: number | null;
  signals: Array<{ label: string; direction?: string }> | null;
  hard_failed: string[] | null;
  last_run_at: string | null;
}
interface PeerSection {
  verdict: string;
  metric_breakdown: Array<{ metric: string; stock_value: number; peer_median: number; status: string }> | null;
  peer_summary: string | null;
  peer_count: number | null;
  peer_set_weak: boolean;
  last_run_at: string | null;
  peers_generated_at: string | null;
}
interface NewsSection {
  verdict: string;
  stock_signals: Array<{ label: string; direction?: string }> | null;
  source_count: number | null;
  qualitative: Record<string, unknown> | null;
  sector: string | null;
  last_run_at: string | null;
  newest_headline_at: string | null;
}

interface OpportunityItem {
  symbol: string;
  name: string | null;
  exchange: string;
  score: number;
  sentiment: string;
  summary: string | null;
  headline_count: number;
  discovered_at: string | null;
  has_nse_fno: boolean;
  has_bse_fno: boolean;
  sector: string | null;
  industry: string | null;
  cmp: number | null;
  market_cap: number | null;
  pe_ratio: number | null;
  day_change_pct: number | null;
  report_id: number | null;
  // 3-section grid (Price / Peers / News) — populated by the backend
  // from stock_analyses. May be null for brand-new opportunities that
  // haven't been analyzed yet.
  valuation_section: ValuationSection | null;
  peer_section: PeerSection | null;
  news_section: NewsSection | null;
}

interface OpportunitiesResponse {
  items: OpportunityItem[];
  report_date: string | null;
}

interface WatchlistOption {
  id: number;
  name: string;
  is_system?: boolean;
}

interface HeadlineData {
  title: string;
  source: string;
  sentiment: string;
  url?: string;
}

interface ChartCandle { time: string; close: number | null }
interface ChartResponse {
  candles: ChartCandle[];
  prev_close: number | null;
  current_price: number | null;
}

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

// Replaced the OpportunitySignalPills block by promoting the 3-section
// grid (Price / Peers / News) to the primary signal surface on the
// opportunity card. Each SectionCard header already carries the
// verdict pill, so the redundant "Today" row was removed.

// ── 3-section grid (Price · Peers · News) ────────────────────────
function OpportunitySectionGrid({ item, onReadSources }: {
  item: OpportunityItem;
  onReadSources: () => void;
}) {
  const v = item.valuation_section;
  const p = item.peer_section;
  const n = item.news_section;

  // Skip the grid entirely for brand-new opportunities that have no
  // analysis row yet AND no peers yet. They'll get analyzed by the next
  // post-close pipeline run.
  const hasAnyData = v || p || n;
  if (!hasAnyData) {
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

  // Count visible columns so the grid sizes match the number of cards.
  const cols = [v, p, n].filter(Boolean).length;
  const fmtMetricVal = (val: number, metric: string) => {
    if (metric.includes("margin") || metric.includes("roe") || metric.includes("growth") || metric.includes("yield"))
      return `${Math.round(val * 100)}%`;
    return val.toFixed(1);
  };
  const fmtPE = item.pe_ratio != null ? item.pe_ratio.toFixed(1) : "—";
  const fmtMcap = item.market_cap != null
    ? item.market_cap >= 1_00_000 ? `₹${(item.market_cap / 1_00_000).toFixed(1)}L Cr` : `₹${Math.round(item.market_cap)}Cr`
    : "—";

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
              <FootStat label="P/E" value={fmtPE} />
              <FootStat label="MCAP" value={fmtMcap} />
              <FootStat label="SCORE" value={item.score >= 0 ? `+${item.score}` : `${item.score}`}
                color={item.score >= 0 ? "var(--buy)" : "var(--act)"} />
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
                {(n.source_count || item.headline_count || 0)} source{(n.source_count || item.headline_count || 0) === 1 ? "" : "s"}
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

// ── Opportunity Card ──────────────────────────────────────────────
function OpportunityCard({
  item,
  watchlists,
  onTriaged,
}: {
  item: OpportunityItem;
  watchlists: WatchlistOption[];
  onTriaged: (symbol: string) => void;
}) {
  const [chart, setChart] = useState<number[] | null>(null);
  const [livePrice, setLivePrice] = useState<number | null>(null);
  const [livePrevClose, setLivePrevClose] = useState<number | null>(null);
  const [headlinesOpen, setHeadlinesOpen] = useState(false);
  const [headlines, setHeadlines] = useState<HeadlineData[] | null>(null);
  const [headlinesLoading, setHeadlinesLoading] = useState(false);
  const [headlinesDate, setHeadlinesDate] = useState<string | null>(null);
  const [triaging, setTriaging] = useState(false);
  const [wlPickerOpen, setWlPickerOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      await acquireChartSlot();
      if (cancelled) { releaseChartSlot(); return; }
      try {
        const d = await api.get<ChartResponse>(
          `/api/market-data/chart/${item.symbol}?range=1M&exchange=${item.exchange}`,
        );
        if (cancelled) return;
        setChart(d.candles.map((c) => c.close).filter((v): v is number => v != null));
        setLivePrice(d.current_price ?? null);
        setLivePrevClose(d.prev_close ?? null);
      } catch {
        if (!cancelled) setChart(null);
      } finally {
        releaseChartSlot();
      }
    })();
    return () => { cancelled = true; };
  }, [item.symbol, item.exchange]);

  const cmp = livePrice ?? item.cmp;
  let dayChangePct = item.day_change_pct;
  if (livePrice != null && livePrevClose != null && livePrevClose !== 0) {
    dayChangePct = ((livePrice - livePrevClose) / livePrevClose) * 100;
  } else if (chart && chart.length >= 2) {
    const last = chart[chart.length - 1];
    const prev = chart[chart.length - 2];
    dayChangePct = prev ? ((last - prev) / prev) * 100 : null;
  }
  const isUp = (dayChangePct ?? 0) >= 0;

  async function loadHeadlines() {
    if (headlines !== null) return;
    setHeadlinesLoading(true);
    try {
      const data = await api.get<{ headlines: HeadlineData[]; report_date: string | null }>(
        `/api/news/opportunities/${item.symbol}/headlines`
      );
      setHeadlines(data.headlines);
      setHeadlinesDate(data.report_date);
    } catch {
      setHeadlines([]);
    } finally {
      setHeadlinesLoading(false);
    }
  }

  function toggleHeadlines() {
    setHeadlinesOpen((v) => {
      if (!v) loadHeadlines();
      return !v;
    });
  }

  async function triage(action: "watchlist" | "not_interested", targetWlId?: number) {
    setTriaging(true);
    try {
      await api.post("/api/news/opportunities/triage", {
        action,
        symbol: item.symbol,
        report_id: item.report_id,
        target_watchlist_id: targetWlId || null,
        name: item.name,
        notes: item.summary ? `Score: ${item.score} | ${item.summary}` : null,
      });
      onTriaged(item.symbol);
    } catch { /* ignore */ }
    finally { setTriaging(false); }
  }

  const isPositive = item.sentiment === "bullish";
  const isNegative = item.sentiment === "bearish";
  const sectorDisplay = [item.industry, item.sector].filter(Boolean).join(" · ");

  return (
    <article style={{
      background: "var(--bg-primary)",
      border: `1px solid ${isPositive ? "rgba(52,199,89,0.25)" : isNegative ? "rgba(255,59,48,0.25)" : "var(--separator-light)"}`,
      borderRadius: 16,
      padding: "18px 20px",
      boxShadow: "var(--shadow-sm)",
      display: "flex", flexDirection: "column", gap: 14,
      marginBottom: 14,
      opacity: triaging ? 0.5 : 1,
      transition: "opacity 0.15s",
    }}>
      {/* Header */}
      <header className="ocard-header" style={{
        display: "grid", gridTemplateColumns: "1fr auto auto",
        alignItems: "center", gap: 16,
      }}>
        <div style={{ display: "flex", gap: 12, alignItems: "center", minWidth: 0 }}>
          <div style={{
            width: 40, height: 40, borderRadius: 9,
            display: "grid", placeItems: "center",
            fontFamily: "var(--font-mono)", fontWeight: 600, fontSize: 12,
            background: isPositive ? "var(--buy-bg, rgba(48,209,88,0.08))" : isNegative ? "var(--act-bg)" : "var(--bg-secondary)",
            color: isPositive ? "var(--buy)" : isNegative ? "var(--act)" : "var(--label-secondary)",
            border: `1px solid ${isPositive ? "rgba(52,199,89,0.3)" : isNegative ? "rgba(255,59,48,0.3)" : "var(--separator-light)"}`,
            flexShrink: 0,
          }}>
            {item.symbol.slice(0, 2)}
          </div>
          <div style={{ minWidth: 0, flex: 1 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
              <button
                onClick={() => openStockDetail(item.symbol, item.exchange)}
                style={{
                  fontFamily: "var(--font-mono)", fontWeight: 600, fontSize: 15,
                  color: "var(--label-primary)", background: "transparent",
                  border: 0, padding: 0, cursor: "pointer",
                }}
              >{item.symbol}</button>
              {(item.has_nse_fno || item.has_bse_fno) && (
                <span style={{
                  fontSize: 9, fontWeight: 700, padding: "1px 5px", borderRadius: 4,
                  background: "rgba(255,149,0,0.12)", color: "#C77700",
                }}>F&O</span>
              )}
              <span style={{
                fontSize: 12, fontWeight: 700, fontFamily: "var(--font-mono)",
                padding: "2px 8px", borderRadius: 99,
                background: isPositive ? "rgba(52,199,89,0.1)" : isNegative ? "rgba(255,59,48,0.1)" : "var(--fill-secondary)",
                color: isPositive ? "#248A3D" : isNegative ? "#D70015" : "var(--label-secondary)",
              }}>
                {item.score > 0 ? `+${item.score}` : item.score}
              </span>
            </div>
            <div style={{
              fontSize: 13, color: "var(--label-tertiary)", marginTop: 2,
              whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
            }}>
              {item.name || "—"}
              {sectorDisplay && <span style={{ color: "var(--label-quaternary)" }}> · {sectorDisplay}</span>}
            </div>
            {item.discovered_at && (
              <div style={{ fontSize: 11, color: "var(--label-quaternary)", marginTop: 2 }}>
                Discovered {fmtRelative(item.discovered_at)}
              </div>
            )}
          </div>
        </div>

        <div className="ocard-spark" style={{ padding: "0 6px" }}>
          {chart && chart.length > 1 ? (
            <Sparkline data={chart} width={96} height={32} showGrid={false} />
          ) : (
            <div style={{ width: 96, height: 32, background: "var(--fill-gray)", borderRadius: 4 }} />
          )}
        </div>

        <div className="ocard-price" style={{ textAlign: "right", minWidth: 110 }}>
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

      {/* Summary */}
      {item.summary && (
        <div style={{ fontSize: 12.5, color: "var(--label-secondary)", lineHeight: 1.5 }}>
          {item.summary}
        </div>
      )}

      {/* 3-section grid (Price · Peers · News) — same shape as portfolio
          PositionCard. Peers card shows a "generating peers…" placeholder
          when peer_section is null; the backend has already dispatched
          warm_peers_for_symbol so it materializes on next reload. */}
      <OpportunitySectionGrid item={item} onReadSources={toggleHeadlines} />

      {/* Headlines accordion */}
      <div style={{ borderTop: "1px solid var(--separator-light)", paddingTop: 12 }}>
        <button
          onClick={toggleHeadlines}
          style={{
            background: "none", border: "none", padding: "2px 0",
            cursor: "pointer", fontSize: 11.5, color: "var(--label-tertiary)",
            display: "flex", alignItems: "center", gap: 5, fontWeight: 500,
          }}
        >
          <span style={{
            display: "inline-block", transition: "transform 0.15s",
            transform: headlinesOpen ? "rotate(90deg)" : "rotate(0deg)",
            fontSize: 10,
          }}>&#9654;</span>
          Headlines{item.headline_count > 0 && ` (${item.headline_count})`}
        </button>

        {headlinesOpen && (
          <div style={{ padding: "8px 0 4px", display: "flex", flexDirection: "column", gap: 4 }}>
            {headlinesLoading ? (
              <div style={{ fontSize: 11, color: "var(--label-tertiary)" }}>Loading headlines...</div>
            ) : headlines && headlines.length > 0 ? (
              <>
                {headlines.map((h, i) => {
                  const dotColor = h.sentiment === "bullish" ? "#34C759" : h.sentiment === "bearish" ? "#FF3B30" : "#8E8E93";
                  const titleNode = h.url ? (
                    <a
                      href={h.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      style={{ color: "inherit", textDecoration: "none" }}
                      onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.textDecoration = "underline"; }}
                      onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.textDecoration = "none"; }}
                    >
                      {h.title}
                    </a>
                  ) : (
                    h.title
                  );
                  return (
                    <div key={i} style={{ display: "flex", alignItems: "flex-start", fontSize: 11.5, lineHeight: 1.4, color: "var(--label-secondary)" }}>
                      <span style={{ display: "inline-block", width: 6, height: 6, borderRadius: "50%", backgroundColor: dotColor, marginRight: 6, marginTop: 5, flexShrink: 0 }} />
                      <span>
                        {titleNode}
                        {h.source && <span style={{ color: "var(--label-quaternary)", marginLeft: 4 }}>— {h.source}</span>}
                      </span>
                    </div>
                  );
                })}
                {headlinesDate && (
                  <div style={{ fontSize: 10, color: "var(--label-quaternary)", marginTop: 2 }}>
                    Based on {headlinesDate} scan
                  </div>
                )}
              </>
            ) : (
              <div style={{ fontSize: 11, color: "var(--label-quaternary)" }}>
                Headlines not available for this scan
              </div>
            )}
          </div>
        )}
      </div>

      {/* Triage actions */}
      <div style={{ display: "flex", gap: 8, borderTop: "1px solid var(--separator-light)", paddingTop: 14, position: "relative" }}>
        <div style={{ position: "relative", flex: 1 }}>
          <button
            onClick={() => setWlPickerOpen((v) => !v)}
            disabled={triaging}
            style={{
              width: "100%",
              padding: "8px 0", borderRadius: 8,
              fontSize: 12, fontWeight: 600,
              background: "var(--label-primary)", color: "var(--bg-primary)",
              border: "none", cursor: triaging ? "wait" : "pointer",
              display: "flex", alignItems: "center", justifyContent: "center", gap: 4,
            }}
          >
            + Add to Watchlist
            <span style={{ fontSize: 10, opacity: 0.7 }}>▾</span>
          </button>
          {wlPickerOpen && (
            <div style={{
              position: "absolute", bottom: "100%", left: 0, right: 0,
              marginBottom: 4, background: "var(--bg-primary)",
              border: "1px solid var(--separator)", borderRadius: 8,
              boxShadow: "var(--shadow-lg, 0 8px 24px rgba(0,0,0,0.3))",
              zIndex: 50, overflow: "hidden",
              maxHeight: 200, overflowY: "auto",
            }}>
              {watchlists.length === 0 ? (
                <button
                  onClick={() => { setWlPickerOpen(false); triage("watchlist"); }}
                  style={{
                    width: "100%", padding: "10px 14px", fontSize: 12,
                    background: "transparent", border: "none", color: "var(--label-secondary)",
                    cursor: "pointer", textAlign: "left",
                  }}
                >
                  Default watchlist
                </button>
              ) : (
                watchlists.map((wl) => (
                  <button
                    key={wl.id}
                    onClick={() => { setWlPickerOpen(false); triage("watchlist", wl.id); }}
                    style={{
                      width: "100%", padding: "10px 14px", fontSize: 12,
                      background: "transparent", border: "none",
                      borderBottom: "1px solid var(--separator-light)",
                      color: "var(--label-primary)", cursor: "pointer",
                      textAlign: "left",
                    }}
                    onMouseEnter={(e) => { (e.target as HTMLElement).style.background = "var(--bg-secondary)"; }}
                    onMouseLeave={(e) => { (e.target as HTMLElement).style.background = "transparent"; }}
                  >
                    {wl.name}
                  </button>
                ))
              )}
            </div>
          )}
        </div>
        <button
          onClick={() => triage("not_interested")}
          disabled={triaging}
          style={{
            flex: 1,
            padding: "8px 0", borderRadius: 8,
            fontSize: 12, fontWeight: 600,
            background: "transparent", color: "var(--label-tertiary)",
            border: "1px solid var(--separator)", cursor: triaging ? "wait" : "pointer",
          }}
        >
          Not interested
        </button>
      </div>

      <style jsx>{`
        /* Mobile rules for the OpportunityCard. The 3-section grid stacks
           via the global rule in SectionCard.tsx; these handle the header
           and the surrounding card layout. */
        @media (max-width: 720px) {
          /* Hide the sparkline column entirely — it competes with the
             symbol/name and price for a tight viewport. Price + day-change
             stay; chart already lives in the stock-detail panel deep dive. */
          :global(.ocard-header) {
            grid-template-columns: 1fr auto !important;
            gap: 10px !important;
          }
          :global(.ocard-spark) { display: none !important; }
          :global(.ocard-price) { min-width: auto !important; }
        }
      `}</style>
    </article>
  );
}

// ── Main panel ────────────────────────────────────────────────────
interface OpportunitiesPanelProps {
  // Lifted up so a parent rendering this inside a tab can show the
  // current count in the tab label. Optional.
  onCountChange?: (n: number) => void;
}

export default function OpportunitiesPanel({ onCountChange }: OpportunitiesPanelProps = {}) {
  const [items, setItems] = useState<OpportunityItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [watchlists, setWatchlists] = useState<WatchlistOption[]>([]);
  const [filter, setFilter] = useState<"all" | "bullish" | "bearish" | "neutral">("all");
  const [fnoOnly, setFnoOnly] = useState(false);
  const [sort, setSort] = useState<"strongest" | "newest">("strongest");

  useEffect(() => { onCountChange?.(items.length); }, [items.length, onCountChange]);

  const load = useCallback(async () => {
    try {
      const [opps, wls] = await Promise.all([
        api.get<OpportunitiesResponse>("/api/news/opportunities"),
        api.get<WatchlistOption[]>("/api/watchlists"),
      ]);
      setItems(opps.items);
      setWatchlists((wls || []).filter((w) => !w.is_system));
    } catch {
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    const handler = () => { load(); };
    window.addEventListener("news-refreshed", handler);
    return () => window.removeEventListener("news-refreshed", handler);
  }, [load]);

  function handleTriaged(symbol: string) {
    setItems((prev) => prev.filter((i) => i.symbol !== symbol));
  }

  const filteredItems = React.useMemo(() => {
    let result = [...items];
    if (fnoOnly) {
      result = result.filter((item) => item.has_nse_fno || item.has_bse_fno);
    }
    if (filter !== "all") {
      result = result.filter((item) => item.sentiment === filter);
    }
    result.sort((a, b) => {
      if (sort === "strongest") {
        return Math.abs(b.score) - Math.abs(a.score);
      }
      return (b.discovered_at ?? "").localeCompare(a.discovered_at ?? "");
    });
    return result;
  }, [items, fnoOnly, filter, sort]);

  const counts = React.useMemo(() => {
    let bullish = 0, bearish = 0, neutral = 0, fno = 0;
    for (const item of items) {
      if (item.sentiment === "bullish") bullish++;
      else if (item.sentiment === "bearish") bearish++;
      else neutral++;
      if (item.has_nse_fno || item.has_bse_fno) fno++;
    }
    return { all: items.length, bullish, bearish, neutral, fno };
  }, [items]);

  if (loading) {
    return (
      <div style={{ padding: 0 }}>
        <div style={{
          fontSize: 15, fontWeight: 700, marginBottom: 16,
          color: "var(--label-primary)",
        }}>New Opportunities</div>
        {[1, 2, 3].map((i) => (
          <div key={i} style={{
            height: 160, borderRadius: 16, marginBottom: 14,
            background: "var(--fill-secondary)",
            animation: "opp-pulse 1.5s ease-in-out infinite",
          }} />
        ))}
        <style>{`@keyframes opp-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }`}</style>
      </div>
    );
  }

  return (
    <div style={{ padding: 0 }}>
      <div style={{
        fontSize: 15, fontWeight: 700, marginBottom: 4,
        color: "var(--label-primary)",
      }}>New Opportunities</div>
      <div style={{
        fontSize: 12, color: "var(--label-tertiary)", marginBottom: 16,
      }}>
        {items.length === 0
          ? "No new opportunities — all clear"
          : `${items.length} stock${items.length === 1 ? "" : "s"} discovered in recent news`}
      </div>

      {items.length > 0 && (
        <div style={{
          display: "flex", justifyContent: "space-between", alignItems: "center",
          marginBottom: 14, gap: 8, flexWrap: "wrap",
        }}>
          <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
            {(["all", "bullish", "bearish", "neutral"] as const).map((f) => (
              <button
                key={f}
                onClick={() => setFilter(f)}
                style={{
                  padding: "4px 10px", borderRadius: 6, fontSize: 11, fontWeight: 500,
                  border: "1px solid",
                  borderColor: filter === f ? "var(--label-primary)" : "var(--separator)",
                  background: filter === f ? "var(--label-primary)" : "transparent",
                  color: filter === f ? "var(--bg-primary)" : "var(--label-secondary)",
                  cursor: "pointer",
                }}
              >
                {f.charAt(0).toUpperCase() + f.slice(1)} ({counts[f]})
              </button>
            ))}
            <button
              onClick={() => setFnoOnly((v) => !v)}
              style={{
                padding: "4px 10px", borderRadius: 6, fontSize: 11, fontWeight: 500,
                border: "1px solid",
                borderColor: fnoOnly ? "#FF9500" : "var(--separator)",
                background: fnoOnly ? "rgba(255,149,0,0.12)" : "transparent",
                color: fnoOnly ? "#C77700" : "var(--label-secondary)",
                cursor: "pointer",
              }}
            >
              F&O ({counts.fno})
            </button>
          </div>
          <select
            value={sort}
            onChange={(e) => setSort(e.target.value as typeof sort)}
            style={{
              padding: "4px 8px", borderRadius: 6, fontSize: 11,
              border: "1px solid var(--separator)",
              background: "var(--bg-secondary)", color: "var(--label-secondary)",
              cursor: "pointer",
            }}
          >
            <option value="strongest">Strongest signal</option>
            <option value="newest">Newest first</option>
          </select>
        </div>
      )}

      {items.length > 0 && filteredItems.length === 0 && (
        <div style={{
          padding: "24px 16px", textAlign: "center",
          fontSize: 13, color: "var(--label-tertiary)",
        }}>
          No {fnoOnly ? "F&O " : ""}{filter !== "all" ? `${filter} ` : ""}opportunities
        </div>
      )}

      {items.length === 0 && (
        <div style={{
          padding: "32px 16px", textAlign: "center",
          borderRadius: 16,
          background: "var(--fill-secondary)",
          border: "1px solid var(--separator-light)",
        }}>
          <div style={{ fontSize: 28, marginBottom: 8 }}>&#10003;</div>
          <div style={{ fontSize: 13, color: "var(--label-secondary)" }}>
            The morning pipeline will surface new companies here when it finds them in the news. Check back after the next scan.
          </div>
        </div>
      )}

      <div style={{ display: "flex", flexDirection: "column" }}>
        {filteredItems.map((item) => (
          <OpportunityCard
            key={item.symbol}
            item={item}
            watchlists={watchlists}
            onTriaged={handleTriaged}
          />
        ))}
      </div>
    </div>
  );
}
