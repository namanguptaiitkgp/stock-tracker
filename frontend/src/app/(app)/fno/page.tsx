"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { openStockDetail } from "@/lib/stock-detail";
import SentimentBadge from "@/components/common/SentimentBadge";

interface FnoStock {
  symbol: string;
  name: string | null;
  exchange: string;
  lot_size: number | null;
  nearest_expiry: string | null;
  min_investment_inr: number | null;
  verdict: "INVEST" | "WAIT" | "AVOID" | null;
  verdict_confidence: number | null;
  verdict_at: string | null;
  news_sentiment: "bullish" | "bearish" | "neutral" | null;
  news_score: number | null;
  news_at: string | null;
  cmp: number | null;
  market_cap: number | null;
  pe_ratio: number | null;
  ttm_pe: number | null;
  pb_ratio: number | null;
  revenue_growth_1y: number | null;
  eps_growth_1y: number | null;
  net_profit_margin: number | null;
  debt_to_equity: number | null;
  dividend_yield: number | null;
  roe: number | null;
}

interface Response {
  exchange: string;
  count: number;
  stocks: FnoStock[];
  warning?: string;
}

type Tab = "NSE" | "BSE";
type SortKey =
  | "symbol"
  | "name"
  | "verdict"
  | "news_score"
  | "cmp"
  | "market_cap"
  | "pe_ratio"
  | "ttm_pe"
  | "pb_ratio"
  | "revenue_growth_1y"
  | "eps_growth_1y"
  | "net_profit_margin"
  | "debt_to_equity"
  | "roe"
  | "dividend_yield"
  | "min_investment_inr";

function fmtNum(n: number | null): string {
  if (n === null || n === undefined) return "—";
  return n.toLocaleString("en-IN", { minimumFractionDigits: 1, maximumFractionDigits: 2 });
}

function fmtMoney(n: number | null): string {
  if (n === null || n === undefined) return "—";
  if (n >= 1e7) return `${(n / 1e7).toFixed(2)}Cr`;
  if (n >= 1e5) return `${(n / 1e5).toFixed(2)}L`;
  return n.toLocaleString("en-IN");
}

function fmtPct(n: number | null): string {
  if (n === null || n === undefined) return "—";
  const v = Math.abs(n) > 5 ? n : n * 100;
  return `${v >= 0 ? "+" : ""}${v.toFixed(1)}%`;
}

const VERDICT_COLOR: Record<string, { bg: string; fg: string }> = {
  INVEST: { bg: "rgba(36,138,61,0.1)", fg: "#248A3D" },
  WAIT: { bg: "rgba(245,166,35,0.1)", fg: "#A05A00" },
  AVOID: { bg: "rgba(215,0,21,0.1)", fg: "#D70015" },
};

const SENTIMENT_COLOR: Record<string, { bg: string; fg: string }> = {
  bullish: { bg: "rgba(36,138,61,0.1)", fg: "#248A3D" },
  bearish: { bg: "rgba(215,0,21,0.1)", fg: "#D70015" },
  neutral: { bg: "rgba(142,142,147,0.1)", fg: "#6E6E73" },
};

function SortTh({
  k,
  sortKey,
  sortAsc,
  onClick,
  align = "left",
  children,
}: {
  k: SortKey;
  sortKey: SortKey;
  sortAsc: boolean;
  onClick: (k: SortKey) => void;
  align?: "left" | "center" | "right";
  children: React.ReactNode;
}) {
  const active = sortKey === k;
  const alignCls = align === "left" ? "text-left" : align === "right" ? "text-right" : "text-center";
  return (
    <th
      onClick={() => onClick(k)}
      className={`${alignCls} p-2 cursor-pointer select-none ${active ? "text-white" : "text-gray-500"} hover:text-white`}
      style={{ whiteSpace: "nowrap" }}
    >
      {children}
      {active && <span style={{ marginLeft: 4, fontSize: 9 }}>{sortAsc ? "▲" : "▼"}</span>}
    </th>
  );
}

