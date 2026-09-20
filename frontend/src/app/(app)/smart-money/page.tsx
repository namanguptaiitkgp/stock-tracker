"use client";

/**
 * /smart-money — daily-action page (addendum §A2 redesign).
 *
 * Top:    ActionSummary three cards (Accumulation / Distribution / Avoid).
 * Middle: Expandable sections — insider, sharks, net positions, red flags,
 *         data freshness. Collapsed by default; counts on the chip.
 * Bottom: Explore links to deep-dive sub-pages and the deal analyzer.
 *
 * The old monolithic layout (top-positive/negative composite, top active
 * traders, curated sharks) is now reachable via the expandable
 * "Net Positions" section and the Explore footer.
 */

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { fmtTradingDay } from "@/lib/format";
import ActionSummaryCard, { ActionSummaryRow } from "@/components/common/ActionSummaryCard";
import HoldingsSignalTable, { HoldingSignalRow } from "@/components/common/HoldingsSignalTable";
import NotableInsiderTable, { NotableInsiderRow } from "@/components/common/NotableInsiderTable";
import NetTradersTable, { NetTraderRow } from "@/components/common/NetTradersTable";

interface ActionSummary {
  as_of: string | null;
  accumulation: ActionSummaryRow[];
  distribution: ActionSummaryRow[];
  avoid: ActionSummaryRow[];
}

interface SourceRunRow {
  source: string;
  last_success_at: string | null;
  last_run_status: string | null;
  cadence_hours: number;
  stale: boolean;
}

interface RedFlagRow {
  symbol: string;
  red_flag_score: number;
  triggered: string[];
  detail: Record<string, { penalty?: number; pledge_pct?: number; pct_change_20d?: number; suspects?: string[] }>;
}

interface SharkRow {
  canonical_name: string;
  display_name: string;
  deal_count: number;
}

const RED_FLAG_LABEL: Record<string, string> = {
  circular_trading: "Circular trading",
  pump_pattern: "Pump pattern",
  promoter_selling: "Promoter selling",
  high_pledge: "High pledge",
  pledge_invocation: "Pledge invocation",
};

const CRITICAL_SOURCES = new Set(["nse_deals", "nse_bhavcopy", "nse_insider"]);

