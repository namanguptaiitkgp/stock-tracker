"use client";

import React, { useEffect, useState } from "react";
import { api } from "@/lib/api";
import FreshnessChip from "@/components/ui/FreshnessChip";

interface StrategyReason {
  metric: string;
  text: string;
  failed: boolean;
}

interface StrategyBreakdown {
  strategy_name: string;
  strategy_type: string;
  passed: boolean;
  score: number;
  reasons: StrategyReason[];
  description?: string;
  signal_rules?: string;
}

interface InvestmentResult {
  id?: number;
  created_at?: string;
  symbol: string;
  verdict: "INVEST" | "WAIT" | "AVOID";
  confidence: number;
  reasoning: string;
  strategy_consensus?: {
    summary: string;
    best_fit_strategy: string;
    worst_fit_strategy: string;
  };
  strategy_breakdown?: StrategyBreakdown[];
  strategies_summary?: {
    total: number;
    passed: number;
  };
  valuation_view?: string;
  technical_view?: string;
  market_sentiment?: {
    nifty_trend: string;
    sector_outlook: string;
    sentiment_summary: string;
  };
  entry_recommendation?: {
    entry_price_low: number;
    entry_price_high: number;
    stop_loss: number;
    target_price: number;
    time_horizon: string;
  };
  key_risks?: string[];
  action_items?: string[];
  news_sentiment_context?: string;
  news_sentiment?: string | null;
  news_score?: number | null;
  status?: string;
  message?: string;
}

interface HistoryItem {
  id: number;
  created_at: string;
  symbol: string;
  verdict: "INVEST" | "WAIT" | "AVOID";
  confidence: number;
  reasoning: string;
  strategy_breakdown?: StrategyBreakdown[];
  strategies_summary?: { total: number; passed: number };
  entry_recommendation?: InvestmentResult["entry_recommendation"];
  market_sentiment?: InvestmentResult["market_sentiment"];
  key_risks?: string[];
  action_items?: string[];
  strategy_consensus?: InvestmentResult["strategy_consensus"];
  valuation_view?: string;
  technical_view?: string;
  news_sentiment_context?: string;
  news_sentiment?: string | null;
  news_score?: number | null;
  status?: string;
  message?: string;
}

interface Props {
  symbol: string;
  exchange?: string;
}

const VERDICT_STYLES: Record<string, React.CSSProperties> = {
  INVEST: {
    backgroundColor: "rgba(52,199,89,0.08)",
    color: "#248A3D",
    border: "1px solid rgba(52,199,89,0.2)",
  },
  WAIT: {
    backgroundColor: "rgba(255,204,0,0.08)",
    color: "#A05A00",
    border: "1px solid rgba(255,204,0,0.2)",
  },
  AVOID: {
    backgroundColor: "rgba(255,59,48,0.08)",
    color: "#D70015",
    border: "1px solid rgba(255,59,48,0.2)",
  },
};

function N(v: number | null | undefined): string {
  if (v === null || v === undefined) return "--";
  return v.toLocaleString("en-IN", { maximumFractionDigits: 2 });
}

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleString("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function VerdictBadge({ verdict, small }: { verdict: string; small?: boolean }) {
  const style = VERDICT_STYLES[verdict] || VERDICT_STYLES.WAIT;
  return (
    <span
      style={{
        ...style,
        display: "inline-block",
        padding: small ? "1px 8px" : "2px 10px",
        borderRadius: "6px",
        fontWeight: 600,
        fontSize: small ? "11px" : "13px",
        letterSpacing: "0.5px",
      }}
    >
      {verdict}
    </span>
  );
}

