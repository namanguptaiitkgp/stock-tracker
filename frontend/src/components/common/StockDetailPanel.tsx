"use client";

import React, { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import StockDetailTabs from "./StockDetailTabs";
import OverviewTab from "./tabs/OverviewTab";
import NewsTab from "./tabs/NewsTab";
import AnalysisTab from "./tabs/AnalysisTab";
import ActivityTab from "./tabs/ActivityTab";
import NotesTab from "./tabs/NotesTab";
import FundamentalReportTab from "./tabs/FundamentalReportTab";
import FreshnessChip from "@/components/ui/FreshnessChip";
import MobileBanner from "@/components/ui/MobileBanner";
import { useBodyScrollLock } from "@/lib/modal-utils";

function StatPill({ label, value, valueColor, sub }: { label: string; value: string; valueColor?: string; sub?: string | null }) {
  return (
    <div style={{
      flex: 1,
      padding: "8px 14px",
      background: "var(--bg-secondary)",
      minWidth: 0,
      display: "flex", flexDirection: "column", gap: 2,
    }}>
      <span style={{
        fontSize: 10, fontWeight: 600, color: "var(--label-tertiary)",
        textTransform: "uppercase", letterSpacing: "0.06em", whiteSpace: "nowrap",
      }}>{label}</span>
      <span style={{
        display: "flex", alignItems: "baseline", gap: 6,
        fontFamily: "var(--font-mono)", fontSize: 14, fontWeight: 600,
        color: valueColor || "var(--label-primary)",
        whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
      }}>
        {value}
        {sub && (
          <span style={{
            fontFamily: "var(--font-sans)", fontSize: 10.5, fontWeight: 500,
            color: "var(--label-tertiary)", letterSpacing: 0,
          }}>{sub}</span>
        )}
      </span>
    </div>
  );
}

function fmtShortDate(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (isNaN(d.getTime())) return null;
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "2-digit" }).replace(/(\d+)\s+(\w+)\s+(\d+)/, "$1 $2 '$3");
}

function SkeletonCard({ height = 120 }: { height?: number }) {
  return (
    <div
      className="animate-pulse"
      style={{
        height,
        background: "var(--bg-primary)",
        border: "1px solid var(--separator-light)",
        borderRadius: 12,
        padding: 16,
        boxShadow: "var(--shadow-card)",
      }}
    >
      <div style={{ width: "30%", height: 10, background: "var(--fill-gray)", borderRadius: 4, marginBottom: 12 }} />
      <div style={{ width: "70%", height: 16, background: "var(--fill-gray)", borderRadius: 4 }} />
    </div>
  );
}

function OverviewSkeleton() {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ display: "grid", gridTemplateColumns: "1.55fr 1fr", gap: 16 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 16, minWidth: 0 }}>
          <SkeletonCard height={280} />
          <SkeletonCard height={80} />
          <SkeletonCard height={120} />
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 16, minWidth: 0 }}>
          <SkeletonCard height={180} />
          <SkeletonCard height={140} />
          <SkeletonCard height={180} />
          <SkeletonCard height={200} />
        </div>
      </div>
      <SkeletonCard height={220} />
    </div>
  );
}

interface Holding {
  quantity: number;
  average_price: number;
  last_price: number;
  invested: number;
  current_value: number;
  pnl: number;
  pnl_pct: number;
  day_change_pct: number;
}

interface StockDetail {
  symbol: string;
  exchange: string;
  holding: Holding | null;
  last_price: number | null;
  volume: number | null;
  average_price: number | null;
  last_quantity: number | null;
  last_trade_time: string | null;
  net_change: number | null;
  change_pct: number | null;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number | null;
  buy_quantity: number | null;
  sell_quantity: number | null;
  oi: number | null;
  lower_circuit: number | null;
  upper_circuit: number | null;
  depth_buy: Array<{ price: number; quantity: number; orders: number }>;
  depth_sell: Array<{ price: number; quantity: number; orders: number }>;
  fundamentals: Record<string, unknown> | null;
  note: { content: string; updated_at: string | null };
}

interface Props {
  symbol: string;
  exchange?: string;
  initialTab?: string;
  onClose: () => void;
}

const TABS = ["Overview", "Fundamentals", "News", "Analysis", "Smart Money", "Notes"];

