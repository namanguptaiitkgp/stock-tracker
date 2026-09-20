"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { NoteIcon, StockNoteModal } from "@/components/common/StockNote";

interface StockAnalysis {
  symbol: string;
  signal: "HOLD" | "SELL" | "WATCHFUL";
  confidence: number;
  current_price: number;
  target_exit_price: number;
  stop_loss: number;
  pnl_pct: number;
  key_triggers: string[];
  tax_impact: string;
  reasoning: string;
}

interface PortfolioSummary {
  overall_health: string;
  total_stocks_analyzed: number;
  sell_count: number;
  hold_count: number;
  watchful_count: number;
  key_portfolio_risks: string[];
  sector_concentration_warning: string | null;
  tax_optimization_note: string;
}

interface AnalysisResult {
  portfolio_summary?: PortfolioSummary;
  stocks?: StockAnalysis[];
  top_actions?: string[];
  meta?: { model_used: string; holdings_analyzed: number; id?: number; created_at?: string };
  status?: string;
  raw_response?: string;
  message?: string;
}

interface HistoryItem {
  id: number;
  created_at: string;
  model_used: string;
  holdings_count: number;
  sell_count: number;
  hold_count: number;
  watchful_count: number;
  overall_health: string | null;
  top_actions: string[];
}

function formatDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString("en-IN", {
    day: "numeric", month: "short", year: "numeric",
    hour: "numeric", minute: "2-digit", hour12: true,
  });
}

const signalColors: Record<string, string> = {
  SELL: "bg-red-900 text-red-200 border-red-700",
  WATCHFUL: "bg-yellow-900 text-yellow-200 border-yellow-700",
  HOLD: "bg-green-900 text-green-200 border-green-700",
};

const healthColors: Record<string, string> = {
  STRONG: "text-green-400",
  MODERATE: "text-yellow-400",
  WEAK: "text-red-400",
};

