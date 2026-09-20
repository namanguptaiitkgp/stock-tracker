"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { usePrivacyMode } from "@/lib/privacy-mode";
import { openStockDetail } from "@/lib/stock-detail";
import { getTodayBrief, invalidateTodayBrief } from "@/lib/today-brief";
import { api } from "@/lib/api";
import type { SectorCard } from "@/lib/market-brief-api";
import MarketPulse from "@/components/common/MarketPulse";
import PortfolioHero from "@/components/common/PortfolioHero";
import PortfolioExposure from "@/components/common/PortfolioExposure";
import PositionCard from "@/components/common/PositionCard";
import HoldRollup from "@/components/common/HoldRollup";
import PortfolioDetails from "@/components/common/PortfolioDetails";
import { useAuth } from "@/lib/auth";
import { usePageActions } from "@/lib/page-actions";
import SignalPill from "@/components/common/SignalPill";
import RiskFlag from "@/components/common/RiskFlag";
import UrgencyBadge, { actionToUrgency, URGENCY_COLOR } from "@/components/common/UrgencyBadge";
import { usePipelineStatus } from "@/lib/use-pipeline-status";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface HoldingAction {
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
  smart_money_top_shark?: string | null;
  high_conviction?: boolean;
  signals?: Array<{
    source: "FII" | "DII" | "MF" | "INS" | "PRO" | "RET";
    direction: "accumulating" | "distributing" | "neutral";
    recency?: string | null;
    strength?: number;
    label?: string;
  }>;
  risk_flags?: Array<{ severity: "red" | "amber" | "blue"; label: string; icon?: string }>;
  reviewed_at?: string | null;
}

interface PortfolioSummary {
  total_invested: number;
  total_current: number;
  total_pnl: number;
  total_pnl_pct: number;
  total_day_pnl: number;
  stock_count: number;
}

interface MorningBrief {
  date: string;
  holdings_actions: HoldingAction[];
  action_counts: Record<string, number>;
  portfolio_summary: PortfolioSummary;
  sectors?: SectorCard[];
  kite_connected: boolean;
  cached?: boolean;
  refreshed_at?: string | null;
  compute_ms?: number | null;
  news_task_id?: string | null;
}

// ---------------------------------------------------------------------------
// Formatters
// ---------------------------------------------------------------------------

function fmt(n: number): string {
  if (Math.abs(n) >= 10000000) return `${(n / 10000000).toFixed(2)} Cr`;
  if (Math.abs(n) >= 100000) return `${(n / 100000).toFixed(2)} L`;
  if (Math.abs(n) >= 1000) return `${(n / 1000).toFixed(1)} K`;
  return n.toLocaleString("en-IN", { maximumFractionDigits: 0 });
}

