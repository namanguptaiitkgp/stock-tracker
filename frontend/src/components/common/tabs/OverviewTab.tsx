"use client";

import React, { useEffect, useState } from "react";
import { N, Pct, Vol } from "@/lib/format";
import { api } from "@/lib/api";
import EntryRecommendation from "../EntryRecommendation";
import { useLatestDecision } from "@/hooks/useLatestDecision";
import {
  SignalCards,
  ValuationCard,
  RiskFlags,
  useDecisionData,
} from "../DecisionBlock";
import DataSourceLegend, { DataSourceCaption } from "../DataSourceLegend";
import Sparkline from "../Sparkline";

interface StockDetail {
  symbol: string;
  exchange: string;
  holding: {
    quantity: number;
    average_price: number;
    last_price: number;
    invested: number;
    current_value: number;
    pnl: number;
    pnl_pct: number;
    day_change_pct: number;
  } | null;
  last_price: number | null;
  change_pct: number | null;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number | null;
  volume: number | null;
  average_price: number | null;
  buy_quantity: number | null;
  sell_quantity: number | null;
  oi: number | null;
  lower_circuit: number | null;
  upper_circuit: number | null;
  depth_buy: Array<{ price: number; quantity: number; orders: number }>;
  depth_sell: Array<{ price: number; quantity: number; orders: number }>;
  fundamentals: Record<string, unknown> | null;
}

interface Technicals {
  dma20: number | null;
  dma50: number | null;
  dma200: number | null;
  high_52w: number | null;
  low_52w: number | null;
  pct_from_52w_high: number | null;
  pct_from_52w_low: number | null;
  return_1m: number | null;
  return_3m: number | null;
  return_6m: number | null;
  return_1y: number | null;
  tech_signal: { direction: "accumulating" | "distributing" | "neutral"; label: string; strength: number } | null;
}

interface Props {
  data: StockDetail;
  onSwitchTab?: (tab: string) => void;
}

interface ChartData {
  candles: Array<{ time: string; open: number; high: number; low: number; close: number }>;
  prev_close: number | null;
  range: string;
  interval: string;
}

const RANGES = ["1D", "1W", "1M", "3M", "1Y", "5Y"] as const;
type RangeKey = typeof RANGES[number];

function SectionTitle({ children, right }: { children: React.ReactNode; right?: React.ReactNode }) {
  return (
    <div style={{
      display: "flex", justifyContent: "space-between", alignItems: "center",
      marginBottom: 10,
    }}>
      <span style={{
        fontSize: 11, fontWeight: 600,
        textTransform: "uppercase", letterSpacing: "0.08em",
        color: "var(--label-tertiary)",
      }}>{children}</span>
      {right}
    </div>
  );
}

function Card({ children, padding = 16 }: { children: React.ReactNode; padding?: number }) {
  return (
    <section style={{
      background: "var(--bg-primary)",
      border: "1px solid var(--separator-light)",
      borderRadius: 12,
      padding,
      boxShadow: "var(--shadow-card)",
    }}>
      {children}
    </section>
  );
}

function Row({ label, value, last, accent, missingTip }: {
  label: string; value: React.ReactNode; last?: boolean; accent?: string;
  // Tooltip shown on the value when it's a null-placeholder ("—" / "--").
  // Without this, an analyst can't tell silent-dash from genuinely-missing.
  missingTip?: string;
}) {
  // Treat the standard null placeholders as "missing" so the tooltip kicks in.
  const isMissing =
    value == null
    || value === "—"
    || value === "--"
    || (React.isValidElement(value) && (value.props as { children?: unknown })?.children === "--");
  return (
    <div style={{
      display: "flex", justifyContent: "space-between", alignItems: "center",
      padding: "9px 0",
      borderBottom: last ? "none" : "1px dashed var(--separator-light)",
    }}>
      <span style={{ fontSize: 13, color: "var(--label-tertiary)" }}>{label}</span>
      <span
        title={isMissing && missingTip ? missingTip : undefined}
        style={{
          fontSize: 13, fontWeight: 500,
          fontFamily: "var(--font-mono)",
          color: accent || "var(--label-primary)",
          cursor: isMissing && missingTip ? "help" : undefined,
        }}
      >{value}</span>
    </div>
  );
}

