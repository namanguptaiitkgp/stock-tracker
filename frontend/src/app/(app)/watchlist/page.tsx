"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { openStockDetail } from "@/lib/stock-detail";
import { usePageActions } from "@/lib/page-actions";
import { fmtRelative } from "@/lib/format";
import SentimentBadge from "@/components/common/SentimentBadge";
import ResearchingCard from "@/components/common/ResearchingCard";


interface Fundamentals {
  cmp: number | null;
  market_cap: number | null;
  pe_ratio: number | null;
  ttm_pe: number | null;
  forward_pe: number | null;
  pb_ratio: number | null;
  revenue_growth_1y: number | null;
  eps_growth_1y: number | null;
  earnings_growth_forward: number | null;
  net_profit_margin: number | null;
  debt_to_equity: number | null;
  dividend_yield: number | null;
  roe: number | null;
  pct_from_52w_high?: number | null;
  sector?: string | null;
  industry?: string | null;
  fetched_at: string | null;
}

interface WatchlistStock {
  id: number;
  symbol: string;
  name: string | null;
  exchange: string;
  fundamentals?: Fundamentals | null;
  in_watchlists?: string[];
  verdict?: string | null;
  verdict_confidence?: number | null;
  news_sentiment?: string | null;
  news_score?: number | null;
  reason_tag?: string | null;
  has_nse_fno?: boolean;
  has_bse_fno?: boolean;
  watching_since?: string | null;
  lane?: string | null;
  triggered_alerts?: Array<{ id: number }>;
  fundamental_analysis?: {
    verdict: "STRONG" | "FAIR" | "WEAK" | "NA";
    score: number | null;
    rules_passed: number;
    rules_failed: number;
    rules_missing: number;
    snapshot_fetched_at: string | null;
  } | null;
}

type FnoTab = "all" | "nse_fno" | "bse_fno";

interface WatchlistData {
  id: number;
  name: string;
  description: string | null;
  stock_count: number;
  missing_fundamentals?: number;
  stocks: WatchlistStock[];
}

// Aggregated /all/detail response — same shape as WatchlistData but with
// a list of all watchlists for the filter dropdown and a null id.
interface AllWatchlistsData {
  id: null;
  name: string;
  description: string | null;
  stock_count: number;
  missing_fundamentals?: number;
  stocks: WatchlistStock[];
  watchlists: Array<{ id: number; name: string; description: string | null; stock_count?: number }>;
}

interface ResolvedStock {
  input: string;
  symbol: string | null;
  name: string | null;
  exchange?: string;
  confidence?: string;
  error?: string;
}

interface UploadResult {
  matched: ResolvedStock[];
  errors: ResolvedStock[];
  raw_extracted: string[];
}

function fmtMoney(n: number | null): string {
  if (n === null) return "--";
  if (Math.abs(n) >= 10000000) return `${(n / 10000000).toFixed(2)} Cr`;
  if (Math.abs(n) >= 100000) return `${(n / 100000).toFixed(2)} L`;
  if (Math.abs(n) >= 1000) return `${(n / 1000).toFixed(1)} K`;
  return n.toFixed(2);
}

function fmtNum(n: number | null, decimals: number = 2): string {
  if (n === null || n === undefined) return "--";
  return n.toFixed(decimals);
}

function fmtPct(n: number | null): string {
  if (n === null || n === undefined) return "--";
  return `${(n * 100).toFixed(1)}%`;
}

function SortTh({
  k,
  sortKey,
  sortAsc,
  onClick,
  align,
  children,
}: {
  k: WatchlistSortKey;
  sortKey: WatchlistSortKey;
  sortAsc: boolean;
  onClick: (k: WatchlistSortKey) => void;
  align: "left" | "center" | "right";
  children: React.ReactNode;
}) {
  const active = sortKey === k;
  const alignCls = align === "left" ? "text-left" : align === "right" ? "text-right" : "text-center";
  return (
    <th
      onClick={() => onClick(k)}
      className={`${alignCls} p-2 cursor-pointer select-none hover:text-white ${active ? "text-white" : ""}`}
    >
      <span style={{ whiteSpace: "nowrap" }}>
        {children}
        {active && <span style={{ marginLeft: 4, fontSize: 9 }}>{sortAsc ? "▲" : "▼"}</span>}
      </span>
    </th>
  );
}

type WatchlistSortKey =
  | "symbol"
  | "verdict"
  | "sentiment"
  | "cmp"
  | "market_cap"
  | "pe_ratio"
  | "ttm_pe"
  | "forward_pe"
  | "pb_ratio"
  | "revenue_growth_1y"
  | "eps_growth_1y"
  | "earnings_growth_forward"
  | "net_profit_margin"
  | "debt_to_equity";

/**
 * Renders the upload icon into the AppShell tab bar via the page-actions
 * slot. Watchlist picker and "+ New" moved into the page body header.
 */
function WatchlistPageActions({
  activeId,
  onClickUpload,
}: {
  activeId: number | null;
  watchlists: WatchlistData[];
  onPickWatchlist: (id: number | null) => void;
  onClickNew: () => void;
  onClickUpload: () => void;
}) {
  const node = (
    <div style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
      <button
        onClick={onClickUpload}
        disabled={activeId === null}
        title={
          activeId === null
            ? "Pick a watchlist first to upload stocks into it"
            : "Upload stocks (CSV / list)"
        }
        aria-label="Upload stocks"
        style={{
          width: 30,
          height: 30,
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center",
          borderRadius: 7,
          background: "var(--bg-secondary)",
          color: "var(--label-primary)",
          border: "1px solid var(--separator)",
          cursor: activeId === null ? "not-allowed" : "pointer",
          opacity: activeId === null ? 0.4 : 1,
        }}
      >
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width="14"
          height="14"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2}
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M4 16v2a2 2 0 002 2h12a2 2 0 002-2v-2M7 10l5-5m0 0l5 5m-5-5v12"
          />
        </svg>
      </button>
    </div>
  );
  usePageActions(node, [activeId, onClickUpload]);
  return null;
}


