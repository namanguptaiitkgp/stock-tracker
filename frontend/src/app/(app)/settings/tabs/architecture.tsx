"use client";

import SettingsCard from "@/components/settings/SettingsCard";

const SERVICES = [
  {
    name: "Backend (FastAPI)",
    container: "backend-1",
    port: "8000",
    description:
      "The main API server. Serves all REST endpoints — portfolio, watchlists, news, smart money, stock analysis, settings. Runs uvicorn with hot-reload in dev, multi-worker in production.",
    tech: "Python 3.12, FastAPI, SQLAlchemy 2.0 async, Pydantic v2",
    depends: "TimescaleDB, Redis",
  },
  {
    name: "Frontend (Next.js)",
    container: "frontend-1",
    port: "3000",
    description:
      "The web UI. App Router with React 19 server and client components. Communicates with the backend via REST API calls with JWT auth.",
    tech: "Next.js 16, React 19, Tailwind v4, Turbopack",
    depends: "Backend API",
  },
  {
    name: "TimescaleDB",
    container: "timescaledb-1",
    port: "5432",
    description:
      "PostgreSQL with TimescaleDB extension. Stores all persistent data — users, watchlists, holdings metadata, stock fundamentals, news reports, smart-money signals, investment decisions, and the unified fetch cache.",
    tech: "PostgreSQL 16 + TimescaleDB",
    depends: "None (root service)",
  },
  {
    name: "Redis",
    container: "redis-1",
    port: "6379",
    description:
      "In-memory data store used as the Celery task broker and result backend. Queues background jobs and stores task results.",
    tech: "Redis 7 Alpine",
    depends: "None (root service)",
  },
  {
    name: "Celery Worker",
    container: "celery-worker-1",
    port: "—",
    description:
      "Executes background tasks from the Redis queue. Handles the morning pipeline (news scan, sentiment analysis, fundamentals refresh, AI evaluations), smart-money data ingest (bulk/block deals, insider disclosures, bhavcopy), and periodic maintenance (instrument sync, watchlist snapshots, review alerts).",
    tech: "Celery 5 with NullPool (async DB safe)",
    depends: "Redis, TimescaleDB, Backend code",
  },
  {
    name: "Celery Beat",
    container: "celery-beat-1",
    port: "—",
    description:
      "The scheduler. Triggers tasks on a cron schedule — morning pipeline at 10:00 IST Mon-Fri, smart-money ingest at 18:00-19:00 IST, intraday index snapshots every 15 min during market hours, weekly instrument sync, and monthly/quarterly data refreshes.",
    tech: "Celery Beat scheduler",
    depends: "Redis",
  },
  {
    name: "Flower (optional)",
    container: "flower-1",
    port: "5555",
    description:
      "Web-based monitoring dashboard for Celery. Shows active tasks, worker status, task history, and queue lengths. Only runs when started with the monitoring profile — not required for normal operation.",
    tech: "Flower 2.x",
    depends: "Redis, Celery Worker",
  },
];

const DATA_FLOW = [
  {
    title: "Morning Pipeline (10:00 IST, Mon-Fri)",
    steps: [
      "Celery Beat triggers the morning pipeline task",
      "Worker fetches portfolio holdings from Kite (or snapshot if disconnected)",
      "Broad news scan: 18+ RSS feeds + BSE filings aggregated and classified by Gemini",
      "New companies not in your portfolio/watchlists added to \"News Scan\" as opportunities",
      "Per-symbol news sentiment analysis via Google News + Gemini for all held/watched stocks",
      "Fundamentals refreshed from yfinance (bypasses 24h cache)",
      "Kite quotes force-refreshed for live prices",
      "AI investment evaluation (INVEST/WAIT/AVOID) run on every portfolio holding",
      "Dashboard morning brief recomputed and cached",
    ],
  },
  {
    title: "Smart Money Ingest (18:00-19:00 IST daily)",
    steps: [
      "NSE & BSE bulk/block deals fetched and classified (PROP, FII, DII, MF, etc.)",
      "NSE insider disclosures with intra-group transfer detection",
      "NSE bhavcopy (daily price + delivery data)",
      "FII/DII stock-level activity",
      "Corporate announcements",
      "Composite smart-money signal rollup: conviction + flow + red-flag scores per stock",
    ],
  },
  {
    title: "User Request Flow",
    steps: [
      "Browser makes API call via JWT-authenticated fetch",
      "FastAPI handler validates auth, loads user, runs service logic",
      "Services read/write TimescaleDB via async SQLAlchemy sessions",
      "External data (Kite quotes, RSS feeds) served from unified fetch cache (2h TTL)",
      "AI analysis routed through provider abstraction (Gemini Vertex by default)",
      "Response returned as JSON to the frontend",
    ],
  },
];

const EXTERNAL_INTEGRATIONS = [
  { name: "Zerodha Kite Connect", purpose: "Live holdings, quotes, historical data, order placement", auth: "OAuth token (expires daily ~6 AM IST)" },
  { name: "Google Gemini (Vertex AI)", purpose: "Headline classification, sentiment analysis, investment evaluation", auth: "Service account (service_account.json)" },
  { name: "yfinance", purpose: "Stock fundamentals (PE, PB, ROE, revenue growth, etc.)", auth: "None (public API)" },
  { name: "NSE India", purpose: "Insider disclosures, bulk/block deals, bhavcopy, option chains", auth: "None (public scrape)" },
  { name: "BSE India", purpose: "Corporate filings, bulk/block deals, bhavcopy", auth: "None (public API)" },
  { name: "RSS Feeds (18+)", purpose: "News headlines from Hindu BL, Moneycontrol, ET, Mint, Reuters, PIB", auth: "None (public RSS)" },
  { name: "Google News", purpose: "Per-stock headline search for sentiment analysis", auth: "None (public scrape)" },
  { name: "SEBI/AMFI", purpose: "PMS strategies, AIF holdings, mutual fund portfolios (quarterly)", auth: "None (public data)" },
];