export default function AnalysisPage() {
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [showHistory, setShowHistory] = useState(false);
  const [search, setSearch] = useState("");
  const [signalFilter, setSignalFilter] = useState<string>("all");
  const [noteSymbols, setNoteSymbols] = useState<Set<string>>(new Set());
  const [noteModalSymbol, setNoteModalSymbol] = useState<string | null>(null);

  const loadNotes = useCallback(async () => {
    try {
      const notes = await api.get<Array<{ symbol: string }>>("/api/notes/");
      setNoteSymbols(new Set(notes.map(n => n.symbol)));
    } catch {
      // ignore
    }
  }, []);

  useEffect(() => { loadNotes(); }, [loadNotes]);

  const loadHistory = useCallback(async () => {
    try {
      const data = await api.get<HistoryItem[]>("/api/analysis/history");
      setHistory(data);
    } catch {
      // ignore
    }
  }, []);

  useEffect(() => {
    loadHistory();
  }, [loadHistory]);

  async function runAnalysis() {
    setLoading(true);
    setError(null);
    setResult(null);

    try {
      const data = await api.post<AnalysisResult>("/api/analysis/run-portfolio");
      setResult(data);
      loadHistory();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Analysis failed");
    } finally {
      setLoading(false);
    }
  }

  async function viewHistorical(id: number) {
    setLoading(true);
    setError(null);
    setResult(null);
    setShowHistory(false);
    try {
      const data = await api.get<AnalysisResult>(`/api/analysis/history/${id}`);
      setResult(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load analysis");
    } finally {
      setLoading(false);
    }
  }

  async function deleteHistorical(id: number) {
    if (!confirm("Delete this analysis from history?")) return;
    try {
      await api.delete(`/api/analysis/history/${id}`);
      loadHistory();
      if (result?.meta?.id === id) setResult(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete");
    }
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold">AI Portfolio Analysis</h1>
        <div className="flex gap-2">
          <button
            onClick={() => setShowHistory(!showHistory)}
            className="px-4 py-2 bg-gray-800 hover:bg-gray-700 text-white text-sm rounded-md transition-colors"
          >
            History ({history.length})
          </button>
          <button
            onClick={runAnalysis}
            disabled={loading}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white text-sm rounded-md transition-colors"
          >
            {loading ? "Analyzing with AI..." : "Run Analysis on My Portfolio"}
          </button>
        </div>
      </div>

      {/* History Panel */}
      {showHistory && (
        <div className="mb-6 p-4 bg-gray-900 border border-gray-800 rounded-lg">
          <h2 className="font-semibold mb-3">Analysis History</h2>
          {history.length === 0 ? (
            <div className="text-sm text-gray-600 text-center py-6">
              No history yet. Run your first analysis to get started.
            </div>
          ) : (
            <div className="space-y-2">
              {history.map((h) => (
                <div
                  key={h.id}
                  className="p-3 bg-gray-800 hover:bg-gray-750 rounded-md border border-gray-700 transition-colors"
                >
                  <div className="flex items-start justify-between gap-3">
                    <button
                      onClick={() => viewHistorical(h.id)}
                      className="flex-1 text-left"
                    >
                      <div className="flex items-center gap-3 mb-1">
                        <span className="text-sm font-semibold text-white">
                          {formatDate(h.created_at)}
                        </span>
                        {h.overall_health && (
                          <span className={`text-xs px-2 py-0.5 rounded ${healthColors[h.overall_health] || "text-gray-400"} bg-gray-900`}>
                            {h.overall_health}
                          </span>
                        )}
                      </div>
                      <div className="flex gap-3 text-xs text-gray-400">
                        <span>{h.holdings_count} stocks</span>
                        <span className="text-red-400">SELL: {h.sell_count}</span>
                        <span className="text-yellow-400">WATCH: {h.watchful_count}</span>
                        <span className="text-green-400">HOLD: {h.hold_count}</span>
                        <span className="text-gray-600">{h.model_used}</span>
                      </div>
                      {h.top_actions && h.top_actions.length > 0 && (
                        <div className="text-xs text-gray-500 mt-1 truncate">
                          {h.top_actions[0]}
                        </div>
                      )}
                    </button>
                    <button
                      onClick={() => deleteHistorical(h.id)}
                      className="text-xs text-gray-600 hover:text-red-400 transition-colors"
                    >
                      Delete
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Show which analysis is being viewed */}
      {result?.meta?.created_at && (
        <div className="mb-4 p-2 bg-gray-900 border border-gray-800 rounded text-xs text-gray-500 flex items-center justify-between">
          <span>Viewing analysis from {formatDate(result.meta.created_at)}</span>
          <button
            onClick={() => setResult(null)}
            className="text-blue-400 hover:text-blue-300"
          >
            Clear view
          </button>
        </div>
      )}

      {loading && (
        <div className="p-6 bg-gray-900 border border-gray-800 rounded-lg text-center">
          <div className="text-gray-400 mb-2">Fetching your holdings from Kite and running AI analysis...</div>
          <div className="text-xs text-gray-500">Using Indian Market Smart Exit Strategy (Gemini)</div>
        </div>
      )}

      {error && (
        <div className="p-4 bg-red-950 border border-red-800 rounded-lg text-red-300 text-sm mb-4">{error}</div>
      )}

      {/* Raw response fallback */}
      {result?.status === "partial" && (
        <div className="p-4 bg-yellow-950 border border-yellow-800 rounded-lg mb-4">
          <div className="text-yellow-300 text-sm mb-2">{result.message}</div>
          <pre className="text-xs text-gray-400 whitespace-pre-wrap max-h-96 overflow-auto">{result.raw_response}</pre>
        </div>
      )}

      {/* Full Analysis Results */}
      {result?.portfolio_summary && (
        <div className="space-y-6">
          {/* Portfolio Health */}
          <div className="p-4 bg-gray-900 border border-gray-800 rounded-lg">
            <div className="flex items-center justify-between mb-4">
              <h2 className="font-semibold">Portfolio Health</h2>
              <span className={`text-lg font-bold ${healthColors[result.portfolio_summary.overall_health] || "text-gray-400"}`}>
                {result.portfolio_summary.overall_health}
              </span>
            </div>
            <div className="grid grid-cols-3 gap-4 mb-4">
              <div className="text-center p-3 bg-green-950/30 rounded">
                <div className="text-2xl font-bold text-green-400">{result.portfolio_summary.hold_count}</div>
                <div className="text-xs text-gray-500">HOLD</div>
              </div>
              <div className="text-center p-3 bg-yellow-950/30 rounded">
                <div className="text-2xl font-bold text-yellow-400">{result.portfolio_summary.watchful_count}</div>
                <div className="text-xs text-gray-500">WATCHFUL</div>
              </div>
              <div className="text-center p-3 bg-red-950/30 rounded">
                <div className="text-2xl font-bold text-red-400">{result.portfolio_summary.sell_count}</div>
                <div className="text-xs text-gray-500">SELL</div>
              </div>
            </div>

            {result.portfolio_summary.key_portfolio_risks?.length > 0 && (
              <div className="mb-3">
                <div className="text-xs text-gray-500 mb-1">Key Risks:</div>
                <ul className="text-sm text-yellow-300 space-y-1">
                  {result.portfolio_summary.key_portfolio_risks.map((r, i) => (
                    <li key={i}>- {r}</li>
                  ))}
                </ul>
              </div>
            )}

            {result.portfolio_summary.tax_optimization_note && (
              <div className="text-xs text-gray-400 bg-gray-800 p-2 rounded">
                Tax: {result.portfolio_summary.tax_optimization_note}
              </div>
            )}
          </div>

          {/* Top Actions */}
          {result.top_actions && result.top_actions.length > 0 && (
            <div className="p-4 bg-blue-950/30 border border-blue-800/50 rounded-lg">
              <h2 className="font-semibold text-blue-300 mb-3">Top Actions</h2>
              <ol className="space-y-2">
                {result.top_actions.map((action, i) => (
                  <li key={i} className="text-sm text-gray-300 flex gap-2">
                    <span className="text-blue-400 font-bold">{i + 1}.</span>
                    {action}
                  </li>
                ))}
              </ol>
            </div>
          )}

          {/* Stock-by-Stock Analysis */}
          <StockAnalysisSection
            stocks={result.stocks || []}
            search={search}
            setSearch={setSearch}
            signalFilter={signalFilter}
            setSignalFilter={setSignalFilter}
            noteSymbols={noteSymbols}
            onOpenNote={setNoteModalSymbol}
          />

          {/* Meta */}
          {result.meta && (
            <div className="text-xs text-gray-600 text-right">
              Model: {result.meta.model_used} | Stocks analyzed: {result.meta.holdings_analyzed}
            </div>
          )}
        </div>
      )}

      {/* Strategy Explanation */}
      {!result && !loading && (
        <div className="space-y-4">
          <div className="p-4 bg-gray-900 border border-gray-800 rounded-lg">
            <h2 className="font-semibold mb-3">Indian Market Smart Exit Strategy</h2>
            <p className="text-sm text-gray-400 mb-3">
              Click &quot;Run Analysis&quot; to analyze your Kite holdings using a composite strategy combining:
            </p>
            <ul className="text-sm text-gray-400 space-y-2">
              <li><span className="text-white">Peter Lynch Fair Value Exit</span> — Sell when stock overshoots intrinsic value by 30%+</li>
              <li><span className="text-white">CAN SLIM Stop-Loss</span> — Cut losers at 7-8% below buy price</li>
              <li><span className="text-white">Trend Following</span> — Exit when price breaks below 50-DMA</li>
              <li><span className="text-white">Trailing Stop</span> — Dynamic 15-20% trailing stop from 52-week high</li>
              <li><span className="text-white">Relative Strength</span> — Exit if stock underperforms Nifty 50</li>
            </ul>
            <div className="mt-3 p-3 bg-gray-800 rounded text-xs text-gray-400">
              <strong className="text-gray-300">Indian Market Adjustments:</strong> STCG/LTCG tax optimization, wider stops for mid/small caps, FII/DII flow patterns, quarterly results cycle, budget season volatility, promoter pledge monitoring.
            </div>
          </div>
        </div>
      )}

      {/* Note Editor Modal */}
      {noteModalSymbol && (
        <StockNoteModal
          symbol={noteModalSymbol}
          onClose={() => setNoteModalSymbol(null)}
          onSaved={(saved) => {
            const next = new Set(noteSymbols);
            if (saved) next.add(noteModalSymbol);
            else next.delete(noteModalSymbol);
            setNoteSymbols(next);
          }}
        />
      )}
    </div>
  );
}


function StockAnalysisSection({
  stocks,
  search,
  setSearch,
  signalFilter,
  setSignalFilter,
  noteSymbols,
  onOpenNote,
}: {
  stocks: StockAnalysis[];
  search: string;
  setSearch: (v: string) => void;
  signalFilter: string;
  setSignalFilter: (v: string) => void;
  noteSymbols: Set<string>;
  onOpenNote: (symbol: string) => void;
}) {
  const filtered = useMemo(() => {
    const order: Record<string, number> = { SELL: 0, WATCHFUL: 1, HOLD: 2 };
    const q = search.trim().toUpperCase();
    return [...stocks]
      .filter((s) => {
        if (signalFilter !== "all" && s.signal !== signalFilter) return false;
        if (q && !s.symbol.toUpperCase().includes(q) && !(s.reasoning || "").toUpperCase().includes(q)) return false;
        return true;
      })
      .sort((a, b) => (order[a.signal] ?? 2) - (order[b.signal] ?? 2));
  }, [stocks, search, signalFilter]);

  return (
    <div>
      <div className="flex items-center justify-between mb-3 gap-3">
        <h2 className="font-semibold">Stock Analysis ({stocks.length})</h2>
        <div className="flex items-center gap-2">
          <div className="relative">
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search stocks..."
              className="pl-8 pr-3 py-1.5 w-52 bg-gray-800 border border-gray-700 rounded-md text-white text-sm focus:outline-none focus:border-blue-500"
            />
            <svg className="w-4 h-4 absolute left-2 top-1/2 -translate-y-1/2 text-gray-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-4.35-4.35M17 10a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
            {search && (
              <button
                onClick={() => setSearch("")}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-500 hover:text-white text-lg leading-none"
              >
                ×
              </button>
            )}
          </div>
          <select
            value={signalFilter}
            onChange={(e) => setSignalFilter(e.target.value)}
            className="px-2 py-1.5 bg-gray-800 border border-gray-700 rounded-md text-white text-sm focus:outline-none focus:border-blue-500"
          >
            <option value="all">All signals</option>
            <option value="SELL">SELL only</option>
            <option value="WATCHFUL">WATCHFUL only</option>
            <option value="HOLD">HOLD only</option>
          </select>
        </div>
      </div>

      {filtered.length === 0 ? (
        <div className="p-6 text-center text-sm text-gray-600 bg-gray-900 border border-gray-800 rounded-lg">
          No stocks match your search
        </div>
      ) : (
        <div className="space-y-3">
          {filtered.map((stock) => {
            const hasNote = noteSymbols.has(stock.symbol);
            return (
              <div
                key={stock.symbol}
                className={`p-4 rounded-lg border ${signalColors[stock.signal] || "bg-gray-900 border-gray-800"}`}
              >
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-3">
                    <span className="font-mono font-bold text-lg">{stock.symbol}</span>
                    <span className={`text-xs px-2 py-1 rounded font-bold ${
                      stock.signal === "SELL" ? "bg-red-700 text-white" :
                      stock.signal === "WATCHFUL" ? "bg-yellow-700 text-white" :
                      "bg-green-700 text-white"
                    }`}>
                      {stock.signal}
                    </span>
                    <span className="text-xs text-gray-400">
                      Confidence: {stock.confidence}%
                    </span>
                    <NoteIcon symbol={stock.symbol} hasNote={hasNote} onClick={onOpenNote} />
                  </div>
                  <div className="text-right text-sm">
                    <div>LTP: {stock.current_price}</div>
                    <div className={stock.pnl_pct >= 0 ? "text-green-300" : "text-red-300"}>
                      {stock.pnl_pct >= 0 ? "+" : ""}{stock.pnl_pct?.toFixed(1)}%
                    </div>
                  </div>
                </div>

                <p className="text-sm mb-3 opacity-90">{stock.reasoning}</p>

                <div className="grid grid-cols-4 gap-3 text-xs">
                  <div>
                    <span className="text-gray-400">Target Exit:</span>
                    <div className="font-mono">{stock.target_exit_price}</div>
                  </div>
                  <div>
                    <span className="text-gray-400">Stop Loss:</span>
                    <div className="font-mono">{stock.stop_loss}</div>
                  </div>
                  <div>
                    <span className="text-gray-400">Tax:</span>
                    <div>{stock.tax_impact}</div>
                  </div>
                  <div>
                    <span className="text-gray-400">Triggers:</span>
                    <div>{stock.key_triggers?.join(", ")}</div>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
