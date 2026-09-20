"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import ConvictionGauge from "./ConvictionGauge";
import SmartMoneyCoverageCallout from "./SmartMoneyCoverageCallout";

interface Deal {
  trade_date: string;
  exchange: string;
  symbol: string;
  client_name: string;
  side: "BUY" | "SELL";
  quantity: number;
  avg_price: number | null;
  trade_value_inr: number | null;
  deal_type: string;
  is_known_shark: boolean;
}

interface Signal {
  symbol: string;
  as_of: string;
  mf_score: number | null;
  pms_score: number | null;
  aif_score: number | null;
  deals_score: number | null;
  delivery_score: number | null;
  composite: number | null;
  conviction_score: number | null;
  flow_score: number | null;
  red_flag_score: number | null;
  signal_breakdown: SignalBreakdown | null;
  named_sharks: Array<{
    name: string;
    side: string;
    quantity: number;
    price: number | null;
    value_inr: number | null;
    date: string;
    deal_type: string;
  }> | null;
  meta: Record<string, unknown> | null;
}

interface SignalBreakdown {
  conviction?: Record<string, BreakdownItem>;
  flow?: Record<string, BreakdownItem>;
  red_flags?: { triggered?: string[]; detail?: Record<string, RedFlagDetail> };
  signals_available?: string[];
  signals_absent?: string[];
}

interface BreakdownItem {
  raw?: number | null;
  normalized?: number | null;
  note?: string;
  source_rows?: number;
  // Ad-hoc per-signal fields (e.g. quarter, fund_houses, fii_net_cr) flow through here.
  [key: string]: unknown;
}

interface RedFlagDetail {
  penalty?: number;
  pledge_pct?: number;
  pct_change_20d?: number;
  shares_sold?: number;
  events?: number;
  suspects?: string[];
  quarter?: string;
}

interface DeliveryPoint {
  trade_date: string;
  close_price: number | null;
  traded_qty: number | null;
  delivery_pct: number | null;
}

interface Payload {
  symbol: string;
  signal: Signal | null;
  deals_last_30d: Deal[];
  delivery_trend: DeliveryPoint[];
}

interface InsiderRow {
  id: number;
  symbol: string;
  person_name: string;
  category: string;
  transaction_type: string;
  shares: number;
  value_inr: number | null;
  transaction_date: string | null;
  intimation_date: string | null;
  mode: string | null;
  is_known_shark: boolean;
}

function fmtInr(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  if (Math.abs(n) >= 1e7) return `Rs ${(n / 1e7).toFixed(2)} Cr`;
  if (Math.abs(n) >= 1e5) return `Rs ${(n / 1e5).toFixed(2)} L`;
  return `Rs ${Math.round(n).toLocaleString("en-IN")}`;
}

function fmtQty(n: number): string {
  if (Math.abs(n) >= 1e7) return `${(n / 1e7).toFixed(2)} Cr`;
  if (Math.abs(n) >= 1e5) return `${(n / 1e5).toFixed(1)} L`;
  if (Math.abs(n) >= 1e3) return `${(n / 1e3).toFixed(1)} K`;
  return n.toLocaleString("en-IN");
}

const RED_FLAG_LABEL: Record<string, string> = {
  circular_trading: "Circular trading suspects",
  pump_pattern: "Pump pattern (price up, delivery down)",
  promoter_selling: "Promoter selling",
  high_pledge: "High promoter pledge",
  pledge_invocation: "Pledge invocation",
};

interface CoverageResp {
  symbol: string;
  coverage_score: number;
  sources_with_data: string[];
  sources_missing: string[];
  gap_explanation: string | null;
}