function CircuitRangeBar({ lower, upper, low, high, current }: {
  lower: number; upper: number; low: number; high: number; current: number;
}) {
  const range = upper - lower;
  if (range <= 0) return null;
  const lowPct = Math.max(0, Math.min(100, ((low - lower) / range) * 100));
  const highPct = Math.max(0, Math.min(100, ((high - lower) / range) * 100));
  const currentPct = Math.max(0, Math.min(100, ((current - lower) / range) * 100));

  return (
    <div>
      <SectionTitle>Circuit Range</SectionTitle>
      <div style={{ position: "relative", height: 6, borderRadius: 99, background: "var(--bg-secondary)" }}>
        <div style={{
          position: "absolute", top: 0, height: "100%", borderRadius: 99,
          left: `${lowPct}%`,
          width: `${Math.max(0, highPct - lowPct)}%`,
          background: "var(--system-blue)", opacity: 0.4,
        }} />
        <div style={{
          position: "absolute", top: "50%", transform: "translate(-50%, -50%)",
          left: `${currentPct}%`,
          width: 12, height: 12, borderRadius: "50%",
          background: "var(--label-primary)",
          border: "2px solid var(--bg-primary)",
          boxShadow: "var(--shadow-sm)",
        }} />
      </div>
      <div style={{
        display: "flex", justifyContent: "space-between",
        fontSize: 11, color: "var(--label-tertiary)", marginTop: 6,
        fontFamily: "var(--font-mono)",
      }}>
        <span>{N(lower)}</span>
        <span style={{ color: "var(--label-quaternary)", fontSize: 10 }}>today&apos;s range</span>
        <span>{N(upper)}</span>
      </div>
    </div>
  );
}

function PriceChartCard({ symbol, exchange, currentPrice, changePct }: {
  symbol: string; exchange: string; currentPrice: number | null; changePct: number | null;
}) {
  const [range, setRange] = useState<RangeKey>("1M");
  const [chart, setChart] = useState<ChartData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api.get<ChartData>(`/api/market-data/chart/${symbol}?range=${range}&exchange=${exchange}`)
      .then((d) => { if (!cancelled) setChart(d); })
      .catch(() => { if (!cancelled) setChart(null); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [symbol, exchange, range]);

  const validCandles = chart?.candles?.filter(c => c.close != null) ?? [];
  const closes = validCandles.map(c => c.close!);
  const timeLabels = validCandles.map(c => {
    const d = new Date(c.time);
    return range === "1D"
      ? d.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", hour12: true })
      : d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: range === "1W" || range === "1M" ? undefined : "2-digit" });
  });

  return (
    <Card>
      <div className="overview-chart-header" style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 14 }}>
        <div>
          <div style={{
            fontSize: 11, fontWeight: 600, color: "var(--label-tertiary)",
            textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 4,
          }}>Last Trade</div>
          <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
            <span style={{ fontFamily: "var(--font-mono)", fontSize: 36, fontWeight: 700, letterSpacing: "-0.02em", lineHeight: 1 }}>
              {N(currentPrice)}
            </span>
            <span style={{ fontSize: 11, color: "var(--label-tertiary)", fontWeight: 500, letterSpacing: "0.06em" }}>INR</span>
          </div>
          <div style={{ marginTop: 6, fontSize: 14, fontWeight: 500 }}>
            {Pct(changePct)}
            <span style={{ marginLeft: 8, fontSize: 12, color: "var(--label-tertiary)", fontWeight: 400 }}>Today</span>
          </div>
        </div>
        <div style={{ display: "inline-flex", gap: 2, padding: 3, background: "var(--bg-secondary)", borderRadius: 8 }}>
          {RANGES.map(r => (
            <button
              key={r}
              onClick={() => setRange(r)}
              style={{
                background: range === r ? "var(--bg-primary)" : "transparent",
                color: range === r ? "var(--label-primary)" : "var(--label-tertiary)",
                boxShadow: range === r ? "var(--shadow-sm)" : "none",
                border: 0,
                padding: "5px 10px",
                borderRadius: 6,
                fontSize: 11, fontWeight: 500,
                fontFamily: "var(--font-mono)",
                cursor: "pointer",
              }}
            >{r}</button>
          ))}
        </div>
      </div>
      <div style={{ height: 200, position: "relative" }}>
        {loading && (
          <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--label-tertiary)", fontSize: 12 }}>
            Loading…
          </div>
        )}
        {!loading && (
          <Sparkline
            data={closes}
            labels={timeLabels}
            height={200}
            prevClose={range === "1D" ? chart?.prev_close ?? null : null}
          />
        )}
      </div>
    </Card>
  );
}

