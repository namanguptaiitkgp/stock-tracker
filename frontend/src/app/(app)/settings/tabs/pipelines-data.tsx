"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { fmtRelative } from "@/lib/format";
import { useToast } from "@/lib/use-toast";
import SettingsCard from "@/components/settings/SettingsCard";
import { settingsButtonPrimary, settingsButtonSecondary } from "@/components/settings/SettingsField";
import DataSourcesSection from "@/components/settings/DataSourcesSection";
import { usePipelineStatus } from "@/lib/use-pipeline-status";

/* ── Types ─────────────────────────────────────────────────────── */

interface LastRun {
  status: string;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
}

interface BeatJob {
  id: string;
  task: string;
  schedule_str: string | null;
  schedule_human?: string | null;
  next_run_at: string | null;
  last_run: LastRun | null;
}

interface AISignal {
  id: string;
  name: string;
  refresh_policy: string;
  ttl_seconds: number | null;
  last_run_at: string | null;
  scope: string;
  stale_after_days?: number;
}

interface DataCache {
  id: string;
  name: string;
  ttl_seconds: number | null;
  last_fetched_at: string | null;
}

interface CacheStatus {
  ai_signals: AISignal[];
  data_caches: DataCache[];
  beat_jobs: BeatJob[];
  as_of: string;
}

interface StockListInfo {
  stock_count: number;
  last_sync: string | null;
}

/* ── Constants ─────────────────────────────────────────────────── */

const PIPELINE_STEPS = [
  {
    num: 1,
    title: "Broad news scan + opportunities",
    detail: "Aggregates headlines from all sources via the unified aggregator: Hindu Business Line (7 feeds), Moneycontrol (3 feeds), Economic Times (2 feeds), Mint (2 feeds), Reuters (2 feeds), PIB (1 feed), Google News, and BSE Filings. Gemini Flash-Lite classifies each headline — tagging stock symbols, sentiment (tailwind/headwind/context), and confidence. Companies mentioned that are NOT in your portfolio or watchlists are added to the \"News Scan\" watchlist as new opportunities. Stocks auto-expire after 7 days if not triaged.",
    writes: "daily_news_reports + News Scan watchlist",
  },
  {
    num: 2,
    title: "Per-symbol news sentiment",
    detail: "For every symbol in your portfolio holdings AND watchlist, pulls headlines from all 18 sources (unified aggregator + classifier, filtered for the stock) plus Google News per-stock search (last 7 days, multiple query variants). Headlines are merged and deduped. Gemini analyzes sentiment per stock — bullish/bearish/neutral score from -100 to +100, key themes, per-headline breakdown. Runs 5 symbols concurrently. The stock detail Refresh button triggers the same flow but with a 3-day window.",
    writes: "news_sentiment_cache",
  },
  {
    num: 3,
    title: "Fundamentals refresh",
    detail: "Force-refreshes fundamentals from yfinance for all portfolio + watchlist symbols, bypassing the 24-hour cache. Fallback chain: yfinance → NSE Shareholding Pattern (for promoter_holding) → Gemini AI (for any remaining null key fields). Runs 10 symbols concurrently. Tracks which source provided each field in the data_sources JSONB column.",
    writes: "stock_fundamentals",
  },
  {
    num: 4,
    title: "Kite price refresh",
    detail: "Force-refreshes Kite holdings (bypasses 2-hour cache) and batch-fetches live quotes for all symbols (bypasses 60-second cache). Batched in groups of 50 symbols per Kite API call. Skipped if Kite is not connected.",
    writes: "portfolio_cache (FetchCache)",
  },
  {
    num: 5,
    title: "AI investment evaluation",
    detail: "Runs \"Should I Invest?\" on every portfolio holding. Each evaluation assembles: fresh fundamentals, technicals (Kite historical), smart-money signals (conviction/flow/red-flags), and the just-refreshed news sentiment — then sends a structured prompt to the configured AI provider (Gemini Vertex by default) for an INVEST / AVOID / WAIT verdict with confidence score and reasoning. Runs sequentially to respect LLM rate limits and budget.",
    writes: "investment_decisions",
  },
  {
    num: 0,
    title: "Brief cache refresh",
    detail: "Recomputes the dashboard morning brief with all the fresh data so the next page load reflects the new analysis immediately — no manual refresh needed.",
    writes: "today_brief_cache",
  },
];