function StrategyRow({ s, defaultExpanded }: { s: StrategyBreakdown; defaultExpanded: boolean }) {
  const [expanded, setExpanded] = useState(defaultExpanded);

  return (
    <div className="border-b border-gray-800 last:border-b-0">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-2 py-2.5 px-2 text-left hover:bg-gray-800/50 transition-colors"
      >
        <span style={{ color: s.passed ? "#34C759" : "#FF3B30", fontSize: "14px", width: "18px", flexShrink: 0 }}>
          {s.passed ? "\u2713" : "\u2717"}
        </span>
        <div className="flex-1 min-w-0">
          <div className="text-sm font-medium truncate">{s.strategy_name}</div>
          {!expanded && s.description && (
            <div className="text-xs text-gray-500 truncate">{s.description}</div>
          )}
        </div>
        <span className="text-xs font-mono" style={{ color: s.passed ? "#34C759" : "#FF3B30" }}>
          {s.score.toFixed(1)}
        </span>
        <span className="text-[10px] text-gray-500 bg-gray-800 px-1.5 py-0.5 rounded">
          {s.strategy_type}
        </span>
        <span className="text-gray-500 text-xs">{expanded ? "\u25B2" : "\u25BC"}</span>
      </button>

      {expanded && (
        <div className="pl-7 pr-2 pb-3 space-y-2">
          {s.description && (
            <p className="text-xs text-gray-400 italic">{s.description}</p>
          )}
          {s.signal_rules && (
            <div className="text-xs p-2 rounded" style={{ backgroundColor: "rgba(0,122,255,0.06)", color: "#007AFF" }}>
              <span className="font-semibold">Rule: </span>{s.signal_rules}
            </div>
          )}
          {s.reasons?.length > 0 && (
            <div className="space-y-1">
              <div className="text-xs font-semibold text-gray-500 mb-1">Filter Results:</div>
              {s.reasons.map((r, i) => (
                <div key={i} className="flex items-start gap-1.5 text-xs">
                  <span style={{ color: r.failed ? "#FF3B30" : "#34C759", flexShrink: 0, marginTop: "2px" }}>
                    {r.failed ? "\u2717" : "\u2713"}
                  </span>
                  <span className="text-gray-400">{r.text}</span>
                </div>
              ))}
            </div>
          )}
          <div className="text-xs text-gray-500 pt-1">
            Overall score: <span className="font-mono font-semibold" style={{ color: s.passed ? "#34C759" : "#FF3B30" }}>{s.score.toFixed(1)}/100</span>
            {" — "}
            {s.passed
              ? <span style={{ color: "#34C759" }}>Stock PASSES this strategy</span>
              : <span style={{ color: "#FF3B30" }}>Stock FAILS this strategy</span>
            }
          </div>
        </div>
      )}
    </div>
  );
}