function fmtPrice(n: number): string {
  return n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function pnlColor(v: number): string {
  return v >= 0 ? "#248A3D" : "#D70015";
}

function pnlSign(v: number): string {
  return v >= 0 ? "+" : "";
}

// ---------------------------------------------------------------------------
// Market clock (IST-based)
// ---------------------------------------------------------------------------

function getISTNow(): Date {
  const now = new Date();
  const utcMs = now.getTime() + now.getTimezoneOffset() * 60_000;
  return new Date(utcMs + 5.5 * 60 * 60_000);
}

function marketStatus(): {
  status: "pre_open" | "open" | "closed" | "weekend";
  closeMs: number | null;
  openMs: number | null;
} {
  const istNow = getISTNow();
  const day = istNow.getDay();
  if (day === 0 || day === 6) return { status: "weekend", closeMs: null, openMs: null };

  // NSE pre-open auction is the strict 09:00-09:15 IST window. The
  // regular session runs 09:15-15:30. Everything else on a weekday is
  // "Closed" — either early-morning-before-pre-open or after-hours.
  const preOpenStart = new Date(istNow);
  preOpenStart.setHours(9, 0, 0, 0);
  const marketOpen = new Date(istNow);
  marketOpen.setHours(9, 15, 0, 0);
  const closeToday = new Date(istNow);
  closeToday.setHours(15, 30, 0, 0);

  if (istNow >= preOpenStart && istNow < marketOpen) {
    return {
      status: "pre_open",
      openMs: marketOpen.getTime() - istNow.getTime(),
      closeMs: null,
    };
  }
  if (istNow >= marketOpen && istNow < closeToday) {
    return { status: "open", closeMs: closeToday.getTime() - istNow.getTime(), openMs: null };
  }
  // Closed: include `openMs` when a same-day open is still ahead (the
  // countdown chip uses it to render "Opens in HH:MM" even though the
  // header label correctly reads "Market closed"). After 15:30 IST or
  // before pre-open on a fresh weekday morning, this is the next open.
  const sameDayOpenAhead = istNow < marketOpen ? marketOpen.getTime() - istNow.getTime() : null;
  return { status: "closed", closeMs: null, openMs: sameDayOpenAhead };
}

function fmtDuration(ms: number): string {
  if (ms <= 0) return "00:00";
  const totalMin = Math.floor(ms / 60_000);
  const h = Math.floor(totalMin / 60);
  const m = totalMin % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
}

/**
 * Renders the dashboard's Refresh button + last-refresh meta + MarketClock
 * into the AppShell tab bar via the page-actions slot. Renders nothing here.
 */
function DashboardHeaderActions({
  refresh, refreshing, refreshedAt, cached, computeMs, kiteConnected,
  pipelineRunning, pipelineSource, pipelineStartedAt, newsAvailable,
}: {
  refresh: () => void;
  refreshing: boolean;
  refreshedAt?: string | null;
  cached: boolean;
  computeMs: number | null;
  kiteConnected?: boolean;
  pipelineRunning: boolean;
  pipelineSource: string | null;
  pipelineStartedAt: string | null;
  newsAvailable: boolean;
}) {
  const disabled = refreshing || pipelineRunning;
  const buttonLabel = pipelineRunning
    ? `${pipelineSource === "morning_pipeline" ? "Pipeline" : pipelineSource === "news_scan" ? "News scan" : "Refreshing"}… since ${formatRelative(pipelineStartedAt)}`
    : refreshing
      ? "Refreshing…"
      : "Refresh";

  const node = (
    <div style={{ display: "inline-flex", alignItems: "center", gap: 10 }}>
      {!kiteConnected && (
        <span style={{ fontSize: 11, color: "var(--system-red)", fontWeight: 500 }}>
          Kite not connected
        </span>
      )}
      <div style={{ textAlign: "right", fontSize: 10.5, color: "var(--label-tertiary)", lineHeight: 1.25 }}>
        <div>Last refreshed <span style={{ color: "var(--label-primary)", fontWeight: 600 }}>{formatRelative(refreshedAt ?? null)}</span></div>
        {computeMs != null && (
          <div style={{ fontSize: 9.5, color: "var(--label-quaternary)" }}>
            {cached ? "cached" : "live"} · {computeMs} ms
          </div>
        )}
      </div>
      <div style={{ position: "relative", display: "inline-flex" }}>
        <button
          onClick={refresh}
          disabled={disabled}
          style={{
            padding: "5px 12px", borderRadius: 7,
            background: disabled ? "var(--label-quaternary)" : "var(--label-primary)",
            color: "var(--bg-primary)", border: "none",
            fontSize: 12, fontWeight: 600,
            cursor: disabled ? "not-allowed" : "pointer",
            whiteSpace: "nowrap",
            maxWidth: pipelineRunning ? 260 : undefined,
            overflow: "hidden", textOverflow: "ellipsis",
          }}
        >
          {buttonLabel}
        </button>
        {newsAvailable && !pipelineRunning && !refreshing && (
          <span
            title="New news data available — refresh to update analysis"
            style={{
              position: "absolute", top: -3, right: -3,
              width: 8, height: 8, borderRadius: 99,
              background: "#FF3B30",
              border: "2px solid var(--bg-primary)",
            }}
          />
        )}
      </div>
      <MarketClock />
    </div>
  );
  usePageActions(node, [refreshing, refreshedAt, cached, computeMs, kiteConnected, pipelineRunning, pipelineSource, pipelineStartedAt, newsAvailable]);
  return null;
}

function MarketClock() {
  const [, setTick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 30_000);
    return () => clearInterval(id);
  }, []);

  const info = marketStatus();

  const baseStyle: React.CSSProperties = {
    display: "inline-flex",
    alignItems: "center",
    gap: 6,
    padding: "4px 10px",
    border: "1px solid #E2E8F0",
    borderRadius: 6,
    fontSize: 12,
    color: "#6E6E73",
  };

  const dotStyle = (color: string): React.CSSProperties => ({
    display: "inline-block",
    width: 7,
    height: 7,
    borderRadius: "50%",
    backgroundColor: color,
  });

  if (info.status === "open") {
    return (
      <span style={baseStyle}>
        <span style={{ ...dotStyle("#34C759"), boxShadow: "0 0 4px #34C759" }} />
        Market open &middot;{" "}
        <span style={{ fontFamily: "monospace", fontWeight: 600, color: "#1D1D1F" }}>
          {fmtDuration(info.closeMs!)}
        </span>{" "}
        to close
      </span>
    );
  }
  if (info.status === "pre_open") {
    return (
      <span style={baseStyle}>
        <span style={dotStyle("#FFCC00")} />
        Opens in{" "}
        <span style={{ fontFamily: "monospace", fontWeight: 600, color: "#1D1D1F" }}>
          {fmtDuration(info.openMs!)}
        </span>
      </span>
    );
  }
  if (info.status === "weekend") {
    return (
      <span style={baseStyle}>
        <span style={dotStyle("#AEAEB2")} />
        Market closed &middot; Weekend
      </span>
    );
  }
  // Closed (weekday early-morning or after-hours). When openMs is set
  // we still know the next open is same-day, so show the countdown
  // alongside the correct "Closed" label rather than misreading
  // "Pre-open" outside the strict 09:00-09:15 window.
  if (info.status === "closed" && info.openMs != null) {
    return (
      <span style={baseStyle}>
        <span style={dotStyle("#AEAEB2")} />
        Market closed &middot; Opens in{" "}
        <span style={{ fontFamily: "monospace", fontWeight: 600, color: "#1D1D1F" }}>
          {fmtDuration(info.openMs)}
        </span>
      </span>
    );
  }
  return (
    <span style={baseStyle}>
      <span style={dotStyle("#AEAEB2")} />
      Market closed
    </span>
  );
}

// ---------------------------------------------------------------------------
// Action badge styles
// ---------------------------------------------------------------------------

const ACTION_STYLES: Record<
  HoldingAction["action"],
  { bg: string; color: string; border: string; emoji: string; label: string }