export default function ArchitectureTab() {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <SettingsCard
        title="System architecture"
        subtitle="How the services fit together."
      >
        <pre style={{
          margin: 0, fontSize: 11, lineHeight: 1.6,
          fontFamily: "var(--font-mono)",
          color: "var(--label-secondary)",
          whiteSpace: "pre", overflowX: "auto",
        }}>
{`Kite Connect ──┐                              ┌── Frontend (Next.js :3000)
               │                              │
News sources ──┼── Backend FastAPI :8000 ──────┤── OpenAPI at /docs
               │        │                     │
AI provider  ──┘        │── TimescaleDB :5432  └── Flower :5555 (optional)
(Gemini Vertex)         │
                        └── Celery worker + beat (Redis broker :6379)`}
        </pre>
      </SettingsCard>

      <SettingsCard
        title="Docker services"
        subtitle="Each service runs as a container. All except Flower are required."
      >
        {SERVICES.map((s, i) => (
          <div key={s.name} style={{
            padding: "14px 0",
            borderBottom: i < SERVICES.length - 1 ? "1px solid var(--separator-light)" : "none",
          }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
              <span style={{ fontSize: 13, fontWeight: 600, color: "var(--label-primary)" }}>
                {s.name}
              </span>
              <span style={{
                fontSize: 10, fontFamily: "var(--font-mono)",
                padding: "2px 8px", borderRadius: 4,
                background: "var(--fill-secondary)", color: "var(--label-tertiary)",
              }}>
                {s.container} {s.port !== "—" ? `· :${s.port}` : ""}
              </span>
            </div>
            <p style={{ margin: "0 0 6px", fontSize: 12, lineHeight: 1.5, color: "var(--label-secondary)" }}>
              {s.description}
            </p>
            <div style={{ display: "flex", gap: 16, fontSize: 11, color: "var(--label-tertiary)" }}>
              <span><strong>Tech:</strong> {s.tech}</span>
              <span><strong>Depends on:</strong> {s.depends}</span>
            </div>
          </div>
        ))}
      </SettingsCard>

      <SettingsCard
        title="Data flows"
        subtitle="How data moves through the system on key paths."
      >
        {DATA_FLOW.map((flow, fi) => (
          <div key={flow.title} style={{
            padding: "14px 0",
            borderBottom: fi < DATA_FLOW.length - 1 ? "1px solid var(--separator-light)" : "none",
          }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: "var(--label-primary)", marginBottom: 8 }}>
              {flow.title}
            </div>
            <ol style={{ margin: 0, paddingLeft: 20, display: "flex", flexDirection: "column", gap: 4 }}>
              {flow.steps.map((step, si) => (
                <li key={si} style={{ fontSize: 12, lineHeight: 1.5, color: "var(--label-secondary)" }}>
                  {step}
                </li>
              ))}
            </ol>
          </div>
        ))}
      </SettingsCard>

      <SettingsCard
        title="External integrations"
        subtitle="Third-party services the platform connects to."
      >
        {EXTERNAL_INTEGRATIONS.map((int, i) => (
          <div key={int.name} style={{
            display: "flex", justifyContent: "space-between", alignItems: "flex-start",
            padding: "10px 0",
            borderBottom: i < EXTERNAL_INTEGRATIONS.length - 1 ? "1px solid var(--separator-light)" : "none",
            gap: 16,
          }}>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: "var(--label-primary)" }}>{int.name}</div>
              <div style={{ fontSize: 11, color: "var(--label-secondary)", marginTop: 2 }}>{int.purpose}</div>
            </div>
            <span style={{
              fontSize: 10, fontFamily: "var(--font-mono)", whiteSpace: "nowrap",
              padding: "2px 8px", borderRadius: 4, flexShrink: 0,
              background: "var(--fill-secondary)", color: "var(--label-tertiary)",
            }}>
              {int.auth}
            </span>
          </div>
        ))}
      </SettingsCard>

      <SettingsCard
        title="Database"
        subtitle="TimescaleDB (PostgreSQL 16) stores all persistent state."
      >
        <p style={{ margin: "0 0 10px", fontSize: 12, lineHeight: 1.5, color: "var(--label-secondary)" }}>
          All per-user tables cascade-delete with the user. Credentials are Fernet-encrypted at rest.
          The unified fetch cache (2h TTL) deduplicates external API calls across services.
        </p>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
          {[
            "users", "watchlists", "strategies", "investment_decisions",
            "stock_fundamentals", "daily_news_reports", "news_sentiment_cache",
            "smart_money_signals", "bulk_block_deals", "insider_disclosures",
            "fetch_cache", "today_brief_cache", "stocks", "review_alerts",
          ].map((t) => (
            <span key={t} style={{
              fontSize: 10, fontFamily: "var(--font-mono)",
              padding: "3px 8px", borderRadius: 4,
              background: "var(--fill-secondary)", color: "var(--label-tertiary)",
            }}>
              {t}
            </span>
          ))}
          <span style={{ fontSize: 10, color: "var(--label-quaternary)", alignSelf: "center" }}>
            + 35 more tables
          </span>
        </div>
      </SettingsCard>
    </div>
  );
}