export default function WatchlistPage() {
  const [watchlists, setWatchlists] = useState<WatchlistData[]>([]);
  // null = "All watchlists" aggregated view (default); number = focused on
  // a specific watchlist. The dropdown drives this.
  const [activeId, setActiveId] = useState<number | null>(null);
  const [detail, setDetail] = useState<WatchlistData | AllWatchlistsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [sortKey, setSortKey] = useState<WatchlistSortKey>("symbol");
  const [sortAsc, setSortAsc] = useState(true);
  const [fnoTab, setFnoTab] = useState<FnoTab>("all");
  const [viewMode, setViewMode] = useState<"cards" | "table">("cards");
  const [sortAscCards, setSortAscCards] = useState(false);
  const [selectedSectors, setSelectedSectors] = useState<Set<string>>(new Set());
  // Researching-card sort modes (cards view only). The table view still
  // uses the column-header sort above.
  const [researchingSort, setResearchingSort] = useState<
    "triggered" | "biggest_move" | "recent" | "news_score" | "fundamentals_score" | "ai_score"
  >("triggered");
  // Free-text symbol/name filter for the Researching cards. Matches the
  // PortfolioDetails "Filter by symbol…" UX.
  const [symbolFilter, setSymbolFilter] = useState<string>("");
  const [laneFilter, setLaneFilter] = useState<string>("all");
  const [slidingOutId, setSlidingOutId] = useState<number | null>(null);

  function toggleSort(k: WatchlistSortKey) {
    if (sortKey === k) {
      setSortAsc((a) => !a);
    } else {
      setSortKey(k);
      // Numeric columns default to descending (biggest first)
      setSortAsc(k === "symbol" || k === "verdict" || k === "sentiment");
    }
  }

  const fnoCounts = useMemo(() => {
    const s = detail?.stocks || [];
    return {
      all: s.length,
      nse_fno: s.filter((x) => x.has_nse_fno).length,
      bse_fno: s.filter((x) => x.has_bse_fno).length,
    };
  }, [detail?.stocks]);

  // Sector counts across the whole watchlist (not affected by F&O / symbol filter).
  const sectorCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const s of detail?.stocks || []) {
      const sec = s.fundamentals?.sector;
      if (sec) counts[sec] = (counts[sec] || 0) + 1;
    }
    return Object.entries(counts)
      .sort((a, b) => b[1] - a[1])
      .map(([name, count]) => ({ name, count }));
  }, [detail?.stocks]);

  const lastUpdatedLabel = useMemo(() => {
    if (!detail?.stocks?.length) return null;
    let latest = "";
    for (const s of detail.stocks) {
      const t = s.fundamentals?.fetched_at;
      if (t && t > latest) latest = t;
    }
    if (!latest) return null;
    return fmtRelative(latest);
  }, [detail?.stocks]);

  const sortedStocks = useMemo(() => {
    const source = detail?.stocks ? [...detail.stocks] : [];
    const filtered = source.filter((x) => {
      if (fnoTab === "nse_fno" && !x.has_nse_fno) return false;
      if (fnoTab === "bse_fno" && !x.has_bse_fno) return false;
      if (selectedSectors.size > 0) {
        const sec = x.fundamentals?.sector;
        if (!sec || !selectedSectors.has(sec)) return false;
      }
      return true;
    });
    const list = filtered;
    const verdictRank: Record<string, number> = { INVEST: 2, WAIT: 1, AVOID: 0 };
    const sentRank: Record<string, number> = { bullish: 2, neutral: 1, bearish: 0 };
    list.sort((a, b) => {
      const fa = a.fundamentals || ({} as Fundamentals);
      const fb = b.fundamentals || ({} as Fundamentals);
      let av: string | number = "";
      let bv: string | number = "";
      switch (sortKey) {
        case "symbol":
          av = a.symbol; bv = b.symbol; break;
        case "verdict":
          av = verdictRank[a.verdict || ""] ?? -1;
          bv = verdictRank[b.verdict || ""] ?? -1;
          break;
        case "sentiment":
          av = sentRank[(a.news_sentiment || "").toLowerCase()] ?? -1;
          bv = sentRank[(b.news_sentiment || "").toLowerCase()] ?? -1;
          break;
        default:
          av = (fa as unknown as Record<string, number | null>)[sortKey] ?? -Infinity;
          bv = (fb as unknown as Record<string, number | null>)[sortKey] ?? -Infinity;
      }
      if (typeof av === "string" && typeof bv === "string") {
        return sortAsc ? av.localeCompare(bv) : bv.localeCompare(av);
      }
      const ax = av as number;
      const bx = bv as number;
      return sortAsc ? ax - bx : bx - ax;
    });
    return list;
  }, [detail?.stocks, sortKey, sortAsc, fnoTab, selectedSectors]);

  // Cards view applies its own sort (the table view keeps the column-header
  // sort above). "Triggered first" pushes any card with a pending
  // review_alert to the top — that's what replaces the standalone Pending
  // Review section.
  const laneCounts = useMemo(() => {
    const counts: Record<string, number> = { all: 0 };
    for (const s of sortedStocks) {
      const l = (s.lane || "researching").toLowerCase();
      counts[l] = (counts[l] || 0) + 1;
      counts.all += 1;
    }
    return counts;
  }, [sortedStocks]);

  const researchingStocks = useMemo(() => {
    const q = symbolFilter.trim().toLowerCase();
    let filtered = q
      ? sortedStocks.filter((s) =>
          s.symbol.toLowerCase().includes(q) ||
          (s.name ?? "").toLowerCase().includes(q),
        )
      : sortedStocks;
    if (laneFilter !== "all") {
      filtered = filtered.filter((s) => (s.lane || "researching") === laneFilter);
    }
    const list = [...filtered];
    if (researchingSort === "triggered") {
      list.sort((a, b) => {
        const at = (a as { triggered_alerts?: unknown[] }).triggered_alerts?.length ?? 0;
        const bt = (b as { triggered_alerts?: unknown[] }).triggered_alerts?.length ?? 0;
        if (at !== bt) return bt - at;
        // Tie-break: most-recent watching_since first.
        const aw = a.watching_since ? Date.parse(a.watching_since) : 0;
        const bw = b.watching_since ? Date.parse(b.watching_since) : 0;
        return bw - aw;
      });
    } else if (researchingSort === "biggest_move") {
      list.sort((a, b) => {
        const am = Math.abs(a.fundamentals?.pct_from_52w_high ?? 0);
        const bm = Math.abs(b.fundamentals?.pct_from_52w_high ?? 0);
        return bm - am;
      });
    } else if (researchingSort === "news_score") {
      list.sort((a, b) => {
        const an = Math.abs(a.news_score ?? 0);
        const bn = Math.abs(b.news_score ?? 0);
        return bn - an;
      });
    } else if (researchingSort === "fundamentals_score") {
      const faRank: Record<string, number> = { STRONG: 3, FAIR: 2, WEAK: 1, NA: 0 };
      list.sort((a, b) => {
        const av = a.fundamental_analysis?.score ?? (faRank[a.fundamental_analysis?.verdict ?? ""] ?? -1);
        const bv = b.fundamental_analysis?.score ?? (faRank[b.fundamental_analysis?.verdict ?? ""] ?? -1);
        return bv - av;
      });
    } else if (researchingSort === "ai_score") {
      const vRank: Record<string, number> = { INVEST: 3, WAIT: 2, AVOID: 1 };
      list.sort((a, b) => {
        const ac = a.verdict ? (a.verdict_confidence ?? 0) + (vRank[a.verdict] ?? 0) * 100 : -1;
        const bc = b.verdict ? (b.verdict_confidence ?? 0) + (vRank[b.verdict] ?? 0) * 100 : -1;
        return bc - ac;
      });
    } else {
      // recently added
      list.sort((a, b) => {
        const aw = a.watching_since ? Date.parse(a.watching_since) : 0;
        const bw = b.watching_since ? Date.parse(b.watching_since) : 0;
        return bw - aw;
      });
    }
    if (sortAscCards) list.reverse();
    return list;
  }, [sortedStocks, researchingSort, symbolFilter, sortAscCards, laneFilter]);

  const [showUpload, setShowUpload] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadResult, setUploadResult] = useState<UploadResult | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [uploadTargetIds, setUploadTargetIds] = useState<Set<number>>(new Set());

  const [showOverflowMenu, setShowOverflowMenu] = useState(false);
  const [dismissedFundBadge, setDismissedFundBadge] = useState(false);
  const [showWatchlistPicker, setShowWatchlistPicker] = useState(false);
  const [watchlistSearch, setWatchlistSearch] = useState("");
  const [pendingSectors, setPendingSectors] = useState<Set<string>>(new Set());
  const [showSectorPicker, setShowSectorPicker] = useState(false);
  const [sectorSearch, setSectorSearch] = useState("");

  // Bulk Run Analysis
  const [selectMode, setSelectMode] = useState(false);
  const [selectedItemIds, setSelectedItemIds] = useState<Set<number>>(new Set());
  const [bulkRunning, setBulkRunning] = useState(false);
  const [bulkStatuses, setBulkStatuses] = useState<Record<number, "queued" | "running" | "done" | "error">>({});
  const [bulkAbort, setBulkAbort] = useState(false);

  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState("");
  const [newDesc, setNewDesc] = useState("");

  const [showMembership, setShowMembership] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ text: string; type: "ok" | "err" } | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const router = useRouter();

  const showMsg = useCallback((text: string, type: "ok" | "err") => {
    setMsg({ text, type });
    setTimeout(() => setMsg(null), 4000);
  }, []);

  const loadWatchlists = useCallback(async () => {
    try {
      const data = await api.get<WatchlistData[]>("/api/watchlists/");
      setWatchlists(data);
    } catch {
      // ignore — the /all/detail call below also seeds this list
    } finally {
      setLoading(false);
    }
  }, []);

  const [refreshingFund, setRefreshingFund] = useState(false);
  const [myStrategies, setMyStrategies] = useState<Array<{ id: number; name: string; strategy_type: string }>>([]);
  const [showStrategyPicker, setShowStrategyPicker] = useState(false);

  const loadDetail = useCallback(async (id: number | null) => {
    setLoadingDetail(true);
    try {
      if (id === null) {
        const data = await api.get<AllWatchlistsData>("/api/watchlists/all/detail");
        setDetail(data);
        // Aggregated response carries the list of watchlists too — use it
        // to seed the dropdown so the page works on a single round-trip.
        if (Array.isArray(data.watchlists)) {
          setWatchlists(
            data.watchlists.map((w) => ({
              id: w.id,
              name: w.name,
              description: w.description,
              stock_count: w.stock_count ?? 0,
              stocks: [],
            })),
          );
        }
      } else {
        const data = await api.get<WatchlistData>(`/api/watchlists/${id}/detail`);
        setDetail(data);
      }
    } catch {
      setDetail(null);
    } finally {
      setLoadingDetail(false);
    }
  }, []);

  const refreshFundamentals = useCallback(async (id: number, onlyStale: boolean = false) => {
    setRefreshingFund(true);
    try {
      const res = await api.post<{ fetched: number; skipped: number; failed: number }>(
        `/api/watchlists/${id}/refresh-fundamentals?only_stale=${onlyStale}`,
      );
      showMsg(`Refreshed ${res.fetched} stocks (${res.skipped} cached, ${res.failed} failed)`, "ok");
      await loadDetail(id);
    } catch (err) {
      showMsg(err instanceof Error ? err.message : "Refresh failed", "err");
    } finally {
      setRefreshingFund(false);
    }
  }, [loadDetail, showMsg]);

  useEffect(() => { loadWatchlists(); }, [loadWatchlists]);
  // null activeId = aggregated view (default); a real id = focused view.
  useEffect(() => {
    loadDetail(activeId);
    setDismissedFundBadge(false);
    setSelectedSectors(new Set());
    setPendingSectors(new Set());
    setLaneFilter("all");
    setSelectMode(false);
    setSelectedItemIds(new Set());
    setBulkStatuses({});
  }, [activeId, loadDetail]);

  useEffect(() => {
    api.get<{ mine: Array<{ id: number; name: string; strategy_type: string }> }>("/api/strategies/")
      .then((d) => setMyStrategies(d.mine || []))
      .catch(() => {});
  }, []);

  function runStrategyOnWatchlist(strategyId: number) {
    if (!activeId) return;
    router.push(`/strategies?strategy=${strategyId}&target=watchlist&watchlist_id=${activeId}`);
  }

  // Bulk-runs comprehensive analysis on a set of selected stocks. Concurrency
  // is capped at 2 because each call kicks off ~5 parallel external fetches +
  // an AI call — higher concurrency causes yfinance rate-limiting.
  const runBulkAnalysis = useCallback(async () => {
    if (!detail?.stocks || selectedItemIds.size === 0) return;
    const targets = detail.stocks.filter((s) => selectedItemIds.has(s.id));
    if (targets.length === 0) return;

    if (targets.length > 10) {
      const ok = confirm(
        `Run analysis on ${targets.length} stocks? This will take ~${Math.ceil(targets.length * 4)}s and uses ~₹${(targets.length * 0.15).toFixed(2)} of AI budget.`,
      );
      if (!ok) return;
    }

    setBulkRunning(true);
    setBulkAbort(false);
    const initial: Record<number, "queued" | "running" | "done" | "error"> = {};
    for (const t of targets) initial[t.id] = "queued";
    setBulkStatuses(initial);

    const queue = [...targets];
    const CONCURRENCY = 2;

    const worker = async () => {
      while (queue.length > 0) {
        if (bulkAbort) return;
        const t = queue.shift();
        if (!t) return;
        setBulkStatuses((m) => ({ ...m, [t.id]: "running" }));
        try {
          type AnalyzeResp = {
            investment_decision?: { verdict?: string | null; confidence?: number | null; reasoning?: string | null } | null;
            news_sentiment?: { sentiment?: string | null; score?: number | null } | null;
          };
          const res = await api.post<AnalyzeResp>(
            `/api/stocks/${t.symbol}/analyze?exchange=${t.exchange || "NSE"}`,
            {},
          );
          // Best-effort journal entry mirroring the per-card flow
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
            await api.post(`/api/watchlists/items/${t.id}/journal`, { body });
          } catch { /* ignore */ }
          setBulkStatuses((m) => ({ ...m, [t.id]: "done" }));
        } catch {
          setBulkStatuses((m) => ({ ...m, [t.id]: "error" }));
        }
      }
    };

    const workers = Array.from({ length: Math.min(CONCURRENCY, targets.length) }, () => worker());
    await Promise.all(workers);

    setBulkRunning(false);
    // Refresh the watchlist so SignalPills reflect the new verdicts
    await loadDetail(activeId);
  }, [detail?.stocks, selectedItemIds, bulkAbort, activeId, loadDetail]);

  async function createWatchlist() {
    if (!newName.trim()) return;
    try {
      const wl = await api.post<WatchlistData>("/api/watchlists/", { name: newName, description: newDesc || null });
      showMsg(`Created "${wl.name}"`, "ok");
      setNewName("");
      setNewDesc("");
      setShowCreate(false);
      await loadWatchlists();
      setActiveId(wl.id);
    } catch (err) {
      showMsg(err instanceof Error ? err.message : "Failed to create", "err");
    }
  }

  async function deleteWatchlist() {
    if (!activeId || !detail) return;
    if (!confirm(`Delete watchlist "${detail.name}"?`)) return;
    try {
      await api.delete(`/api/watchlists/${activeId}`);
      showMsg("Deleted", "ok");
      await loadWatchlists();
      const remaining = watchlists.filter(w => w.id !== activeId);
      setActiveId(remaining[0]?.id || null);
    } catch (err) {
      showMsg(err instanceof Error ? err.message : "Failed to delete", "err");
    }
  }

  async function handleUpload(file: File) {
    if (!activeId) return;
    setUploading(true);
    setUploadResult(null);
    // Default the target to the currently active watchlist
    setUploadTargetIds(new Set([activeId]));

    const formData = new FormData();
    formData.append("file", file);

    try {
      const res = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/watchlists/${activeId}/upload`,
        {
          method: "POST",
          headers: { Authorization: `Bearer ${localStorage.getItem("algo_trader_token")}` },
          body: formData,
        },
      );
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `Upload failed: ${res.status}`);
      }
      const data: UploadResult = await res.json();
      setUploadResult(data);
    } catch (err) {
      showMsg(err instanceof Error ? err.message : "Upload failed", "err");
    } finally {
      setUploading(false);
    }
  }

  function toggleUploadTarget(id: number) {
    const next = new Set(uploadTargetIds);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setUploadTargetIds(next);
  }

  function onFileSelect(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (file) handleUpload(file);
    e.target.value = "";
  }

  function onDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files[0];
    if (file) handleUpload(file);
  }

  async function confirmAdd(stocks: ResolvedStock[]) {
    if (uploadTargetIds.size === 0) {
      showMsg("Select at least one watchlist to add stocks to", "err");
      return;
    }
    const validStocks = stocks.filter((s) => s.symbol);
    const payload = {
      stocks: validStocks.map((s) => ({
        symbol: s.symbol,
        name: s.name,
        exchange: s.exchange || "NSE",
      })),
    };

    const results: Array<{ wlName: string; added: number; skipped: number }> = [];
    const errors: string[] = [];

    for (const wlId of uploadTargetIds) {
      const wl = watchlists.find(w => w.id === wlId);
      try {
        const res = await api.post<{ added: string[]; skipped: string[] }>(
          `/api/watchlists/${wlId}/stocks/bulk`,
          payload,
        );
        results.push({
          wlName: wl?.name || `#${wlId}`,
          added: res.added.length,
          skipped: res.skipped.length,
        });
      } catch (err) {
        errors.push(`${wl?.name || wlId}: ${err instanceof Error ? err.message : "failed"}`);
      }
    }

    if (results.length > 0) {
      const summary = results
        .map(r => `${r.wlName}: +${r.added}${r.skipped ? ` (${r.skipped} existed)` : ""}`)
        .join(" | ");
      showMsg(`Added to ${results.length} watchlist(s). ${summary}`, "ok");
    }
    if (errors.length > 0) {
      showMsg(errors.join("; "), "err");
    }

    setUploadResult(null);
    setShowUpload(false);
    await loadWatchlists();
    if (activeId) loadDetail(activeId);
  }

  async function removeStock(itemId: number) {
    if (!activeId) return;
    try {
      await api.delete(`/api/watchlists/${activeId}/stocks/${itemId}`);
      loadDetail(activeId);
    } catch (err) {
      showMsg(err instanceof Error ? err.message : "Failed to remove", "err");
    }
  }

  if (loading) return <div className="text-gray-500">Loading watchlists...</div>;

  return (
    <div>
      <WatchlistPageActions
        activeId={activeId}
        watchlists={watchlists}
        onPickWatchlist={setActiveId}
        onClickNew={() => setShowCreate(!showCreate)}
        onClickUpload={() => { setShowUpload(!showUpload); setUploadResult(null); }}
      />

      {msg && (
        <div className={`mb-4 p-3 rounded text-sm ${msg.type === "ok" ? "bg-green-950 border border-green-800 text-green-300" : "bg-red-950 border border-red-800 text-red-300"}`}>
          {msg.text}
        </div>
      )}

      {/* Create form */}
      {showCreate && (
        <div className="mb-4 p-4 bg-gray-900 border border-gray-800 rounded-lg">
          <h2 className="font-semibold mb-3">Create Watchlist</h2>
          <div className="space-y-2">
            <input
              type="text"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="Watchlist name"
              className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-md text-white text-sm focus:outline-none focus:border-blue-500"
            />
            <textarea
              value={newDesc}
              onChange={(e) => setNewDesc(e.target.value)}
              placeholder="Description (optional)"
              rows={2}
              className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-md text-white text-sm focus:outline-none focus:border-blue-500"
            />
            <div className="flex gap-2">
              <button onClick={createWatchlist} className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm rounded-md">Create</button>
              <button onClick={() => setShowCreate(false)} className="px-4 py-2 bg-gray-800 hover:bg-gray-700 text-sm rounded-md">Cancel</button>
            </div>
          </div>
        </div>
      )}

      {/* Upload Area */}
      {showUpload && (
        <div className="mb-6 p-4 bg-gray-900 border border-gray-800 rounded-lg">
          <h2 className="font-semibold mb-3">Upload Stocks</h2>

          {/* Step 1: Pick target watchlist(s) BEFORE uploading */}
          {!uploadResult && (
            <div className="mb-4 p-3 bg-gray-800 border border-gray-700 rounded">
              <div className="text-xs text-gray-400 mb-2 font-semibold">
                Step 1 — Which watchlist(s) should these stocks be added to?
              </div>
              <div className="space-y-1.5 max-h-48 overflow-auto">
                {watchlists.map((wl) => (
                  <label
                    key={wl.id}
                    className="flex items-center gap-2 p-2 bg-gray-900 hover:bg-gray-850 rounded cursor-pointer transition-colors"
                  >
                    <input
                      type="checkbox"
                      checked={uploadTargetIds.has(wl.id)}
                      onChange={() => toggleUploadTarget(wl.id)}
                      className="rounded"
                    />
                    <span className="flex-1 text-sm text-white">{wl.name}</span>
                    <span className="text-xs text-gray-500">{wl.stock_count} stocks</span>
                  </label>
                ))}
              </div>
              <div className="mt-2 flex items-center gap-2 text-xs">
                <button
                  onClick={() => setUploadTargetIds(new Set(watchlists.map(w => w.id)))}
                  className="text-blue-400 hover:text-blue-300"
                >
                  Select all
                </button>
                <span className="text-gray-700">·</span>
                <button
                  onClick={() => setUploadTargetIds(new Set())}
                  className="text-gray-500 hover:text-gray-400"
                >
                  Clear
                </button>
                <span className="ml-auto text-gray-500">
                  {uploadTargetIds.size} selected
                </span>
              </div>
            </div>
          )}

          {/* Step 2: File drop area — disabled until at least one watchlist selected */}
          {!uploadResult && (
            <>
              <div className="text-xs text-gray-400 mb-2 font-semibold">
                Step 2 — Choose your file
              </div>
              <div
                onDragOver={(e) => { e.preventDefault(); if (uploadTargetIds.size > 0) setDragOver(true); }}
                onDragLeave={() => setDragOver(false)}
                onDrop={(e) => {
                  if (uploadTargetIds.size === 0) {
                    e.preventDefault();
                    showMsg("Select at least one watchlist first", "err");
                    return;
                  }
                  onDrop(e);
                }}
                className={`border-2 border-dashed rounded-lg p-8 text-center transition-colors ${
                  uploadTargetIds.size === 0
                    ? "border-gray-800 bg-gray-950/30 cursor-not-allowed opacity-50"
                    : dragOver
                      ? "border-blue-500 bg-blue-950/30 cursor-pointer"
                      : "border-gray-700 hover:border-gray-600 cursor-pointer"
                }`}
                onClick={() => {
                  if (uploadTargetIds.size === 0) {
                    showMsg("Select at least one watchlist first", "err");
                    return;
                  }
                  fileInputRef.current?.click();
                }}
              >
                <input
                  ref={fileInputRef}
                  type="file"
                  onChange={onFileSelect}
                  accept=".xlsx,.xls,.csv,.txt,.png,.jpg,.jpeg,.webp"
                  className="hidden"
                />
                {uploading ? (
                  <div className="text-gray-400">Processing file with AI...</div>
                ) : uploadTargetIds.size === 0 ? (
                  <div>
                    <div className="text-gray-500 mb-2">Pick a watchlist above first</div>
                    <div className="text-xs text-gray-600">Excel, CSV, Images, Text</div>
                  </div>
                ) : (
                  <div>
                    <div className="text-gray-400 mb-2">Drop a file here or click to browse</div>
                    <div className="text-xs text-gray-500">Excel, CSV, Images, Text</div>
                  </div>
                )}
              </div>
            </>
          )}

          {uploadResult && (
            <div className="space-y-4">
              <div className="text-sm text-gray-400">
                Extracted {uploadResult.raw_extracted.length} items, matched {uploadResult.matched.length}, errors {uploadResult.errors.length}
              </div>

              {uploadResult.errors.length > 0 && (
                <div className="p-3 bg-red-950/30 border border-red-900/50 rounded max-h-40 overflow-auto">
                  <div className="text-xs font-semibold text-red-400 mb-2">Could not map:</div>
                  <div className="space-y-1 text-xs">
                    {uploadResult.errors.map((e, i) => (
                      <div key={i} className="text-red-300">
                        <span className="font-mono">{e.input}</span>
                        <span className="text-gray-500"> — {e.error}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {uploadResult.matched.length > 0 && uploadResult.matched.length <= 30 && (
                <div className="p-3 bg-green-950/20 border border-green-900/30 rounded max-h-40 overflow-auto">
                  <div className="text-xs font-semibold text-green-400 mb-2">Matched stocks:</div>
                  <div className="flex flex-wrap gap-1.5">
                    {uploadResult.matched.map((s, i) => (
                      <span key={i} className="text-xs bg-green-900/50 text-green-200 px-2 py-0.5 rounded font-mono">
                        {s.symbol}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {uploadResult.matched.length > 0 && (
                <>
                  <div className="p-3 bg-gray-800 border border-gray-700 rounded text-xs">
                    <span className="text-gray-400">Will be added to: </span>
                    {Array.from(uploadTargetIds).map((id) => watchlists.find(w => w.id === id)?.name).filter(Boolean).map((name, i, arr) => (
                      <span key={i} className="text-white font-semibold">
                        {name}{i < arr.length - 1 ? ", " : ""}
                      </span>
                    ))}
                  </div>

                  <div className="flex gap-2">
                    <button
                      onClick={() => confirmAdd(uploadResult.matched)}
                      disabled={uploadTargetIds.size === 0}
                      className="px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-40 text-white text-sm rounded-md"
                    >
                      Add {uploadResult.matched.length} stocks to {uploadTargetIds.size} watchlist{uploadTargetIds.size === 1 ? "" : "s"}
                    </button>
                    <button onClick={() => setUploadResult(null)} className="px-4 py-2 bg-gray-700 hover:bg-gray-600 text-sm rounded-md">
                      Upload Another
                    </button>
                  </div>
                </>
              )}
            </div>
          )}
        </div>
      )}

      {/* ── Unified Header ─────────────────────────────────────────── */}
      {detail && (
        <div style={{ marginBottom: 16 }}>
          {/* Row 1: Breadcrumb + title + actions */}
          {activeId !== null ? (
            <>
              <div style={{
                display: "flex", alignItems: "center", justifyContent: "space-between",
                gap: 16, flexWrap: "wrap",
              }}>
                <div style={{ display: "flex", alignItems: "baseline", gap: 12, flexWrap: "wrap" }}>
                  {/* Watchlist name + picker dropdown */}
                  <div style={{ position: "relative" }}>
                    <button
                      onClick={() => { setShowWatchlistPicker(!showWatchlistPicker); setWatchlistSearch(""); }}
                      style={{
                        display: "inline-flex", alignItems: "baseline", gap: 8,
                        background: "none", border: 0, cursor: "pointer", padding: 0,
                      }}
                    >
                      <h2 style={{
                        fontFamily: "var(--font-serif)", fontSize: 22, fontWeight: 600,
                        letterSpacing: "-0.015em", color: "var(--label-primary)", margin: 0,
                      }}>{detail.name}</h2>
                      <span style={{ fontSize: 12, color: "var(--label-tertiary)" }}>
                        {showWatchlistPicker ? "∧" : "∨"}
                      </span>
                    </button>
                    {showWatchlistPicker && (
                      <>
                        <div style={{ position: "fixed", inset: 0, zIndex: 10 }} onClick={() => setShowWatchlistPicker(false)} />
                        <div style={{
                          position: "absolute", left: 0, top: "100%", marginTop: 8, width: 320, zIndex: 20,
                          background: "var(--bg-primary)", border: "1px solid var(--separator)",
                          borderRadius: 12, boxShadow: "var(--shadow-lg)",
                          overflow: "hidden",
                        }}>
                          {/* Search */}
                          <div style={{ padding: "10px 12px", borderBottom: "1px solid var(--separator-light)" }}>
                            <div style={{ position: "relative" }}>
                              <span style={{
                                position: "absolute", left: 8, top: "50%", transform: "translateY(-50%)",
                                color: "var(--label-tertiary)", fontSize: 13,
                              }}>⌕</span>
                              <input
                                type="text"
                                value={watchlistSearch}
                                onChange={(e) => setWatchlistSearch(e.target.value)}
                                placeholder="Find watchlist…"
                                autoFocus
                                style={{
                                  width: "100%", padding: "6px 8px 6px 28px", borderRadius: 6,
                                  border: "1px solid var(--separator-light)",
                                  background: "var(--bg-secondary)", color: "var(--label-primary)",
                                  fontSize: 13, outline: "none",
                                }}
                              />
                            </div>
                          </div>
                          {/* Watchlist list */}
                          <div style={{ maxHeight: 320, overflowY: "auto", padding: "4px 0" }}>
                            {/* All watchlists option */}
                            <button
                              onClick={() => { setActiveId(null); setShowWatchlistPicker(false); }}
                              style={{
                                display: "flex", alignItems: "center", gap: 10, width: "100%",
                                padding: "10px 14px", border: 0, cursor: "pointer", fontSize: 13,
                                background: "transparent", color: "var(--label-primary)",
                              }}
                              onMouseEnter={(e) => (e.currentTarget.style.background = "var(--bg-secondary)")}
                              onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
                            >
                              <span style={{
                                width: 8, height: 8, borderRadius: "50%",
                                background: activeId === null ? "var(--accent)" : "var(--label-quaternary)",
                                flexShrink: 0,
                              }} />
                              <span style={{ flex: 1, textAlign: "left" }}>
                                <div style={{ fontWeight: 500 }}>All watchlists</div>
                              </span>
                              {activeId === null && <span style={{ color: "var(--accent)", fontSize: 14 }}>✓</span>}
                            </button>
                            {watchlists
                              .filter((w) => !watchlistSearch || w.name.toLowerCase().includes(watchlistSearch.toLowerCase()))
                              .map((w) => {
                                const isActive = w.id === activeId;
                                return (
                                  <button
                                    key={w.id}
                                    onClick={() => { setActiveId(w.id); setShowWatchlistPicker(false); }}
                                    style={{
                                      display: "flex", alignItems: "center", gap: 10, width: "100%",
                                      padding: "10px 14px", border: 0, cursor: "pointer", fontSize: 13,
                                      background: "transparent", color: "var(--label-primary)",
                                    }}
                                    onMouseEnter={(e) => (e.currentTarget.style.background = "var(--bg-secondary)")}
                                    onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
                                  >
                                    <span style={{
                                      width: 8, height: 8, borderRadius: "50%",
                                      background: isActive ? "var(--accent)" : "var(--label-quaternary)",
                                      flexShrink: 0,
                                    }} />
                                    <span style={{ flex: 1, textAlign: "left" }}>
                                      <div style={{ fontWeight: isActive ? 600 : 500 }}>{w.name}</div>
                                      {w.description && (
                                        <div style={{ fontSize: 11, color: "var(--label-tertiary)", marginTop: 1 }}>{w.description}</div>
                                      )}
                                    </span>
                                    <span style={{
                                      fontSize: 12, color: "var(--label-tertiary)",
                                      background: "var(--bg-secondary)", borderRadius: 10,
                                      padding: "2px 8px", fontWeight: 500,
                                    }}>{w.stock_count}</span>
                                    {isActive && <span style={{ color: "var(--accent)", fontSize: 14 }}>✓</span>}
                                  </button>
                                );
                              })}
                          </div>
                          {/* + New watchlist */}
                          <div style={{ borderTop: "1px solid var(--separator-light)", padding: "4px 0" }}>
                            <button
                              onClick={() => { setShowWatchlistPicker(false); setShowCreate(true); }}
                              style={{
                                display: "flex", alignItems: "center", gap: 10, width: "100%",
                                padding: "10px 14px", border: 0, cursor: "pointer", fontSize: 13,
                                background: "transparent", color: "var(--label-primary)",
                              }}
                              onMouseEnter={(e) => (e.currentTarget.style.background = "var(--bg-secondary)")}
                              onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
                            >
                              <span style={{ fontSize: 16, color: "var(--label-tertiary)" }}>+</span>
                              New watchlist
                            </button>
                          </div>
                        </div>
                      </>
                    )}
                  </div>
                  <span style={{ fontSize: 13, color: "var(--label-tertiary)" }}>
                    {detail.stocks.length} stocks
                    {lastUpdatedLabel ? ` · Updated ${lastUpdatedLabel}` : ""}
                  </span>
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  {/* Missing fundamentals badge */}
                  {!dismissedFundBadge && detail.missing_fundamentals && detail.missing_fundamentals > 0 && (
                    <div style={{
                      display: "inline-flex", alignItems: "center", gap: 8,
                      padding: "5px 12px", borderRadius: 20, fontSize: 13,
                      background: "#FEF3C7", color: "#92400E",
                      border: "1px solid #FCD34D",
                    }}>
                      <span style={{ fontSize: 14 }}>⚠</span>
                      {detail.missing_fundamentals} missing fundamentals
                      <button
                        onClick={() => activeId && refreshFundamentals(activeId)}
                        disabled={refreshingFund}
                        style={{
                          background: "none", border: 0, cursor: "pointer",
                          textDecoration: "underline", color: "#92400E", fontWeight: 600,
                          fontSize: 13, padding: 0,
                        }}
                      >{refreshingFund ? "Fetching…" : "Fetch"}</button>
                      <button
                        onClick={() => setDismissedFundBadge(true)}
                        style={{
                          background: "none", border: 0, cursor: "pointer",
                          color: "#B45309", fontSize: 14, padding: 0, lineHeight: 1,
                        }}
                      >×</button>
                    </div>
                  )}

                  {/* Run Strategy */}
                  <div style={{ position: "relative" }}>
                    <button
                      onClick={() => setShowStrategyPicker(!showStrategyPicker)}
                      disabled={detail.stocks.length === 0}
                      style={{
                        display: "inline-flex", alignItems: "center", gap: 6,
                        padding: "6px 14px", borderRadius: 8, fontSize: 13, fontWeight: 500,
                        border: "1px solid var(--separator-light)",
                        background: "var(--bg-primary)", color: "var(--label-primary)",
                        cursor: "pointer", opacity: detail.stocks.length === 0 ? 0.5 : 1,
                      }}
                    >
                      <span style={{ fontSize: 13 }}>✓</span> Run Strategy <span style={{ fontSize: 10, opacity: 0.6 }}>▾</span>
                    </button>
                    {showStrategyPicker && (
                      <>
                        <div style={{ position: "fixed", inset: 0, zIndex: 10 }} onClick={() => setShowStrategyPicker(false)} />
                        <div style={{
                          position: "absolute", right: 0, marginTop: 4, width: 256, zIndex: 20,
                          background: "var(--bg-primary)", border: "1px solid var(--separator)",
                          borderRadius: 10, boxShadow: "var(--shadow-lg)",
                          maxHeight: 320, overflow: "auto",
                        }}>
                          {myStrategies.length === 0 ? (
                            <div style={{ padding: 12, fontSize: 13, color: "var(--label-tertiary)" }}>
                              No strategies imported yet.{" "}
                              <button
                                onClick={() => router.push("/strategies")}
                                style={{ background: "none", border: 0, color: "var(--accent)", cursor: "pointer", textDecoration: "underline", fontSize: 13, padding: 0 }}
                              >Import one</button>
                            </div>
                          ) : (
                            <div style={{ padding: "4px 0" }}>
                              {myStrategies.map((s) => (
                                <button
                                  key={s.id}
                                  onClick={() => { setShowStrategyPicker(false); runStrategyOnWatchlist(s.id); }}
                                  style={{
                                    display: "block", width: "100%", textAlign: "left",
                                    padding: "8px 12px", border: 0, cursor: "pointer",
                                    background: "transparent", color: "var(--label-primary)", fontSize: 13,
                                  }}
                                  onMouseEnter={(e) => (e.currentTarget.style.background = "var(--bg-secondary)")}
                                  onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
                                >
                                  <div>{s.name}</div>
                                  <div style={{ fontSize: 11, color: "var(--label-tertiary)" }}>{s.strategy_type}</div>
                                </button>
                              ))}
                            </div>
                          )}
                        </div>
                      </>
                    )}
                  </div>

                  {/* Overflow menu (⋯) */}
                  <div style={{ position: "relative" }}>
                    <button
                      onClick={() => setShowOverflowMenu(!showOverflowMenu)}
                      style={{
                        width: 34, height: 34, borderRadius: 8, fontSize: 18,
                        border: "1px solid var(--separator-light)",
                        background: "var(--bg-primary)", color: "var(--label-secondary)",
                        cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center",
                      }}
                    >⋯</button>
                    {showOverflowMenu && (
                      <>
                        <div style={{ position: "fixed", inset: 0, zIndex: 10 }} onClick={() => setShowOverflowMenu(false)} />
                        <div style={{
                          position: "absolute", right: 0, marginTop: 4, width: 220, zIndex: 20,
                          background: "var(--bg-primary)", border: "1px solid var(--separator)",
                          borderRadius: 10, boxShadow: "var(--shadow-lg)",
                          padding: "4px 0",
                        }}>
                          <button
                            onClick={() => { setShowOverflowMenu(false); activeId && refreshFundamentals(activeId, false); }}
                            disabled={refreshingFund || detail.stocks.length === 0}
                            style={{
                              display: "flex", alignItems: "center", gap: 10, width: "100%",
                              padding: "10px 14px", border: 0, cursor: "pointer", fontSize: 13,
                              background: "transparent", color: "var(--label-primary)",
                              opacity: refreshingFund ? 0.5 : 1,
                            }}
                            onMouseEnter={(e) => (e.currentTarget.style.background = "var(--bg-secondary)")}
                            onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
                          >
                            <span style={{ fontSize: 15 }}>↻</span>
                            {refreshingFund ? "Refreshing…" : "Refresh fundamentals"}
                          </button>
                          <button
                            disabled
                            style={{
                              display: "flex", alignItems: "center", gap: 10, width: "100%",
                              padding: "10px 14px", border: 0, fontSize: 13,
                              background: "transparent", color: "var(--label-quaternary)",
                              cursor: "default",
                            }}
                          >
                            <span style={{ fontSize: 15 }}>↓</span>
                            Export as CSV
                            <span style={{ marginLeft: "auto", fontSize: 11, opacity: 0.6 }}>Soon</span>
                          </button>
                          <button
                            disabled
                            style={{
                              display: "flex", alignItems: "center", gap: 10, width: "100%",
                              padding: "10px 14px", border: 0, fontSize: 13,
                              background: "transparent", color: "var(--label-quaternary)",
                              cursor: "default",
                            }}
                          >
                            <span style={{ fontSize: 15 }}>⚙</span>
                            Watchlist settings
                            <span style={{ marginLeft: "auto", fontSize: 11, opacity: 0.6 }}>Soon</span>
                          </button>
                          <div style={{ height: 1, background: "var(--separator-light)", margin: "4px 0" }} />
                          <button
                            onClick={() => { setShowOverflowMenu(false); deleteWatchlist(); }}
                            style={{
                              display: "flex", alignItems: "center", gap: 10, width: "100%",
                              padding: "10px 14px", border: 0, cursor: "pointer", fontSize: 13,
                              background: "transparent", color: "#DC2626",
                            }}
                            onMouseEnter={(e) => (e.currentTarget.style.background = "var(--bg-secondary)")}
                            onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
                          >
                            <span style={{ fontSize: 15 }}>🗑</span>
                            Delete watchlist
                          </button>
                        </div>
                      </>
                    )}
                  </div>
                </div>
              </div>
            </>
          ) : (
            <div style={{
              display: "flex", alignItems: "center", justifyContent: "space-between",
              gap: 16, flexWrap: "wrap",
            }}>
              <div style={{ display: "flex", alignItems: "baseline", gap: 12, flexWrap: "wrap" }}>
                {/* Watchlist picker in All view */}
                <div style={{ position: "relative" }}>
                  <button
                    onClick={() => { setShowWatchlistPicker(!showWatchlistPicker); setWatchlistSearch(""); }}
                    style={{
                      display: "inline-flex", alignItems: "baseline", gap: 8,
                      background: "none", border: 0, cursor: "pointer", padding: 0,
                    }}
                  >
                    <h2 style={{
                      fontFamily: "var(--font-serif)", fontSize: 22, fontWeight: 600,
                      letterSpacing: "-0.015em", color: "var(--label-primary)", margin: 0,
                    }}>Researching</h2>
                    <span style={{ fontSize: 12, color: "var(--label-tertiary)" }}>
                      {showWatchlistPicker ? "∧" : "∨"}
                    </span>
                  </button>
                  {showWatchlistPicker && (
                    <>
                      <div style={{ position: "fixed", inset: 0, zIndex: 10 }} onClick={() => setShowWatchlistPicker(false)} />
                      <div style={{
                        position: "absolute", left: 0, top: "100%", marginTop: 8, width: 320, zIndex: 20,
                        background: "var(--bg-primary)", border: "1px solid var(--separator)",
                        borderRadius: 12, boxShadow: "var(--shadow-lg)",
                        overflow: "hidden",
                      }}>
                        <div style={{ padding: "10px 12px", borderBottom: "1px solid var(--separator-light)" }}>
                          <div style={{ position: "relative" }}>
                            <span style={{
                              position: "absolute", left: 8, top: "50%", transform: "translateY(-50%)",
                              color: "var(--label-tertiary)", fontSize: 13,
                            }}>⌕</span>
                            <input
                              type="text"
                              value={watchlistSearch}
                              onChange={(e) => setWatchlistSearch(e.target.value)}
                              placeholder="Find watchlist…"
                              autoFocus
                              style={{
                                width: "100%", padding: "6px 8px 6px 28px", borderRadius: 6,
                                border: "1px solid var(--separator-light)",
                                background: "var(--bg-secondary)", color: "var(--label-primary)",
                                fontSize: 13, outline: "none",
                              }}
                            />
                          </div>
                        </div>
                        <div style={{ maxHeight: 320, overflowY: "auto", padding: "4px 0" }}>
                          <button
                            onClick={() => { setActiveId(null); setShowWatchlistPicker(false); }}
                            style={{
                              display: "flex", alignItems: "center", gap: 10, width: "100%",
                              padding: "10px 14px", border: 0, cursor: "pointer", fontSize: 13,
                              background: "transparent", color: "var(--label-primary)",
                            }}
                            onMouseEnter={(e) => (e.currentTarget.style.background = "var(--bg-secondary)")}
                            onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
                          >
                            <span style={{
                              width: 8, height: 8, borderRadius: "50%",
                              background: "var(--accent)", flexShrink: 0,
                            }} />
                            <span style={{ flex: 1, textAlign: "left" }}>
                              <div style={{ fontWeight: 600 }}>All watchlists</div>
                            </span>
                            <span style={{ color: "var(--accent)", fontSize: 14 }}>✓</span>
                          </button>
                          {watchlists
                            .filter((w) => !watchlistSearch || w.name.toLowerCase().includes(watchlistSearch.toLowerCase()))
                            .map((w) => (
                              <button
                                key={w.id}
                                onClick={() => { setActiveId(w.id); setShowWatchlistPicker(false); }}
                                style={{
                                  display: "flex", alignItems: "center", gap: 10, width: "100%",
                                  padding: "10px 14px", border: 0, cursor: "pointer", fontSize: 13,
                                  background: "transparent", color: "var(--label-primary)",
                                }}
                                onMouseEnter={(e) => (e.currentTarget.style.background = "var(--bg-secondary)")}
                                onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
                              >
                                <span style={{
                                  width: 8, height: 8, borderRadius: "50%",
                                  background: "var(--label-quaternary)", flexShrink: 0,
                                }} />
                                <span style={{ flex: 1, textAlign: "left" }}>
                                  <div style={{ fontWeight: 500 }}>{w.name}</div>
                                  {w.description && (
                                    <div style={{ fontSize: 11, color: "var(--label-tertiary)", marginTop: 1 }}>{w.description}</div>
                                  )}
                                </span>
                                <span style={{
                                  fontSize: 12, color: "var(--label-tertiary)",
                                  background: "var(--bg-secondary)", borderRadius: 10,
                                  padding: "2px 8px", fontWeight: 500,
                                }}>{w.stock_count}</span>
                              </button>
                            ))}
                        </div>
                        <div style={{ borderTop: "1px solid var(--separator-light)", padding: "4px 0" }}>
                          <button
                            onClick={() => { setShowWatchlistPicker(false); setShowCreate(true); }}
                            style={{
                              display: "flex", alignItems: "center", gap: 10, width: "100%",
                              padding: "10px 14px", border: 0, cursor: "pointer", fontSize: 13,
                              background: "transparent", color: "var(--label-primary)",
                            }}
                            onMouseEnter={(e) => (e.currentTarget.style.background = "var(--bg-secondary)")}
                            onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
                          >
                            <span style={{ fontSize: 16, color: "var(--label-tertiary)" }}>+</span>
                            New watchlist
                          </button>
                        </div>
                      </div>
                    </>
                  )}
                </div>
                <span style={{ fontSize: 13, color: "var(--label-tertiary)" }}>
                  {detail.stocks.length} stocks
                </span>
              </div>
            </div>
          )}

          {/* Row 2: Toolbar — white card with F&O tabs | Filter | Sort | View toggle */}
          <div className="wl-toolbar" style={{
            display: "flex", alignItems: "center", justifyContent: "space-between",
            gap: 12, flexWrap: "wrap", marginTop: 16,
            padding: "10px 16px", borderRadius: 12,
            background: "var(--bg-primary)",
            border: "1px solid var(--separator-light)",
            boxShadow: "var(--shadow-sm)",
          }}>
            <style jsx>{`
              @media (max-width: 720px) {
                .wl-toolbar {
                  flex-wrap: nowrap !important;
                  overflow-x: auto;
                  -webkit-overflow-scrolling: touch;
                  scrollbar-width: none;
                }
                .wl-toolbar::-webkit-scrollbar { display: none; }
                .wl-toolbar :global(button) { min-height: 36px; }
              }
            `}</style>
            <div style={{ display: "flex", alignItems: "center", gap: 12, flex: 1, minWidth: 0 }}>
              {/* F&O exchange filter — prefixed with "Exchange:" so the
                  "All" chip here is not confused with the Lane "All" chip
                  on the right. */}
              {fnoCounts.all > 0 && (
                <div style={{ display: "inline-flex", alignItems: "center", gap: 6, flexShrink: 0 }}>
                  <span style={{
                    fontSize: 11, color: "var(--label-tertiary)",
                    textTransform: "uppercase", letterSpacing: "0.04em",
                    fontWeight: 600,
                  }}>Exchange</span>
                <div style={{
                  display: "inline-flex", padding: 3, borderRadius: 8,
                  border: "1px solid var(--separator-light)", flexShrink: 0,
                }}>
                  {([
                    { k: "all", label: "All", n: fnoCounts.all },
                    { k: "nse_fno", label: "NSE F&O", n: fnoCounts.nse_fno },
                    { k: "bse_fno", label: "BSE F&O", n: fnoCounts.bse_fno },
                  ] as const).map((t) => {
                    const active = fnoTab === t.k;
                    return (
                      <button
                        key={t.k}
                        onClick={() => setFnoTab(t.k)}
                        style={{
                          padding: "5px 12px", borderRadius: 6, fontSize: 12, fontWeight: active ? 600 : 500,
                          border: active ? "1px solid var(--separator-light)" : "1px solid transparent",
                          cursor: "pointer",
                          background: active ? "var(--bg-primary)" : "transparent",
                          color: active ? "var(--label-primary)" : "var(--label-tertiary)",
                          boxShadow: active ? "var(--shadow-sm)" : "none",
                        }}
                      >{t.label} <span style={{ fontWeight: 400, marginLeft: 2 }}>{t.n}</span></button>
                    );
                  })}
                </div>
                </div>
              )}
              {/* Vertical separator */}
              {fnoCounts.all > 0 && (
                <div style={{ width: 1, height: 22, background: "var(--separator-light)", flexShrink: 0 }} />
              )}
              {/* Lane tabs */}
              <span style={{
                fontSize: 11, color: "var(--label-tertiary)",
                textTransform: "uppercase", letterSpacing: "0.04em",
                fontWeight: 600, flexShrink: 0,
              }}>Lane</span>
              <div style={{
                display: "inline-flex", padding: 3, borderRadius: 8,
                border: "1px solid var(--separator-light)", flexShrink: 0,
              }}>
                {([
                  { k: "all",          label: "All",                 dot: null },
                  { k: "researching",  label: "Researching",        dot: "var(--system-blue)" },
                  { k: "awaiting",     label: "Awaiting Correction", dot: "var(--review)" },
                  { k: "buy",          label: "Buy",                dot: "var(--buy)" },
                  { k: "hold",         label: "Hold",               dot: "var(--hold)" },
                  { k: "exit",         label: "Exit Watch",         dot: "var(--act)" },
                ] as const).filter((t) => t.k === "all" || (laneCounts[t.k] ?? 0) > 0).map((t) => {
                  const active = laneFilter === t.k;
                  const count = laneCounts[t.k] ?? 0;
                  return (
                    <button
                      key={t.k}
                      onClick={() => setLaneFilter(t.k)}
                      style={{
                        display: "inline-flex", alignItems: "center", gap: 5,
                        padding: "5px 10px", borderRadius: 6, fontSize: 12, fontWeight: active ? 600 : 500,
                        border: active ? "1px solid var(--separator-light)" : "1px solid transparent",
                        cursor: "pointer",
                        background: active ? "var(--bg-primary)" : "transparent",
                        color: active ? "var(--label-primary)" : "var(--label-tertiary)",
                        boxShadow: active ? "var(--shadow-sm)" : "none",
                        whiteSpace: "nowrap",
                      }}
                    >
                      {t.dot && <span style={{ width: 7, height: 7, borderRadius: 99, background: t.dot, flexShrink: 0 }} />}
                      {t.label}
                      <span style={{ fontWeight: 400, fontSize: 11, color: "var(--label-quaternary)" }}>{count}</span>
                    </button>
                  );
                })}
              </div>
              {(laneCounts.all ?? 0) > 0 && (
                <div style={{ width: 1, height: 22, background: "var(--separator-light)", flexShrink: 0 }} />
              )}
              {/* Filter input */}
              <div style={{
                display: "flex", alignItems: "center", gap: 8,
                background: "var(--bg-secondary)",
                borderRadius: 8, padding: "0 12px", height: 30,
                width: 260, flexShrink: 0,
              }}>
                <span style={{ color: "var(--label-tertiary)", fontSize: 13, flexShrink: 0 }}>⌕</span>
                <input
                  type="text"
                  className="bg-secondary-override"
                  value={symbolFilter}
                  onChange={(e) => setSymbolFilter(e.target.value)}
                  placeholder="Filter by symbol…"
                  aria-label="Filter by symbol"
                  style={{
                    border: "none", outline: "none",
                    fontSize: 13, color: "var(--label-primary)",
                    padding: 0, flex: 1, minWidth: 0,
                  }}
                />
              </div>

              {/* Sector filter */}
              {sectorCounts.length > 0 && (
                <div style={{ position: "relative" }}>
                  <button
                    onClick={() => {
                      setPendingSectors(new Set(selectedSectors));
                      setSectorSearch("");
                      setShowSectorPicker(!showSectorPicker);
                    }}
                    style={{
                      display: "inline-flex", alignItems: "center", gap: 6,
                      padding: "0 12px", height: 30, borderRadius: 8,
                      fontSize: 13, fontWeight: selectedSectors.size > 0 ? 600 : 500,
                      border: "1px solid var(--separator-light)",
                      background: selectedSectors.size > 0 ? "var(--bg-secondary)" : "var(--bg-primary)",
                      color: "var(--label-primary)",
                      cursor: "pointer", flexShrink: 0,
                    }}
                  >
                    <span style={{ fontSize: 12, color: "var(--label-tertiary)" }}>⏷</span>
                    Sector
                    {selectedSectors.size > 0 && (
                      <span style={{
                        marginLeft: 2, padding: "1px 7px", borderRadius: 10,
                        background: "var(--label-primary)", color: "var(--bg-primary)",
                        fontSize: 11, fontWeight: 600,
                      }}>{selectedSectors.size}</span>
                    )}
                    <span style={{ fontSize: 9, color: "var(--label-tertiary)", marginLeft: 2 }}>▾</span>
                  </button>
                  {showSectorPicker && (
                    <>
                      <div style={{ position: "fixed", inset: 0, zIndex: 10 }} onClick={() => setShowSectorPicker(false)} />
                      <div style={{
                        position: "absolute", left: 0, top: "calc(100% + 6px)", width: 340, zIndex: 20,
                        background: "var(--bg-primary)", border: "1px solid var(--separator)",
                        borderRadius: 12, boxShadow: "var(--shadow-lg)",
                        overflow: "hidden", display: "flex", flexDirection: "column",
                      }}>
                        {/* Header */}
                        <div style={{
                          display: "flex", alignItems: "center", justifyContent: "space-between",
                          padding: "12px 14px 8px",
                        }}>
                          <span style={{
                            fontSize: 11, fontWeight: 600, letterSpacing: "0.06em",
                            color: "var(--label-tertiary)", textTransform: "uppercase",
                          }}>Filter by sector</span>
                          {pendingSectors.size > 0 && (
                            <button
                              onClick={() => setPendingSectors(new Set())}
                              style={{
                                background: "none", border: 0, cursor: "pointer", padding: 0,
                                fontSize: 12, fontWeight: 500, color: "var(--system-blue, #007AFF)",
                              }}
                            >Clear all</button>
                          )}
                        </div>
                        {/* Search */}
                        <div style={{ padding: "0 14px 8px" }}>
                          <div style={{
                            display: "flex", alignItems: "center", gap: 8,
                            background: "var(--bg-secondary)",
                            borderRadius: 8, padding: "0 10px", height: 32,
                          }}>
                            <span style={{ color: "var(--label-tertiary)", fontSize: 13, flexShrink: 0 }}>⌕</span>
                            <input
                              type="text"
                              className="bg-secondary-override"
                              value={sectorSearch}
                              onChange={(e) => setSectorSearch(e.target.value)}
                              placeholder="Search sectors…"
                              autoFocus
                              style={{
                                border: "none", outline: "none",
                                fontSize: 13, color: "var(--label-primary)",
                                padding: 0, flex: 1, minWidth: 0,
                              }}
                            />
                          </div>
                        </div>
                        {/* Sector list */}
                        <div style={{ maxHeight: 320, overflowY: "auto", padding: "4px 0" }}>
                          {sectorCounts
                            .filter((s) => !sectorSearch || s.name.toLowerCase().includes(sectorSearch.toLowerCase()))
                            .map((s) => {
                              const checked = pendingSectors.has(s.name);
                              return (
                                <label
                                  key={s.name}
                                  style={{
                                    display: "flex", alignItems: "center", gap: 12, width: "100%",
                                    padding: "8px 14px", cursor: "pointer", fontSize: 13,
                                    color: "var(--label-primary)",
                                  }}
                                  onMouseEnter={(e) => (e.currentTarget.style.background = "var(--bg-secondary)")}
                                  onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
                                >
                                  <input
                                    type="checkbox"
                                    checked={checked}
                                    onChange={() => {
                                      const next = new Set(pendingSectors);
                                      if (checked) next.delete(s.name);
                                      else next.add(s.name);
                                      setPendingSectors(next);
                                    }}
                                    style={{
                                      width: 16, height: 16, cursor: "pointer", flexShrink: 0,
                                      accentColor: "var(--label-primary)",
                                    }}
                                  />
                                  <span style={{ flex: 1 }}>{s.name}</span>
                                  <span style={{
                                    fontSize: 12, color: "var(--label-tertiary)", fontWeight: 500,
                                  }}>{s.count}</span>
                                </label>
                              );
                            })}
                          {sectorCounts.filter((s) => !sectorSearch || s.name.toLowerCase().includes(sectorSearch.toLowerCase())).length === 0 && (
                            <div style={{ padding: "16px 14px", fontSize: 13, color: "var(--label-tertiary)", textAlign: "center" }}>
                              No sectors match
                            </div>
                          )}
                        </div>
                        {/* Footer */}
                        <div style={{
                          display: "flex", gap: 8, justifyContent: "space-between",
                          padding: "10px 14px", borderTop: "1px solid var(--separator-light)",
                        }}>
                          <button
                            onClick={() => setPendingSectors(new Set())}
                            style={{
                              padding: "7px 18px", borderRadius: 8, fontSize: 13, fontWeight: 500,
                              border: "1px solid var(--separator)",
                              background: "var(--bg-primary)", color: "var(--label-primary)",
                              cursor: "pointer",
                            }}
                          >Reset</button>
                          <button
                            onClick={() => {
                              setSelectedSectors(new Set(pendingSectors));
                              setShowSectorPicker(false);
                            }}
                            style={{
                              padding: "7px 18px", borderRadius: 8, fontSize: 13, fontWeight: 600,
                              border: 0,
                              background: "var(--label-primary)", color: "var(--bg-primary)",
                              cursor: "pointer",
                            }}
                          >Apply</button>
                        </div>
                      </div>
                    </>
                  )}
                </div>
              )}
            </div>

            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              {/* Run Analysis (bulk) toggle */}
              <button
                onClick={() => {
                  if (selectMode) {
                    setSelectMode(false);
                    setSelectedItemIds(new Set());
                  } else {
                    setSelectMode(true);
                  }
                }}
                style={{
                  display: "inline-flex", alignItems: "center", gap: 6,
                  padding: "0 12px", height: 30, borderRadius: 8,
                  fontSize: 13, fontWeight: 600,
                  border: selectMode ? "1px solid transparent" : "1px solid var(--separator-light)",
                  background: selectMode
                    ? "linear-gradient(90deg, #4796E5 0%, #9168C0 50%, #D96570 100%)"
                    : "var(--bg-primary)",
                  color: selectMode ? "#FFFFFF" : "var(--label-primary)",
                  cursor: "pointer", flexShrink: 0,
                }}
                title="Bulk-run AI analysis on selected stocks"
              >
                {selectMode ? "Done" : "Run Analysis"}
              </button>
              {/* Sort dropdown — minimal text style */}
              <span style={{ fontSize: 14, color: "var(--label-tertiary)" }}>≡</span>
              <span style={{ fontSize: 13, color: "var(--label-tertiary)" }}>Sort:</span>
              <select
                value={researchingSort}
                onChange={(e) => {
                  setResearchingSort(e.target.value as typeof researchingSort);
                  setSortAscCards(false);
                }}
                style={{
                  padding: "4px 4px", borderRadius: 4, fontSize: 13, fontWeight: 600,
                  border: "none",
                  background: "transparent", color: "var(--label-primary)",
                  cursor: "pointer", outline: "none",
                  WebkitAppearance: "none", MozAppearance: "none", appearance: "none",
                  backgroundImage: "none",
                }}
              >
                <option value="triggered">Triggered first</option>
                <option value="biggest_move">Biggest move</option>
                <option value="recent">Recently added</option>
                <option value="news_score">News</option>
                <option value="fundamentals_score">Fundamentals</option>
                <option value="ai_score">AI</option>
              </select>
              <span style={{ fontSize: 10, color: "var(--label-tertiary)", marginLeft: -4 }}>▾</span>
              <button
                onClick={() => setSortAscCards((v) => !v)}
                title={sortAscCards ? "Ascending" : "Descending"}
                style={{
                  width: 24, height: 24, borderRadius: 4, fontSize: 12,
                  border: "none", marginLeft: 2,
                  background: "transparent", color: "var(--label-tertiary)",
                  cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center",
                }}
              >{sortAscCards ? "↑" : "↓"}</button>

              {/* View toggle icons */}
              <div style={{
                display: "inline-flex", padding: 2, borderRadius: 8, marginLeft: 4,
                border: "1px solid var(--separator-light)",
              }}>
                <button
                  onClick={() => setViewMode("cards")}
                  title="Cards view"
                  style={{
                    width: 30, height: 28, borderRadius: 6, fontSize: 15,
                    border: 0, cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center",
                    background: viewMode === "cards" ? "var(--bg-secondary)" : "transparent",
                    color: viewMode === "cards" ? "var(--label-primary)" : "var(--label-tertiary)",
                    boxShadow: viewMode === "cards" ? "var(--shadow-sm)" : "none",
                  }}
                >⊞</button>
                <button
                  onClick={() => setViewMode("table")}
                  title="Table view"
                  style={{
                    width: 30, height: 28, borderRadius: 6, fontSize: 15,
                    border: 0, cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center",
                    background: viewMode === "table" ? "var(--bg-secondary)" : "transparent",
                    color: viewMode === "table" ? "var(--label-primary)" : "var(--label-tertiary)",
                    boxShadow: viewMode === "table" ? "var(--shadow-sm)" : "none",
                  }}
                >☰</button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Cards view */}
      {viewMode === "cards" && (
        <div style={{ minWidth: 0 }}>
          {loadingDetail && (
            <div style={{ padding: 20, color: "var(--label-tertiary)", fontSize: 13 }}>Loading…</div>
          )}
          {sortedStocks.length === 0 && !loadingDetail && (
            <div style={{
              padding: 40, textAlign: "center",
              background: "var(--bg-primary)", border: "1px dashed var(--separator)",
              borderRadius: 12, color: "var(--label-tertiary)", fontSize: 13,
            }}>
              {activeId === null
                ? <>No stocks across your watchlists yet. Click <strong>+ New Watchlist</strong> in the tab bar to get started, or pick a specific watchlist and use the upload icon to add stocks.</>
                : <>No stocks in this watchlist. Use the <strong>upload icon</strong> in the tab bar to add some.</>}
            </div>
          )}
          {/* Bulk action bar — appears when in select mode. Gemini-style
              multi-stop gradient that softens to transparent on the right. */}
          {selectMode && (
            <div style={{
              position: "sticky", top: 0, zIndex: 5,
              display: "flex", alignItems: "center", justifyContent: "space-between",
              gap: 12, marginBottom: 12, padding: "12px 16px", borderRadius: 12,
              color: "#FFFFFF",
              background: "linear-gradient(90deg, #4796E5 0%, #7B61D7 28%, #B965B8 55%, #E8728A 78%, rgba(232,114,138,0.55) 100%)",
              boxShadow: "0 6px 20px rgba(123, 97, 215, 0.25), 0 1px 0 rgba(255,255,255,0.06) inset",
            }}>
              <div style={{ display: "flex", alignItems: "center", gap: 12, fontSize: 13 }}>
                <span style={{
                  display: "inline-flex", alignItems: "center", justifyContent: "center",
                  width: 22, height: 22, borderRadius: "50%",
                  background: "rgba(255,255,255,0.18)", fontSize: 13,
                }}>✦</span>
                <span style={{ fontWeight: 600 }}>
                  {selectedItemIds.size} selected
                </span>
                <button
                  onClick={() => {
                    const visible = researchingStocks.map((s) => s.id);
                    const allSelected = visible.every((id) => selectedItemIds.has(id));
                    setSelectedItemIds(allSelected ? new Set() : new Set(visible));
                  }}
                  style={{
                    background: "none", border: 0, cursor: "pointer", padding: 0,
                    color: "#FFFFFF", opacity: 0.85, fontSize: 12,
                    textDecoration: "underline",
                  }}
                >
                  {researchingStocks.every((s) => selectedItemIds.has(s.id)) && researchingStocks.length > 0
                    ? "Clear visible"
                    : `Select all visible (${researchingStocks.length})`}
                </button>
              </div>
              <div style={{ display: "flex", gap: 8 }}>
                {bulkRunning && (
                  <button
                    onClick={() => setBulkAbort(true)}
                    style={{
                      padding: "6px 14px", borderRadius: 7, fontSize: 12, fontWeight: 500,
                      border: "1px solid rgba(255,255,255,0.35)",
                      background: "rgba(255,255,255,0.12)", color: "#FFFFFF",
                      cursor: "pointer", backdropFilter: "blur(8px)",
                    }}
                  >Stop</button>
                )}
                <button
                  onClick={runBulkAnalysis}
                  disabled={selectedItemIds.size === 0 || bulkRunning}
                  style={{
                    padding: "6px 16px", borderRadius: 7, fontSize: 12, fontWeight: 600,
                    border: 0,
                    background: "#FFFFFF", color: "#4D2C7A",
                    cursor: selectedItemIds.size === 0 || bulkRunning ? "not-allowed" : "pointer",
                    opacity: selectedItemIds.size === 0 || bulkRunning ? 0.55 : 1,
                    boxShadow: "0 1px 2px rgba(0,0,0,0.08)",
                  }}
                >
                  {bulkRunning ? "Running…" : `Run Analysis (${selectedItemIds.size})`}
                </button>
              </div>
            </div>
          )}
          {researchingStocks.map((s) => (
            <div
              key={s.id}
              style={{
                transition: "opacity 0.3s ease, transform 0.3s ease, max-height 0.35s ease",
                ...(slidingOutId === s.id
                  ? { opacity: 0, transform: "translateX(60px)", maxHeight: 0, overflow: "hidden", marginBottom: 0 }
                  : { opacity: 1, transform: "translateX(0)", maxHeight: 2000 }),
              }}
            >
              <ResearchingCard
                stock={s as unknown as Parameters<typeof ResearchingCard>[0]["stock"]}
                onMoveLane={(newLane) => {
                  if ((s.lane || "researching") === newLane) return;
                  setSlidingOutId(s.id);
                  setTimeout(() => {
                    setSlidingOutId(null);
                    setDetail((prev) => {
                      if (!prev) return prev;
                      return {
                        ...prev,
                        stocks: prev.stocks.map((st) =>
                          st.id === s.id ? { ...st, lane: newLane } : st
                        ),
                      };
                    });
                  }, 350);
                }}
                onStop={() => removeStock(s.id)}
                onAnalysisComplete={() => loadDetail(activeId)}
                selectMode={selectMode}
                selected={selectedItemIds.has(s.id)}
                onToggleSelect={() => {
                  const next = new Set(selectedItemIds);
                  if (next.has(s.id)) next.delete(s.id);
                  else next.add(s.id);
                  setSelectedItemIds(next);
                }}
                bulkStatus={bulkStatuses[s.id] ?? null}
              />
            </div>
          ))}
        </div>
      )}

      {/* Stocks Table with Fundamentals */}
      {viewMode === "table" && (
      <div className="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
        {loadingDetail && <div className="p-4 text-xs text-gray-500">Loading fundamentals...</div>}
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-800 text-xs text-gray-500 uppercase">
                <SortTh k="symbol" sortKey={sortKey} sortAsc={sortAsc} onClick={toggleSort} align="left">Symbol</SortTh>
                <SortTh k="verdict" sortKey={sortKey} sortAsc={sortAsc} onClick={toggleSort} align="center">Verdict</SortTh>
                <SortTh k="sentiment" sortKey={sortKey} sortAsc={sortAsc} onClick={toggleSort} align="center">Sentiment</SortTh>
                <SortTh k="cmp" sortKey={sortKey} sortAsc={sortAsc} onClick={toggleSort} align="right">CMP</SortTh>
                <SortTh k="market_cap" sortKey={sortKey} sortAsc={sortAsc} onClick={toggleSort} align="right">Mkt Cap</SortTh>
                <SortTh k="pe_ratio" sortKey={sortKey} sortAsc={sortAsc} onClick={toggleSort} align="right">P/E</SortTh>
                <SortTh k="ttm_pe" sortKey={sortKey} sortAsc={sortAsc} onClick={toggleSort} align="right">TTM P/E</SortTh>
                <SortTh k="forward_pe" sortKey={sortKey} sortAsc={sortAsc} onClick={toggleSort} align="right">Fwd P/E</SortTh>
                <SortTh k="pb_ratio" sortKey={sortKey} sortAsc={sortAsc} onClick={toggleSort} align="right">P/B</SortTh>
                <SortTh k="revenue_growth_1y" sortKey={sortKey} sortAsc={sortAsc} onClick={toggleSort} align="right">Rev Gr 1Y</SortTh>
                <SortTh k="eps_growth_1y" sortKey={sortKey} sortAsc={sortAsc} onClick={toggleSort} align="right">EPS Gr 1Y</SortTh>
                <SortTh k="earnings_growth_forward" sortKey={sortKey} sortAsc={sortAsc} onClick={toggleSort} align="right">EPS Gr Fwd</SortTh>
                <SortTh k="net_profit_margin" sortKey={sortKey} sortAsc={sortAsc} onClick={toggleSort} align="right">Net Mrgn</SortTh>
                <SortTh k="debt_to_equity" sortKey={sortKey} sortAsc={sortAsc} onClick={toggleSort} align="right">D/E</SortTh>
                <th className="text-center p-2">Lists</th>
                <th className="text-right p-2"></th>
              </tr>
            </thead>
            <tbody>
              {sortedStocks.length ? (
                sortedStocks.map((stock) => {
                  const f = stock.fundamentals;
                  return (
                    <tr key={stock.id} className="border-b border-gray-800/50 hover:bg-gray-800/30">
                      <td className="p-2">
                        <button
                          onClick={() => openStockDetail(stock.symbol, stock.exchange)}
                          className="text-left group"
                        >
                          <div className="font-mono text-xs font-medium group-hover:text-blue-600 transition-colors">{stock.symbol}</div>
                          <div className="text-xs text-gray-500 truncate max-w-[150px]" title={stock.name || ""}>
                            {stock.name || "--"}
                          </div>
                          {stock.reason_tag && (
                            <div className="text-[10px] text-gray-600 mt-0.5">{stock.reason_tag}</div>
                          )}
                        </button>
                      </td>
                      <td className="p-2 text-center">
                        {stock.verdict ? (
                          <span
                            style={
                              stock.verdict === "INVEST"
                                ? { backgroundColor: "rgba(52,199,89,0.08)", color: "#248A3D" }
                                : stock.verdict === "WAIT"
                                  ? { backgroundColor: "rgba(255,204,0,0.08)", color: "#A05A00" }
                                  : { backgroundColor: "rgba(255,59,48,0.08)", color: "#D70015" }
                            }
                            className="text-[11px] font-semibold px-2 py-0.5 rounded-full"
                          >
                            {stock.verdict}
                            {stock.verdict_confidence != null && (
                              <span className="ml-1 opacity-70">{stock.verdict_confidence}%</span>
                            )}
                          </span>
                        ) : (
                          <span className="text-xs text-gray-600">--</span>
                        )}
                      </td>
                      <td className="p-2 text-center">
                        {stock.news_sentiment ? (
                          <SentimentBadge sentiment={stock.news_sentiment} score={stock.news_score} />
                        ) : (
                          <span className="text-xs text-gray-600">--</span>
                        )}
                      </td>
                      <td className="p-2 text-right">{fmtNum(f?.cmp ?? null)}</td>
                      <td className="p-2 text-right text-gray-400">{fmtMoney(f?.market_cap ?? null)}</td>
                      <td className="p-2 text-right">{fmtNum(f?.pe_ratio ?? null)}</td>
                      <td className="p-2 text-right">{fmtNum(f?.ttm_pe ?? null)}</td>
                      <td className="p-2 text-right">{fmtNum(f?.forward_pe ?? null)}</td>
                      <td className="p-2 text-right">{fmtNum(f?.pb_ratio ?? null)}</td>
                      <td className="p-2 text-right">
                        <span className={f?.revenue_growth_1y && f.revenue_growth_1y > 0 ? "text-green-400" : "text-red-400"}>
                          {fmtPct(f?.revenue_growth_1y ?? null)}
                        </span>
                      </td>
                      <td className="p-2 text-right">
                        <span className={f?.eps_growth_1y && f.eps_growth_1y > 0 ? "text-green-400" : "text-red-400"}>
                          {fmtPct(f?.eps_growth_1y ?? null)}
                        </span>
                      </td>
                      <td className="p-2 text-right">
                        <span className={f?.earnings_growth_forward && f.earnings_growth_forward > 0 ? "text-green-400" : "text-red-400"}>
                          {fmtPct(f?.earnings_growth_forward ?? null)}
                        </span>
                      </td>
                      <td className="p-2 text-right">{fmtPct(f?.net_profit_margin ?? null)}</td>
                      <td className="p-2 text-right">{fmtNum(f?.debt_to_equity ?? null)}</td>
                      <td className="p-2 text-center">
                        {stock.in_watchlists && stock.in_watchlists.length > 1 ? (
                          <button
                            onClick={() => setShowMembership(showMembership === stock.symbol ? null : stock.symbol)}
                            className="text-xs bg-blue-900 text-blue-300 px-2 py-0.5 rounded hover:bg-blue-800"
                          >
                            In {stock.in_watchlists.length}
                          </button>
                        ) : (
                          <span className="text-xs text-gray-600">1</span>
                        )}
                        {showMembership === stock.symbol && stock.in_watchlists && (
                          <div className="mt-1 text-xs text-gray-400">
                            {stock.in_watchlists.map((w, i) => (
                              <div key={i} className="italic">{w}</div>
                            ))}
                          </div>
                        )}
                      </td>
                      <td className="p-2 text-right">
                        <button
                          onClick={() => removeStock(stock.id)}
                          className="text-xs text-gray-500 hover:text-red-400 transition-colors"
                        >
                          Remove
                        </button>
                      </td>
                    </tr>
                  );
                })
              ) : (
                <tr>
                  <td colSpan={16} className="text-center py-12 text-gray-600 text-sm">
                    No stocks in this watchlist. Use &quot;Add stock&quot; search or &quot;Upload Stocks&quot; to add stocks.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <div className="p-3 text-xs text-gray-600 border-t border-gray-800">
          Fundamentals from Yahoo Finance (yfinance) — cached 24h. Kite Connect does not provide fundamental data.
        </div>
      </div>
      )}

    </div>
  );
}