> = {
  SELL: {
    bg: "#FEF2F2",
    color: "#DC2626",
    border: "1px solid rgba(220,38,38,0.2)",
    emoji: "\uD83D\uDD34",
    label: "ACT NOW",
  },
  ACCUMULATE: {
    bg: "#F0FDF4",
    color: "#16A34A",
    border: "1px solid rgba(22,163,74,0.2)",
    emoji: "\uD83D\uDFE2",
    label: "BUY",
  },
  HOLD: {
    bg: "#F9FAFB",
    color: "#6B7280",
    border: "1px solid #E4E7EC",
    emoji: "\u26AA",
    label: "HOLD",
  },
  WATCHFUL: {
    bg: "#FFFBEB",
    color: "#D97706",
    border: "1px solid rgba(217,119,6,0.2)",
    emoji: "\uD83D\uDFE1",
    label: "REVIEW",
  },
};

function ActionBadge({ action }: { action: HoldingAction["action"] }) {
  const s = ACTION_STYLES[action];
  return (
    <span
      style={{
        display: "inline-block",
        padding: "2px 8px",
        fontSize: 11,
        fontWeight: 700,
        letterSpacing: 0.5,
        borderRadius: 4,
        backgroundColor: s.bg,
        color: s.color,
        border: s.border,
      }}
    >
      {s.label}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Holding card
// ---------------------------------------------------------------------------

function HoldingCard({ h }: { h: HoldingAction }) {
  return (
    <div
      style={{
        backgroundColor: "#FFFFFF",
        border: "1px solid #E2E8F0",
        borderRadius: 10,
        padding: "14px 18px",
        marginBottom: 10,
        cursor: "pointer",
      }}
      onClick={() => openStockDetail(h.symbol, h.exchange)}
    >
      {/* Row 1 — identity + urgency + score + signal pills (design spec) */}
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8, flexWrap: "wrap" }}>
        <span
          style={{
            fontFamily: '"DM Mono", monospace',
            fontWeight: 800,
            fontSize: 15,
            color: "#1D1D1F",
          }}
        >
          {h.symbol}
        </span>
        <UrgencyBadge urgency={actionToUrgency(h.action)} />
        {h.confidence !== null && (
          <span
            style={{
              fontFamily: '"DM Mono", monospace',
              fontSize: 11,
              background: "#F3F4F6",
              color: "#6B7280",
              padding: "2px 7px",
              borderRadius: 5,
            }}
          >
            Score {h.confidence}%
          </span>
        )}
        {h.high_conviction && (
          <span
            title="AI + news + smart-money aligned"
            style={{
              fontSize: 10,
              fontWeight: 700,
              padding: "2px 8px",
              borderRadius: 10,
              background: "rgba(175,82,222,0.1)",
              color: "#AF52DE",
              textTransform: "uppercase",
              letterSpacing: "0.04em",
            }}
          >
            HC
          </span>
        )}
        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap", justifyContent: "flex-end" }}>
          {(h.signals || []).slice(0, 4).map((sig, i) => (
            <SignalPill
              key={`${sig.source}-${i}`}
              source={sig.source}
              direction={sig.direction}
              recency={sig.recency}
              title={`${sig.source} — ${sig.direction}${sig.strength ? ` · strength ${(sig.strength * 100).toFixed(0)}%` : ""}`}
            />
          ))}
        </div>
      </div>

      {/* Row 2 — risk flags above the fold (design spec: never in prose) */}
      {(h.risk_flags && h.risk_flags.length > 0) && (
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 8 }}>
          {h.risk_flags.slice(0, 4).map((rf, i) => (
            <RiskFlag key={i} severity={rf.severity} icon={rf.icon || (rf.severity === "red" ? "⚠" : rf.severity === "amber" ? "📊" : "✓")} label={rf.label} />
          ))}
        </div>
      )}

      {/* Row 3 — P&L + Day % (right aligned inside metrics row) */}
      <div style={{ display: "flex", alignItems: "baseline", gap: 10, marginBottom: 6, justifyContent: "flex-end" }}>
        <span
          title="Day % change"
          style={{
            fontSize: 11,
            color: pnlColor(h.day_change_pct),
            fontWeight: 500,
          }}
        >
          day {pnlSign(h.day_change_pct)}{h.day_change_pct.toFixed(2)}%
        </span>
        <span
          title="Change since you bought"
          style={{ fontWeight: 600, fontSize: 14, color: pnlColor(h.pnl_pct) }}
        >
          {pnlSign(h.pnl_pct)}{h.pnl_pct.toFixed(1)}%
        </span>
      </div>

      {/* Reasoning */}
      <div
        style={{
          fontSize: 13,
          color: "#48484A",
          lineHeight: 1.45,
          marginBottom: 8,
          fontStyle: "italic",
        }}
      >
        &ldquo;{h.reasoning}&rdquo;
      </div>

      {/* Bottom row: LTP, Avg, Qty, Day P&L */}
      <div style={{ display: "flex", gap: 16, fontSize: 12, color: "#6E6E73", flexWrap: "wrap" }}>
        <span>
          LTP: <span style={{ color: "#1D1D1F", fontWeight: 500 }}>{fmtPrice(h.last_price)}</span>
        </span>
        <span>
          Avg: <span style={{ color: "#1D1D1F", fontWeight: 500 }}>{fmtPrice(h.average_price)}</span>
        </span>
        <span>
          Qty: <span style={{ color: "#1D1D1F", fontWeight: 500 }}>{h.quantity}</span>
        </span>
        <span>
          P&amp;L:{" "}
          <span style={{ color: pnlColor(h.pnl), fontWeight: 500 }}>
            {pnlSign(h.pnl)}{fmt(h.pnl)}
          </span>
        </span>
        <span>
          Day:{" "}
          <span style={{ color: pnlColor(h.day_pnl), fontWeight: 500 }}>
            {pnlSign(h.day_pnl)}{fmt(h.day_pnl)} ({pnlSign(h.day_change_pct)}{h.day_change_pct.toFixed(1)}%)
          </span>
        </span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Action group
