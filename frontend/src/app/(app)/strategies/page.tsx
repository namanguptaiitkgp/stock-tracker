"use client";

import React, { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { api } from "@/lib/api";
import StrategyBuilder, { type StrategyFormData } from "./StrategyBuilder";
import { fmtRelative } from "@/lib/format";

interface Strategy {
  id: number;
  name: string;
  description: string | null;
  strategy_type: string;
  is_default: boolean;
  is_active: boolean;
  is_mine: boolean;
  config_json: Record<string, unknown>;
}

interface StrategiesResponse {
  defaults: Strategy[];
  mine: Strategy[];
}

interface WatchlistSummary {
  id: number;
  name: string;
  stock_count: number;
}

interface ReasonDetail {
  metric: string;
  actual?: number | null;
  threshold?: number | null;
  comparison?: string;
  text: string;
  failed: boolean;
  missing?: boolean;
}

interface StockRow {
  symbol: string;
  name?: string | null;
  passed: boolean;
  score: number;
  reasons?: ReasonDetail[] | string[];  // supports legacy + new format
  failure_reasons?: string[];
  cmp?: number | null;
  pe?: number | null;
  pb?: number | null;
  de?: number | null;
  rev_gr?: number | null;
  eps_gr?: number | null;
  margin?: number | null;
  roe?: number | null;
  missing_data?: boolean;
}

function getFailureTexts(s: StockRow): string[] {
  if (s.failure_reasons && s.failure_reasons.length > 0) return s.failure_reasons;
  if (!s.reasons) return [];
  return s.reasons.map(r => typeof r === "string" ? r : r.text).filter(Boolean);
}

interface AiInsight {
  top_picks?: string[];
  strategy_fit_summary?: string;
  stocks?: Array<{ symbol: string; signal: string; reasoning: string }>;
  error?: string;
}

interface RunResult {
  run_id?: number;
  created_at?: string;
  strategy_name: string;
  target_label: string;
  total_evaluated: number;
  passed_count: number;
  stocks: StockRow[];
  ai_insight?: AiInsight | null;
}

interface RunHistoryItem {
  id: number;
  created_at: string;
  strategy_id: number;
  strategy_name: string;
  target_type: string;
  target_label: string;
  symbols_count: number;
  pass_count: number;
}

const typeColors: Record<string, string> = {
  value: "bg-blue-50 text-blue-700 dark:bg-blue-950/30 dark:text-blue-400",
  growth: "bg-green-50 text-green-700 dark:bg-green-950/30 dark:text-green-400",
  quality: "bg-purple-50 text-purple-700 dark:bg-purple-950/30 dark:text-purple-400",
  momentum: "bg-orange-50 text-orange-700 dark:bg-orange-950/30 dark:text-orange-400",
  dividend: "bg-yellow-50 text-yellow-700 dark:bg-yellow-950/30 dark:text-yellow-400",
};

const signalColors: Record<string, string> = {
  STRONG_BUY: "bg-green-700 text-white",
  BUY: "bg-green-900 text-green-200",
  HOLD: "bg-gray-700 text-gray-200",
  AVOID: "bg-red-900 text-red-200",
};

function fmtNum(n: number | null | undefined, d = 2): string {
  if (n === null || n === undefined) return "--";
  return n.toFixed(d);
}

function fmtPct(n: number | null | undefined): string {
  if (n === null || n === undefined) return "--";
  return `${(n * 100).toFixed(1)}%`;
}

const formatDate = fmtRelative;

export default function StrategiesPage() {
  const [data, setData] = useState<StrategiesResponse | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [expanded, setExpanded] = useState<number | null>(null);
  const [msg, setMsg] = useState<{ text: string; type: "ok" | "err" } | null>(null);

  const [runModal, setRunModal] = useState<Strategy | null>(null);
  const [watchlists, setWatchlists] = useState<WatchlistSummary[]>([]);
  const [targetType, setTargetType] = useState<string>("holdings");
  const [targetWlId, setTargetWlId] = useState<number | null>(null);
  const [running, setRunning] = useState(false);
  const [runResult, setRunResult] = useState<RunResult | null>(null);

  const [history, setHistory] = useState<RunHistoryItem[]>([]);
  const [showHistory, setShowHistory] = useState(false);
  const [expandedReasons, setExpandedReasons] = useState<string | null>(null);
  const [showOnlyPassed, setShowOnlyPassed] = useState(false);

  const [builderOpen, setBuilderOpen] = useState(false);
  const [builderInitial, setBuilderInitial] = useState<StrategyFormData | null>(null);
  const [builderEditId, setBuilderEditId] = useState<number | null>(null);
  const [builderSaving, setBuilderSaving] = useState(false);

  const showMsg = useCallback((text: string, type: "ok" | "err") => {
    setMsg({ text, type });
    setTimeout(() => setMsg(null), 4000);
  }, []);

  const loadStrategies = useCallback(async () => {
    const result = await api.get<StrategiesResponse>("/api/strategies/");
    setData(result);
    if (result.defaults.length === 0) {
      await api.post("/api/strategies/seed-defaults");
      const fresh = await api.get<StrategiesResponse>("/api/strategies/");
      setData(fresh);
    }
  }, []);

  const loadWatchlists = useCallback(async () => {
    try {
      const wls = await api.get<WatchlistSummary[]>("/api/watchlists/");
      setWatchlists(wls);
      if (wls.length > 0) setTargetWlId(wls[0].id);
    } catch {
      // ignore
    }
  }, []);

  const loadHistory = useCallback(async () => {
    try {
      const h = await api.get<RunHistoryItem[]>("/api/strategies/runs/history");
      setHistory(h);
    } catch {
      // ignore
    }
  }, []);

  useEffect(() => {
    loadStrategies();
    loadWatchlists();
    loadHistory();
  }, [loadStrategies, loadWatchlists, loadHistory]);

  // Auto-open run modal when arriving from watchlist with ?strategy=ID&target=watchlist&watchlist_id=WID
  const searchParams = useSearchParams();
  useEffect(() => {
    if (!data) return;
    const strategyIdParam = searchParams.get("strategy");
    const targetParam = searchParams.get("target");
    const wlIdParam = searchParams.get("watchlist_id");
    if (!strategyIdParam) return;

    const sid = parseInt(strategyIdParam, 10);
    const found = data.mine.find(s => s.id === sid) || data.defaults.find(s => s.id === sid);
    if (!found) return;

    setRunModal(found);
    if (targetParam) setTargetType(targetParam);
    if (wlIdParam) setTargetWlId(parseInt(wlIdParam, 10));
  }, [data, searchParams]);

  function toggleSelect(id: number) {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSelected(next);
  }

  async function importSelected() {
    if (selected.size === 0) {
      showMsg("Select at least one strategy to import", "err");
      return;
    }
    try {
      const res = await api.post<{ imported: string[]; count: number }>(
        "/api/strategies/import",
        { strategy_ids: Array.from(selected) },
      );
      showMsg(`Imported ${res.count} strategies`, "ok");
      setSelected(new Set());
      loadStrategies();
    } catch (err) {
      showMsg(err instanceof Error ? err.message : "Import failed", "err");
    }
  }

  async function deleteStrategy(id: number, name: string) {
    if (!confirm(`Delete strategy "${name}"? This cannot be undone.`)) return;
    try {
      await api.delete(`/api/strategies/${id}`);
      loadStrategies();
    } catch (err) {
      showMsg(err instanceof Error ? err.message : "Delete failed", "err");
    }
  }

  async function runStrategy() {
    if (!runModal) return;
    if (targetType === "watchlist" && !targetWlId) {
      showMsg("Select a watchlist", "err");
      return;
    }
    setRunning(true);
    setRunResult(null);
    try {
      const payload: { target_type: string; watchlist_id?: number } = { target_type: targetType };
      if (targetType === "watchlist" && targetWlId) payload.watchlist_id = targetWlId;
      const result = await api.post<RunResult>(`/api/strategies/${runModal.id}/run`, payload);
      setRunResult(result);
      loadHistory();
    } catch (err) {
      showMsg(err instanceof Error ? err.message : "Run failed", "err");
    } finally {
      setRunning(false);
    }
  }

  async function viewHistoricalRun(item: RunHistoryItem) {
    try {
      const runData = await api.get<RunResult>(`/api/strategies/runs/${item.id}`);
      // Find the underlying strategy so we can populate runModal (the result
      // view is rendered inside the modal). Fall back to a synthetic stub if
      // the strategy was deleted after this run was recorded.
      const found =
        data?.mine.find((s) => s.id === item.strategy_id) ||
        data?.defaults.find((s) => s.id === item.strategy_id);
      const modalStrategy: Strategy = found || {
        id: item.strategy_id,
        name: item.strategy_name,
        description: null,
        strategy_type: "value",
        is_default: false,
        is_active: false,
        is_mine: false,
        config_json: {},
      };
      setRunModal(modalStrategy);
      setRunResult(runData);
      setShowHistory(false);
    } catch (err) {
      showMsg(err instanceof Error ? err.message : "Failed to load run", "err");
    }
  }

  function openCreateBuilder() {
    setBuilderInitial(null);
    setBuilderEditId(null);
    setBuilderOpen(true);
  }

  function openCloneBuilder(s: Strategy) {
    setBuilderInitial({
      name: `${s.name} (Copy)`,
      description: s.description ?? "",
      strategy_type: s.strategy_type,
      config_json: s.config_json as StrategyFormData["config_json"],
    });
    setBuilderEditId(null);
    setBuilderOpen(true);
  }

  function openEditBuilder(s: Strategy) {
    setBuilderInitial({
      name: s.name,
      description: s.description ?? "",
      strategy_type: s.strategy_type,
      config_json: s.config_json as StrategyFormData["config_json"],
    });
    setBuilderEditId(s.id);
    setBuilderOpen(true);
  }

  async function handleBuilderSave(formData: StrategyFormData, editId: number | null) {
    setBuilderSaving(true);
    try {
      if (editId) {
        await api.put(`/api/strategies/${editId}`, formData);
        showMsg("Strategy updated", "ok");
      } else {
        await api.post("/api/strategies/create", formData);
        showMsg("Strategy created", "ok");
      }
      setBuilderOpen(false);
      loadStrategies();
    } catch (err) {
      showMsg(err instanceof Error ? err.message : "Save failed", "err");
    } finally {
      setBuilderSaving(false);
    }
  }

  if (!data) return <div className="text-gray-500">Loading strategies...</div>;

  const StrategyCard = ({ s, importable }: { s: Strategy; importable: boolean }) => (
    <div className="p-4 bg-gray-900 border border-gray-800 rounded-lg">
      <div className="flex items-start justify-between gap-3 mb-2">
        <div className="flex items-start gap-3 flex-1">
          {importable && (
            <input
              type="checkbox"
              checked={selected.has(s.id)}
              onChange={() => toggleSelect(s.id)}
              className="mt-1"
            />
          )}
          <div className="flex-1">
            <div className="flex items-center gap-2 mb-1">
              <h3 className="font-semibold text-white">{s.name}</h3>
              <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${typeColors[s.strategy_type] || "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400"}`}>
                {s.strategy_type}
              </span>
            </div>
            <p className="text-sm text-gray-400">{s.description}</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {!importable && (
            <button
              onClick={() => { setRunModal(s); setRunResult(null); }}
              className="px-3 py-1 bg-blue-600 hover:bg-blue-700 text-white text-xs rounded-md transition-colors"
            >
              Run
            </button>
          )}
          <button
            onClick={() => openCloneBuilder(s)}
            className="text-xs text-green-400 hover:text-green-300"
          >
            Clone
          </button>
          {!importable && s.is_mine && (
            <button
              onClick={() => openEditBuilder(s)}
              className="text-xs text-yellow-400 hover:text-yellow-300"
            >
              Edit
            </button>
          )}
          <button
            onClick={() => setExpanded(expanded === s.id ? null : s.id)}
            className="text-xs text-blue-400 hover:text-blue-300"
          >
            {expanded === s.id ? "Hide" : "Details"}
          </button>
          {!importable && s.is_mine && (
            <button
              onClick={() => deleteStrategy(s.id, s.name)}
              className="text-xs text-red-400 hover:text-red-300 hover:bg-red-950/40 px-2 py-1 rounded border border-red-900/40"
              aria-label={`Delete strategy ${s.name}`}
            >
              Delete
            </button>
          )}
        </div>
      </div>
      {expanded === s.id && (
        <pre className="text-xs text-gray-400 bg-gray-950 p-3 rounded mt-2 overflow-auto">
          {JSON.stringify(s.config_json, null, 2)}
        </pre>
      )}
    </div>
  );

  return (
    <div>
      {builderOpen && (
        <StrategyBuilder
          initial={builderInitial}
          editId={builderEditId}
          onSave={handleBuilderSave}
          onCancel={() => setBuilderOpen(false)}
          saving={builderSaving}
        />
      )}

      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between mb-2 gap-3">
        <h1 className="text-2xl font-bold">Trading Strategies</h1>
        <div className="flex items-center gap-2 flex-wrap">
          <button
            onClick={openCreateBuilder}
            className="px-3 py-1.5 bg-green-600 hover:bg-green-700 text-white text-sm rounded-md transition-colors"
          >
            + Create Strategy
          </button>
          <button
            onClick={() => setShowHistory(!showHistory)}
            className="px-3 py-1.5 bg-gray-800 hover:bg-gray-700 text-sm rounded-md transition-colors"
          >
            Run History ({history.length})
          </button>
        </div>
      </div>
      <p className="text-sm text-gray-400 mb-6">
        World-renowned strategies adapted for the Indian market. Import, then click <span className="text-blue-400 font-semibold">Run</span> to evaluate against your holdings, a watchlist, or Nifty 50.
      </p>

      {msg && (
        <div className={`mb-4 p-3 rounded text-sm ${msg.type === "ok" ? "bg-green-950 border border-green-800 text-green-300" : "bg-red-950 border border-red-800 text-red-300"}`}>
          {msg.text}
        </div>
      )}

      {/* Run History Panel */}
      {showHistory && (
        <div className="mb-6 p-4 bg-gray-900 border border-gray-800 rounded-lg">
          <h2 className="font-semibold mb-3">Strategy Run History</h2>
          {history.length === 0 ? (
            <div className="text-sm text-gray-600 text-center py-6">No runs yet</div>
          ) : (
            <div className="space-y-2">
              {history.map((r) => (
                <button
                  key={r.id}
                  onClick={() => viewHistoricalRun(r)}
                  className="w-full text-left p-3 bg-gray-800 hover:bg-gray-750 rounded-md border border-gray-700"
                >
                  <div className="flex items-center justify-between mb-1">
                    <span className="font-semibold text-white text-sm">{r.strategy_name}</span>
                    <span className="text-xs text-gray-500">{formatDate(r.created_at)}</span>
                  </div>
                  <div className="text-xs text-gray-400">
                    {r.target_label} · <span className="text-green-400">{r.pass_count} passed</span> / {r.symbols_count} evaluated
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Run Modal */}
      {runModal && (
        <div className="fixed inset-0 bg-black/70 z-50 flex items-start justify-center p-6 overflow-auto">
          <div className="bg-gray-900 border border-gray-800 rounded-lg max-w-4xl w-full my-6">
            <div className="p-4 border-b border-gray-800 flex items-start justify-between">
              <div>
                <h2 className="text-lg font-semibold text-white">{runModal.name}</h2>
                <p className="text-xs text-gray-500">{runModal.description}</p>
              </div>
              <button
                onClick={() => { setRunModal(null); setRunResult(null); }}
                className="text-gray-400 hover:text-white text-xl leading-none"
              >
                ×
              </button>
            </div>

            {!runResult && (
              <div className="p-4">
                <label className="block text-xs text-gray-400 mb-2">Run on target:</label>
                <div className="space-y-2 mb-4">
                  <label className="flex items-center gap-2 p-3 bg-gray-800 rounded cursor-pointer hover:bg-gray-750">
                    <input type="radio" name="target" value="holdings" checked={targetType === "holdings"} onChange={(e) => setTargetType(e.target.value)} />
                    <div>
                      <div className="text-sm text-white">My Holdings</div>
                      <div className="text-xs text-gray-500">Evaluate stocks in your Kite portfolio</div>
                    </div>
                  </label>
                  <label className="flex items-start gap-2 p-3 bg-gray-800 rounded cursor-pointer hover:bg-gray-750">
                    <input type="radio" name="target" value="watchlist" checked={targetType === "watchlist"} onChange={(e) => setTargetType(e.target.value)} className="mt-1" />
                    <div className="flex-1">
                      <div className="text-sm text-white">A specific Watchlist</div>
                      {targetType === "watchlist" && (
                        <select
                          value={targetWlId || ""}
                          onChange={(e) => setTargetWlId(Number(e.target.value))}
                          className="mt-2 px-2 py-1 bg-gray-700 border border-gray-600 rounded text-white text-sm"
                        >
                          {watchlists.map(w => <option key={w.id} value={w.id}>{w.name} ({w.stock_count})</option>)}
                        </select>
                      )}
                    </div>
                  </label>
                  <label className="flex items-center gap-2 p-3 bg-gray-800 rounded cursor-pointer hover:bg-gray-750">
                    <input type="radio" name="target" value="nifty50" checked={targetType === "nifty50"} onChange={(e) => setTargetType(e.target.value)} />
                    <div>
                      <div className="text-sm text-white">Nifty 50 Universe</div>
                      <div className="text-xs text-gray-500">Screen top 50 Indian stocks by market cap</div>
                    </div>
                  </label>
                </div>
                <button
                  onClick={runStrategy}
                  disabled={running}
                  className="w-full px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white text-sm rounded-md transition-colors"
                >
                  {running ? "Running strategy (fetching fundamentals + AI analysis)..." : "Run Strategy"}
                </button>
                <p className="text-xs text-gray-600 mt-2 text-center">
                  This may take 30-60 seconds depending on the target size
                </p>
              </div>
            )}

            {runResult && (
              <div className="p-4">
                <div className="mb-4 p-3 bg-gray-800 rounded flex items-center justify-between">
                  <div>
                    <div className="text-sm text-white">{runResult.target_label}</div>
                    <div className="text-xs text-gray-500">
                      <span className="text-green-400">{runResult.passed_count}</span> passed filters / {runResult.total_evaluated} evaluated
                    </div>
                  </div>
                  <button
                    onClick={() => setRunResult(null)}
                    className="text-xs text-blue-400 hover:text-blue-300"
                  >
                    New Run
                  </button>
                </div>

                {/* Common failure reasons summary */}
                {(() => {
                  const failureCounts: Record<string, number> = {};
                  runResult.stocks.forEach(s => {
                    if (!s.passed && !s.missing_data && s.reasons) {
                      s.reasons.forEach((r) => {
                        const isFailObj = typeof r === "object" && r !== null && "failed" in r && r.failed && "metric" in r;
                        if (isFailObj) {
                          const metric = (r as ReasonDetail).metric;
                          failureCounts[metric] = (failureCounts[metric] || 0) + 1;
                        }
                      });
                    }
                  });
                  const sorted = Object.entries(failureCounts).sort((a, b) => b[1] - a[1]).slice(0, 5);
                  if (sorted.length === 0) return null;
                  return (
                    <div className="mb-4 p-3 bg-red-950/20 border border-red-900/40 rounded">
                      <div className="text-xs uppercase text-red-400 mb-2">Most Common Failure Reasons</div>
                      <div className="flex flex-wrap gap-2">
                        {sorted.map(([metric, count]) => (
                          <span key={metric} className="text-xs bg-red-900/40 text-red-200 px-2 py-1 rounded">
                            {metric}: <span className="font-bold">{count}</span> stocks failed
                          </span>
                        ))}
                      </div>
                    </div>
                  );
                })()}

                {runResult.ai_insight?.top_picks && runResult.ai_insight.top_picks.length > 0 && (
                  <div className="mb-4 p-3 bg-green-950/30 border border-green-800/50 rounded">
                    <div className="text-xs uppercase text-green-400 mb-1">AI Top Picks</div>
                    <div className="flex flex-wrap gap-2">
                      {runResult.ai_insight.top_picks.map((s) => (
                        <span key={s} className="text-sm font-mono font-semibold text-white bg-green-900/50 px-2 py-1 rounded">{s}</span>
                      ))}
                    </div>
                    {runResult.ai_insight.strategy_fit_summary && (
                      <p className="text-xs text-gray-400 mt-2">{runResult.ai_insight.strategy_fit_summary}</p>
                    )}
                  </div>
                )}

                {/* Filter toggle */}
                <div className="flex items-center justify-end gap-3 mb-2 text-xs">
                  <label className="flex items-center gap-2 cursor-pointer text-gray-400">
                    <input
                      type="checkbox"
                      checked={showOnlyPassed}
                      onChange={(e) => setShowOnlyPassed(e.target.checked)}
                    />
                    Show only passed
                  </label>
                </div>

                <div className="overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="border-b border-gray-800 text-gray-500 uppercase">
                        <th className="text-left p-2 w-8"></th>
                        <th className="text-left p-2">Symbol</th>
                        <th className="text-center p-2">Pass</th>
                        <th className="text-right p-2">Score</th>
                        <th className="text-center p-2">Signal</th>
                        <th className="text-right p-2">CMP</th>
                        <th className="text-right p-2">P/E</th>
                        <th className="text-right p-2">P/B</th>
                        <th className="text-right p-2">D/E</th>
                        <th className="text-right p-2">Rev Gr</th>
                        <th className="text-right p-2">EPS Gr</th>
                        <th className="text-right p-2">Margin</th>
                        <th className="text-right p-2">ROE</th>
                      </tr>
                    </thead>
                    <tbody>
                      {runResult.stocks
                        .filter(s => !showOnlyPassed || s.passed)
                        .map((s) => {
                          const aiEntry = runResult.ai_insight?.stocks?.find(x => x.symbol === s.symbol);
                          const failures = getFailureTexts(s);
                          const isExpanded = expandedReasons === s.symbol;
                          const canExpand = !s.passed && failures.length > 0;
                          return (
                            <React.Fragment key={s.symbol}>
                              <tr
                                className={`border-b border-gray-800/50 hover:bg-gray-800/30 ${canExpand ? "cursor-pointer" : ""}`}
                                onClick={() => canExpand && setExpandedReasons(isExpanded ? null : s.symbol)}
                              >
                                <td className="p-2 text-center">
                                  {canExpand && (
                                    <span className="text-gray-500 text-[10px]">{isExpanded ? "▼" : "▶"}</span>
                                  )}
                                </td>
                                <td className="p-2 font-mono text-white">{s.symbol}</td>
                                <td className="p-2 text-center">
                                  {s.passed ? (
                                    <span className="text-green-400">✓</span>
                                  ) : s.missing_data ? (
                                    <span className="text-gray-600" title="No fundamentals data">?</span>
                                  ) : (
                                    <span className="text-red-400">✗</span>
                                  )}
                                </td>
                                <td className="p-2 text-right">
                                  <span className={s.score >= 70 ? "text-green-400" : s.score >= 40 ? "text-yellow-400" : "text-gray-500"}>
                                    {s.score.toFixed(0)}
                                  </span>
                                </td>
                                <td className="p-2 text-center">
                                  {aiEntry ? (
                                    <span className={`text-xs px-2 py-0.5 rounded ${signalColors[aiEntry.signal] || "bg-gray-700"}`} title={aiEntry.reasoning}>
                                      {aiEntry.signal}
                                    </span>
                                  ) : (
                                    <span className="text-gray-700">--</span>
                                  )}
                                </td>
                                <td className="p-2 text-right">{fmtNum(s.cmp)}</td>
                                <td className="p-2 text-right">{fmtNum(s.pe)}</td>
                                <td className="p-2 text-right">{fmtNum(s.pb)}</td>
                                <td className="p-2 text-right">{fmtNum(s.de)}</td>
                                <td className="p-2 text-right">{fmtPct(s.rev_gr)}</td>
                                <td className="p-2 text-right">{fmtPct(s.eps_gr)}</td>
                                <td className="p-2 text-right">{fmtPct(s.margin)}</td>
                                <td className="p-2 text-right">{fmtPct(s.roe)}</td>
                              </tr>

                              {/* Inline failure reasons row */}
                              {!s.passed && !s.missing_data && failures.length > 0 && (
                                <tr className="bg-red-950/20 border-b border-gray-800/50">
                                  <td colSpan={13} className="px-3 py-2">
                                    <div className="flex items-start gap-2">
                                      <span className="text-red-400 text-xs font-semibold whitespace-nowrap">Why {s.symbol} failed:</span>
                                      <ul className="flex-1 space-y-1 text-xs text-red-200">
                                        {failures.map((reason, i) => (
                                          <li key={i} className="leading-relaxed">- {reason}</li>
                                        ))}
                                      </ul>
                                    </div>
                                    {isExpanded && aiEntry?.reasoning && (
                                      <div className="mt-2 pt-2 border-t border-red-900/30 text-xs text-gray-400">
                                        <span className="text-blue-300">AI note:</span> {aiEntry.reasoning}
                                      </div>
                                    )}
                                  </td>
                                </tr>
                              )}

                              {/* Missing data row */}
                              {s.missing_data && (
                                <tr className="bg-gray-900/40 border-b border-gray-800/50">
                                  <td colSpan={13} className="px-3 py-2 text-xs text-gray-500">
                                    <span className="font-semibold">{s.symbol}:</span> Fundamentals data not available from yfinance for this stock.
                                  </td>
                                </tr>
                              )}
                            </React.Fragment>
                          );
                        })}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* My Strategies */}
      {data.mine.length > 0 && (
        <div className="mb-8">
          <h2 className="text-lg font-semibold mb-3">My Strategies ({data.mine.length})</h2>
          <div className="space-y-2">
            {data.mine.map((s) => (
              <StrategyCard key={s.id} s={s} importable={false} />
            ))}
          </div>
        </div>
      )}

      {/* Default Strategies */}
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-lg font-semibold">Default Strategies ({data.defaults.length})</h2>
        <button
          onClick={importSelected}
          disabled={selected.size === 0}
          className="px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-30 text-white text-sm rounded-md transition-colors"
        >
          Import Selected ({selected.size})
        </button>
      </div>
      <div className="space-y-2">
        {data.defaults.map((s) => (
          <StrategyCard key={s.id} s={s} importable={true} />
        ))}
      </div>
    </div>
  );
}