const JOB_META: Record<string, { title: string; description: string }> = {
  "pre-open-news-scan": {
    title: "Pre-open news scan",
    description: "08:15 IST (Mon–Fri). Scrapes 18 news sources, classifies headlines by company, and refreshes per-stock sentiment for tagged or stale symbols. Builds the daily news report.",
  },
  "post-close-pipeline": {
    title: "Post-close full pipeline",
    description: "16:00 IST (Mon–Fri). Refreshes fundamentals, runs three-section card analysis (valuation + peers + news) for every holding, evaluates AI verdicts where triggers fire, and rebuilds the dashboard brief cache.",
  },
  "instrument-sync": {
    title: "Instrument sync",
    description: "Refresh NSE/BSE master equity list from Kite instruments API. Required for autocomplete and ticker resolution.",
  },
  "nse-insider-disclosures": {
    title: "NSE Insider disclosures",
    description: "Ingests PIT Regulation 7 / SAST insider trade filings from NSE.",
  },
  "nse-corporate-announcements": {
    title: "Corporate announcements",
    description: "NSE buyback, pledge invoked/released filings. Affects red-flag and flow scoring.",
  },
  "nse-bhavcopy": {
    title: "NSE Bhavcopy",
    description: "Daily OHLC + delivery percentage data from NSE bhavcopy CSV.",
  },
  "fii-dii-stock-daily": {
    title: "FII/DII stock-level activity",
    description: "Per-stock foreign and domestic institutional net flows from NSE. Feeds into flow scoring.",
  },
  "nse-bulk-block-deals": {
    title: "NSE Bulk & Block deals",
    description: "Downloads daily bulk and block deal CSVs from NSE.",
  },
  "bse-bulk-block-deals": {
    title: "BSE Bulk & Block deals",
    description: "Downloads daily bulk and block deal data from BSE API.",
  },
  "smart-money-rollup": {
    title: "Smart Money rollup",
    description: "Aggregates conviction, flow, and red-flag scores across all data sources into composite smart-money signals.",
  },
  "amfi-nav-and-schemes": {
    title: "AMFI NAV & Schemes",
    description: "Daily mutual fund NAV sync from AMFI India.",
  },
  "amfi-monthly-mf-portfolios": {
    title: "AMFI Monthly MF Portfolios",
    description: "Monthly mutual fund portfolio holdings from AMFI XLS files.",
  },
  "sebi-pms-quarterly": {
    title: "SEBI PMS Quarterly",
    description: "Quarterly PMS (Portfolio Management Services) portfolio data from SEBI.",
  },
  "sebi-aif-quarterly": {
    title: "SEBI AIF Quarterly",
    description: "Quarterly AIF (Alternative Investment Fund) data from SEBI.",
  },
  "shareholding-pattern-monthly": {
    title: "Shareholding pattern",
    description: "Quarterly promoter/FII/DII/retail shareholding from NSE XBRL (BSE fallback).",
  },
  "market-indices-quotes": {
    title: "Market indices quotes",
    description: "Live index quotes (Nifty 50, Sensex, Bank Nifty, sectors, VIX, Gift Nifty).",
  },
  "market-indices-summaries": {
    title: "Market indices summaries",
    description: "AI-generated market summary narratives for each index.",
  },
  "watchlist-valuation-snapshot": {
    title: "Watchlist valuation snapshot",
    description: "Daily valuation snapshot for all watchlist stocks after market close.",
  },
  "review-alerts-eval": {
    title: "Review alerts",
    description: "End-of-day evaluation of watch rules, valuation alerts, verdict staleness, and sentiment shifts.",
  },
  "review-alerts-intraday": {
    title: "Intraday alerts",
    description: "Fast rules (single-day drop, price-below) checked during market hours.",
  },
};

const NEWS_INBOX_SOURCES = [
  { name: "Hindu Business Line", feeds: 7, examples: "Markets, Stock Markets, Companies, Portfolio, Economy, Money & Banking, Stock Fundamentals" },
  { name: "Moneycontrol", feeds: 3, examples: "Markets, Top News, Buzzing Stocks" },
  { name: "ET Markets", feeds: 2, examples: "ET Markets, ET Stocks" },
  { name: "Mint", feeds: 2, examples: "Markets, Companies" },
  { name: "Reuters", feeds: 2, examples: "Business, Markets" },
  { name: "Press Information Bureau", feeds: 1, examples: "Government press releases" },
  { name: "Google News", feeds: 0, examples: "Broad Indian market query (Nifty, Sensex)" },
  { name: "BSE Filings", feeds: 0, examples: "Corporate filings via BSE India API (not RSS)" },
];

const NEWS_INBOX_FLOW = [
  { num: 1, title: "RSS aggregation", detail: "Fetches headlines from all 7 RSS source groups concurrently. BSE filings are fetched separately via the BSE India API. All results are merged into a single stream." },
  { num: 2, title: "Deduplication", detail: "Headlines are normalized (lowercase, trimmed to 80 chars) and deduped so the same story from multiple outlets only appears once." },
  { num: 3, title: "Gemini classification", detail: "Headlines are batched (40 per batch) and sent to Gemini Flash-Lite for stock-symbol tagging and sentiment — the model identifies which NSE/BSE-listed companies are mentioned, tags sentiment (tailwind/headwind/context), and assigns confidence. Batching prevents Gemini response truncation on large headline sets." },
  { num: 4, title: "Scope filtering", detail: "Results can be filtered by scope: \"all\" (everything), \"watchlist\" (only stocks on your watchlist), \"holdings\" (only portfolio stocks), or a specific symbol. Source and keyword filters are also available." },
];