// ---------------------------------------------------------------------------

function ActionGroup({
  action,
  holdings,
  defaultCollapsed,
}: {
  action: HoldingAction["action"];
  holdings: HoldingAction[];
  defaultCollapsed: boolean;
}) {
  const [collapsed, setCollapsed] = useState(defaultCollapsed);
  const s = ACTION_STYLES[action];

  if (holdings.length === 0) return null;

  const anchorId: Record<HoldingAction["action"], string> = {
    SELL: "act-now",
    WATCHFUL: "review",
    HOLD: "hold",
    ACCUMULATE: "hold",
  };

  return (
    <div id={anchorId[action]} style={{ marginBottom: 24, scrollMarginTop: 20 }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          marginBottom: 10,
          cursor: "pointer",
          userSelect: "none",
        }}
        onClick={() => setCollapsed(!collapsed)}
      >
        <span style={{ fontSize: 16 }}>{s.emoji}</span>
        <span style={{ fontSize: 14, fontWeight: 700, color: s.color }}>
          {s.label}
        </span>
        <span style={{ fontSize: 13, color: "#6E6E73" }}>
          ({holdings.length} stock{holdings.length !== 1 ? "s" : ""})
        </span>
        <span
          style={{
            fontSize: 11,
            color: "#6E6E73",
            marginLeft: 4,
            transition: "transform 0.2s",
            display: "inline-block",
            transform: collapsed ? "rotate(-90deg)" : "rotate(0deg)",
          }}
        >
          &#9660;
        </span>
      </div>

      {!collapsed && (
        <div>
          {holdings.map((h) => (
            <HoldingCard key={h.symbol} h={h} />
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Portfolio summary bar
// ---------------------------------------------------------------------------

function PortfolioBar({ s }: { s: PortfolioSummary }) {
  const mask = usePrivacyMode();
  const mv = (v: string) => (mask ? "••••" : v);
  const items: { label: string; value: string; color?: string }[] = [
    { label: "Invested", value: mv(fmt(s.total_invested)) },
    { label: "Current", value: mv(fmt(s.total_current)) },
    {
      label: "P&L",
      value: mask
        ? `•••• (${pnlSign(s.total_pnl_pct)}${s.total_pnl_pct.toFixed(1)}%)`
        : `${pnlSign(s.total_pnl)}${fmt(s.total_pnl)} (${pnlSign(s.total_pnl_pct)}${s.total_pnl_pct.toFixed(1)}%)`,
      color: pnlColor(s.total_pnl),
    },
    {
      label: "Day",
      value: mv(`${pnlSign(s.total_day_pnl)}${fmt(s.total_day_pnl)}`),
      color: pnlColor(s.total_day_pnl),
    },
    { label: "Stocks", value: String(s.stock_count) },
  ];

  return (
    <div
      style={{
        display: "flex",
        flexWrap: "wrap",
        gap: 4,
        backgroundColor: "#FFFFFF",
        border: "1px solid #E2E8F0",
        borderRadius: 10,
        padding: "12px 18px",
        marginBottom: 28,
      }}
    >
      {items.map((item, i) => (
        <div
          key={item.label}
          style={{
            flex: "1 1 0",
            minWidth: 100,
            textAlign: "center",
            borderRight: i < items.length - 1 ? "1px solid #E2E8F0" : "none",
            paddingRight: i < items.length - 1 ? 12 : 0,
            paddingLeft: i > 0 ? 12 : 0,
          }}
        >
          <div style={{ fontSize: 11, color: "#6E6E73", marginBottom: 2, textTransform: "uppercase", letterSpacing: 0.5 }}>
            {item.label}
          </div>
          <div
            style={{
              fontSize: 16,
              fontWeight: 700,
              color: item.color || "#1D1D1F",
            }}
          >
            {item.value}
          </div>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

function formatRelative(iso: string | null | undefined): string {
  if (!iso) return "never";
  const t = new Date(iso).getTime();
  if (isNaN(t)) return "unknown";
  const diff = (Date.now() - t) / 1000;
  if (diff < 60) return `${Math.max(1, Math.round(diff))}s ago`;
  if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.round(diff / 3600)}h ago`;
  return `${Math.round(diff / 86400)}d ago`;
}

export default function DashboardPage() {
  const [brief, setBrief] = useState<MorningBrief | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { user } = useAuth();
  const pipeline = usePipelineStatus();

  const [actionFilter, setActionFilter] = useState<"all" | "SELL" | "WATCHFUL" | "ACCUMULATE">("all");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getTodayBrief<MorningBrief>();
      setBrief(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load morning brief");
    } finally {
      setLoading(false);
    }
  }, []);

  // When a running pipeline completes, reload the brief
  const prevRunning = useRef(pipeline.running);
  useEffect(() => {
    if (prevRunning.current && !pipeline.running) {
      invalidateTodayBrief();
      load();
    }
    prevRunning.current = pipeline.running;
  }, [pipeline.running, load]);

  const refresh = useCallback(async () => {
    setRefreshing(true);
    setError(null);
    try {
      await pipeline.dispatch("refresh");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to dispatch refresh");
    } finally {
      setRefreshing(false);
    }
  }, [pipeline]);

  const handleReview = useCallback(async (h: HoldingAction) => {
    if (!brief) return;
    const isUndo = !!h.reviewed_at;
    const now = new Date().toISOString();
    setBrief({
      ...brief,
      holdings_actions: brief.holdings_actions.map((x) =>
        x.symbol === h.symbol ? { ...x, reviewed_at: isUndo ? null : now } : x
      ),
    });
    try {
      if (isUndo) {
        await api.delete(`/api/investment/review/${encodeURIComponent(h.symbol)}`);
      } else {
        await api.post(`/api/investment/review/${encodeURIComponent(h.symbol)}`);
      }
    } catch {
      setBrief({
        ...brief,
        holdings_actions: brief.holdings_actions.map((x) =>
          x.symbol === h.symbol ? { ...x, reviewed_at: h.reviewed_at } : x
        ),
      });
    }
  }, [brief]);

  const [refreshingSymbol, setRefreshingSymbol] = useState<string | null>(null);
  const handleRefreshSections = useCallback(async (h: HoldingAction) => {
    if (!brief) return;
    setRefreshingSymbol(h.symbol);
    try {
      const updated = await api.post<Record<string, unknown>>(
        `/api/today/stock/${encodeURIComponent(h.symbol)}/refresh`,
      );
      setBrief({
        ...brief,
        holdings_actions: brief.holdings_actions.map((x) =>
          x.symbol === h.symbol ? { ...x, ...updated } : x
        ),
      });
    } catch {
      // silently fail — user can retry
    } finally {
      setRefreshingSymbol(null);
    }
  }, [brief]);

  useEffect(() => {
    load();
  }, [load]);

  const pageStyle: React.CSSProperties = {
    maxWidth: 1200,
    margin: "0 auto",
    padding: "0 16px",
  };

  // --- Loading ---
  if (loading) {
    return (
      <div style={pageStyle}>
        <div style={{ padding: 40, textAlign: "center", color: "#6E6E73", fontSize: 15 }}>
          Loading morning brief...
        </div>
      </div>
    );
  }

  // --- Error ---
  if (error) {
    return (
      <div style={pageStyle}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 24 }}>
          <h1 style={{ fontSize: 26, fontWeight: 800, color: "#1D1D1F", margin: 0 }}>Today</h1>
          <MarketClock />
        </div>
        <div
          style={{
            padding: 16,
            backgroundColor: "rgba(255,59,48,0.06)",
            border: "1px solid rgba(255,59,48,0.15)",
            borderRadius: 10,
            color: "#D70015",
            fontSize: 14,
            marginBottom: 12,
          }}
        >
          {error}
        </div>
        <button
          onClick={load}
          style={{
            padding: "8px 16px",
            fontSize: 13,
            fontWeight: 600,
            borderRadius: 6,
            border: "none",
            backgroundColor: "#007AFF",
            color: "#FFFFFF",
            cursor: "pointer",
          }}
        >
          Retry
        </button>
      </div>
    );
  }

  if (!brief) return null;

  // --- Group holdings by action ---
  const actionOrder: HoldingAction["action"][] = ["SELL", "ACCUMULATE", "WATCHFUL", "HOLD"];
  const grouped: Record<HoldingAction["action"], HoldingAction[]> = {
    SELL: [],
    ACCUMULATE: [],
    HOLD: [],
    WATCHFUL: [],
  };
  for (const h of brief.holdings_actions) {
    grouped[h.action].push(h);
  }
  const staleness = (iso: string | null | undefined) =>
    iso ? (Date.now() - new Date(iso).getTime()) / 1000 : Infinity;
  for (const action of actionOrder) {
    grouped[action].sort((a, b) => {
      const ra = a.reviewed_at ? 1 : 0;
      const rb = b.reviewed_at ? 1 : 0;
      if (ra !== rb) return ra - rb;
      const sa = staleness(a.analyzed_at);
      const sb = staleness(b.analyzed_at);
      if (sa !== sb) return sb - sa;
      return -abs(a.pnl_pct) + abs(b.pnl_pct);
    });
  }
  function abs(n: number) { return n < 0 ? -n : n; }

  const hasAnalysis = brief.holdings_actions.length > 0;

  return (
    <div style={pageStyle}>
      <DashboardHeaderActions
        refresh={refresh}
        refreshing={refreshing}
        refreshedAt={brief.refreshed_at}
        cached={!!brief.cached}
        computeMs={brief.compute_ms ?? null}
        kiteConnected={brief.kite_connected}
        pipelineRunning={pipeline.running}
        pipelineSource={pipeline.active?.source ?? null}
        pipelineStartedAt={pipeline.active?.started_at ?? null}
        newsAvailable={pipeline.news_available}
      />

      {/* No-analysis banner */}
      {!hasAnalysis && (
        <div
          style={{
            padding: "16px 20px",
            backgroundColor: "rgba(255,204,0,0.08)",
            border: "1px solid rgba(255,204,0,0.15)",
            borderRadius: 10,
            color: "#A05A00",
            fontSize: 14,
            marginBottom: 28,
            lineHeight: 1.5,
          }}
        >
          No analysis data yet. Run your first daily analysis from{" "}
          <strong>Settings &rarr; Scheduled Tasks</strong> to see action recommendations for your
          holdings.
        </div>
      )}

      {/* Pending Review section retired — pending alerts now surface as
          a "Triggered first" sort in the Action Queue tabs below. */}

      {/* Market Pulse — gradient pill + collapsible drivers/indices/sectors/headlines */}
      <MarketPulse sectors={brief.sectors ?? []} />

      {/* Portfolio Hero — greeting + summary + main P&L */}
      <PortfolioHero
        username={user?.username ?? null}
        summary={brief.portfolio_summary}
        actCount={grouped.SELL.length}
        reviewCount={grouped.WATCHFUL.length}
        topActSymbol={
          grouped.SELL[0]?.symbol
          ?? grouped.WATCHFUL[0]?.symbol
          ?? grouped.ACCUMULATE[0]?.symbol
          ?? null
        }
        marketStatus={marketStatus().status}
        lastRefreshIso={brief.refreshed_at ?? null}
      />

      {/* Portfolio Exposure — sector/cap concentration risk */}
      <PortfolioExposure />

      {/* Action Queue — grouped position cards */}
      {(grouped.SELL.length + grouped.WATCHFUL.length + grouped.ACCUMULATE.length) > 0 && (
        <section style={{ marginBottom: 28 }}>
          <div style={{
            display: "flex", justifyContent: "space-between", alignItems: "flex-end",
            marginBottom: 16, gap: 16, flexWrap: "wrap",
          }}>
            <div>
              <h3 style={{
                margin: 0, fontFamily: "var(--font-serif)", fontSize: 26, fontWeight: 600,
                letterSpacing: "-0.015em",
              }}>Action Queue</h3>
              <p style={{ margin: "6px 0 0", fontSize: 14, color: "var(--label-tertiary)" }}>
                Ranked by urgency · {grouped.SELL.length + grouped.WATCHFUL.length + grouped.ACCUMULATE.length} positions
              </p>
            </div>
            {(() => {
              const tabs: Array<{
                k: "all" | "SELL" | "WATCHFUL" | "ACCUMULATE";
                label: string;
                count: number;
                dot?: string;
              }> = [
                { k: "all",        label: "All",     count: grouped.SELL.length + grouped.WATCHFUL.length + grouped.ACCUMULATE.length },
                { k: "SELL",       label: "Act now", count: grouped.SELL.length,       dot: "var(--act)" },
                { k: "WATCHFUL",   label: "Review",  count: grouped.WATCHFUL.length,   dot: "var(--review)" },
                { k: "ACCUMULATE", label: "Buy",     count: grouped.ACCUMULATE.length, dot: "var(--buy)" },
              ];
              return (
                <div style={{
                  display: "inline-flex", padding: 3, borderRadius: 8,
                  background: "var(--bg-secondary)",
                  border: "1px solid var(--separator-light)",
                }}>
                  {tabs.map((t) => {
                    const active = actionFilter === t.k;
                    return (
                      <button
                        key={t.k}
                        onClick={() => setActionFilter(t.k)}
                        style={{
                          display: "inline-flex", alignItems: "center", gap: 6,
                          padding: "5px 12px", borderRadius: 6,
                          fontSize: 12, fontWeight: active ? 600 : 500,
                          border: 0, cursor: "pointer",
                          background: active ? "var(--bg-primary)" : "transparent",
                          color: active ? "var(--label-primary)" : "var(--label-tertiary)",
                          boxShadow: active ? "var(--shadow-sm)" : "none",
                        }}
                      >
                        {t.dot && <span style={{ width: 7, height: 7, borderRadius: 99, background: t.dot }} />}
                        {t.label}
                        <span style={{
                          fontFamily: "var(--font-mono)", fontSize: 11,
                          color: active ? "var(--label-tertiary)" : "var(--label-quaternary)",
                          marginLeft: 2,
                        }}>{t.count}</span>
                      </button>
                    );
                  })}
                </div>
              );
            })()}
          </div>

          {/* ACT NOW group */}
          {grouped.SELL.length > 0 && (actionFilter === "all" || actionFilter === "SELL") && (
            <div style={{ marginBottom: 24 }}>
              <div style={{
                display: "flex", alignItems: "center", gap: 10,
                padding: "12px 16px", marginBottom: 12, borderRadius: 8,
                background: "var(--act-bg)", color: "var(--act)", fontSize: 14,
              }}>
                <span style={{ width: 8, height: 8, borderRadius: 99, background: "var(--act)" }} />
                <span style={{ fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.08em", fontSize: 12.5 }}>Act now</span>
                <span style={{ color: "var(--label-tertiary)", fontWeight: 500 }}>
                  {grouped.SELL.length} stock{grouped.SELL.length !== 1 ? "s" : ""} need immediate decision
                </span>
              </div>
              {grouped.SELL.map(h => (
                <PositionCard key={h.symbol} h={h as unknown as Parameters<typeof PositionCard>[0]["h"]}
                  onClickSymbol={() => openStockDetail(h.symbol, h.exchange)}
                  onClickAction={() => openStockDetail(h.symbol, h.exchange)}
                  onReview={handleReview as unknown as Parameters<typeof PositionCard>[0]["onReview"]}
                  onRefreshSections={handleRefreshSections as unknown as Parameters<typeof PositionCard>[0]["onRefreshSections"]}
                  sectionRefreshing={refreshingSymbol === h.symbol}
                  pipelineRunning={pipeline.running}
                  onComparePeers={() => openStockDetail(h.symbol, h.exchange, "Smart Money")}
                  onReadSources={() => openStockDetail(h.symbol, h.exchange, "News")}
                />
              ))}
            </div>
          )}

          {/* REVIEW group */}
          {grouped.WATCHFUL.length > 0 && (actionFilter === "all" || actionFilter === "WATCHFUL") && (
            <div style={{ marginBottom: 24 }}>
              <div style={{
                display: "flex", alignItems: "center", gap: 10,
                padding: "12px 16px", marginBottom: 12, borderRadius: 8,
                background: "var(--review-bg)", color: "var(--review)", fontSize: 14,
              }}>
                <span style={{ width: 8, height: 8, borderRadius: 99, background: "var(--review)" }} />
                <span style={{ fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.08em", fontSize: 12.5 }}>Review</span>
                <span style={{ color: "var(--label-tertiary)", fontWeight: 500 }}>
                  {grouped.WATCHFUL.length} stock{grouped.WATCHFUL.length !== 1 ? "s" : ""} with mixed signals
                </span>
              </div>
              {grouped.WATCHFUL.map(h => (
                <PositionCard key={h.symbol} h={h as unknown as Parameters<typeof PositionCard>[0]["h"]}
                  onClickSymbol={() => openStockDetail(h.symbol, h.exchange)}
                  onClickAction={() => openStockDetail(h.symbol, h.exchange)}
                  onReview={handleReview as unknown as Parameters<typeof PositionCard>[0]["onReview"]}
                  onRefreshSections={handleRefreshSections as unknown as Parameters<typeof PositionCard>[0]["onRefreshSections"]}
                  sectionRefreshing={refreshingSymbol === h.symbol}
                  pipelineRunning={pipeline.running}
                  onComparePeers={() => openStockDetail(h.symbol, h.exchange, "Smart Money")}
                  onReadSources={() => openStockDetail(h.symbol, h.exchange, "News")}
                />
              ))}
            </div>
          )}

          {/* BUY group */}
          {grouped.ACCUMULATE.length > 0 && (actionFilter === "all" || actionFilter === "ACCUMULATE") && (
            <div style={{ marginBottom: 24 }}>
              <div style={{
                display: "flex", alignItems: "center", gap: 10,
                padding: "12px 16px", marginBottom: 12, borderRadius: 8,
                background: "var(--buy-bg)", color: "var(--buy)", fontSize: 14,
              }}>
                <span style={{ width: 8, height: 8, borderRadius: 99, background: "var(--buy)" }} />
                <span style={{ fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.08em", fontSize: 12.5 }}>Buy</span>
                <span style={{ color: "var(--label-tertiary)", fontWeight: 500 }}>
                  {grouped.ACCUMULATE.length} positive opportunit{grouped.ACCUMULATE.length !== 1 ? "ies" : "y"}
                </span>
              </div>
              {grouped.ACCUMULATE.map(h => (
                <PositionCard key={h.symbol} h={h as unknown as Parameters<typeof PositionCard>[0]["h"]}
                  onClickSymbol={() => openStockDetail(h.symbol, h.exchange)}
                  onClickAction={() => openStockDetail(h.symbol, h.exchange)}
                  onReview={handleReview as unknown as Parameters<typeof PositionCard>[0]["onReview"]}
                  onRefreshSections={handleRefreshSections as unknown as Parameters<typeof PositionCard>[0]["onRefreshSections"]}
                  sectionRefreshing={refreshingSymbol === h.symbol}
                  pipelineRunning={pipeline.running}
                  onComparePeers={() => openStockDetail(h.symbol, h.exchange, "Smart Money")}
                  onReadSources={() => openStockDetail(h.symbol, h.exchange, "News")}
                />
              ))}
            </div>
          )}

          {/* HOLD rollup */}
          {grouped.HOLD.length > 0 && (
            <HoldRollup
              holdings={grouped.HOLD as unknown as Parameters<typeof HoldRollup>[0]["holdings"]}
              onClickSymbol={(h) => openStockDetail(h.symbol, h.exchange)}
            />
          )}
        </section>
      )}

      {/* Portfolio Details — full holdings table grouped by market cap */}
      {brief.holdings_actions.length > 0 && (
        <PortfolioDetails
          holdings={brief.holdings_actions as unknown as Parameters<typeof PortfolioDetails>[0]["holdings"]}
          onClickSymbol={(h) => openStockDetail(h.symbol, h.exchange)}
        />
      )}

      {/* News + Opportunities now live on the /news page */}
    </div>
  );
}


/* ─── Portfolio Details Table ──────────────────────────────────── */

type SortKey = "symbol" | "last_price" | "average_price" | "quantity" | "pnl" | "pnl_pct" | "day_pnl" | "day_change_pct" | "action" | "confidence";

function PortfolioTable({ holdings }: { holdings: HoldingAction[] }) {
  const mask = usePrivacyMode();
  const [expanded, setExpanded] = useState(false);
  const [sortKey, setSortKey] = useState<SortKey>("pnl_pct");
  const [sortAsc, setSortAsc] = useState(false);
  const [search, setSearch] = useState("");

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) setSortAsc(!sortAsc);
    else { setSortKey(key); setSortAsc(key === "symbol"); }
  };

  const sorted = [...holdings]
    .filter(h => {
      if (!search.trim()) return true;
      return h.symbol.toLowerCase().includes(search.toLowerCase());
    })
    .sort((a, b) => {
      const av = a[sortKey];
      const bv = b[sortKey];
      if (typeof av === "string" && typeof bv === "string") return sortAsc ? av.localeCompare(bv) : bv.localeCompare(av);
      const an = Number(av ?? 0);
      const bn = Number(bv ?? 0);
      return sortAsc ? an - bn : bn - an;
    });

  const SH = ({ label, col }: { label: string; col: SortKey }) => {
    const active = sortKey === col;
    return (
      <th style={{ padding: "8px 10px", textAlign: "right", cursor: "pointer", whiteSpace: "nowrap", fontSize: 11, fontWeight: 600, color: active ? "#007AFF" : "#6E6E73" }} onClick={() => toggleSort(col)}>
        {label} {active ? (sortAsc ? "▲" : "▼") : "↕"}
      </th>
    );
  };

  return (
    <div style={{ marginTop: 32 }}>
      <button
        onClick={() => setExpanded(!expanded)}
        style={{ display: "flex", alignItems: "center", gap: 8, background: "none", border: "none", cursor: "pointer", padding: 0, marginBottom: 12 }}
      >
        <span style={{ fontSize: 16, fontWeight: 700, color: "#1D1D1F" }}>
          Portfolio Details
        </span>
        <span style={{ fontSize: 12, color: "#6E6E73" }}>
          ({holdings.length} stocks) {expanded ? "▲" : "▼"}
        </span>
      </button>

      {expanded && (
        <div style={{ backgroundColor: "#FFFFFF", border: "1px solid #E2E8F0", borderRadius: 10, overflow: "hidden" }}>
          <div style={{ padding: "10px 14px", borderBottom: "1px solid #E2E8F0", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <span style={{ fontSize: 12, color: "#6E6E73" }}>Click column headers to sort</span>
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Filter by symbol..."
              style={{ padding: "5px 10px", borderRadius: 6, border: "1px solid #C6C6C8", fontSize: 12, width: 180, color: "#1D1D1F", outline: "none" }}
            />
          </div>
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
              <thead>
                <tr style={{ borderBottom: "1px solid #E2E8F0" }}>
                  <th style={{ padding: "8px 10px", textAlign: "left", fontSize: 11, fontWeight: 600, color: sortKey === "symbol" ? "#007AFF" : "#6E6E73", cursor: "pointer" }} onClick={() => toggleSort("symbol")}>
                    Stock {sortKey === "symbol" ? (sortAsc ? "▲" : "▼") : "↕"}
                  </th>
                  <SH label="Action" col="action" />
                  <SH label="Conf" col="confidence" />
                  <SH label="Qty" col="quantity" />
                  <SH label="Avg" col="average_price" />
                  <SH label="LTP" col="last_price" />
                  <SH label="P&L" col="pnl" />
                  <SH label="P&L %" col="pnl_pct" />
                  <SH label="Day P&L" col="day_pnl" />
                  <SH label="Day %" col="day_change_pct" />
                </tr>
              </thead>
              <tbody>
                {sorted.map(h => {
                  const as = ACTION_STYLES[h.action];
                  return (
                    <tr
                      key={h.symbol}
                      style={{ borderBottom: "1px solid #F2F2F7", cursor: "pointer" }}
                      onClick={() => openStockDetail(h.symbol, h.exchange)}
                      onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.backgroundColor = "#F8F8FA"; }}
                      onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.backgroundColor = "transparent"; }}
                    >
                      <td style={{ padding: "8px 10px", fontFamily: "monospace", fontWeight: 600, color: "#1D1D1F" }}>
                        {h.symbol}
                      </td>
                      <td style={{ padding: "8px 10px", textAlign: "right" }}>
                        <span style={{ fontSize: 10, fontWeight: 700, padding: "2px 6px", borderRadius: 4, backgroundColor: as.bg, color: as.color, border: as.border }}>
                          {as.label}
                        </span>
                      </td>
                      <td style={{ padding: "8px 10px", textAlign: "right", color: "#6E6E73", fontSize: 12 }}>
                        {h.confidence != null ? `${h.confidence}%` : "--"}
                      </td>
                      <td style={{ padding: "8px 10px", textAlign: "right" }}>{mask ? "••" : h.quantity}</td>
                      <td style={{ padding: "8px 10px", textAlign: "right" }}>{mask ? "••••" : fmtPrice(h.average_price)}</td>
                      <td style={{ padding: "8px 10px", textAlign: "right" }}>{fmtPrice(h.last_price)}</td>
                      <td style={{ padding: "8px 10px", textAlign: "right", color: pnlColor(h.pnl), fontWeight: 600 }}>
                        {mask ? "••••" : `${pnlSign(h.pnl)}${fmt(h.pnl)}`}
                      </td>
                      <td style={{ padding: "8px 10px", textAlign: "right", color: pnlColor(h.pnl_pct), fontWeight: 600 }}>
                        {`${pnlSign(h.pnl_pct)}${h.pnl_pct.toFixed(1)}%`}
                      </td>
                      <td style={{ padding: "8px 10px", textAlign: "right", color: pnlColor(h.day_pnl) }}>
                        {mask ? "••••" : `${pnlSign(h.day_pnl)}${fmt(h.day_pnl)}`}
                      </td>
                      <td style={{ padding: "8px 10px", textAlign: "right", color: pnlColor(h.day_change_pct) }}>
                        {`${pnlSign(h.day_change_pct)}${h.day_change_pct.toFixed(1)}%`}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