function ResultDisplay({ result }: { result: InvestmentResult }) {
  const isPartial = !result.verdict && result.status;
  const [expandAll, setExpandAll] = useState(false);

  return (
    <div className="space-y-4 mt-3">
      {/* Verdict Banner */}
      {result.verdict && (
        <div style={{ ...VERDICT_STYLES[result.verdict], borderRadius: "10px", padding: "14px 16px" }}>
          <div className="flex items-center justify-between mb-2">
            <span style={{ fontSize: "20px", fontWeight: 700, letterSpacing: "1px" }}>
              {result.verdict}
            </span>
            <span style={{ fontSize: "14px", fontWeight: 600 }}>
              Confidence: {result.confidence}%
            </span>
          </div>
          <p style={{ fontSize: "13px", lineHeight: "1.5", opacity: 0.9 }}>
            {result.reasoning}
          </p>
        </div>
      )}

      {/* Partial result fallback */}
      {isPartial && (
        <div
          className="rounded-lg p-3 text-sm"
          style={{ backgroundColor: "rgba(255,204,0,0.08)", color: "#A05A00", border: "1px solid rgba(255,204,0,0.2)" }}
        >
          <div className="font-semibold mb-1">Partial Result</div>
          <p className="text-xs">{result.message || "AI analysis was unavailable. Showing strategy breakdown only."}</p>
        </div>
      )}

      {/* Strategy Scorecard */}
      {result.strategy_breakdown && result.strategy_breakdown.length > 0 && (
        <div>
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-xs font-semibold text-gray-500 uppercase">Strategy Scorecard</h3>
            <button
              onClick={() => setExpandAll(!expandAll)}
              className="text-xs hover:underline"
              style={{ color: "#007AFF" }}
            >
              {expandAll ? "Collapse All" : "Expand All"}
            </button>
          </div>
          {result.strategies_summary && (
            <div className="mb-2">
              <div className="text-sm text-gray-300 mb-1">
                Passed {result.strategies_summary.passed} of {result.strategies_summary.total} strategies
              </div>
              <div className="w-full bg-gray-800 rounded-full h-2">
                <div
                  className="h-2 rounded-full transition-all"
                  style={{
                    width: `${(result.strategies_summary.passed / result.strategies_summary.total) * 100}%`,
                    backgroundColor: result.strategies_summary.passed / result.strategies_summary.total >= 0.6 ? "#34C759" : result.strategies_summary.passed / result.strategies_summary.total >= 0.4 ? "#FFCC00" : "#FF3B30",
                  }}
                />
              </div>
            </div>
          )}
          <div className="border border-gray-800 rounded-lg overflow-hidden">
            {result.strategy_breakdown.map((s, i) => (
              <StrategyRow key={i} s={s} defaultExpanded={expandAll} />
            ))}
          </div>
          {result.strategy_consensus && (
            <div className="mt-2 text-xs text-gray-400 space-y-0.5">
              <p>{result.strategy_consensus.summary}</p>
              <p>
                <span className="text-gray-500">Best fit:</span>{" "}
                <span className="text-green-400">{result.strategy_consensus.best_fit_strategy}</span>
                {" | "}
                <span className="text-gray-500">Worst fit:</span>{" "}
                <span className="text-red-400">{result.strategy_consensus.worst_fit_strategy}</span>
              </p>
            </div>
          )}
        </div>
      )}

      {/* Technical View */}
      {result.technical_view && (
        <div className="rounded-lg p-3" style={{ backgroundColor: "rgba(0,122,255,0.05)", border: "1px solid rgba(0,122,255,0.1)" }}>
          <span className="text-xs font-semibold" style={{ color: "#6E6E73" }}>Technicals: </span>
          <span className="text-sm" style={{ color: "#1D1D1F" }}>{result.technical_view}</span>
        </div>
      )}

      {/* Key Risks */}
      {result.key_risks && result.key_risks.length > 0 && (
        <div>
          <h3 className="text-xs font-semibold uppercase mb-2" style={{ color: "#6E6E73" }}>Key Risks</h3>
          <ul className="space-y-1.5">
            {result.key_risks.map((risk, i) => (
              <li key={i} className="text-xs flex items-start gap-1.5" style={{ color: "#48484A" }}>
                <span style={{ color: "#FF3B30", marginTop: "2px", flexShrink: 0 }}>&bull;</span>
                {risk}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Action Items */}
      {result.action_items && result.action_items.length > 0 && (
        <div>
          <h3 className="text-xs font-semibold uppercase mb-2" style={{ color: "#6E6E73" }}>Action Items</h3>
          <ul className="space-y-1.5">
            {result.action_items.map((item, i) => (
              <li key={i} className="text-xs flex items-start gap-1.5" style={{ color: "#48484A" }}>
                <span style={{ color: "#007AFF", marginTop: "2px", flexShrink: 0 }}>&bull;</span>
                {item}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

export default function InvestmentDecision({ symbol, exchange = "NSE" }: Props) {
  const [result, setResult] = useState<InvestmentResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [expandedHistoryId, setExpandedHistoryId] = useState<number | null>(null);

  // Fetch past decisions on mount + auto-load the most recent one
  useEffect(() => {
    setResult(null);
    setError(null);
    api
      .get<HistoryItem[]>(`/api/investment/history?symbol=${symbol}&limit=5`)
      .then((items) => {
        setHistory(items);
        // Auto-load the most recent evaluation so it shows immediately
        if (items.length > 0 && !result) {
          api
            .get<InvestmentResult>(`/api/investment/history/${items[0].id}`)
            .then(setResult)
            .catch(() => {});
        }
      })
      .catch(() => {});
  }, [symbol]); // eslint-disable-line react-hooks/exhaustive-deps

  async function evaluate() {
    // Paid LLM call — confirm before firing. Skip the prompt on the
    // very first evaluation (when `result` is null) since the user
    // explicitly tapped "Should I Invest?" which is its own intent
    // signal; only guard the cheap "Re-evaluate" / Retry buttons.
    if (result && !confirm(`Re-evaluate ${symbol}? This makes an AI call and may take a minute.`)) {
      return;
    }
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const res = await api.post<InvestmentResult>("/api/investment/evaluate", {
        symbol,
        exchange,
      });
      setResult(res);
      // Refresh history after new evaluation
      api
        .get<HistoryItem[]>(`/api/investment/history?symbol=${symbol}&limit=3`)
        .then(setHistory)
        .catch(() => {});
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to evaluate. Please try again.");
    } finally {
      setLoading(false);
    }
  }

  function loadHistoryResult(item: HistoryItem) {
    if (expandedHistoryId === item.id) {
      setExpandedHistoryId(null);
      return;
    }
    setExpandedHistoryId(item.id);
    setResult({
      ...item,
      created_at: item.created_at,
    });
  }

  return (
    <div className="border-t border-gray-800 pt-3">
      {/* Evaluate Button — show when no result or allow re-evaluate */}
      {!loading && !result && (
        <button
          onClick={evaluate}
          className="w-full py-3 px-4 rounded-lg font-semibold text-sm transition-all hover:brightness-110 active:scale-[0.98]"
          style={{ backgroundColor: "#007AFF", color: "#FFFFFF" }}
        >
          Should I Invest?
        </button>
      )}
      {!loading && result && (
        <div className="flex items-center justify-between mb-2 gap-2 flex-wrap">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-xs" style={{ color: "#6E6E73" }}>
              {result.created_at ? "Evaluated" : "Latest evaluation"}
            </span>
            {result.created_at && (
              <FreshnessChip kind="ai" iso={result.created_at} />
            )}
          </div>
          <button
            onClick={evaluate}
            className="text-xs px-3 py-1 rounded-md font-medium transition-colors hover:brightness-110"
            style={{ backgroundColor: "#007AFF", color: "#FFFFFF" }}
          >
            Re-evaluate
          </button>
        </div>
      )}

      {/* Loading */}
      {loading && (
        <div className="w-full py-4 px-4 rounded-lg text-center" style={{ backgroundColor: "rgba(0,122,255,0.06)", border: "1px solid rgba(0,122,255,0.15)" }}>
          <div className="flex items-center justify-center gap-2 mb-1">
            <svg className="animate-spin h-4 w-4 text-blue-400" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
            <span className="text-sm font-medium text-blue-400">Evaluating...</span>
          </div>
          <p className="text-xs text-gray-500">Evaluating against all strategies + AI analysis...</p>
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="space-y-2">
          <div
            className="rounded-lg p-3 text-sm"
            style={{ backgroundColor: "rgba(255,59,48,0.08)", color: "#D70015", border: "1px solid rgba(255,59,48,0.2)" }}
          >
            {error}
          </div>
          <button
            onClick={evaluate}
            className="w-full py-2 px-4 rounded-lg font-medium text-sm transition-all hover:brightness-110"
            style={{ backgroundColor: "#007AFF", color: "#FFFFFF" }}
          >
            Retry
          </button>
        </div>
      )}

      {/* Result */}
      {result && !loading && (
        <>
          <ResultDisplay result={result} />
          <button
            onClick={evaluate}
            className="mt-3 w-full py-2 px-4 rounded-lg text-sm font-medium transition-all hover:brightness-110"
            style={{ backgroundColor: "rgba(0,122,255,0.1)", color: "#007AFF", border: "1px solid rgba(0,122,255,0.2)" }}
          >
            Re-evaluate
          </button>
        </>
      )}

      {/* Past Decisions */}
      {history.length > 0 && (
        <div className="mt-4">
          <h3 className="text-xs font-semibold text-gray-500 uppercase mb-2">Past Decisions</h3>
          <div className="space-y-1.5">
            {history.map((h) => (
              <button
                key={h.id}
                onClick={() => loadHistoryResult(h)}
                className={`w-full text-left px-3 py-2 rounded-lg border transition-colors ${
                  expandedHistoryId === h.id
                    ? "border-gray-600 bg-gray-800"
                    : "border-gray-800 bg-gray-800/30 hover:bg-gray-800/60"
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="text-xs text-gray-400">{formatDate(h.created_at)}</span>
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-gray-500">{h.confidence}%</span>
                    <VerdictBadge verdict={h.verdict} small />
                  </div>
                </div>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