export default function SmartMoneyPage() {
  const [summary, setSummary] = useState<ActionSummary | null>(null);
  const [insider, setInsider] = useState<NotableInsiderRow[]>([]);
  const [traders, setTraders] = useState<NetTraderRow[]>([]);
  const [redFlags, setRedFlags] = useState<RedFlagRow[]>([]);
  const [sharks, setSharks] = useState<SharkRow[]>([]);
  const [runs, setRuns] = useState<SourceRunRow[]>([]);
  const [holdings, setHoldings] = useState<HoldingSignalRow[]>([]);
  const [holdingCounts, setHoldingCounts] = useState<Record<string, number>>({});
  const [showBrokers, setShowBrokers] = useState(false);
  const [loading, setLoading] = useState(true);
  const [holdingsLoading, setHoldingsLoading] = useState(true);
  const [openSection, setOpenSection] = useState<string | null>("insider");

  // Re-fetch traders when the broker toggle flips
  useEffect(() => {
    const url = `/api/smart-money/net-traders?days=30&limit=30${showBrokers ? "&show_brokers=true" : ""}`;
    api.get<{ rows: NetTraderRow[] }>(url).then((r) => setTraders(r.rows || [])).catch(() => setTraders([]));
  }, [showBrokers]);

  useEffect(() => {
    Promise.all([
      api.get<ActionSummary>("/api/smart-money/action-summary").catch(() => null),
      api.get<{ rows: NotableInsiderRow[] }>("/api/smart-money/notable-insider?days=14&limit=50").catch(() => ({ rows: [] })),
      api.get<{ rows: RedFlagRow[] }>("/api/smart-money/red-flags?min_severity=20").catch(() => ({ rows: [] })),
      api.get<{ sharks: SharkRow[] }>("/api/smart-money/sharks?only_with_deals=true").catch(() => ({ sharks: [] })),
      api.get<{ sources: SourceRunRow[] }>("/api/smart-money/runs/latest").catch(() => ({ sources: [] })),
    ]).then(([sum, ins, rf, sh, runsResp]) => {
      setSummary(sum);
      setInsider((ins as { rows: NotableInsiderRow[] }).rows);
      setRedFlags((rf as { rows: RedFlagRow[] }).rows);
      setSharks((sh as { sharks: SharkRow[] }).sharks);
      setRuns((runsResp as { sources: SourceRunRow[] }).sources);
      setLoading(false);
    });

    // Holdings signals — separate fetch because it's the only one that
    // needs Kite credentials and can take a couple of seconds.
    api
      .get<{ rows: HoldingSignalRow[]; counts: Record<string, number> }>(
        "/api/smart-money/holdings-signals",
      )
      .then((d) => {
        setHoldings(d.rows || []);
        setHoldingCounts(d.counts || {});
        setHoldingsLoading(false);
      })
      .catch(() => {
        setHoldings([]);
        setHoldingsLoading(false);
      });
  }, []);

  const criticalStale = useMemo(
    () => runs.some((s) => CRITICAL_SOURCES.has(s.source) && s.stale),
    [runs],
  );
  const directionalSharks = useMemo(
    () => traders.filter((t) => t.is_known_shark).slice(0, 5),
    [traders],
  );

  return (
    <div className="sm-page" style={{ padding: "32px 40px", maxWidth: 1200, margin: "0 auto" }}>
      <header className="sm-header" style={{ marginBottom: 24, display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 16 }}>
        <div>
          <h1 style={{ fontFamily: "var(--font-serif)", fontSize: 30, fontWeight: 600, letterSpacing: "-0.02em", margin: 0 }}>
            Smart Money
          </h1>
          <p style={{ fontSize: 13, color: "var(--label-tertiary)", marginTop: 4, marginBottom: 0 }}>
            Where institutional flows are putting money.{" "}
            {summary?.as_of && (
              <span style={{ fontFamily: "var(--font-mono)" }}>· {fmtTradingDay(summary.as_of)}</span>
            )}
          </p>
        </div>
        <Link
          href="/smart-money/analyzer"
          style={{
            padding: "8px 14px",
            borderRadius: 8,
            background: "var(--label-primary)",
            color: "var(--bg-primary)",
            fontSize: 12,
            fontWeight: 600,
            textDecoration: "none",
            whiteSpace: "nowrap",
          }}
        >
          Deal Analyzer →
        </Link>
      </header>
      <style jsx>{`
        @media (max-width: 720px) {
          .sm-page { padding: 20px 16px !important; }
          .sm-header {
            flex-direction: column !important;
            align-items: flex-start !important;
            gap: 12px !important;
          }
        }
      `}</style>

      {/* Critical-source stale warning */}
      {criticalStale && (
        <div
          style={{
            marginBottom: 16,
            padding: "8px 12px",
            borderRadius: 8,
            background: "var(--review-bg, rgba(255,149,0,0.08))",
            border: "1px solid var(--review-edge, rgba(255,149,0,0.2))",
            fontSize: 12,
            color: "var(--review)",
          }}
        >
          ⚠ A critical data source is stale. Check &ldquo;Data Freshness&rdquo; below.
        </div>
      )}

      {/* 0. YOUR HOLDINGS — per-holding ADD/HOLD/TRIM/REVIEW/NO_SIGNAL.
          Surfaced ABOVE the Action Summary because for an existing
          long-term portfolio "what should I do with what I own" is the
          first question; "what new stocks are interesting" is second. */}
      <section style={{ marginBottom: 28 }}>
        <h2
          style={{
            margin: 0,
            marginBottom: 12,
            fontSize: 14,
            fontWeight: 600,
            textTransform: "uppercase",
            letterSpacing: "0.06em",
            color: "var(--label-tertiary)",
          }}
        >
          Your Holdings ({holdings.length})
        </h2>
        <HoldingsSignalTable
          rows={holdings}
          counts={holdingCounts}
          loading={holdingsLoading}
        />
      </section>

      {/* 1. ACTION SUMMARY (discovery) */}
      <section style={{ marginBottom: 32 }}>
        <h2
          style={{
            margin: 0,
            marginBottom: 12,
            fontSize: 14,
            fontWeight: 600,
            textTransform: "uppercase",
            letterSpacing: "0.06em",
            color: "var(--label-tertiary)",
          }}
        >
          Discovery
        </h2>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit,minmax(300px,1fr))",
            gap: 14,
          }}
        >
          <ActionSummaryCard kind="accumulation" rows={summary?.accumulation || []} loading={loading} />
          <ActionSummaryCard kind="distribution" rows={summary?.distribution || []} loading={loading} />
          <ActionSummaryCard kind="avoid" rows={summary?.avoid || []} loading={loading} />
        </div>
      </section>

      {/* 2. SIGNAL DETAIL — expandable sections */}
      <section style={{ marginBottom: 32, display: "flex", flexDirection: "column", gap: 8 }}>
        <ExpandableSection
          id="insider"
          title="Insider Activity"
          count={insider.length}
          countSuffix="notable in 14d"
          openId={openSection}
          onToggle={setOpenSection}
        >
          <NotableInsiderTable rows={insider} />
        </ExpandableSection>

        <ExpandableSection
          id="sharks"
          title="Shark Trades"
          count={directionalSharks.length}
          countSuffix={`tracked HNI${directionalSharks.length === 1 ? "" : "s"} active`}
          openId={openSection}
          onToggle={setOpenSection}
        >
          {directionalSharks.length === 0 ? (
            <div style={{ fontSize: 12, color: "var(--label-tertiary)", padding: "4px 0", fontStyle: "italic" }}>
              No tracked-shark directional trades in the last 30 days.{" "}
              {sharks.length > 0 && (
                <>The {sharks.length} sharks with any deals are listed in Explore → All Active Traders.</>
              )}
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {directionalSharks.map((t) => (
                <Link
                  key={t.client_name_norm}
                  href={`/smart-money/shark/${encodeURIComponent(t.display_name)}`}
                  style={{
                    padding: "8px 12px",
                    fontSize: 12,
                    background: "var(--bg-primary)",
                    border: "1px solid var(--separator-light)",
                    borderRadius: 6,
                    color: "var(--label-primary)",
                    textDecoration: "none",
                    display: "flex",
                    justifyContent: "space-between",
                  }}
                >
                  <span style={{ fontWeight: 600 }}>{t.display_name}</span>
                  <span
                    style={{
                      color: t.net_value_inr >= 0 ? "var(--buy)" : "var(--act)",
                      fontFamily: "var(--font-mono)",
                      fontWeight: 700,
                    }}
                  >
                    {t.net_value_inr >= 0 ? "+" : "-"}Rs {(Math.abs(t.net_value_inr) / 1e7).toFixed(1)} Cr
                    <span style={{ marginLeft: 6, color: "var(--label-tertiary)", fontWeight: 400 }}>
                      · {Math.round(t.net_to_total_ratio * 100)}%
                    </span>
                  </span>
                </Link>
              ))}
            </div>
          )}
        </ExpandableSection>

        <ExpandableSection
          id="net-positions"
          title="Net Positions — Who's Actually Buying"
          count={traders.length}
          countSuffix="directional"
          openId={openSection}
          onToggle={setOpenSection}
        >
          <NetTradersTable rows={traders} showBrokers={showBrokers} onToggleBrokers={setShowBrokers} />
        </ExpandableSection>

        <ExpandableSection
          id="red-flags"
          title="Red Flags"
          count={redFlags.length}
          countSuffix="active"
          openId={openSection}
          onToggle={setOpenSection}
        >
          {redFlags.length === 0 ? (
            <div style={{ fontSize: 12, color: "var(--label-tertiary)", fontStyle: "italic" }}>
              No active red flags.
            </div>
          ) : (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(280px,1fr))", gap: 10 }}>
              {redFlags.map((r) => (
                <Link
                  key={r.symbol}
                  href={`/researching?symbol=${r.symbol}`}
                  style={{
                    padding: 12,
                    background: "var(--act-bg, rgba(255,59,48,0.05))",
                    border: "1px solid var(--act-edge, rgba(255,59,48,0.2))",
                    borderRadius: 8,
                    textDecoration: "none",
                    color: "var(--label-primary)",
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 6 }}>
                    <span style={{ fontFamily: "var(--font-mono)", fontWeight: 700, fontSize: 14 }}>{r.symbol}</span>
                    <span style={{ color: "var(--act)", fontWeight: 700, fontSize: 13, fontFamily: "var(--font-mono)" }}>
                      {Math.round(r.red_flag_score)}
                    </span>
                  </div>
                  {r.triggered.map((f) => {
                    const d = r.detail?.[f] || {};
                    return (
                      <div key={f} style={{ fontSize: 11, color: "var(--label-secondary)", marginTop: 2 }}>
                        • {RED_FLAG_LABEL[f] || f}
                        {d.pledge_pct !== undefined && ` (${d.pledge_pct}% pledged)`}
                        {d.pct_change_20d !== undefined && ` (+${d.pct_change_20d}% in 20d)`}
                      </div>
                    );
                  })}
                </Link>
              ))}
            </div>
          )}
        </ExpandableSection>

        <ExpandableSection
          id="freshness"
          title="Data Freshness"
          count={runs.filter((s) => s.stale).length}
          countSuffix="stale"
          openId={openSection}
          onToggle={setOpenSection}
          warning={criticalStale}
        >
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
            {runs.map((s) => (
              <div
                key={s.source}
                title={s.last_success_at ? `Last success: ${new Date(s.last_success_at).toLocaleString("en-IN")}` : "Never run"}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 6,
                  padding: "4px 10px",
                  borderRadius: 14,
                  background: s.last_run_status === "failed"
                    ? "var(--act-bg, rgba(255,59,48,0.08))"
                    : s.stale
                      ? "var(--review-bg, rgba(255,149,0,0.08))"
                      : "var(--buy-bg, rgba(48,209,88,0.06))",
                  fontSize: 11,
                }}
              >
                <span
                  style={{
                    width: 6,
                    height: 6,
                    borderRadius: 3,
                    background: s.last_run_status === "failed"
                      ? "var(--act)"
                      : s.stale
                        ? "var(--review)"
                        : "var(--buy)",
                  }}
                />
                <span style={{ fontFamily: "var(--font-mono)", fontWeight: 600, color: "var(--label-secondary)" }}>
                  {s.source}
                </span>
                {s.stale && <span style={{ color: "var(--review)" }}>stale</span>}
              </div>
            ))}
          </div>
        </ExpandableSection>
      </section>

      {/* 3. EXPLORE footer */}
      <section style={{ marginTop: 16 }}>
        <div
          style={{
            fontSize: 11,
            fontWeight: 600,
            textTransform: "uppercase",
            letterSpacing: "0.05em",
            color: "var(--label-tertiary)",
            marginBottom: 8,
          }}
        >
          Explore
        </div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
          <ExploreLink href="/smart-money/insider" label="All Insider Disclosures" />
          <ExploreLink href="/smart-money/deals" label="All Deals" />
          <ExploreLink href="/smart-money/traders" label="All Active Traders" />
          <ExploreLink href="/smart-money/analyzer" label="Deal Analyzer →" />
        </div>
      </section>
    </div>
  );
}