export default function FnoPage() {
  const [tab, setTab] = useState<Tab>("NSE");
  const [nseData, setNseData] = useState<Response | null>(null);
  const [bseData, setBseData] = useState<Response | null>(null);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("symbol");
  const [sortAsc, setSortAsc] = useState(true);
  const [scanStatus, setScanStatus] = useState<string | null>(null);
  const [scanning, setScanning] = useState(false);
  const [fundStatus, setFundStatus] = useState<string | null>(null);
  const [fundLoading, setFundLoading] = useState(false);
  const [newsFilter, setNewsFilter] = useState<"all" | "bullish" | "bearish" | "neutral" | "has_news" | "no_news">("all");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [nse, bse] = await Promise.all([
        api.get<Response>("/api/fno/stocks?exchange=NSE").catch(() => null),
        api.get<Response>("/api/fno/stocks?exchange=BSE").catch(() => null),
      ]);
      setNseData(nse);
      setBseData(bse);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const runNewsScan = useCallback(async () => {
    setScanning(true);
    setScanStatus("Running news scan for NSE F&O universe…");
    try {
      const data = await api.post<{
        companies_found: number;
        total_headlines: number;
        filter?: string;
      }>("/api/market-data/news-reports/run-now?fno_only=true");
      setScanStatus(
        `Scan done — ${data.companies_found} F&O stocks matched across ${data.total_headlines} headlines. Refreshing table…`,
      );
      await load();
      setScanStatus(
        `Scan done — ${data.companies_found} F&O stocks updated from ${data.total_headlines} headlines.`,
      );
    } catch (e) {
      setScanStatus(`Scan failed: ${(e as Error).message}`);
    } finally {
      setScanning(false);
    }
  }, [load]);

  const loadFundamentals = useCallback(async () => {
    setFundLoading(true);
    setFundStatus(`Loading fundamentals for ${tab} F&O… this can take 30-60s.`);
    try {
      const data = await api.post<{
        universe_size: number;
        already_cached: number;
        attempted: number;
        ok: number;
        failed: number;
      }>(`/api/fno/refresh-fundamentals?exchange=${tab}`);
      setFundStatus(
        `Loaded ${data.ok} of ${data.attempted} (${data.already_cached} were already cached; ${data.failed} failed). Refreshing table…`,
      );
      await load();
      setFundStatus(
        `Fundamentals updated: ${data.already_cached + data.ok} of ${data.universe_size} rows now populated.`,
      );
    } catch (e) {
      setFundStatus(`Load failed: ${(e as Error).message}`);
    } finally {
      setFundLoading(false);
    }
  }, [tab, load]);

  const active = tab === "NSE" ? nseData : bseData;

  function toggleSort(k: SortKey) {
    if (sortKey === k) setSortAsc((a) => !a);
    else {
      setSortKey(k);
      setSortAsc(k === "symbol" || k === "name" || k === "verdict");
    }
  }

  const rows = useMemo(() => {
    const src = active?.stocks ?? [];
    const q = search.trim().toLowerCase();
    let filtered = q
      ? src.filter(
          (s) =>
            s.symbol.toLowerCase().includes(q) ||
            (s.name || "").toLowerCase().includes(q),
        )
      : src;

    if (newsFilter !== "all") {
      filtered = filtered.filter((s) => {
        const sent = (s.news_sentiment || "").toLowerCase();
        if (newsFilter === "has_news") return !!s.news_sentiment;
        if (newsFilter === "no_news") return !s.news_sentiment;
        return sent === newsFilter;
      });
    }

    const verdictRank: Record<string, number> = { INVEST: 2, WAIT: 1, AVOID: 0 };
    const sorted = [...filtered].sort((a, b) => {
      let av: string | number = "";
      let bv: string | number = "";
      switch (sortKey) {
        case "symbol":
          av = a.symbol; bv = b.symbol; break;
        case "name":
          av = a.name || ""; bv = b.name || ""; break;
        case "verdict":
          av = verdictRank[a.verdict || ""] ?? -1;
          bv = verdictRank[b.verdict || ""] ?? -1;
          break;
        default:
          av = (a as unknown as Record<string, number | null>)[sortKey] ?? -Infinity;
          bv = (b as unknown as Record<string, number | null>)[sortKey] ?? -Infinity;
      }
      if (typeof av === "string" && typeof bv === "string") {
        return sortAsc ? av.localeCompare(bv) : bv.localeCompare(av);
      }
      return sortAsc ? (av as number) - (bv as number) : (bv as number) - (av as number);
    });
    return sorted;
  }, [active?.stocks, search, sortKey, sortAsc, newsFilter]);

  return (
    <div style={{ padding: "28px 32px", maxWidth: 1400, margin: "0 auto" }}>
      <div style={{ marginBottom: 16, display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
        <div style={{ flex: 1, minWidth: 280 }}>
          <h1 style={{ fontSize: 26, fontWeight: 800, color: "#1D1D1F", margin: 0 }}>F&O Universe</h1>
          <p style={{ fontSize: 13, color: "#6E6E73", marginTop: 4 }}>
            All stocks with futures &amp; options available on NSE or BSE. AI verdict and news sentiment
            show up as soon as that stock gets analysed anywhere in the app (daily analysis, news scan, etc).
          </p>
        </div>
        <div className="fno-actions" style={{ textAlign: "right", display: "flex", flexDirection: "column", gap: 6, alignItems: "flex-end" }}>
          <div className="fno-action-row" style={{ display: "flex", gap: 6, flexWrap: "wrap", justifyContent: "flex-end" }}>
            <button
              onClick={loadFundamentals}
              disabled={fundLoading}
              style={{
                padding: "8px 14px",
                borderRadius: 8,
                background: fundLoading ? "#8E8E93" : "white",
                color: fundLoading ? "white" : "#1D1D1F",
                border: "1px solid #1D1D1F",
                fontSize: 12,
                fontWeight: 600,
                cursor: fundLoading ? "wait" : "pointer",
                whiteSpace: "nowrap",
              }}
            >
              {fundLoading ? "Loading…" : `Fetch fundamentals (${tab})`}
            </button>
            <button
              onClick={runNewsScan}
              disabled={scanning}
              style={{
                padding: "8px 14px",
                borderRadius: 8,
                background: scanning ? "#8E8E93" : "#1D1D1F",
                color: "white",
                border: "none",
                fontSize: 12,
                fontWeight: 600,
                cursor: scanning ? "wait" : "pointer",
                whiteSpace: "nowrap",
              }}
            >
              {scanning ? "Scanning…" : "Run news scan"}
            </button>
          </div>
          <style jsx>{`
            @media (max-width: 720px) {
              .fno-actions { align-items: stretch !important; }
              .fno-action-row {
                justify-content: stretch !important;
              }
              .fno-action-row :global(button) {
                flex: 1 1 auto;
              }
            }
          `}</style>
          {fundStatus && (
            <div style={{ fontSize: 11, color: "#48484A", maxWidth: 320, textAlign: "right" }}>
              {fundStatus}
            </div>
          )}
          {scanStatus && (
            <div style={{ fontSize: 11, color: "#48484A", maxWidth: 320, textAlign: "right" }}>
              {scanStatus}
            </div>
          )}
        </div>
      </div>

      {/* Tabs */}
      <div style={{ display: "flex", gap: 4, marginBottom: 10 }}>
        {(["NSE", "BSE"] as const).map((t) => {
          const n = (t === "NSE" ? nseData : bseData)?.count ?? 0;
          return (
            <button
              key={t}
              onClick={() => setTab(t)}
              style={{
                padding: "6px 14px",
                borderRadius: 8,
                border: "1px solid",
                borderColor: tab === t ? "#1D1D1F" : "#E2E8F0",
                background: tab === t ? "#1D1D1F" : "white",
                color: tab === t ? "white" : "#1D1D1F",
                fontSize: 13,
                fontWeight: 600,
                cursor: "pointer",
              }}
            >
              {t} F&amp;O <span style={{ opacity: 0.6, marginLeft: 4 }}>({n})</span>
            </button>
          );
        })}
      </div>

      {/* Search */}
      <input
        type="text"
        placeholder={`Search ${tab} F&O — symbol or name…`}
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        style={{
          width: "100%",
          padding: "8px 12px",
          borderRadius: 8,
          border: "1px solid #E2E8F0",
          fontSize: 13,
          marginBottom: 12,
          outline: "none",
        }}
      />

      {active?.warning && (
        <div
          style={{
            padding: 12,
            background: "rgba(245,166,35,0.12)",
            border: "1px solid rgba(245,166,35,0.4)",
            borderRadius: 6,
            color: "#5C3F00",
            fontSize: 12,
            marginBottom: 10,
            display: "flex",
            flexWrap: "wrap",
            alignItems: "center",
            gap: 12,
            justifyContent: "space-between",
          }}
        >
          <div style={{ flex: 1, minWidth: 0 }}>{active.warning}</div>
          {/* When Kite is the underlying issue, the off-screen header link
              isn't enough on mobile — surface a primary CTA here. */}
          {/Kite|instruments|connect|auth/i.test(active.warning) && (
            <Link
              href="/settings"
              style={{
                padding: "6px 12px",
                borderRadius: 6,
                background: "#1D1D1F",
                color: "white",
                fontSize: 12,
                fontWeight: 600,
                textDecoration: "none",
                whiteSpace: "nowrap",
              }}
            >
              Reconnect Kite →
            </Link>
          )}
        </div>
      )}

      {loading && <div style={{ color: "#6E6E73" }}>Loading F&O universe…</div>}

      {!loading && active && (
        <div className="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-800 text-xs uppercase">
                  <SortTh k="symbol" sortKey={sortKey} sortAsc={sortAsc} onClick={toggleSort}>Symbol</SortTh>
                  <SortTh k="verdict" sortKey={sortKey} sortAsc={sortAsc} onClick={toggleSort} align="center">Verdict</SortTh>
                  <th className="text-center p-2" style={{ whiteSpace: "nowrap" }}>
                    <div style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
                      <span
                        onClick={() => toggleSort("news_score")}
                        className={`cursor-pointer select-none ${sortKey === "news_score" ? "text-white" : "text-gray-500"} hover:text-white`}
                      >
                        News
                        {sortKey === "news_score" && <span style={{ marginLeft: 4, fontSize: 9 }}>{sortAsc ? "▲" : "▼"}</span>}
                      </span>
                      <select
                        value={newsFilter}
                        onChange={(e) => setNewsFilter(e.target.value as typeof newsFilter)}
                        onClick={(e) => e.stopPropagation()}
                        title="Filter by news sentiment"
                        style={{
                          padding: "1px 4px",
                          fontSize: 10,
                          borderRadius: 4,
                          border: "1px solid rgba(255,255,255,0.2)",
                          background: newsFilter === "all" ? "rgba(255,255,255,0.05)" : "rgba(0,122,255,0.2)",
                          color: "#D4D4D4",
                          cursor: "pointer",
                          textTransform: "none",
                          letterSpacing: 0,
                        }}
                      >
                        <option value="all">All</option>
                        <option value="has_news">Has news</option>
                        <option value="bullish">Bullish only</option>
                        <option value="bearish">Bearish only</option>
                        <option value="neutral">Neutral only</option>
                        <option value="no_news">No news</option>
                      </select>
                    </div>
                  </th>
                  <SortTh k="cmp" sortKey={sortKey} sortAsc={sortAsc} onClick={toggleSort} align="right">CMP</SortTh>
                  <SortTh k="market_cap" sortKey={sortKey} sortAsc={sortAsc} onClick={toggleSort} align="right">Mkt Cap</SortTh>
                  <SortTh k="pe_ratio" sortKey={sortKey} sortAsc={sortAsc} onClick={toggleSort} align="right">P/E</SortTh>
                  <SortTh k="ttm_pe" sortKey={sortKey} sortAsc={sortAsc} onClick={toggleSort} align="right">TTM P/E</SortTh>
                  <SortTh k="pb_ratio" sortKey={sortKey} sortAsc={sortAsc} onClick={toggleSort} align="right">P/B</SortTh>
                  <SortTh k="revenue_growth_1y" sortKey={sortKey} sortAsc={sortAsc} onClick={toggleSort} align="right">Rev Gr</SortTh>
                  <SortTh k="eps_growth_1y" sortKey={sortKey} sortAsc={sortAsc} onClick={toggleSort} align="right">EPS Gr</SortTh>
                  <SortTh k="net_profit_margin" sortKey={sortKey} sortAsc={sortAsc} onClick={toggleSort} align="right">Net Mrgn</SortTh>
                  <SortTh k="debt_to_equity" sortKey={sortKey} sortAsc={sortAsc} onClick={toggleSort} align="right">D/E</SortTh>
                  <SortTh k="roe" sortKey={sortKey} sortAsc={sortAsc} onClick={toggleSort} align="right">ROE</SortTh>
                  <SortTh k="dividend_yield" sortKey={sortKey} sortAsc={sortAsc} onClick={toggleSort} align="right">Div Y</SortTh>
                  <SortTh k="min_investment_inr" sortKey={sortKey} sortAsc={sortAsc} onClick={toggleSort} align="right">Lot Value</SortTh>
                </tr>
              </thead>
              <tbody>
                {rows.map((s) => (
                  <tr
                    key={s.symbol}
                    onClick={() => openStockDetail(s.symbol, s.exchange)}
                    className="border-b border-gray-800/50 hover:bg-gray-800/30 cursor-pointer"
                  >
                    <td className="p-2">
                      <div className="font-mono text-xs font-medium text-blue-400">{s.symbol}</div>
                      <div className="text-xs text-gray-500 truncate max-w-[180px]" title={s.name || ""}>
                        {s.name || "--"}
                      </div>
                    </td>
                    <td className="p-2 text-center">
                      {s.verdict ? (
                        <span
                          style={{
                            padding: "2px 8px",
                            borderRadius: 10,
                            fontSize: 10,
                            fontWeight: 700,
                            ...VERDICT_COLOR[s.verdict],
                          }}
                        >
                          {s.verdict}
                          {s.verdict_confidence != null && (
                            <span style={{ marginLeft: 3, opacity: 0.7 }}>{s.verdict_confidence}%</span>
                          )}
                        </span>
                      ) : (
                        <span className="text-gray-600 text-xs">—</span>
                      )}
                    </td>
                    <td className="p-2 text-center">
                      {s.news_sentiment ? (
                        <SentimentBadge sentiment={s.news_sentiment} score={s.news_score} />
                      ) : (
                        <span className="text-gray-600 text-xs">—</span>
                      )}
                    </td>
                    <td className="p-2 text-right">{fmtNum(s.cmp)}</td>
                    <td className="p-2 text-right text-gray-400">{fmtMoney(s.market_cap)}</td>
                    <td className="p-2 text-right">{fmtNum(s.pe_ratio)}</td>
                    <td className="p-2 text-right">{fmtNum(s.ttm_pe)}</td>
                    <td className="p-2 text-right">{fmtNum(s.pb_ratio)}</td>
                    <td className="p-2 text-right">{fmtPct(s.revenue_growth_1y)}</td>
                    <td className="p-2 text-right">{fmtPct(s.eps_growth_1y)}</td>
                    <td className="p-2 text-right">{fmtPct(s.net_profit_margin)}</td>
                    <td className="p-2 text-right">{fmtNum(s.debt_to_equity)}</td>
                    <td className="p-2 text-right">{fmtPct(s.roe)}</td>
                    <td className="p-2 text-right">{fmtPct(s.dividend_yield)}</td>
                    <td
                      className="p-2 text-right"
                      title={
                        s.lot_size && s.cmp
                          ? `Lot ${s.lot_size} × CMP ${s.cmp.toFixed(2)} = notional value. Margin typically ~15-20% of this.${s.nearest_expiry ? ` Expiry ${s.nearest_expiry}.` : ""}`
                          : s.lot_size
                          ? `Lot size ${s.lot_size} — lot value requires CMP (click "Load Fundamentals")`
                          : "Lot size unknown"
                      }
                    >
                      {s.min_investment_inr ? (
                        <span style={{ fontWeight: 600 }}>{fmtMoney(s.min_investment_inr)}</span>
                      ) : (
                        <span className="text-gray-600">{s.lot_size ? `lot ${s.lot_size}` : "—"}</span>
                      )}
                    </td>
                  </tr>
                ))}
                {rows.length === 0 && (
                  <tr>
                    <td colSpan={14} className="p-8 text-center text-gray-500">
                      No stocks match &quot;{search}&quot;
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div style={{ marginTop: 8, fontSize: 11, color: "#8E8E93" }}>
        Showing {rows.length} of {active?.count ?? 0} {tab} F&O stocks
        {(search || newsFilter !== "all") && (
          <> (filtered
            {search && " by search"}
            {search && newsFilter !== "all" && " +"}
            {newsFilter !== "all" && ` news:${newsFilter}`}
            )
          </>
        )}. Verdict/News columns populate as daily analysis or news scan covers each stock;
        fundamentals populate when cached (click a row to open the detail panel and trigger fresh evaluation).
      </div>
    </div>
  );
}