interface Technicals {
  high_52w: number | null;
  low_52w: number | null;
  high_52w_date: string | null;
  low_52w_date: string | null;
  pct_from_52w_high: number | null;
  pct_from_52w_low: number | null;
}

export default function StockDetailPanel({ symbol, exchange = "NSE", initialTab, onClose }: Props) {
  const [data, setData] = useState<StockDetail | null>(null);
  const [technicals, setTechnicals] = useState<Technicals | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // Distinct from `error` — set only when the quote fetch returns 401
  // (Kite token expired). Lets the panel render the tab bar + non-quote
  // tabs (Fundamentals, News, Analysis, Smart Money, Notes) instead of
  // collapsing to a single error banner.
  const [kiteAuthRequired, setKiteAuthRequired] = useState(false);
  const [noteText, setNoteText] = useState("");
  const [wlOpen, setWlOpen] = useState(false);
  const [wlList, setWlList] = useState<Array<{ id: number; name: string }>>([]);
  const [wlAdding, setWlAdding] = useState<number | null>(null);
  const [wlMsg, setWlMsg] = useState<string | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [analysisResult, setAnalysisResult] = useState<Record<string, unknown> | null>(null);
  // Default tab promotion: when Kite is disconnected, Overview is the
  // least useful starting point because its primary card (live quote) is
  // unavailable. We can't see kiteAuthRequired until the fetch resolves,
  // so this is re-evaluated in the fetch effect.
  const [activeTab, setActiveTab] = useState(initialTab && TABS.includes(initialTab) ? initialTab : "Overview");
  const [visitedTabs, setVisitedTabs] = useState<Set<string>>(new Set(["Overview", ...(initialTab ? [initialTab] : [])]));
  // Scroll position drives the collapsed header at <md. Anything > 80 px
  // collapses the verbose top section into a single-line ticker strip.
  const [headerCollapsed, setHeaderCollapsed] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Body scroll lock + emit modal:state-change so the FAB hides under us.
  useBodyScrollLock(true);

  useEffect(() => {
    setLoading(true);
    setError(null);
    setKiteAuthRequired(false);
    api.get<StockDetail>(`/api/market-data/quote/${symbol}?exchange=${exchange}`)
      .then((d) => {
        setData(d);
        setNoteText(d.note?.content || "");
      })
      .catch((e: unknown) => {
        // Detect 401 / "Not authenticated" specifically — the rest of the
        // panel's tabs read from non-Kite sources and should still render.
        const msg = e instanceof Error ? e.message : String(e);
        const status = (e as { status?: number } | null)?.status;
        if (status === 401 || /not authenticated|unauthori[sz]ed|401/i.test(msg)) {
          setKiteAuthRequired(true);
          // Promote Fundamentals as the active tab when Kite is down and
          // the user hadn't explicitly requested another tab.
          if (!initialTab) {
            setActiveTab("Fundamentals");
            setVisitedTabs((prev) => new Set(prev).add("Fundamentals"));
          }
        } else {
          setError(msg || "Failed to load");
        }
      })
      .finally(() => setLoading(false));
    // Fire technicals in parallel — needed for header pills
    api.get<Technicals>(`/api/market-data/technicals/${symbol}?exchange=${exchange}`)
      .then(setTechnicals)
      .catch(() => setTechnicals(null));
  }, [symbol, exchange, initialTab]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  function handleTabChange(tab: string) {
    setActiveTab(tab);
    setVisitedTabs((prev) => new Set(prev).add(tab));
  }

  async function toggleWatchlistPicker() {
    if (wlOpen) { setWlOpen(false); return; }
    try {
      const lists = await api.get<Array<{ id: number; name: string }>>("/api/watchlists/");
      setWlList(lists);
    } catch { /* ignore */ }
    setWlOpen(true);
    setWlMsg(null);
  }

  async function addToWatchlist(wlId: number) {
    setWlAdding(wlId);
    setWlMsg(null);
    try {
      await api.post(`/api/watchlists/${wlId}/stocks`, {
        symbol,
        name: data?.fundamentals ? String((data.fundamentals as Record<string, unknown>).name || "") : "",
        exchange,
      });
      setWlMsg(`Added to ${wlList.find((w) => w.id === wlId)?.name || "watchlist"}`);
      setTimeout(() => { setWlOpen(false); setWlMsg(null); }, 1500);
    } catch (err) {
      setWlMsg(err instanceof Error ? err.message : "Failed to add");
    } finally {
      setWlAdding(null);
    }
  }

  async function runAnalysis() {
    // Paid LLM call — confirm before firing. Matches the Delete-strategy
    // pattern set in the prior batch. The user can disable confirm() via
    // a future preference if we add one.
    if (!confirm(`Run a fresh AI analysis for ${symbol}? This makes an AI call and may take a minute.`)) {
      return;
    }
    setAnalyzing(true);
    setAnalysisResult(null);
    try {
      const result = await api.post<Record<string, unknown>>(`/api/stocks/${symbol}/analyze?exchange=${exchange}`, {});
      setAnalysisResult(result);
      const freshData = await api.get<StockDetail>(`/api/market-data/quote/${symbol}?exchange=${exchange}`);
      setData(freshData);
      setNoteText(freshData.note?.content || "");
    } catch (e) {
      setAnalysisResult({ error: e instanceof Error ? e.message : "Analysis failed" });
    } finally {
      setAnalyzing(false);
    }
  }

  // Header collapse on scroll. The tab-content scroll container is below
  // the header; once its scrollTop crosses 80 px, collapse the verbose
  // top section into a single-line strip so 165 px of vertical real
  // estate returns to the analyst.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    function onScroll() {
      const node = scrollRef.current;
      if (!node) return;
      setHeaderCollapsed(node.scrollTop > 80);
    }
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, []);

  const f = data?.fundamentals as Record<string, string | number | null | Record<string, string>> | null;

  return (
    <>
      {/* Backdrop */}
      <div className="fixed inset-0 z-40" style={{ background: "rgba(0,0,0,0.3)", backdropFilter: "blur(2px)" }} onClick={onClose} />

      {/* Panel */}
      <div
        className="sdp-panel fixed top-0 right-0 z-50 h-full w-[900px] max-w-full flex flex-col animate-slide-in"
        data-collapsed={headerCollapsed ? "true" : "false"}
        style={{ background: "var(--bg-primary)", borderLeft: "0.5px solid var(--separator-light)", boxShadow: "-8px 0 32px rgba(0,0,0,0.12)" }}
      >
        {/* Header — sticky at <md so the title + close stay reachable while
            tab content scrolls. Collapses to a single-line strip past
            scrollTop 80 (see useEffect on scrollRef). */}
        <div
          className="sdp-header px-5 pt-4 pb-3 flex flex-col gap-3"
          style={{ borderBottom: "0.5px solid var(--separator-light)" }}
        >
        {/* Mobile-only back button at <md (left side, mirrors × on right). */}
        <button
          className="sdp-mobile-back"
          onClick={onClose}
          aria-label="Close"
          style={{
            display: "none",
            width: 44, height: 44, borderRadius: 9,
            placeItems: "center",
            background: "transparent",
            color: "var(--label-tertiary)",
            border: "1px solid var(--separator)",
            cursor: "pointer", fontSize: 20,
            position: "absolute", top: 12, left: 12,
            zIndex: 1,
          }}
        >
          ←
        </button>
        {/* Top row: logo + title block + buttons */}
        <div className="flex items-center gap-4 sdp-header-row">
          {/* Logo square */}
          <a
            href={`https://www.google.com/finance/quote/${symbol}:${exchange}`}
            target="_blank"
            rel="noreferrer"
            title={`Open ${symbol} on Google Finance`}
            style={{
              width: 44, height: 44, borderRadius: 10,
              display: "grid", placeItems: "center", flexShrink: 0,
              background: "linear-gradient(135deg, var(--system-blue), color-mix(in srgb, var(--system-blue) 55%, var(--label-primary)))",
              color: "#fff",
              fontSize: 18,
              boxShadow: "var(--shadow-sm)",
              textDecoration: "none",
            }}
          >
            ◆
          </a>

          {/* Title block */}
          <div style={{ minWidth: 0, flex: 1 }}>
            <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
              <span style={{
                fontFamily: "var(--font-serif)",
                fontSize: 24, fontWeight: 700,
                letterSpacing: "-0.02em",
                color: "var(--label-primary)",
                lineHeight: 1.1,
              }}>{symbol}</span>
              {f?.name && (
                <span style={{ fontSize: 14, color: "var(--label-secondary)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", maxWidth: 240 }}>
                  {String(f.name)}
                </span>
              )}
            </div>
            {/* Subtitle row: chips instead of dot-separated string so
                multi-word values ("Consumer Cyclical") no longer wrap each
                word to its own line, and the FreshnessChip carries the
                Live status with a single visual idiom reused across all
                tabs. */}
            <div className="sdp-subtitle" style={{
              display: "flex", alignItems: "center", gap: 8,
              marginTop: 6, fontSize: 12, color: "var(--label-tertiary)",
              flexWrap: "wrap",
            }}>
              <span style={{
                padding: "2px 8px", borderRadius: 999,
                background: "var(--bg-secondary)",
                color: "var(--label-secondary)",
                fontSize: 11, fontWeight: 600,
                whiteSpace: "nowrap",
              }}>{exchange}</span>
              {f?.sector && (
                <span style={{
                  padding: "2px 8px", borderRadius: 999,
                  background: "var(--bg-secondary)",
                  color: "var(--label-secondary)",
                  fontSize: 11, fontWeight: 600,
                  whiteSpace: "nowrap",
                }}>{String(f.sector)}</span>
              )}
              {data?.last_trade_time && (
                <FreshnessChip kind="live" iso={data.last_trade_time} />
              )}
            </div>
          </div>

          {/* Right buttons */}
          <div className="flex items-center gap-2 sdp-actions" style={{ flexShrink: 0 }}>
            <div className="relative">
              <button
                onClick={toggleWatchlistPicker}
                title="Add to watchlist"
                aria-label="Add to watchlist"
                style={{
                  display: "grid", placeItems: "center",
                  width: 44, height: 44, borderRadius: 9,
                  fontSize: 18, fontWeight: 500, lineHeight: 1,
                  background: "var(--bg-primary)",
                  color: "var(--label-primary)",
                  border: "1px solid var(--separator)",
                  cursor: "pointer",
                }}
              >
                +
              </button>
              {wlOpen && (
                <div className="absolute right-0 top-full mt-1 w-52 rounded-xl shadow-xl z-20 py-1" style={{ background: "var(--bg-secondary)", border: "1px solid var(--separator-light)" }}>
                  {wlList.length === 0 ? (
                    <div className="px-3 py-2 text-xs" style={{ color: "var(--label-tertiary)" }}>No watchlists found</div>
                  ) : (
                    wlList.map((wl) => (
                      <button
                        key={wl.id}
                        onClick={() => addToWatchlist(wl.id)}
                        disabled={wlAdding === wl.id}
                        className="w-full text-left px-3 py-2 text-sm transition-colors disabled:opacity-50"
                        style={{ color: "var(--label-primary)" }}
                        onMouseEnter={(e) => (e.currentTarget.style.background = "var(--fill-gray)")}
                        onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
                      >
                        {wlAdding === wl.id ? "Adding..." : wl.name}
                      </button>
                    ))
                  )}
                  {wlMsg && (
                    <div className={`px-3 py-1.5 text-xs`} style={{ borderTop: "0.5px solid var(--separator-light)", color: wlMsg.startsWith("Added") ? "var(--system-green)" : "var(--system-red)" }}>
                      {wlMsg}
                    </div>
                  )}
                </div>
              )}
            </div>
            <button
              onClick={runAnalysis}
              disabled={analyzing}
              style={{
                display: "inline-flex", alignItems: "center", gap: 6,
                padding: "8px 14px", borderRadius: 9,
                fontSize: 13, fontWeight: 600,
                background: "var(--label-primary)",
                color: "var(--bg-primary)",
                border: "1px solid var(--label-primary)",
                cursor: analyzing ? "wait" : "pointer",
                opacity: analyzing ? 0.7 : 1,
                whiteSpace: "nowrap",
              }}
            >
              <span style={{ fontSize: 13 }}>⚡</span>
              {analyzing ? "Analyzing..." : "Run Analysis"}
            </button>
            <button
              onClick={onClose}
              aria-label="Close panel"
              style={{
                display: "grid", placeItems: "center",
                width: 44, height: 44, borderRadius: 9,
                background: "transparent",
                color: "var(--label-tertiary)",
                border: "1px solid var(--separator)",
                cursor: "pointer", fontSize: 18,
              }}
              onMouseEnter={(e) => (e.currentTarget.style.background = "var(--bg-secondary)")}
              onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
            >
              ×
            </button>
          </div>
        </div>

        {/* Bottom row: stat pills (full width, scrolls horizontally if needed) */}
        <div className="sdp-stat-pills" style={{
          display: "flex", alignItems: "stretch", gap: 1,
          background: "var(--separator-light)",
          borderRadius: 10, overflow: "hidden",
          border: "1px solid var(--separator-light)",
        }}>
          <StatPill
            label="Day Range"
            value={
              data?.high != null && data?.low != null
                ? `${data.low.toFixed(2)} — ${data.high.toFixed(2)}`
                : "—"
            }
            sub={
              data?.high != null && data?.low != null && data.high === data.low
                ? "Pre-open · single print so far"
                : null
            }
          />
          <StatPill label="52W Range" value={
            technicals?.high_52w != null && technicals?.low_52w != null
              ? `${technicals.low_52w.toFixed(2)} — ${technicals.high_52w.toFixed(2)}`
              : "—"
          } />
          <StatPill
            label="From 52W High"
            value={technicals?.pct_from_52w_high != null ? `${technicals.pct_from_52w_high >= 0 ? "+" : ""}${technicals.pct_from_52w_high.toFixed(1)}%` : "—"}
            valueColor={
              technicals?.pct_from_52w_high == null
                ? undefined
                : technicals.pct_from_52w_high >= 0
                  ? "var(--system-green)"
                  : "var(--system-red)"
            }
            sub={fmtShortDate(technicals?.high_52w_date)}
          />
        </div>
        </div>

        {/* Analysis banner */}
        {analyzing && (
          <div className="mx-4 mt-3 p-3 rounded-xl" style={{ background: "var(--fill-blue)", border: "1px solid rgba(0,122,255,0.15)" }}>
            <div className="flex items-center gap-2 mb-1">
              <svg className="animate-spin h-4 w-4" style={{ color: "var(--system-blue)" }} xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              <span className="text-sm font-medium" style={{ color: "var(--system-blue)" }}>Running Full Analysis...</span>
            </div>
            <p className="text-xs" style={{ color: "var(--label-tertiary)" }}>Refreshing fundamentals, news sentiment, MF activity, smart money, and AI verdict</p>
          </div>
        )}
        {!analyzing && analysisResult && (() => {
          const ar = analysisResult as Record<string, unknown>;
          const errMsg = ar.error ? String(ar.error) : null;
          const decision = ar.investment_decision as Record<string, unknown> | null;
          const verdict = decision ? String(decision.verdict || "N/A") : null;
          const confidence = decision ? String(decision.confidence || "?") : null;
          return (
            <div
              className="mx-4 mt-3 p-3 rounded-xl text-xs"
              style={{
                background: errMsg ? "rgba(255,59,48,0.06)" : "rgba(52,199,89,0.06)",
                border: errMsg ? "1px solid rgba(255,59,48,0.15)" : "1px solid rgba(52,199,89,0.15)",
                color: errMsg ? "var(--system-red)" : "var(--system-green)",
              }}
            >
              {errMsg ? (
                <span>Analysis failed: {errMsg}</span>
              ) : (
                <div className="flex items-center justify-between">
                  <span>
                    Analysis complete
                    {verdict && <>{" "}&mdash; Verdict: <span className="font-semibold">{verdict}</span> ({confidence}% confidence)</>}
                  </span>
                  <button onClick={() => setAnalysisResult(null)} style={{ color: "var(--label-tertiary)" }}>&times;</button>
                </div>
              )}
            </div>
          );
        })()}

        {/* Kite-401 inline banner — scoped to the panel, not the whole UI.
            The other tabs still render normally; only the quote-dependent
            Overview content needs to know live data is unavailable. */}
        {kiteAuthRequired && (
          <MobileBanner variant="error" mobileOnly={false}>
            <Link
              href="/settings"
              style={{ color: "inherit", textDecoration: "none", fontWeight: 600 }}
            >
              Live quote unavailable — Reconnect Kite →
            </Link>
          </MobileBanner>
        )}

        {/* Non-401 errors still show as a single banner — but the tab bar
            and content render normally below so the user can navigate
            away or pick another tab. Removed the `!error` gate. */}
        {error && !kiteAuthRequired && (
          <div className="p-4 m-4 rounded-xl text-sm" style={{ background: "rgba(255,59,48,0.06)", color: "var(--system-red)" }}>
            {error}
          </div>
        )}

        <>
          {/* Tab bar — visible immediately, even while quote loads */}
          <StockDetailTabs tabs={TABS} activeTab={activeTab} onChange={handleTabChange} />

          {/* Tab content */}
          <div ref={scrollRef} className="flex-1 overflow-y-auto">
            <div className="p-4" style={{ display: activeTab === "Overview" ? "block" : "none" }}>
              {kiteAuthRequired ? (
                <div style={{
                  padding: "32px 20px", textAlign: "center",
                  color: "var(--label-secondary)", fontSize: 13,
                  lineHeight: 1.6,
                }}>
                  <p style={{ marginBottom: 12 }}>
                    Live quote data requires a connected Kite session.
                  </p>
                  <p style={{ color: "var(--label-tertiary)", fontSize: 12 }}>
                    The other tabs (Fundamentals, News, Analysis, Smart Money, Notes)
                    read from cached sources and remain usable.
                  </p>
                </div>
              ) : data ? (
                <OverviewTab data={data} onSwitchTab={handleTabChange} />
              ) : (
                <OverviewSkeleton />
              )}
            </div>

              {visitedTabs.has("Fundamentals") && (
                <div className="p-4" style={{ display: activeTab === "Fundamentals" ? "block" : "none" }}>
                  <FundamentalReportTab symbol={symbol} exchange={exchange} />
                </div>
              )}

              {visitedTabs.has("News") && (
                <div className="p-4" style={{ display: activeTab === "News" ? "block" : "none" }}>
                  <NewsTab symbol={symbol} exchange={exchange} />
                </div>
              )}

              {visitedTabs.has("Analysis") && (
                <div className="p-4" style={{ display: activeTab === "Analysis" ? "block" : "none" }}>
                  <AnalysisTab symbol={symbol} exchange={exchange} />
                </div>
              )}

              {visitedTabs.has("Smart Money") && (
                <div className="p-4" style={{ display: activeTab === "Smart Money" ? "block" : "none" }}>
                  <ActivityTab symbol={symbol} livePctFrom52wHigh={technicals?.pct_from_52w_high ?? null} />
                </div>
              )}

              {visitedTabs.has("Notes") && (
                <div className="p-4" style={{ display: activeTab === "Notes" ? "block" : "none" }}>
                  <NotesTab
                    symbol={symbol}
                    noteText={noteText}
                    setNoteText={setNoteText}
                    lastUpdated={data?.note?.updated_at || null}
                  />
                </div>
              )}
            </div>
        </>
      </div>

      <style jsx global>{`
        @keyframes slideIn {
          from { transform: translateX(100%); }
          to { transform: translateX(0); }
        }
        .animate-slide-in {
          animation: slideIn 0.2s ease-out;
        }
        @keyframes livePulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.4; }
        }
        .live-pulse {
          animation: livePulse 1.6s infinite;
        }
        @keyframes sdp-slide-up {
          from { transform: translateY(100%); }
          to { transform: translateY(0); }
        }
        @media (max-width: 720px) {
          .sdp-panel {
            animation: sdp-slide-up 0.22s cubic-bezier(.2,.9,.3,1.2) !important;
          }
          .sdp-header {
            position: sticky; top: 0; z-index: 2;
            background: var(--bg-primary);
            padding-top: 60px !important; /* room for the absolute back button */
          }
          .sdp-mobile-back { display: grid !important; }
          .sdp-header-row { flex-wrap: wrap !important; gap: 10px !important; }
          .sdp-actions { width: 100% !important; }
          .sdp-stat-pills { flex-direction: column !important; }
          /* Collapsed header: hide the verbose stat pills + action row,
             keep the title bar so the analyst still sees ticker + close. */
          .sdp-panel[data-collapsed="true"] .sdp-stat-pills { display: none; }
          .sdp-panel[data-collapsed="true"] .sdp-actions { display: none; }
          .sdp-panel[data-collapsed="true"] .sdp-subtitle { display: none; }
          .sdp-panel[data-collapsed="true"] .sdp-header { padding-top: 12px !important; padding-bottom: 8px !important; }
          .sdp-panel[data-collapsed="true"] .sdp-mobile-back { top: 6px; }
        }
      `}</style>
    </>
  );
}