const ANALYSIS_STEPS = [
  { num: 1, title: "Data assembly (parallel)", detail: "Fetches fundamentals (yfinance), news sentiment (all 18 RSS sources + Google News per-stock → Gemini), MF activity (AMFI data), and smart-money signals (insider deals, bulk/block trades, delivery patterns) concurrently for the target stock." },
  { num: 2, title: "Technical indicators", detail: "Computes moving averages (20/50/200 DMA), 52-week range, momentum, and relative performance vs Nifty 50 from Kite historical data." },
  { num: 3, title: "Strategy rules evaluation", detail: "Runs the stock through your configured fundamental analysis strategies — checking PE, PB, ROE, margins, debt, and other criteria. Each rule pass/fail feeds into the AI prompt." },
  { num: 4, title: "AI verdict generation", detail: "Assembles all data — fundamentals, technicals, strategy scores, smart-money snapshot, news sentiment, and market context — into a structured prompt. Sends to the configured AI provider (Gemini Vertex by default) for an investment verdict." },
];

/* ── Main Component ────────────────────────────────────────────── */

export default function PipelinesDataTab() {
  const [cacheStatus, setCacheStatus] = useState<CacheStatus | null>(null);
  const [cacheLoading, setCacheLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [stockInfo, setStockInfo] = useState<StockListInfo | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [backfilling, setBackfilling] = useState(false);
  const { toast } = useToast();
  const pipeline = usePipelineStatus();

  // ── Cache status fetch + 60s polling ───────────────────────────
  const loadCacheStatus = useCallback(async () => {
    try {
      setCacheStatus(await api.get<CacheStatus>("/api/system/cache-status"));
    } catch { /* keep last data */ }
    finally { setCacheLoading(false); }
  }, []);

  useEffect(() => {
    loadCacheStatus();
    const id = setInterval(loadCacheStatus, 60_000);
    return () => clearInterval(id);
  }, [loadCacheStatus]);

  // ── Stock info ─────────────────────────────────────────────────
  useEffect(() => {
    api.get<StockListInfo>("/api/stocks/info").then(setStockInfo).catch(() => {});
  }, []);

  // ── Morning pipeline trigger ───────────────────────────────────
  async function runPipeline() {
    try {
      await pipeline.dispatch("full");
      toast({ kind: "ok", text: "Morning pipeline dispatched" });
    } catch (err) {
      toast({ kind: "error", text: err instanceof Error ? err.message : "Failed to start pipeline" });
    }
  }

  async function runCardsRefresh() {
    try {
      await pipeline.dispatch("cards");
      toast({ kind: "ok", text: "Cards refresh dispatched" });
    } catch (err) {
      toast({ kind: "error", text: err instanceof Error ? err.message : "Failed to start cards refresh" });
    }
  }

  // ── Peer backfill trigger ──────────────────────────────────────
  async function backfillPeers() {
    setBackfilling(true);
    try {
      const res = await api.post<{ task_id: string; status: string }>(
        "/api/market-data/peers/backfill",
      );
      toast({
        kind: "ok",
        text: `Peer backfill queued (task ${res.task_id.slice(0, 8)}). Check Celery logs for progress.`,
      });
    } catch (err) {
      toast({ kind: "error", text: err instanceof Error ? err.message : "Backfill failed" });
    } finally {
      setBackfilling(false);
    }
  }

  // ── Stock list sync ────────────────────────────────────────────
  async function doSync() {
    setSyncing(true);
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 120_000);
      const resp = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/stocks/sync`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${localStorage.getItem("algo_trader_token")}`,
          },
          signal: controller.signal,
        },
      );
      clearTimeout(timeoutId);
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.detail || `Sync failed: ${resp.status}`);
      }
      const res = await resp.json();
      toast({ kind: "ok", text: `Synced: ${res.added} new · ${res.total_filtered} total equity` });
      const updated = await api.get<StockListInfo>("/api/stocks/info");
      setStockInfo(updated);
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") {
        toast({ kind: "error", text: "Sync timed out — Kite may be slow, try again" });
      } else {
        toast({ kind: "error", text: err instanceof Error ? err.message : "Sync failed" });
      }
    } finally {
      setSyncing(false);
    }
  }

  // ── Derived: merged job rows ───────────────────────────────────
  // (The legacy "morning-pipeline" filter was removed when commit 33bee5b
  // split it into "pre-open-news-scan" + "post-close-pipeline". Both new
  // IDs render in the table — the dedicated Morning Pipeline card above
  // is a summary, the table is the granular schedule + status source.)
  const jobRows = (cacheStatus?.beat_jobs ?? [])
    .map((j) => ({
      ...j,
      title: JOB_META[j.id]?.title ?? j.id,
      description: JOB_META[j.id]?.description ?? j.task,
    }));

  // ── Render ─────────────────────────────────────────────────────
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {/* ──────── 1. Morning Pipeline ──────── */}
      <SettingsCard
        title="Morning pipeline"
        subtitle="Two jobs daily (Mon–Fri). Pre-open news scan at 08:15 IST tags headlines and refreshes per-stock sentiment for affected symbols. Post-close pipeline at 16:00 IST refreshes data, runs card analysis, and rebuilds the brief."
        actions={
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            {pipeline.running && pipeline.active && (
              <span style={{ fontSize: 11, color: "var(--label-tertiary)", whiteSpace: "nowrap" }}>
                {pipeline.active.source === "morning_pipeline"
                  ? "Pipeline"
                  : pipeline.active.source === "news_scan"
                    ? "News scan"
                    : pipeline.active.source === "cards_refresh"
                      ? "Cards refresh"
                      : "Refresh"}{" "}
                running since {pipeline.active.started_at ? fmtRelative(pipeline.active.started_at) : "now"}
              </span>
            )}
            <button
              onClick={runCardsRefresh}
              disabled={pipeline.running || pipeline.dispatching}
              style={{ ...settingsButtonSecondary, opacity: (pipeline.running || pipeline.dispatching) ? 0.5 : 1, cursor: (pipeline.running || pipeline.dispatching) ? "not-allowed" : "pointer", whiteSpace: "nowrap" }}
              title="Re-runs only the stock-card analysis (valuation + peers + news verdict) for all holdings. Fast (~3 min). Skips news scan, fundamentals, quotes, AI eval."
            >
              Refresh stock cards
            </button>
            <button
              onClick={runPipeline}
              disabled={pipeline.running || pipeline.dispatching}
              style={{ ...settingsButtonPrimary, opacity: (pipeline.running || pipeline.dispatching) ? 0.5 : 1, cursor: (pipeline.running || pipeline.dispatching) ? "not-allowed" : "pointer", whiteSpace: "nowrap" }}
            >
              {pipeline.running ? "Running…" : pipeline.dispatching ? "Dispatching…" : "Run now"}
            </button>
          </div>
        }
      >
        <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
          {PIPELINE_STEPS.map((step, i) => {
            const isLast = i === PIPELINE_STEPS.length - 1;
            return (
              <div key={step.title} style={{ display: "grid", gridTemplateColumns: "32px 1fr", gap: 0 }}>
                <div style={{ display: "flex", flexDirection: "column", alignItems: "center", paddingTop: 1 }}>
                  <span style={{
                    width: 22, height: 22, borderRadius: 99,
                    display: "flex", alignItems: "center", justifyContent: "center",
                    fontSize: 11, fontWeight: 700, fontFamily: "var(--font-mono)",
                    background: step.num === 0 ? "var(--label-quaternary)" : "var(--label-primary)",
                    color: "var(--bg-primary)", flexShrink: 0,
                  }}>{step.num === 0 ? "✓" : step.num}</span>
                  {!isLast && <div style={{ width: 1, flex: 1, minHeight: 12, background: "var(--separator-light)" }} />}
                </div>
                <div style={{ padding: "0 0 14px 8px" }}>
                  <div style={{ fontSize: 13, fontWeight: 600, color: "var(--label-primary)" }}>{step.title}</div>
                  <div style={{ fontSize: 12, color: "var(--label-secondary)", lineHeight: 1.5, marginTop: 3 }}>{step.detail}</div>
                  <div style={{ display: "inline-flex", alignItems: "center", gap: 4, marginTop: 5 }}>
                    <span style={{ fontSize: 10, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em", color: "var(--label-quaternary)" }}>Writes to</span>
                    <span style={{ fontSize: 11, fontFamily: "var(--font-mono)", padding: "1px 6px", borderRadius: 4, background: "var(--fill-secondary)", color: "var(--label-secondary)" }}>{step.writes}</span>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
        <div style={{ padding: "10px 14px", background: "var(--fill-secondary)", borderRadius: 8, fontSize: 12, color: "var(--label-secondary)", lineHeight: 1.5 }}>
          <strong style={{ color: "var(--label-primary)" }}>Scope:</strong> portfolio holdings + all watchlist symbols (including News Scan).
          Each step is fault-tolerant — a failure on one symbol logs a warning and continues to the next.
          The dashboard Refresh button runs a lighter refresh (fundamentals + Kite prices + AI evaluation only).
          New opportunities are added to a system-managed &ldquo;News Scan&rdquo; watchlist — triage them on the News tab.
        </div>
      </SettingsCard>

      {/* ──────── 1a. Activity monitor link ──────── */}
      <SettingsCard
        title="Live activity monitor"
        subtitle="Live Celery tasks, LLM cost per purpose, scrape success rates, and recent ingestion runs — all on one page, polled every 10 seconds."
        actions={
          <a
            href="/admin/monitor"
            style={{ ...settingsButtonSecondary, textDecoration: "none", whiteSpace: "nowrap" }}
          >
            Open monitor →
          </a>
        }
      >
        <div style={{ padding: "10px 14px", background: "var(--fill-secondary)", borderRadius: 8, fontSize: 12, color: "var(--label-secondary)", lineHeight: 1.5 }}>
          Audits every Gemini call and every external scrape. Useful for spotting runaway LLM spend, broken scrape sources, or tasks that hang.
        </div>
      </SettingsCard>

      {/* ──────── 1b. Peer backfill ──────── */}
      <SettingsCard
        title="Peer set backfill"
        subtitle="One-shot job that generates Gemini-curated peer sets for every holding and watchlist symbol that's missing one. The morning pipeline now auto-seeds peers, but this catches the existing backlog in one go."
        actions={
          <button
            onClick={backfillPeers}
            disabled={backfilling}
            style={{ ...settingsButtonPrimary, opacity: backfilling ? 0.5 : 1, cursor: backfilling ? "not-allowed" : "pointer" }}
          >
            {backfilling ? "Queueing…" : "Backfill missing peers"}
          </button>
        }
      >
        <div style={{ padding: "10px 14px", background: "var(--fill-secondary)", borderRadius: 8, fontSize: 12, color: "var(--label-secondary)", lineHeight: 1.5 }}>
          <strong style={{ color: "var(--label-primary)" }}>Cost:</strong> ~1 Gemini Flash call per missing symbol (cheap). Concurrent generation is capped at 3 at a time. Symbols with no industry/sector in <code>stock_fundamentals</code> are skipped — refresh fundamentals first.
        </div>
      </SettingsCard>

      {/* ──────── 2. Scheduled Jobs ──────── */}
      <SettingsCard
        title="Scheduled jobs"
        subtitle="All automated beat jobs with live status from the ingestion log."
        actions={
          <button
            onClick={async () => { setRefreshing(true); await loadCacheStatus(); setRefreshing(false); }}
            disabled={refreshing}
            style={{ ...settingsButtonSecondary, padding: "5px 10px", fontSize: 12, opacity: refreshing ? 0.5 : 1 }}
          >
            {refreshing ? "↻…" : "↻ Reload"}
          </button>
        }
      >
        {cacheLoading && !cacheStatus ? (
          <div style={{ fontSize: 12, color: "var(--label-tertiary)" }}>Loading…</div>
        ) : jobRows.length === 0 ? (
          <div style={{ fontSize: 12, color: "var(--label-tertiary)", fontStyle: "italic" }}>No beat jobs registered.</div>
        ) : (
          <MiniTable
            headers={["Job", "Schedule (IST)", "Next run", "Last run", "Status"]}
            widths={["1fr", "140px", "100px", "100px", "110px"]}
          >
            {jobRows.map((j) => (
              <div key={j.id} style={{ ...gridRow, borderTop: "1px solid var(--separator-light)" }}>
                <div style={{ padding: "7px 8px 7px 0", minWidth: 0 }}>
                  <div style={{ fontSize: 12, fontWeight: 600, color: "var(--label-primary)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={j.title}>{j.title}</div>
                  <div style={{ fontSize: 10, color: "var(--label-quaternary)", marginTop: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={j.description}>{j.description}</div>
                </div>
                <div
                  style={{
                    ...cellMono,
                    fontSize: 10,
                    minWidth: 0,
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                  title={`${j.schedule_str || "—"}  ·  ${j.task}`}
                >
                  {j.schedule_human || j.schedule_str || "—"}
                </div>
                <div style={cellMuted}>{j.next_run_at ? fmtRelative(j.next_run_at) : "—"}</div>
                <div style={cellMuted}>
                  {j.last_run?.finished_at
                    ? fmtRelative(j.last_run.finished_at)
                    : j.last_run?.started_at
                      ? "running…"
                      : "—"}
                </div>
                <div style={{ padding: "7px 0" }}>
                  {j.last_run ? <StatusPill status={j.last_run.status} durationMs={j.last_run.duration_ms} /> : null}
                </div>
              </div>
            ))}
          </MiniTable>
        )}
      </SettingsCard>

      {/* ──────── 3. Data Sources ──────── */}
      <DataSourcesSection />

      {/* ──────── 4. Cache & Signal Status ──────── */}
      <SettingsCard
        title="Cache & signal status"
        subtitle="What refreshes when, and what’s cached how long."
      >
        {!cacheStatus ? (
          <div style={{ fontSize: 12, color: "var(--label-tertiary)" }}>Loading…</div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            <SubCard title="AI signals" subtitle="Manual refresh — no automated cron unless noted">
              <SimpleTable headers={["Signal", "Refresh", "TTL", "Last run", "Scope"]}>
                {cacheStatus.ai_signals.map((s) => (
                  <tr key={s.id} style={rowStyle}>
                    <td style={cellPrimary}>{s.name}</td>
                    <td style={{ ...cellMuted, textTransform: "capitalize" }}>
                      {s.refresh_policy}{s.stale_after_days ? ` · stale after ${s.stale_after_days}d` : ""}
                    </td>
                    <td style={cellMonoTd}>{fmtTtl(s.ttl_seconds)}</td>
                    <td style={cellMuted}>{s.last_run_at ? fmtRelative(s.last_run_at) : "—"}</td>
                    <td style={{ ...cellMuted, fontSize: 11 }}>{s.scope}</td>
                  </tr>
                ))}
              </SimpleTable>
            </SubCard>
            <SubCard title="Data caches" subtitle="Survives backend restarts via the unified fetch_cache table">
              <SimpleTable headers={["Source", "TTL", "Last refresh"]}>
                {cacheStatus.data_caches.map((c) => (
                  <tr key={c.id} style={rowStyle}>
                    <td style={cellPrimary}>{c.name}</td>
                    <td style={cellMonoTd}>{fmtTtl(c.ttl_seconds)}</td>
                    <td style={cellMuted}>{c.last_fetched_at ? fmtRelative(c.last_fetched_at) : "—"}</td>
                  </tr>
                ))}
              </SimpleTable>
            </SubCard>
          </div>
        )}
      </SettingsCard>

      {/* ──────── 5. Stock List ──────── */}
      <SettingsCard
        title="Stock list (NSE/BSE)"
        subtitle="Master equity list pulled from Kite. Required for autocomplete and ticker resolution."
        actions={
          <button onClick={doSync} disabled={syncing} style={{ ...settingsButtonPrimary, opacity: syncing ? 0.5 : 1 }}>
            {syncing ? "Syncing…" : stockInfo?.stock_count ? "Refresh list" : "Sync now"}
          </button>
        }
      >
        <div style={{ display: "flex", alignItems: "center", gap: 16, flexWrap: "wrap" }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
            <span style={statLabel}>Stocks in database</span>
            <span style={statValue}>{stockInfo ? stockInfo.stock_count.toLocaleString() : "—"}</span>
          </div>
          <div style={{ width: 1, height: 28, background: "var(--separator-light)" }} />
          <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
            <span style={statLabel}>Last synced</span>
            <span style={statValue}>
              {stockInfo?.last_sync ? new Date(stockInfo.last_sync).toLocaleDateString("en-IN", { dateStyle: "medium" }) : "Never"}
            </span>
          </div>
        </div>
      </SettingsCard>

      {/* ──────── 6. Reference: News Inbox ──────── */}
      <CollapsibleCard
        title="Reference: News Inbox"
        subtitle="The News tab (left column). Shares the same unified news fetch and classifier as the morning pipeline."
      >
        <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
          {NEWS_INBOX_FLOW.map((step, i) => (
            <div key={step.title} style={{ display: "grid", gridTemplateColumns: "32px 1fr", gap: 0 }}>
              <div style={{ display: "flex", flexDirection: "column", alignItems: "center", paddingTop: 1 }}>
                <span style={stepCircle}>{step.num}</span>
                {i < NEWS_INBOX_FLOW.length - 1 && <div style={stepLine} />}
              </div>
              <div style={{ padding: "0 0 14px 8px" }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: "var(--label-primary)" }}>{step.title}</div>
                <div style={{ fontSize: 12, color: "var(--label-secondary)", lineHeight: 1.5, marginTop: 3 }}>{step.detail}</div>
              </div>
            </div>
          ))}
        </div>

        <div style={{ border: "1px solid var(--separator-light)", borderRadius: 8, overflow: "hidden" }}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 50px 1fr", padding: "8px 12px", background: "var(--fill-secondary)", fontSize: 10, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em", color: "var(--label-quaternary)" }}>
            <span>Source</span>
            <span style={{ textAlign: "center" }}>Feeds</span>
            <span>Coverage</span>
          </div>
          {NEWS_INBOX_SOURCES.map((src) => (
            <div key={src.name} style={{ display: "grid", gridTemplateColumns: "1fr 50px 1fr", padding: "8px 12px", borderTop: "1px solid var(--separator-light)", fontSize: 12 }}>
              <span style={{ fontWeight: 600, color: "var(--label-primary)" }}>{src.name}</span>
              <span style={{ textAlign: "center", fontFamily: "var(--font-mono)", color: "var(--label-secondary)" }}>{src.feeds || "API"}</span>
              <span style={{ color: "var(--label-tertiary)", fontSize: 11 }}>{src.examples}</span>
            </div>
          ))}
        </div>

        <div style={{ padding: "10px 14px", background: "var(--fill-secondary)", borderRadius: 8, fontSize: 12, color: "var(--label-secondary)", lineHeight: 1.5, display: "flex", flexDirection: "column", gap: 6 }}>
          <div><strong style={{ color: "var(--label-primary)" }}>Cache:</strong> 2-hour TTL via fetch_cache. Subsequent page loads within the window are instant.</div>
          <div><strong style={{ color: "var(--label-primary)" }}>Refresh:</strong> The News Inbox refresh button clears all RSS caches and re-fetches from every source. The dashboard Refresh button also triggers a re-fetch after the pipeline completes.</div>
          <div><strong style={{ color: "var(--label-primary)" }}>Search:</strong> Custom keyword search queries Google News RSS directly — results bypass the aggregator and are not cached.</div>
        </div>

        <div style={{ padding: "14px", background: "var(--bg-secondary)", border: "1px solid var(--separator-light)", borderRadius: 8, fontSize: 12, color: "var(--label-secondary)", lineHeight: 1.6 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: "var(--label-primary)", marginBottom: 10 }}>News Refresh for Portfolio Stocks</div>
          <div style={{ marginBottom: 8 }}>
            When refreshing news sentiment for a portfolio stock (e.g. <strong style={{ color: "var(--label-primary)" }}>INDIGO</strong> / InterGlobe Aviation), the system runs two parallel paths and merges the results:
          </div>
          <div style={{ padding: "10px 12px", borderRadius: 6, background: "var(--fill-secondary)", marginBottom: 8 }}>
            <div style={{ fontWeight: 600, color: "var(--label-primary)", marginBottom: 4 }}>Path 1: Unified Aggregator (18 sources)</div>
            <div style={{ marginBottom: 4 }}>
              Reuses cached headlines (2h TTL) from the unified aggregator &mdash; does <em>not</em> re-scrape all 18 sources on each stock refresh. If the cache is warm from the morning pipeline or a recent News tab visit, this step is instant. Gemini then classifies each headline in batches of 40, tagging which NSE/BSE stocks are mentioned. Finally, filters for headlines where Gemini tagged &ldquo;INDIGO&rdquo;.
            </div>
            <div style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--label-tertiary)" }}>
              ~200 headlines fetched &rarr; Gemini tags stocks &rarr; 2-5 headlines mention INDIGO
            </div>
          </div>
          <div style={{ padding: "10px 12px", borderRadius: 6, background: "var(--fill-secondary)", marginBottom: 8 }}>
            <div style={{ fontWeight: 600, color: "var(--label-primary)", marginBottom: 4 }}>Path 2: Google News per-stock search</div>
            <div style={{ marginBottom: 4 }}>Runs targeted Google News RSS queries specifically for the stock:</div>
            <div style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--label-tertiary)", display: "flex", flexDirection: "column", gap: 2 }}>
              <span>1. &ldquo;INDIGO share price&rdquo; when:7d</span>
              <span>2. &ldquo;InterGlobe Aviation share price&rdquo; when:7d</span>
              <span>3. &ldquo;InterGlobe Aviation Ltd&rdquo; stock when:7d</span>
            </div>
            <div style={{ marginTop: 4, fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--label-tertiary)" }}>~15-25 headlines specifically about INDIGO</div>
          </div>
          <div style={{ padding: "10px 12px", borderRadius: 6, background: "var(--fill-secondary)", marginBottom: 8 }}>
            <div style={{ fontWeight: 600, color: "var(--label-primary)", marginBottom: 4 }}>Merge &amp; Analyze</div>
            <div>Both sets are merged, deduped by title, sorted newest-first, and capped at 30 headlines. Sent to Gemini for sentiment analysis — returns a score (-100 to +100), summary, key themes, and per-headline sentiment + impact.</div>
          </div>
          <div style={{ fontSize: 11, color: "var(--label-tertiary)", fontStyle: "italic" }}>
            Path 1 is better for high-profile stocks (Reliance, HDFC Bank, TCS) that appear frequently in general news. Path 2 provides targeted coverage for all stocks including mid-caps. Together they give the broadest view.
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 8, marginTop: 10, fontSize: 11 }}>
            <div style={{ padding: "6px 8px", borderRadius: 6, background: "var(--fill-secondary)", textAlign: "center" }}>
              <div style={{ fontWeight: 600, color: "var(--label-primary)" }}>Pipeline</div>
              <div style={{ color: "var(--label-tertiary)", fontFamily: "var(--font-mono)" }}>7 days</div>
            </div>
            <div style={{ padding: "6px 8px", borderRadius: 6, background: "var(--fill-secondary)", textAlign: "center" }}>
              <div style={{ fontWeight: 600, color: "var(--label-primary)" }}>Page load</div>
              <div style={{ color: "var(--label-tertiary)", fontFamily: "var(--font-mono)" }}>from cache</div>
            </div>
            <div style={{ padding: "6px 8px", borderRadius: 6, background: "var(--fill-secondary)", textAlign: "center" }}>
              <div style={{ fontWeight: 600, color: "var(--label-primary)" }}>Manual refresh</div>
              <div style={{ color: "var(--label-tertiary)", fontFamily: "var(--font-mono)" }}>3 days</div>
            </div>
          </div>
        </div>
      </CollapsibleCard>

      {/* ──────── 7. Reference: Run Analysis ──────── */}
      <CollapsibleCard
        title="Reference: Run Analysis"
        subtitle="On-demand per-stock analysis triggered from the stock detail page. Not a scheduled job — runs when you click the button."
      >
        <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
          {ANALYSIS_STEPS.map((step, i) => (
            <div key={step.title} style={{ display: "grid", gridTemplateColumns: "32px 1fr", gap: 0 }}>
              <div style={{ display: "flex", flexDirection: "column", alignItems: "center", paddingTop: 1 }}>
                <span style={stepCircle}>{step.num}</span>
                {i < ANALYSIS_STEPS.length - 1 && <div style={stepLine} />}
              </div>
              <div style={{ padding: "0 0 14px 8px" }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: "var(--label-primary)" }}>{step.title}</div>
                <div style={{ fontSize: 12, color: "var(--label-secondary)", lineHeight: 1.5, marginTop: 3 }}>{step.detail}</div>
              </div>
            </div>
          ))}
        </div>
        <div style={{ padding: "10px 14px", background: "var(--fill-secondary)", borderRadius: 8, fontSize: 12, color: "var(--label-secondary)", lineHeight: 1.5 }}>
          <strong style={{ color: "var(--label-primary)" }}>Result:</strong> Returns an INVEST / WAIT / AVOID verdict with a confidence score (0–100), reasoning, entry recommendation (price levels + time horizon), key risks, and action items. The verdict is saved to <span style={{ fontFamily: "var(--font-mono)", fontSize: 11 }}>investment_decisions</span> and shown in the stock detail panel.
        </div>
      </CollapsibleCard>
    </div>
  );
}

/* ── Helper Components ─────────────────────────────────────────── */

function StatusPill({ status, durationMs }: { status: string; durationMs: number | null }) {
  const color =
    status === "success" ? "#34c759"
    : status === "partial" ? "#ff9f0a"
    : status === "failed" ? "#ff3b30"
    : status === "running" ? "#5ac8fa"
    : "var(--label-tertiary)";
  const label = status === "success" ? "OK" : status.charAt(0).toUpperCase() + status.slice(1);
  const dur = durationMs != null ? (durationMs >= 60000 ? `${(durationMs / 60000).toFixed(1)}m` : `${(durationMs / 1000).toFixed(1)}s`) : null;
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 4, fontSize: 11 }}>
      <span style={{ display: "inline-block", width: 7, height: 7, borderRadius: 99, background: color, flexShrink: 0 }} />
      <span style={{ color, fontWeight: 600 }}>{label}</span>
      {dur && <span style={{ color: "var(--label-quaternary)", fontFamily: "var(--font-mono)", fontSize: 10 }}>{dur}</span>}
    </span>
  );
}

function SubCard({ title, subtitle, children }: { title: string; subtitle?: string; children: React.ReactNode }) {
  return (
    <div style={{ border: "1px solid var(--separator-light)", borderRadius: 10, background: "var(--bg-secondary)", overflow: "hidden" }}>
      <div style={{ padding: "10px 14px", borderBottom: "1px solid var(--separator-light)" }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: "var(--label-primary)" }}>{title}</div>
        {subtitle && <div style={{ fontSize: 11, color: "var(--label-tertiary)", marginTop: 1 }}>{subtitle}</div>}
      </div>
      <div style={{ padding: "8px 14px 12px" }}>{children}</div>
    </div>
  );
}