function SkeletonRow() {
  return (
    <div style={{ padding: "9px 0", borderBottom: "1px dashed var(--separator-light)" }}>
      <div style={{ height: 14, borderRadius: 4, background: "var(--fill-gray)" }} className="animate-pulse" />
    </div>
  );
}

export default function OverviewTab({ data, onSwitchTab }: Props) {
  const f = data.fundamentals as Record<string, string | number | null | Record<string, string>> | null;
  const ds = (f?.data_sources || {}) as Record<string, string>;

  // Technicals load separately so they don't block the panel render
  const [technicals, setTechnicals] = useState<Technicals | null>(null);
  const [technicalsLoading, setTechnicalsLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setTechnicalsLoading(true);
    api.get<Technicals>(`/api/market-data/technicals/${data.symbol}?exchange=${data.exchange}`)
      .then((t) => { if (!cancelled) setTechnicals(t); })
      .catch(() => { if (!cancelled) setTechnicals(null); })
      .finally(() => { if (!cancelled) setTechnicalsLoading(false); });
    return () => { cancelled = true; };
  }, [data.symbol, data.exchange]);

  const peTtm = f ? (f.ttm_pe ?? f.pe_ratio) as number | null : null;
  const { composite, signals } = useDecisionData(data.symbol, technicals?.tech_signal ?? null, peTtm);
  const { decision } = useLatestDecision(data.symbol);

  const fundForBlock = f as unknown as Parameters<typeof ValuationCard>[0]["f"] | null;

  // Buy/Sell ratio
  const bsRatio = (data.buy_quantity && data.sell_quantity)
    ? (data.buy_quantity / data.sell_quantity).toFixed(2)
    : null;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {/* TOP — 2 column main grid */}
      <div className="overview-main-grid" style={{ display: "grid", gridTemplateColumns: "1.55fr 1fr", gap: 16 }}>
        {/* LEFT COLUMN — Chart, Conviction, Signal Cards */}
        <div style={{ display: "flex", flexDirection: "column", gap: 16, minWidth: 0 }}>
          <PriceChartCard symbol={data.symbol} exchange={data.exchange} currentPrice={data.last_price} changePct={data.change_pct} />

          {data.lower_circuit != null && data.upper_circuit != null && data.last_price != null && (
            <Card>
              <CircuitRangeBar
                lower={data.lower_circuit}
                upper={data.upper_circuit}
                low={data.low ?? data.last_price}
                high={data.high ?? data.last_price}
                current={data.last_price}
              />
            </Card>
          )}

          {signals.length > 0 && (
            <Card>
              <SignalCards signals={signals} onCardClick={onSwitchTab ? (source) => {
                const tabMap: Record<string, string> = { NEWS: "News", TECH: "Overview", MF: "Smart Money", PRO: "Smart Money", RET: "Smart Money", INS: "Smart Money", DII: "Smart Money", VAL: "Smart Money" };
                const tab = tabMap[source];
                if (tab && tab !== "Overview") onSwitchTab(tab);
              } : undefined} />
            </Card>
          )}

          {decision?.verdict && decision?.reasoning && (
            <Card>
              <SectionTitle right={
                decision.created_at ? (
                  <span style={{ fontSize: 11, color: "var(--label-quaternary)" }}>
                    {new Date(decision.created_at).toLocaleDateString("en-IN", { day: "numeric", month: "short" })}
                  </span>
                ) : null
              }>Analysis Summary</SectionTitle>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
                <span style={{
                  display: "inline-block", padding: "2px 10px", borderRadius: 6,
                  fontSize: 12, fontWeight: 600, letterSpacing: "0.5px",
                  ...(decision.verdict === "INVEST"
                    ? { background: "rgba(52,199,89,0.08)", color: "#248A3D", border: "1px solid rgba(52,199,89,0.2)" }
                    : decision.verdict === "AVOID"
                    ? { background: "rgba(255,59,48,0.08)", color: "#D70015", border: "1px solid rgba(255,59,48,0.2)" }
                    : { background: "rgba(255,204,0,0.08)", color: "#A05A00", border: "1px solid rgba(255,204,0,0.2)" }),
                }}>{decision.verdict}</span>
                {decision.confidence != null && (
                  <span style={{ fontSize: 12, fontFamily: "var(--font-mono)", color: "var(--label-secondary)" }}>
                    {decision.confidence}%
                  </span>
                )}
              </div>
              <p style={{
                fontSize: 12.5, lineHeight: 1.5, color: "var(--label-secondary)", margin: 0,
              }}>{decision.reasoning}</p>
            </Card>
          )}
        </div>

        {/* RIGHT COLUMN — Holding, Valuation+Risks, V&T, Depth */}
        <div style={{ display: "flex", flexDirection: "column", gap: 16, minWidth: 0 }}>
          {data.holding && (
            <div style={{
              padding: 14, borderRadius: 12,
              background: "linear-gradient(180deg, var(--fill-blue), var(--bg-primary) 60%)",
              border: "1px solid rgba(0,122,255,0.15)",
              boxShadow: "var(--shadow-card)",
            }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
                <span style={{
                  fontSize: 11, fontWeight: 600, textTransform: "uppercase",
                  color: "var(--system-blue)", letterSpacing: "0.08em",
                }}>Your Position</span>
                <span style={{
                  display: "inline-flex", alignItems: "center",
                  padding: "2px 10px", borderRadius: 99,
                  fontSize: 11, fontWeight: 600,
                  background: data.holding.pnl >= 0 ? "var(--fill-green)" : "var(--fill-red)",
                  color: data.holding.pnl >= 0 ? "var(--system-green)" : "var(--system-red)",
                }}>
                  {data.holding.pnl >= 0 ? "▲" : "▼"} {data.holding.pnl >= 0 ? "+" : ""}{data.holding.pnl_pct?.toFixed(2)}%
                </span>
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px 16px" }}>
                {[
                  { label: "Quantity", value: String(data.holding.quantity) },
                  { label: "Avg Price", value: N(data.holding.average_price) },
                  { label: "Invested", value: Vol(data.holding.invested) },
                  { label: "Current", value: Vol(data.holding.current_value) },
                ].map(({ label, value }) => (
                  <div key={label}>
                    <div style={{ fontSize: 10.5, color: "var(--label-tertiary)", textTransform: "uppercase", letterSpacing: "0.04em", fontWeight: 500, marginBottom: 2 }}>{label}</div>
                    <div style={{ fontSize: 15, fontWeight: 600, fontFamily: "var(--font-mono)", color: "var(--label-primary)" }}>{value}</div>
                  </div>
                ))}
              </div>
              <div style={{
                display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16,
                marginTop: 12, paddingTop: 12,
                borderTop: "1px solid color-mix(in srgb, var(--system-blue) 18%, transparent)",
              }}>
                <div>
                  <div style={{ fontSize: 10.5, color: "var(--label-tertiary)", textTransform: "uppercase", letterSpacing: "0.04em", fontWeight: 500, marginBottom: 2 }}>Unrealised P&amp;L</div>
                  <div style={{
                    fontSize: 15, fontWeight: 700, fontFamily: "var(--font-mono)",
                    color: data.holding.pnl >= 0 ? "var(--system-green)" : "var(--system-red)",
                  }}>
                    {data.holding.pnl >= 0 ? "+" : ""}{Vol(data.holding.pnl)}
                  </div>
                </div>
                <div>
                  <div style={{ fontSize: 10.5, color: "var(--label-tertiary)", textTransform: "uppercase", letterSpacing: "0.04em", fontWeight: 500, marginBottom: 2 }}>Day Chg</div>
                  <div style={{
                    fontSize: 15, fontWeight: 700, fontFamily: "var(--font-mono)",
                    color: data.holding.day_change_pct >= 0 ? "var(--system-green)" : "var(--system-red)",
                  }}>
                    {data.holding.day_change_pct >= 0 ? "+" : ""}{data.holding.day_change_pct?.toFixed(2)}%
                  </div>
                </div>
              </div>
            </div>
          )}

          {fundForBlock && (
            <Card>
              <ValuationCard f={fundForBlock} />
              <div style={{ marginTop: 14 }}>
                <RiskFlags fundamentals={fundForBlock} />
              </div>
            </Card>
          )}

          {decision?.entry_recommendation && (
            <EntryRecommendation
              data={decision.entry_recommendation}
              analyzedAt={decision.created_at}
            />
          )}

          {/* OHLC */}
          <Card padding={14}>
            <SectionTitle>OHLC</SectionTitle>
            <div className="overview-ohlc" style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 1, background: "var(--separator-light)", borderRadius: 10, overflow: "hidden", border: "1px solid var(--separator-light)" }}>
              {[
                { label: "Open", val: data.open },
                { label: "High", val: data.high },
                { label: "Low", val: data.low },
                { label: "Prev", val: data.close },
              ].map(({ label, val }) => (
                <div key={label} style={{ background: "var(--bg-secondary)", padding: "10px 8px" }}>
                  <div style={{ fontSize: 10, color: "var(--label-tertiary)", textTransform: "uppercase", letterSpacing: "0.06em", fontWeight: 500 }}>{label}</div>
                  <div style={{ fontFamily: "var(--font-mono)", fontSize: 13, fontWeight: 500, marginTop: 2 }}>{N(val)}</div>
                </div>
              ))}
            </div>
          </Card>

        </div>
      </div>

      {/* BOTTOM — Fundamentals + Technicals (full width, 2-col stat grid each) */}
      {f && (
        <Card>
          <SectionTitle right={<DataSourceCaption dataSources={ds} />}>Fundamentals</SectionTitle>
          <div className="overview-fund-grid" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", columnGap: 24 }}>
            <div>
              <Row label="Market Cap" value={Vol(f.market_cap as number | null)} />
              <Row label="P/E (TTM)" value={N(f.ttm_pe)} />
              <Row label="Forward P/E" value={N(f.forward_pe)} />
              <Row label="P/B" value={N(f.pb_ratio)} />
              <Row label="Debt/Equity" value={N(f.debt_to_equity)} last />
            </div>
            <div>
              <Row label="Revenue Growth 1Y" value={Pct(f.revenue_growth_1y as number | null)} />
              <Row label="EPS Growth 1Y" value={Pct(f.eps_growth_1y as number | null)} />
              <Row label="Net Margin" value={Pct(f.net_profit_margin as number | null)} />
              <Row label="ROE" value={Pct(f.roe as number | null)} />
              <Row label="Promoter Holding" value={f.promoter_holding != null ? `${Number(f.promoter_holding).toFixed(1)}%` : "--"} last />
            </div>
          </div>
        </Card>
      )}

      <Card>
        <SectionTitle right={technicalsLoading ? <span style={{ fontSize: 11, color: "var(--label-tertiary)" }}>loading…</span> : null}>
          Technicals
        </SectionTitle>
        <div className="overview-tech-grid" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", columnGap: 24 }}>
          <div>
            {technicalsLoading ? (
              <>{[0,1,2,3,4].map(i => <SkeletonRow key={i} />)}</>
            ) : (
              <>
                <Row label="20 DMA" value={N(technicals?.dma20)} />
                <Row label="50 DMA" value={N(technicals?.dma50)} />
                <Row label="200 DMA" value={N(technicals?.dma200)} />
                <Row label="52W High" value={
                  <span style={{ display: "inline-flex", gap: 6, alignItems: "baseline" }}>
                    <span>{N(technicals?.high_52w)}</span>
                    {technicals?.pct_from_52w_high != null && (
                      <span style={{ color: "var(--system-red)", fontSize: 11 }}>
                        ({technicals.pct_from_52w_high.toFixed(1)}%)
                      </span>
                    )}
                  </span>
                } />
                <Row label="52W Low" value={
                  <span style={{ display: "inline-flex", gap: 6, alignItems: "baseline" }}>
                    <span>{N(technicals?.low_52w)}</span>
                    {technicals?.pct_from_52w_low != null && (
                      <span style={{ color: "var(--system-green)", fontSize: 11 }}>
                        (+{technicals.pct_from_52w_low.toFixed(1)}%)
                      </span>
                    )}
                  </span>
                } last />
              </>
            )}
          </div>
          <div>
            {technicalsLoading ? (
              <>{[0,1,2,3].map(i => <SkeletonRow key={i} />)}</>
            ) : (
              <>
                <Row label="1M Return" value={Pct(technicals?.return_1m ?? null)}
                  missingTip="1-month return not available — typically means fewer than 21 trading days of cached price history for this symbol."
                />
                <Row label="3M Return" value={Pct(technicals?.return_3m ?? null)}
                  missingTip="3-month return not available — insufficient cached price history."
                />
                <Row label="6M Return" value={Pct(technicals?.return_6m ?? null)}
                  missingTip="6-month return not available — insufficient cached price history."
                />
                <Row label="1Y Return" value={Pct(technicals?.return_1y ?? null)} last
                  missingTip="1-year return not available — typically means the symbol has been listed for less than a year, or the daily-candle cache hasn't been backfilled. Try refreshing fundamentals from the Fundamentals tab."
                />
              </>
            )}
          </div>
        </div>
      </Card>

      {/* Volume & Trade + Market Depth — side by side */}
      <div className="overview-vol-depth" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
        <Card>
          <SectionTitle right={<span style={{ fontSize: 11, color: "var(--label-tertiary)" }}>today</span>}>Volume &amp; Trade</SectionTitle>
          <Row label="Volume" value={Vol(data.volume)} />
          <Row label="Buy Qty" value={Vol(data.buy_quantity)} accent="var(--system-green)" />
          <Row label="Sell Qty" value={Vol(data.sell_quantity)} accent="var(--system-red)" />
          {bsRatio && <Row label="Buy/Sell Ratio" value={bsRatio} />}
          {data.oi ? <Row label="Open Interest" value={Vol(data.oi)} last /> : <Row label="Avg Trade Price" value={N(data.average_price)} last />}
        </Card>

        {data.depth_buy?.length > 0 && (() => {
          const allQtys = [
            ...data.depth_buy.map(d => d.quantity),
            ...data.depth_sell.map(d => d.quantity),
          ];
          const maxQty = Math.max(...allQtys, 1);

          return (
            <Card>
              <SectionTitle right={<span style={{ fontSize: 11, color: "var(--label-tertiary)" }}>5 levels</span>}>Market Depth</SectionTitle>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
                <div>
                  <div style={{ display: "grid", gridTemplateColumns: "1.2fr 1fr 0.5fr", padding: "0 8px 6px", fontSize: 10, fontWeight: 600, color: "var(--label-tertiary)", textTransform: "uppercase", letterSpacing: "0.04em", borderBottom: "1px solid var(--separator-light)" }}>
                    <span>Bid</span><span style={{ textAlign: "right" }}>Qty</span><span style={{ textAlign: "right" }}>Ord</span>
                  </div>
                  {data.depth_buy.map((d, i) => (
                    <div key={i} style={{ position: "relative", display: "grid", gridTemplateColumns: "1.2fr 1fr 0.5fr", padding: "6px 8px", fontSize: 12, alignItems: "center", fontFamily: "var(--font-mono)", color: "var(--system-green)" }}>
                      <div style={{
                        position: "absolute", top: 2, bottom: 2, left: 0, borderRadius: 4,
                        background: "var(--system-green)", opacity: 0.1,
                        width: `${(d.quantity / maxQty) * 100}%`,
                      }} />
                      <span style={{ position: "relative", fontWeight: 600 }}>{d.price?.toFixed(2)}</span>
                      <span style={{ position: "relative", textAlign: "right", color: "var(--label-primary)" }}>{Vol(d.quantity)}</span>
                      <span style={{ position: "relative", textAlign: "right", color: "var(--label-tertiary)" }}>{d.orders}</span>
                    </div>
                  ))}
                </div>
                <div>
                  <div style={{ display: "grid", gridTemplateColumns: "1.2fr 1fr 0.5fr", padding: "0 8px 6px", fontSize: 10, fontWeight: 600, color: "var(--label-tertiary)", textTransform: "uppercase", letterSpacing: "0.04em", borderBottom: "1px solid var(--separator-light)" }}>
                    <span>Ask</span><span style={{ textAlign: "right" }}>Qty</span><span style={{ textAlign: "right" }}>Ord</span>
                  </div>
                  {data.depth_sell.map((d, i) => (
                    <div key={i} style={{ position: "relative", display: "grid", gridTemplateColumns: "1.2fr 1fr 0.5fr", padding: "6px 8px", fontSize: 12, alignItems: "center", fontFamily: "var(--font-mono)", color: "var(--system-red)" }}>
                      <div style={{
                        position: "absolute", top: 2, bottom: 2, right: 0, borderRadius: 4,
                        background: "var(--system-red)", opacity: 0.1,
                        width: `${(d.quantity / maxQty) * 100}%`,
                      }} />
                      <span style={{ position: "relative", fontWeight: 600 }}>{d.price?.toFixed(2)}</span>
                      <span style={{ position: "relative", textAlign: "right", color: "var(--label-primary)" }}>{Vol(d.quantity)}</span>
                      <span style={{ position: "relative", textAlign: "right", color: "var(--label-tertiary)" }}>{d.orders}</span>
                    </div>
                  ))}
                </div>
              </div>
            </Card>
          );
        })()}
      </div>

      <DataSourceLegend />

      <style jsx>{`
        @media (max-width: 720px) {
          .overview-main-grid { grid-template-columns: 1fr !important; }
          .overview-chart-header { flex-wrap: wrap !important; gap: 10px !important; }
          .overview-ohlc { grid-template-columns: repeat(2, 1fr) !important; }
          .overview-fund-grid { grid-template-columns: 1fr !important; }
          .overview-tech-grid { grid-template-columns: 1fr !important; }
          .overview-vol-depth { grid-template-columns: 1fr !important; }
        }
      `}</style>
    </div>
  );
}