export default function SmartMoneyPanel({ symbol }: { symbol: string }) {
  const [data, setData] = useState<Payload | null>(null);
  const [insider, setInsider] = useState<InsiderRow[]>([]);
  const [coverage, setCoverage] = useState<CoverageResp | null>(null);
  const [loading, setLoading] = useState(true);
  const [showDeals, setShowDeals] = useState(false);
  const [openCat, setOpenCat] = useState<"conviction" | "flow" | "red_flags" | null>(null);

  useEffect(() => {
    setLoading(true);
    Promise.all([
      api.get<Payload>(`/api/smart-money/${symbol}`).catch(() => null),
      api.get<{ rows: InsiderRow[] }>(`/api/smart-money/insider-activity/${symbol}`).catch(() => ({ rows: [] })),
      api.get<CoverageResp>(`/api/smart-money/coverage/${symbol}`).catch(() => null),
    ]).then(([panel, ins, cov]) => {
      setData(panel);
      setInsider(ins?.rows || []);
      setCoverage(cov);
      setLoading(false);
    });
  }, [symbol]);

  const sig = data?.signal;
  const named = sig?.named_sharks || [];
  const deals = data?.deals_last_30d || [];
  const breakdown = sig?.signal_breakdown || null;
  const triggered = breakdown?.red_flags?.triggered || [];
  const rfDetail = breakdown?.red_flags?.detail || {};

  return (
    <section style={{
      background: "var(--bg-primary)",
      border: "1px solid var(--separator-light)",
      borderRadius: 12,
      padding: 16,
      boxShadow: "var(--shadow-card)",
    }}>
      <div style={{
        display: "flex", justifyContent: "space-between", alignItems: "center",
        marginBottom: 10,
      }}>
        <span style={{
          fontSize: 11, fontWeight: 600, textTransform: "uppercase",
          letterSpacing: "0.08em", color: "var(--label-tertiary)",
        }}>
          Smart Money
        </span>
        {sig?.as_of && (
          <span style={{ fontSize: 11, color: "var(--label-quaternary)" }}>{sig.as_of}</span>
        )}
      </div>

      {loading && (
        <div style={{ padding: "8px 0" }}>
          <div style={{ height: 12, borderRadius: 4, backgroundColor: "var(--fill-gray, rgba(99,99,102,0.08))", width: "80%", marginBottom: 8 }} />
          <div style={{ height: 12, borderRadius: 4, backgroundColor: "var(--fill-gray, rgba(99,99,102,0.08))", width: "60%" }} />
        </div>
      )}

      {!loading && !data && (
        <div style={{ fontSize: 13, color: "var(--label-tertiary)", textAlign: "center", padding: 8 }}>
          Smart-money data unavailable
        </div>
      )}

      {!loading && data && (
        <div>
          {/* Coverage callout — only when smart-money data is thin. */}
          {coverage && coverage.coverage_score < 50 && (
            <SmartMoneyCoverageCallout
              score={coverage.coverage_score}
              sourcesWithData={coverage.sources_with_data}
              sourcesMissing={coverage.sources_missing}
              gapExplanation={coverage.gap_explanation}
            />
          )}

          {/* Triple gauge */}
          <div style={{ display: "flex", flexDirection: "column", gap: 10, marginBottom: 12 }}>
            <ConvictionGauge
              label="Conviction"
              value={sig?.conviction_score ?? null}
              hint="Promoter buying + tracked-investor accumulation + MF consensus + shareholding Δ"
            />
            <ConvictionGauge
              label="Flow"
              value={sig?.flow_score ?? null}
              hint="Delivery z-score + stock-level FII/DII + institutional block/bulk + buyback"
            />
            <ConvictionGauge
              label="Red Flags"
              value={sig?.red_flag_score ?? null}
              kind="red_flag"
              hint="Manipulation signatures: circular trading, pump pattern, promoter selling, pledge"
            />
          </div>

          {/* Active red-flag callout — prominent */}
          {triggered.length > 0 && (
            <div
              style={{
                marginBottom: 12,
                padding: "8px 12px",
                borderRadius: 8,
                background: "var(--act-bg)",
                border: "1px solid var(--act-edge)",
                fontSize: 12,
              }}
            >
              <div
                style={{
                  fontSize: 11,
                  fontWeight: 600,
                  color: "var(--act)",
                  textTransform: "uppercase",
                  letterSpacing: "0.05em",
                  marginBottom: 4,
                }}
              >
                Active red flags
              </div>
              {triggered.map((flag) => (
                <div key={flag} style={{ color: "var(--label-secondary)", marginTop: 2 }}>
                  • {RED_FLAG_LABEL[flag] || flag}
                  {rfDetail[flag]?.pledge_pct !== undefined && ` — ${rfDetail[flag].pledge_pct}% pledged`}
                  {rfDetail[flag]?.pct_change_20d !== undefined && ` — +${rfDetail[flag].pct_change_20d}% in 20d`}
                  {rfDetail[flag]?.suspects && rfDetail[flag]!.suspects!.length > 0 && (
                    <span style={{ color: "var(--label-tertiary)" }}>
                      {" "}({rfDetail[flag]!.suspects!.slice(0, 2).join(", ")})
                    </span>
                  )}
                </div>
              ))}
            </div>
          )}

          {/* Signal breakdown accordion */}
          {breakdown && (
            <div style={{ display: "flex", flexDirection: "column", gap: 4, marginBottom: 12 }}>
              {(["conviction", "flow", "red_flags"] as const).map((cat) => (
                <BreakdownAccordion
                  key={cat}
                  category={cat}
                  open={openCat === cat}
                  onToggle={() => setOpenCat(openCat === cat ? null : cat)}
                  breakdown={breakdown}
                />
              ))}
            </div>
          )}

          {/* Insider disclosures (last 12 months) */}
          {insider.length > 0 && (
            <div style={{ borderTop: "1px solid var(--separator-light)", paddingTop: 10, marginBottom: 10 }}>
              <div
                style={{
                  fontSize: 11,
                  fontWeight: 600,
                  color: "var(--label-tertiary)",
                  textTransform: "uppercase",
                  letterSpacing: "0.05em",
                  marginBottom: 6,
                }}
              >
                Insider disclosures ({insider.length})
              </div>
              {insider.slice(0, 5).map((r) => (
                <div key={r.id} style={{ display: "flex", justifyContent: "space-between", fontSize: 12, padding: "3px 0" }}>
                  <span style={{ flex: 1, minWidth: 0, color: "var(--label-secondary)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {r.transaction_date} · {r.person_name}
                  </span>
                  <span
                    style={{
                      color: r.transaction_type === "Buy" ? "var(--buy)" : r.transaction_type === "Sale" ? "var(--act)" : "var(--review)",
                      fontWeight: 600,
                      marginLeft: 8,
                    }}
                  >
                    {r.transaction_type}
                  </span>
                  <span style={{ marginLeft: 8, color: "var(--label-primary)" }}>
                    {fmtQty(r.shares)}
                  </span>
                </div>
              ))}
            </div>
          )}

          {/* Named sharks */}
          {named.length > 0 && (
            <div style={{ borderTop: "1px solid var(--separator-light)", paddingTop: 10, marginBottom: 10 }}>
              <div
                style={{
                  fontSize: 11,
                  fontWeight: 600,
                  color: "var(--label-tertiary)",
                  textTransform: "uppercase",
                  letterSpacing: "0.05em",
                  marginBottom: 6,
                }}
              >
                Named-shark deals (30d)
              </div>
              {named.map((s, i) => (
                <div key={i} style={{ fontSize: 12, marginBottom: 4 }}>
                  <Link
                    href={`/smart-money/shark/${encodeURIComponent(s.name)}`}
                    style={{ color: "var(--system-blue)", textDecoration: "none", fontWeight: 600 }}
                  >
                    {s.name}
                  </Link>{" "}
                  <span style={{ color: s.side === "BUY" ? "var(--buy)" : "var(--act)", fontWeight: 600 }}>
                    {s.side}
                  </span>{" "}
                  <span style={{ color: "var(--label-tertiary)" }}>
                    {fmtQty(s.quantity)} @ Rs {s.price?.toFixed(2)} on {s.date} ({s.deal_type})
                  </span>
                </div>
              ))}
            </div>
          )}

          {/* Deals collapse */}
          {deals.length > 0 && (
            <div style={{ borderTop: "1px solid var(--separator-light)", paddingTop: 10 }}>
              <button
                onClick={() => setShowDeals(!showDeals)}
                style={{ fontSize: 12, color: "var(--system-blue)", background: "none", border: "none", cursor: "pointer", padding: 0 }}
              >
                {showDeals ? "Hide" : "Show"} all bulk/block deals ({deals.length} in last 30d)
              </button>
              {showDeals && (
                <div style={{ marginTop: 8 }}>
                  {deals.slice(0, 30).map((d, i) => (
                    <div key={i} style={{ display: "flex", justifyContent: "space-between", fontSize: 11, padding: "3px 0", color: "var(--label-secondary)" }}>
                      <span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {d.trade_date} · {d.client_name}
                      </span>
                      <span style={{ color: d.side === "BUY" ? "var(--buy)" : "var(--act)", fontWeight: 600, marginLeft: 8 }}>
                        {d.side}
                      </span>
                      <span style={{ marginLeft: 8, color: "var(--label-primary)" }}>
                        {fmtInr(d.trade_value_inr)}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {!sig && deals.length === 0 && insider.length === 0 && (
            <div style={{ fontSize: 13, color: "var(--label-tertiary)", textAlign: "center", padding: 4 }}>
              No smart-money activity detected
            </div>
          )}
        </div>
      )}
    </section>
  );
}

function BreakdownAccordion({
  category,
  open,
  onToggle,
  breakdown,
}: {
  category: "conviction" | "flow" | "red_flags";
  open: boolean;
  onToggle: () => void;
  breakdown: SignalBreakdown;
}) {
  const data = breakdown[category];
  if (!data) return null;
  const items: Array<[string, BreakdownItem | RedFlagDetail]> = [];
  if (category === "red_flags") {
    const triggered = breakdown.red_flags?.triggered || [];
    for (const t of triggered) items.push([t, breakdown.red_flags?.detail?.[t] || {}]);
    if (items.length === 0) return null;
  } else {
    const sub = data as Record<string, BreakdownItem>;
    for (const k of Object.keys(sub)) items.push([k, sub[k]]);
  }

  const titleMap = { conviction: "Conviction signals", flow: "Flow signals", red_flags: "Red flags" };
  const colorMap = { conviction: "var(--buy)", flow: "var(--system-blue)", red_flags: "var(--act)" };

  return (
    <div style={{ border: "1px solid var(--separator-light)", borderRadius: 8, overflow: "hidden" }}>
      <button
        onClick={onToggle}
        style={{
          width: "100%",
          padding: "8px 12px",
          background: "transparent",
          border: 0,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          cursor: "pointer",
          fontSize: 12,
          color: "var(--label-secondary)",
        }}
      >
        <span>
          <span style={{ color: colorMap[category], fontWeight: 600 }}>●</span> {titleMap[category]}
        </span>
        <span style={{ color: "var(--label-tertiary)", fontFamily: "var(--font-mono)" }}>
          {items.length} · {open ? "▴" : "▾"}
        </span>
      </button>
      {open && (
        <div style={{ padding: "8px 12px 10px", borderTop: "1px solid var(--separator-light)", fontSize: 11 }}>
          {items.map(([k, v]) => (
            <BreakdownRow key={k} signalKey={k} item={v} category={category} />
          ))}
        </div>
      )}
    </div>
  );
}

function BreakdownRow({
  signalKey,
  item,
  category,
}: {
  signalKey: string;
  item: BreakdownItem | RedFlagDetail;
  category: "conviction" | "flow" | "red_flags";
}) {
  const labelMap: Record<string, string> = {
    promoter_buying: "Promoter open-market buying",
    shark_accumulation: "Tracked-investor accumulation",
    mf_consensus: "Mutual fund consensus",
    shareholding_delta: "Shareholding pattern Δ",
    delivery: "Delivery % anomaly",
    fii_dii_stock: "Stock-level FII/DII (5d)",
    block_bulk_net: "Institutional block/bulk net",
    buyback_active: "Active buyback",
    circular_trading: "Circular trading suspects",
    pump_pattern: "Pump pattern",
    promoter_selling: "Promoter selling",
    high_pledge: "High promoter pledge",
    pledge_invocation: "Pledge invocation",
  };

  if (category === "red_flags") {
    const d = item as RedFlagDetail;
    return (
      <div style={{ display: "flex", justifyContent: "space-between", padding: "3px 0" }}>
        <span style={{ color: "var(--label-secondary)" }}>{labelMap[signalKey] || signalKey}</span>
        <span style={{ color: "var(--act)", fontWeight: 600, fontFamily: "var(--font-mono)" }}>
          {d.penalty !== undefined ? `${d.penalty > 0 ? "+" : ""}${d.penalty}` : "—"}
        </span>
      </div>
    );
  }

  const it = item as BreakdownItem;
  const norm = it.normalized;
  const note = it.note;
  return (
    <div style={{ padding: "3px 0" }}>
      <div style={{ display: "flex", justifyContent: "space-between" }}>
        <span style={{ color: "var(--label-secondary)" }}>{labelMap[signalKey] || signalKey}</span>
        <span
          style={{
            color: norm === null || norm === undefined
              ? "var(--label-quaternary)"
              : norm > 0
                ? "var(--buy)"
                : norm < 0
                  ? "var(--act)"
                  : "var(--label-tertiary)",
            fontWeight: 600,
            fontFamily: "var(--font-mono)",
          }}
        >
          {norm === null || norm === undefined ? "—" : `${norm >= 0 ? "+" : ""}${Math.round(Number(norm))}`}
        </span>
      </div>
      {note && (
        <div style={{ color: "var(--label-quaternary)", fontStyle: "italic", marginTop: 1 }}>
          {note}
        </div>
      )}
    </div>
  );
}