function ExpandableSection({
  id,
  title,
  count,
  countSuffix,
  openId,
  onToggle,
  warning,
  children,
}: {
  id: string;
  title: string;
  count: number;
  countSuffix?: string;
  openId: string | null;
  onToggle: (id: string | null) => void;
  warning?: boolean;
  children: React.ReactNode;
}) {
  const open = openId === id;
  return (
    <div
      style={{
        border: "1px solid var(--separator-light)",
        borderRadius: 10,
        background: "var(--bg-primary)",
        overflow: "hidden",
      }}
    >
      <button
        onClick={() => onToggle(open ? null : id)}
        style={{
          width: "100%",
          padding: "12px 16px",
          background: "transparent",
          border: 0,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          cursor: "pointer",
          fontSize: 14,
          fontWeight: 600,
          color: "var(--label-primary)",
        }}
      >
        <span style={{ display: "inline-flex", alignItems: "center", gap: 10 }}>
          {warning && <span style={{ color: "var(--review)" }}>⚠</span>}
          <span>{title}</span>
          <span
            style={{
              fontSize: 11,
              fontWeight: 600,
              padding: "2px 8px",
              borderRadius: 99,
              background: "var(--bg-secondary)",
              color: "var(--label-tertiary)",
              fontFamily: "var(--font-mono)",
            }}
          >
            {count}
            {countSuffix ? ` ${countSuffix}` : ""}
          </span>
        </span>
        <span style={{ color: "var(--label-tertiary)", fontFamily: "var(--font-mono)" }}>{open ? "▴" : "▾"}</span>
      </button>
      {open && (
        <div style={{ padding: "0 16px 16px", borderTop: "1px solid var(--separator-light)" }}>
          {children}
        </div>
      )}
    </div>
  );
}

function ExploreLink({ href, label }: { href: string; label: string }) {
  return (
    <Link
      href={href}
      style={{
        padding: "6px 12px",
        borderRadius: 99,
        background: "var(--bg-secondary)",
        border: "1px solid var(--separator-light)",
        fontSize: 12,
        color: "var(--label-secondary)",
        textDecoration: "none",
        fontWeight: 500,
      }}
    >
      {label}
    </Link>
  );
}