function SimpleTable({ headers, children }: { headers: string[]; children: React.ReactNode }) {
  return (
    <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
      <thead>
        <tr>
          {headers.map((h) => (
            <th key={h} style={{ textAlign: "left", padding: "6px 12px 6px 0", fontSize: 10, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--label-tertiary)" }}>
              {h}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>{children}</tbody>
    </table>
  );
}

function MiniTable({ headers, widths, children }: { headers: string[]; widths: string[]; children: React.ReactNode }) {
  const cols = widths.join(" ");
  return (
    <div>
      <div style={{ display: "grid", gridTemplateColumns: cols, fontSize: 10, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--label-tertiary)", padding: "6px 0" }}>
        {headers.map((h) => <span key={h}>{h}</span>)}
      </div>
      {children}
    </div>
  );
}

function CollapsibleCard({ title, subtitle, children }: { title: string; subtitle?: string; children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <SettingsCard
      title={title}
      subtitle={subtitle}
      actions={
        <button
          onClick={() => setOpen(!open)}
          style={{ ...settingsButtonSecondary, padding: "5px 10px", fontSize: 12 }}
        >
          {open ? "Collapse" : "Expand"}
        </button>
      }
    >
      {open ? children : null}
    </SettingsCard>
  );
}

/* ── Styles ─────────────────────────────────────────────────────── */

function fmtTtl(s: number | null): string {
  if (s == null) return "—";
  if (s >= 86400) return `${Math.round(s / 86400)} d`;
  if (s >= 3600) return `${Math.round(s / 3600)} h`;
  if (s >= 60) return `${Math.round(s / 60)} m`;
  return `${s} s`;
}

const gridRow: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "1fr 140px 100px 100px 110px",
  alignItems: "center",
};

const rowStyle: React.CSSProperties = { borderTop: "1px solid var(--separator-light)" };
const cellPrimary: React.CSSProperties = { padding: "7px 12px 7px 0", color: "var(--label-primary)" };
const cellMuted: React.CSSProperties = { padding: "7px 8px 7px 0", color: "var(--label-tertiary)", fontSize: 11 };
const cellMonoTd: React.CSSProperties = { padding: "7px 12px 7px 0", color: "var(--label-tertiary)", fontFamily: "var(--font-mono)" };
const cellMono: React.CSSProperties = { padding: "7px 8px 7px 0", color: "var(--label-tertiary)", fontFamily: "var(--font-mono)", whiteSpace: "nowrap" };

const statLabel: React.CSSProperties = { fontSize: 11, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--label-tertiary)" };
const statValue: React.CSSProperties = { fontSize: 18, fontFamily: "var(--font-serif)", fontWeight: 600, color: "var(--label-primary)" };

const stepCircle: React.CSSProperties = {
  width: 22, height: 22, borderRadius: 99,
  display: "flex", alignItems: "center", justifyContent: "center",
  fontSize: 11, fontWeight: 700, fontFamily: "var(--font-mono)",
  background: "var(--label-primary)", color: "var(--bg-primary)", flexShrink: 0,
};
const stepLine: React.CSSProperties = { width: 1, flex: 1, minHeight: 12, background: "var(--separator-light)" };
