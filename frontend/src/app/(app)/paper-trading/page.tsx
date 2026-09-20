"use client";

import React, { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { fmtINR, pctStr, fmtRelative } from "@/lib/format";

/* ─── types ───────────────────────────────────────────────────── */

interface Scorecard {
  portfolio_value: number;
  cash: number;
  positions_value: number;
  total_return_pct: number;
  realized_pnl: number;
  unrealized_pnl: number;
  win_rate: number;
  avg_holding_days: number;
  total_trades: number;
  positions_count: number;
  best_trade: { symbol: string; pnl: number; pnl_pct: number } | null;
  worst_trade: { symbol: string; pnl: number; pnl_pct: number } | null;
  positions: PositionRow[];
}

interface PositionRow {
  symbol: string;
  quantity: number;
  avg_cost: number;
  current_price: number;
  value: number;
  unrealized_pnl: number;
  unrealized_pnl_pct: number;
}

interface Agent {
  id: number;
  name: string;
  strategy_id: number | null;
  strategy_name: string | null;
  initial_corpus_inr: number;
  config_json: Record<string, unknown>;
  is_active: boolean;
  created_at: string;
  scorecard?: Scorecard;
  recommendations?: Recommendation[];
}

interface Recommendation {
  symbol: string;
  exchange: string;
  side: "BUY" | "SELL";
  suggested_quantity: number;
  current_price: number;
  estimated_cost: number;
  reasoning: string;
  ai_verdict: { verdict: string; confidence: number; target_price?: number };
  has_fno: boolean;
}

interface EventRow {
  id: number;
  event_type: string;
  symbol: string | null;
  exchange: string | null;
  quantity: number | null;
  price_inr: number | null;
  notes: string | null;
  source: string;
  snapshot_json: Record<string, unknown> | null;
  created_at: string;
}

interface StrategySummary {
  id: number;
  name: string;
}

/* ─── color helpers ───────────────────────────────────────────── */

function pnlColor(v: number): string {
  return v > 0 ? "text-green-400" : v < 0 ? "text-red-400" : "text-gray-400";
}

function pnlSign(v: number): string {
  if (v > 0) return `+${fmtINR(v)}`;
  return fmtINR(v);
}

const EVENT_COLORS: Record<string, string> = {
  DEPOSIT: "bg-blue-900/50 text-blue-300",
  BUY: "bg-green-900/50 text-green-300",
  SELL: "bg-red-900/50 text-red-300",
  RESET: "bg-yellow-900/50 text-yellow-300",
};

/* ─── page ────────────────────────────────────────────────────── */

export default function PaperTradingPage() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detailAgent, setDetailAgent] = useState<Agent | null>(null);
  const [events, setEvents] = useState<EventRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [msg, setMsg] = useState<{ text: string; type: "ok" | "err" } | null>(null);

  const [createOpen, setCreateOpen] = useState(false);
  const [tradeOpen, setTradeOpen] = useState(false);
  const [strategies, setStrategies] = useState<StrategySummary[]>([]);

  const showMsg = useCallback((text: string, type: "ok" | "err") => {
    setMsg({ text, type });
    setTimeout(() => setMsg(null), 4000);
  }, []);

  const loadAgents = useCallback(async () => {
    try {
      const data = await api.get<Agent[]>("/api/paper/agents");
      setAgents(data);
    } catch (err) {
      showMsg(err instanceof Error ? err.message : "Failed to load agents", "err");
    } finally {
      setLoading(false);
    }
  }, [showMsg]);

  const loadDetail = useCallback(async (id: number) => {
    try {
      const [state, evts] = await Promise.all([
        api.get<Agent>(`/api/paper/agents/${id}/state`),
        api.get<EventRow[]>(`/api/paper/agents/${id}/events`),
      ]);
      setDetailAgent(state);
      setEvents(evts);
    } catch (err) {
      showMsg(err instanceof Error ? err.message : "Failed to load agent", "err");
    }
  }, [showMsg]);

  const loadStrategies = useCallback(async () => {
    try {
      const data = await api.get<{ defaults: StrategySummary[]; mine: StrategySummary[] }>("/api/strategies/");
      setStrategies([...data.mine, ...data.defaults]);
    } catch { /* ignore */ }
  }, []);

  useEffect(() => {
    loadAgents();
    loadStrategies();
  }, [loadAgents, loadStrategies]);

  useEffect(() => {
    if (selectedId) loadDetail(selectedId);
  }, [selectedId, loadDetail]);

  /* ── create agent ─────────────────────────────────── */

  const [createName, setCreateName] = useState("");
  const [createStrategy, setCreateStrategy] = useState<number | null>(null);
  const [createCorpus, setCreateCorpus] = useState(1000000);
  const [createFno, setCreateFno] = useState(false);
  const [createMaxPos, setCreateMaxPos] = useState(15);
  const [createMinConf, setCreateMinConf] = useState(60);
  const [creating, setCreating] = useState(false);

  async function handleCreate() {
    if (!createName.trim()) { showMsg("Name required", "err"); return; }
    setCreating(true);
    try {
      await api.post("/api/paper/agents", {
        name: createName.trim(),
        strategy_id: createStrategy,
        initial_corpus_inr: createCorpus,
        config_json: {
          fno_only: createFno,
          max_positions: createMaxPos,
          min_confidence: createMinConf,
        },
      });
      showMsg("Agent created", "ok");
      setCreateOpen(false);
      setCreateName("");
      loadAgents();
    } catch (err) {
      showMsg(err instanceof Error ? err.message : "Create failed", "err");
    } finally {
      setCreating(false);
    }
  }

  /* ── trade ────────────────────────────────────────── */

  const [tradeSide, setTradeSide] = useState<"BUY" | "SELL">("BUY");
  const [tradeSymbol, setTradeSymbol] = useState("");
  const [tradeQty, setTradeQty] = useState(1);
  const [tradeNotes, setTradeNotes] = useState("");
  const [trading, setTrading] = useState(false);

  async function handleTrade() {
    if (!tradeSymbol.trim() || tradeQty <= 0 || !selectedId) return;
    setTrading(true);
    try {
      const result = await api.post<{ status: string; price: number; total: number }>(
        `/api/paper/agents/${selectedId}/events`,
        { event_type: tradeSide, symbol: tradeSymbol.trim().toUpperCase(), quantity: tradeQty, notes: tradeNotes || null },
      );
      showMsg(`${tradeSide} ${tradeQty} ${tradeSymbol.toUpperCase()} @ ${fmtINR(result.price)}`, "ok");
      setTradeOpen(false);
      setTradeSymbol("");
      setTradeQty(1);
      setTradeNotes("");
      loadDetail(selectedId);
      loadAgents();
    } catch (err) {
      showMsg(err instanceof Error ? err.message : "Trade failed", "err");
    } finally {
      setTrading(false);
    }
  }

  /* ── approve recommendation ───────────────────────── */

  async function approveRec(rec: Recommendation) {
    if (!selectedId) return;
    try {
      await api.post(`/api/paper/agents/${selectedId}/events`, {
        event_type: rec.side,
        symbol: rec.symbol,
        quantity: rec.suggested_quantity,
        notes: rec.reasoning,
        source: "ai_recommendation",
      });
      showMsg(`${rec.side} ${rec.suggested_quantity} ${rec.symbol} executed`, "ok");
      loadDetail(selectedId);
      loadAgents();
    } catch (err) {
      showMsg(err instanceof Error ? err.message : "Execution failed", "err");
    }
  }

  /* ── reset agent ──────────────────────────────────── */

  async function handleReset() {
    if (!selectedId || !confirm("Reset this agent? All positions will be cleared.")) return;
    try {
      await api.post(`/api/paper/agents/${selectedId}/reset`);
      showMsg("Agent reset", "ok");
      loadDetail(selectedId);
      loadAgents();
    } catch (err) {
      showMsg(err instanceof Error ? err.message : "Reset failed", "err");
    }
  }

  /* ── delete agent ─────────────────────────────────── */

  async function handleDelete(id: number) {
    if (!confirm("Delete this agent and all its history?")) return;
    try {
      await api.delete(`/api/paper/agents/${id}`);
      showMsg("Agent deleted", "ok");
      if (selectedId === id) { setSelectedId(null); setDetailAgent(null); }
      loadAgents();
    } catch (err) {
      showMsg(err instanceof Error ? err.message : "Delete failed", "err");
    }
  }

  /* ─── render ────────────────────────────────────────── */

  if (loading) return <div className="text-gray-500">Loading paper trading...</div>;

  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between mb-2">
        <div>
          <h1 className="text-2xl font-bold">Paper Trading</h1>
          <p className="text-sm text-gray-400">AI agents competing with virtual money</p>
        </div>
        <button
          onClick={() => setCreateOpen(true)}
          className="px-3 py-1.5 bg-green-600 hover:bg-green-700 text-white text-sm rounded-md transition-colors"
        >
          + Create Agent
        </button>
      </div>

      {msg && (
        <div className={`mb-4 p-3 rounded text-sm ${msg.type === "ok" ? "bg-green-950 border border-green-800 text-green-300" : "bg-red-950 border border-red-800 text-red-300"}`}>
          {msg.text}
        </div>
      )}

      {/* Agents comparison table */}
      {agents.length === 0 ? (
        <div className="text-center py-12 text-gray-500">
          <p className="text-lg mb-2">No agents yet</p>
          <p className="text-sm">Create your first paper trading agent to get started.</p>
        </div>
      ) : (
        <div className="overflow-x-auto mb-6">
          <table className="w-full text-sm" style={{ minWidth: 720 }}>
            <thead>
              <tr className="border-b border-gray-800 text-gray-500 text-xs uppercase">
                <th className="text-left p-2 whitespace-nowrap">Agent</th>
                <th className="text-left p-2 whitespace-nowrap">Strategy</th>
                <th className="text-right p-2 whitespace-nowrap">Return</th>
                <th className="text-right p-2 whitespace-nowrap">Realized</th>
                <th className="text-right p-2 whitespace-nowrap">Unrealized</th>
                <th className="text-right p-2 whitespace-nowrap">Win Rate</th>
                <th className="text-right p-2 whitespace-nowrap">Trades</th>
                <th className="text-right p-2 whitespace-nowrap">Cash</th>
                <th className="text-center p-2 whitespace-nowrap">Status</th>
                <th className="p-2"></th>
              </tr>
            </thead>
            <tbody>
              {agents.map(a => {
                const sc = a.scorecard;
                const isSelected = selectedId === a.id;
                return (
                  <tr
                    key={a.id}
                    onClick={() => setSelectedId(isSelected ? null : a.id)}
                    className={`border-b border-gray-800/50 cursor-pointer transition-colors ${
                      isSelected ? "bg-blue-950/30" : "hover:bg-gray-800/30"
                    }`}
                  >
                    <td className="p-2 font-semibold text-white">{a.name}</td>
                    <td className="p-2 text-gray-400 text-xs">{a.strategy_name || "Manual"}</td>
                    <td className={`p-2 text-right font-mono font-semibold ${pnlColor(sc?.total_return_pct ?? 0)}`}>
                      {sc ? `${sc.total_return_pct > 0 ? "+" : ""}${sc.total_return_pct.toFixed(1)}%` : "--"}
                    </td>
                    <td className={`p-2 text-right font-mono ${pnlColor(sc?.realized_pnl ?? 0)}`}>
                      {sc ? pnlSign(sc.realized_pnl) : "--"}
                    </td>
                    <td className={`p-2 text-right font-mono ${pnlColor(sc?.unrealized_pnl ?? 0)}`}>
                      {sc ? pnlSign(sc.unrealized_pnl) : "--"}
                    </td>
                    <td className="p-2 text-right">{sc ? `${sc.win_rate.toFixed(0)}%` : "--"}</td>
                    <td className="p-2 text-right">{sc?.total_trades ?? 0}</td>
                    <td className="p-2 text-right font-mono text-xs">{sc ? fmtINR(sc.cash) : "--"}</td>
                    <td className="p-2 text-center">
                      <span className={`text-xs px-2 py-0.5 rounded-full ${a.is_active ? "bg-green-900/50 text-green-400" : "bg-gray-800 text-gray-500"}`}>
                        {a.is_active ? "Active" : "Paused"}
                      </span>
                    </td>
                    <td className="p-2">
                      <button
                        onClick={e => { e.stopPropagation(); handleDelete(a.id); }}
                        className="text-xs text-gray-600 hover:text-red-400"
                      >
                        Delete
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Single agent detail */}
      {detailAgent && detailAgent.scorecard && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold text-white">{detailAgent.name}</h2>
            <div className="flex items-center gap-2">
              <button onClick={() => { setTradeSide("BUY"); setTradeOpen(true); }} className="px-3 py-1 bg-green-600 hover:bg-green-700 text-white text-xs rounded-md">Buy</button>
              <button onClick={() => { setTradeSide("SELL"); setTradeOpen(true); }} className="px-3 py-1 bg-red-600 hover:bg-red-700 text-white text-xs rounded-md">Sell</button>
              <button onClick={handleReset} className="px-3 py-1 bg-yellow-600 hover:bg-yellow-700 text-white text-xs rounded-md">Reset</button>
            </div>
          </div>

          {/* Scorecard */}
          <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-6 gap-3">
            {[
              { label: "Portfolio Value", value: fmtINR(detailAgent.scorecard.portfolio_value) },
              { label: "Total Return", value: `${detailAgent.scorecard.total_return_pct > 0 ? "+" : ""}${detailAgent.scorecard.total_return_pct.toFixed(2)}%`, color: pnlColor(detailAgent.scorecard.total_return_pct) },
              { label: "Realized P&L", value: pnlSign(detailAgent.scorecard.realized_pnl), color: pnlColor(detailAgent.scorecard.realized_pnl) },
              { label: "Unrealized P&L", value: pnlSign(detailAgent.scorecard.unrealized_pnl), color: pnlColor(detailAgent.scorecard.unrealized_pnl) },
              { label: "Win Rate", value: `${detailAgent.scorecard.win_rate.toFixed(0)}%` },
              { label: "Avg Holding", value: `${detailAgent.scorecard.avg_holding_days.toFixed(0)} days` },
              { label: "Total Trades", value: String(detailAgent.scorecard.total_trades) },
              { label: "Positions", value: String(detailAgent.scorecard.positions_count) },
              { label: "Cash Left", value: fmtINR(detailAgent.scorecard.cash) },
              ...(detailAgent.scorecard.best_trade ? [{ label: "Best Trade", value: `${detailAgent.scorecard.best_trade.symbol} +${detailAgent.scorecard.best_trade.pnl_pct.toFixed(1)}%`, color: "text-green-400" }] : []),
              ...(detailAgent.scorecard.worst_trade ? [{ label: "Worst Trade", value: `${detailAgent.scorecard.worst_trade.symbol} ${detailAgent.scorecard.worst_trade.pnl_pct.toFixed(1)}%`, color: "text-red-400" }] : []),
            ].map((m, i) => (
              <div key={i} className="p-3 bg-gray-900 border border-gray-800 rounded-lg">
                <div className="text-xs text-gray-500 mb-1">{m.label}</div>
                <div className={`text-sm font-semibold font-mono ${m.color || "text-white"}`}>{m.value}</div>
              </div>
            ))}
          </div>

          {/* Recommendations */}
          {detailAgent.recommendations && detailAgent.recommendations.length > 0 && (
            <div>
              <h3 className="text-sm font-semibold text-gray-300 mb-2 uppercase tracking-wide">AI Recommendations</h3>
              <div className="space-y-2">
                {detailAgent.recommendations.map(rec => (
                  <div key={`${rec.side}-${rec.symbol}`} className={`p-3 rounded-lg border ${rec.side === "BUY" ? "bg-green-950/20 border-green-900/40" : "bg-red-950/20 border-red-900/40"}`}>
                    <div className="flex items-center justify-between mb-1">
                      <div className="flex items-center gap-2">
                        <span className={`text-xs font-bold px-2 py-0.5 rounded ${rec.side === "BUY" ? "bg-green-700 text-white" : "bg-red-700 text-white"}`}>
                          {rec.side}
                        </span>
                        <span className="font-mono font-semibold text-white">{rec.symbol}</span>
                        {rec.has_fno && <span className="text-[10px] px-1.5 py-0.5 rounded bg-orange-900/50 text-orange-400">F&O</span>}
                      </div>
                      <div className="flex items-center gap-2">
                        <span className="text-xs text-gray-400">
                          {rec.suggested_quantity} × {fmtINR(rec.current_price)} = {fmtINR(rec.estimated_cost)}
                        </span>
                        <button
                          onClick={() => approveRec(rec)}
                          className={`px-3 py-1 text-xs rounded-md text-white ${rec.side === "BUY" ? "bg-green-600 hover:bg-green-700" : "bg-red-600 hover:bg-red-700"}`}
                        >
                          Approve
                        </button>
                      </div>
                    </div>
                    <p className="text-xs text-gray-400">{rec.reasoning}</p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Open positions */}
          {detailAgent.scorecard.positions.length > 0 && (
            <div>
              <h3 className="text-sm font-semibold text-gray-300 mb-2 uppercase tracking-wide">Open Positions</h3>
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-gray-800 text-gray-500 uppercase">
                      <th className="text-left p-2">Symbol</th>
                      <th className="text-right p-2">Qty</th>
                      <th className="text-right p-2">Avg Cost</th>
                      <th className="text-right p-2">CMP</th>
                      <th className="text-right p-2">Value</th>
                      <th className="text-right p-2">P&L</th>
                      <th className="text-right p-2">P&L %</th>
                    </tr>
                  </thead>
                  <tbody>
                    {detailAgent.scorecard.positions.map(p => (
                      <tr key={p.symbol} className="border-b border-gray-800/50">
                        <td className="p-2 font-mono font-semibold text-white">{p.symbol}</td>
                        <td className="p-2 text-right">{p.quantity}</td>
                        <td className="p-2 text-right font-mono">{fmtINR(p.avg_cost)}</td>
                        <td className="p-2 text-right font-mono">{fmtINR(p.current_price)}</td>
                        <td className="p-2 text-right font-mono">{fmtINR(p.value)}</td>
                        <td className={`p-2 text-right font-mono ${pnlColor(p.unrealized_pnl)}`}>{pnlSign(p.unrealized_pnl)}</td>
                        <td className={`p-2 text-right font-mono ${pnlColor(p.unrealized_pnl_pct)}`}>
                          {p.unrealized_pnl_pct > 0 ? "+" : ""}{p.unrealized_pnl_pct.toFixed(2)}%
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Event log */}
          <div>
            <h3 className="text-sm font-semibold text-gray-300 mb-2 uppercase tracking-wide">Event History</h3>
            {events.length === 0 ? (
              <div className="text-sm text-gray-600 py-4 text-center">No events yet</div>
            ) : (
              <div className="space-y-1 max-h-80 overflow-y-auto">
                {events.map(ev => (
                  <div key={ev.id} className="flex items-center gap-3 px-3 py-2 bg-gray-900/50 rounded text-xs">
                    <span className={`px-2 py-0.5 rounded font-semibold ${EVENT_COLORS[ev.event_type] || "bg-gray-800 text-gray-400"}`}>
                      {ev.event_type}
                    </span>
                    <span className="font-mono text-white w-20">{ev.symbol || "--"}</span>
                    <span className="text-gray-400 w-16 text-right">{ev.quantity ?? "--"}</span>
                    <span className="font-mono text-gray-300 w-24 text-right">
                      {ev.price_inr ? `@ ${fmtINR(ev.price_inr)}` : ""}
                    </span>
                    <span className="text-gray-500 flex-1 truncate">{ev.notes || ""}</span>
                    <span className="text-gray-600 text-[10px] w-24 text-right shrink-0">
                      {fmtRelative(ev.created_at)}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Create Agent Modal */}
      {createOpen && (
        <div className="fixed inset-0 bg-black/70 z-50 flex items-start justify-center p-6 overflow-auto">
          <div className="bg-gray-900 border border-gray-800 rounded-lg max-w-md w-full my-6">
            <div className="p-4 border-b border-gray-800 flex items-center justify-between">
              <h2 className="text-lg font-semibold text-white">Create Agent</h2>
              <button onClick={() => setCreateOpen(false)} className="text-gray-400 hover:text-white text-xl">×</button>
            </div>
            <div className="p-4 space-y-4">
              <div>
                <label className="block text-xs text-gray-400 mb-1">Name *</label>
                <input value={createName} onChange={e => setCreateName(e.target.value)} placeholder="e.g. Graham Bot"
                  className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded text-sm text-white focus:border-blue-500 focus:outline-none" />
              </div>
              <div>
                <label className="block text-xs text-gray-400 mb-1">Strategy</label>
                <select
                  value={createStrategy ?? ""}
                  onChange={e => setCreateStrategy(e.target.value ? Number(e.target.value) : null)}
                  className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded text-sm text-white focus:border-blue-500 focus:outline-none"
                >
                  <option value="">Manual only (no AI recommendations)</option>
                  {strategies.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
                </select>
              </div>
              <div>
                <label className="block text-xs text-gray-400 mb-1">Starting Capital (INR)</label>
                <input type="number" value={createCorpus} onChange={e => setCreateCorpus(Number(e.target.value))}
                  className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded text-sm text-white focus:border-blue-500 focus:outline-none" />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs text-gray-400 mb-1">Min Confidence (%)</label>
                  <input type="number" value={createMinConf} onChange={e => setCreateMinConf(Number(e.target.value))} min={0} max={100}
                    className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded text-sm text-white focus:border-blue-500 focus:outline-none" />
                </div>
                <div>
                  <label className="block text-xs text-gray-400 mb-1">Max Positions</label>
                  <input type="number" value={createMaxPos} onChange={e => setCreateMaxPos(Number(e.target.value))} min={1} max={50}
                    className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded text-sm text-white focus:border-blue-500 focus:outline-none" />
                </div>
              </div>
              <label className="flex items-center gap-2 cursor-pointer">
                <input type="checkbox" checked={createFno} onChange={e => setCreateFno(e.target.checked)} className="accent-orange-500" />
                <span className="text-sm text-gray-300">F&O stocks only</span>
              </label>
              <button onClick={handleCreate} disabled={creating}
                className="w-full px-4 py-2 bg-green-600 hover:bg-green-700 disabled:opacity-50 text-white text-sm rounded-md">
                {creating ? "Creating..." : "Create Agent"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Trade Modal */}
      {tradeOpen && selectedId && (
        <div className="fixed inset-0 bg-black/70 z-50 flex items-start justify-center p-6 overflow-auto">
          <div className="bg-gray-900 border border-gray-800 rounded-lg max-w-sm w-full my-6">
            <div className="p-4 border-b border-gray-800 flex items-center justify-between">
              <h2 className="text-lg font-semibold text-white">{tradeSide} Trade</h2>
              <button onClick={() => setTradeOpen(false)} className="text-gray-400 hover:text-white text-xl">×</button>
            </div>
            <div className="p-4 space-y-3">
              <div className="flex gap-2">
                <button onClick={() => setTradeSide("BUY")} className={`flex-1 py-2 rounded text-sm font-semibold ${tradeSide === "BUY" ? "bg-green-600 text-white" : "bg-gray-800 text-gray-400"}`}>BUY</button>
                <button onClick={() => setTradeSide("SELL")} className={`flex-1 py-2 rounded text-sm font-semibold ${tradeSide === "SELL" ? "bg-red-600 text-white" : "bg-gray-800 text-gray-400"}`}>SELL</button>
              </div>
              <div>
                <label className="block text-xs text-gray-400 mb-1">Symbol</label>
                <input value={tradeSymbol} onChange={e => setTradeSymbol(e.target.value)} placeholder="e.g. RELIANCE"
                  className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded text-sm text-white font-mono uppercase focus:border-blue-500 focus:outline-none" />
              </div>
              <div>
                <label className="block text-xs text-gray-400 mb-1">Quantity</label>
                <input type="number" value={tradeQty} onChange={e => setTradeQty(Number(e.target.value))} min={1}
                  className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded text-sm text-white focus:border-blue-500 focus:outline-none" />
              </div>
              <div>
                <label className="block text-xs text-gray-400 mb-1">Notes (optional)</label>
                <input value={tradeNotes} onChange={e => setTradeNotes(e.target.value)} placeholder="Why this trade?"
                  className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded text-sm text-white focus:border-blue-500 focus:outline-none" />
              </div>
              <p className="text-xs text-gray-500">Price will be fetched from live Kite quotes at execution.</p>
              <button onClick={handleTrade} disabled={trading}
                className={`w-full px-4 py-2 text-white text-sm rounded-md disabled:opacity-50 ${tradeSide === "BUY" ? "bg-green-600 hover:bg-green-700" : "bg-red-600 hover:bg-red-700"}`}>
                {trading ? "Executing..." : `${tradeSide} ${tradeQty} ${tradeSymbol.toUpperCase() || "..."}`}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
