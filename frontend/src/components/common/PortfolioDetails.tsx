"use client";

import { useMemo, useState } from "react";
import { HoldingAction } from "./PositionCard";
import { pctStr } from "@/lib/format";
import { usePrivacyMode } from "@/lib/privacy-mode";

type CapId = "large" | "mid" | "small" | "other";

const CAP_GROUPS: Array<{ id: CapId; title: string; sub: string }> = [
  { id: "large", title: "Large Cap", sub: "Market cap > ₹20,000 Cr" },
  { id: "mid",   title: "Mid Cap",   sub: "Market cap ₹5,000 – 20,000 Cr" },
  { id: "small", title: "Small Cap", sub: "Market cap < ₹5,000 Cr" },
  { id: "other", title: "Others",    sub: "Bonds, ETFs, Gold" },
];

const CAP_COLORS: Record<CapId, { bar: string; mark: string }> = {
  large: { bar: "oklch(60% 0.13 250)", mark: "oklch(45% 0.13 250)" },
  mid:   { bar: "oklch(65% 0.14 180)", mark: "oklch(50% 0.14 180)" },
  small: { bar: "oklch(72% 0.15 80)",  mark: "oklch(55% 0.15 80)" },
  other: { bar: "oklch(60% 0.05 280)", mark: "oklch(50% 0.05 280)" },
};

function classifyCap(h: HoldingAction): CapId {
  const sym = h.symbol.toUpperCase();
  if (sym.includes("SGB") || sym.endsWith("BEES") || sym.includes("ETF")) return "other";
  const cr = h.market_cap;
  if (cr == null || cr <= 0) return "small";
  if (cr >= 20000) return "large";
  if (cr >= 5000) return "mid";
  return "small";
}

function instrumentLabel(h: HoldingAction): string | null {
  const sym = h.symbol.toUpperCase();
  if (sym.includes("SGB")) return "Sovereign Gold Bond";
  if (sym.endsWith("BEES")) return "ETF";
  if (sym.includes("ETF")) return "ETF";
  return null;
}

function fmtCompact(n: number): string {
  const sign = n < 0 ? "-" : "";
  const abs = Math.abs(n);
  if (abs >= 10_000_000) return `${sign}${(abs / 10_000_000).toFixed(2)} Cr`;
  if (abs >= 100_000) return `${sign}${(abs / 100_000).toFixed(2)} L`;
  if (abs >= 1000) return `${sign}${(abs / 1000).toFixed(1)} K`;
  return `${sign}${Math.round(abs)}`;
}

const VERDICT_PILL: Record<HoldingAction["action"], { bg: string; color: string; text: string }> = {
  SELL:       { bg: "var(--act-bg)",    color: "var(--act)",    text: "ACT NOW" },
  ACCUMULATE: { bg: "var(--buy-bg)",    color: "var(--buy)",    text: "BUY" },
  WATCHFUL:   { bg: "var(--review-bg)", color: "var(--review)", text: "REVIEW" },
  HOLD:       { bg: "var(--hold-bg)",   color: "var(--hold)",   text: "HOLD" },
};

interface Props {
  holdings: HoldingAction[];
  onClickSymbol?: (h: HoldingAction) => void;
}

type SortKey = "symbol" | "conf" | "qty" | "avg" | "ltp" | "pl" | "plPct" | "dayPl" | "dayPct";

export default function PortfolioDetails({ holdings, onClickSymbol }: Props) {
  const priv = usePrivacyMode();
  const mv = (v: string) => priv ? "••••" : v;
  const [openGroups, setOpenGroups] = useState<Record<CapId, boolean>>({
    large: true, mid: true, small: true, other: false,
  });
  const [filter, setFilter] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("plPct");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");

  const onSort = (k: SortKey) => {
    if (sortKey === k) setSortDir(d => d === "asc" ? "desc" : "asc");
    else { setSortKey(k); setSortDir("desc"); }
  };
  const sortIcon = (k: SortKey) => sortKey !== k ? "↕" : sortDir === "asc" ? "↑" : "↓";

  // Annotate each holding with cap and a sortKey-friendly view
  const enriched = useMemo(() => holdings.map(h => ({
    ...h,
    cap: classifyCap(h),
    plPct: h.pnl_pct,
    pl: h.pnl,
    dayPct: h.day_change_pct,
    dayPl: h.day_pnl,
    qty: h.quantity,
    avg: h.average_price,
    ltp: h.last_price,
    conf: h.confidence,
  })), [holdings]);

  const filtered = useMemo(() => {
    const q = filter.toLowerCase().trim();
    if (!q) return enriched;
    return enriched.filter(h => h.symbol.toLowerCase().includes(q));
  }, [enriched, filter]);

  const sorted = useMemo(() => {
    const arr = [...filtered];
    arr.sort((a, b) => {
      const av = (a as Record<string, unknown>)[sortKey] ?? -Infinity;
      const bv = (b as Record<string, unknown>)[sortKey] ?? -Infinity;
      if (typeof av === "string" && typeof bv === "string") {
        return sortDir === "asc" ? av.localeCompare(bv) : bv.localeCompare(av);
      }
      const an = typeof av === "number" ? av : Number(av);
      const bn = typeof bv === "number" ? bv : Number(bv);
      return sortDir === "asc" ? an - bn : bn - an;
    });
    return arr;
  }, [filtered, sortKey, sortDir]);

  const grouped = useMemo(() => CAP_GROUPS.map(g => {
    const rows = sorted.filter(h => h.cap === g.id);
    const totalInvested = rows.reduce((s, h) => s + h.avg * h.qty, 0);
    const totalCurrent  = rows.reduce((s, h) => s + h.ltp * h.qty, 0);
    const totalPL = totalCurrent - totalInvested;
    const totalPLPct = totalInvested > 0 ? (totalPL / totalInvested) * 100 : 0;
    return { ...g, rows, totalInvested, totalCurrent, totalPL, totalPLPct };
  }), [sorted]);

  const portfolioInvested = grouped.reduce((s, g) => s + g.totalInvested, 0);

  return (
    <section style={{ marginTop: 22 }}>
      <div style={{
        display: "flex", justifyContent: "space-between", alignItems: "flex-end",
        gap: 16, marginBottom: 14, flexWrap: "wrap",
      }}>
        <div>
          <h3 style={{
            margin: 0, fontFamily: "var(--font-serif)", fontSize: 26, fontWeight: 600,
            letterSpacing: "-0.015em",
          }}>Portfolio Details</h3>
          <p style={{ margin: "6px 0 0", fontSize: 14, color: "var(--label-tertiary)" }}>
            {holdings.length} instruments · grouped by market cap
          </p>
        </div>
        <div style={{
          position: "relative",
          background: "var(--bg-primary)",
          border: "1px solid var(--separator-light)",
          borderRadius: 8, padding: "0 10px 0 30px",
        }}>
          <span style={{
            position: "absolute", left: 10, top: "50%", transform: "translateY(-50%)",
            color: "var(--label-tertiary)", fontSize: 14,
          }}>⌕</span>
          <input
            type="text"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Filter by symbol…"
            style={{
              border: 0, background: "transparent", outline: "none",
              fontSize: 13, color: "var(--label-primary)",
              padding: "8px 0", width: 220,
            }}
          />
        </div>
      </div>

      <div style={{
        background: "var(--bg-primary)",
        border: "1px solid var(--separator-light)",
        borderRadius: 12,
        overflowX: "auto",
      }}>
        {/* Table head — column template + minWidth must match the data
            row below or the right-most columns drift off. */}
        <div style={{
          display: "grid",
          gridTemplateColumns: "minmax(180px, 1.6fr) 100px 70px 70px 90px 90px 100px 90px 100px 80px",
          alignItems: "center", gap: 8, padding: "0 18px", minWidth: 1100,
          height: 42,
          background: "var(--bg-secondary)",
          borderBottom: "1px solid var(--separator-light)",
          fontSize: 11, fontWeight: 600, color: "var(--label-tertiary)",
          textTransform: "uppercase" as const, letterSpacing: "0.06em",
        }}>
          <HeadCell label="Stock" sortKey="symbol" current={sortKey} icon={sortIcon("symbol")} onClick={onSort} />
          <div>Action</div>
          <HeadCell label="Conf" sortKey="conf" current={sortKey} icon={sortIcon("conf")} onClick={onSort} numeric />
          <HeadCell label="Qty" sortKey="qty" current={sortKey} icon={sortIcon("qty")} onClick={onSort} numeric />
          <HeadCell label="Avg" sortKey="avg" current={sortKey} icon={sortIcon("avg")} onClick={onSort} numeric />
          <HeadCell label="LTP" sortKey="ltp" current={sortKey} icon={sortIcon("ltp")} onClick={onSort} numeric />
          <HeadCell label="P&L" sortKey="pl" current={sortKey} icon={sortIcon("pl")} onClick={onSort} numeric />
          <HeadCell label="P&L %" sortKey="plPct" current={sortKey} icon={sortIcon("plPct")} onClick={onSort} numeric />
          <HeadCell label="Day P&L" sortKey="dayPl" current={sortKey} icon={sortIcon("dayPl")} onClick={onSort} numeric />
          <HeadCell label="Day %" sortKey="dayPct" current={sortKey} icon={sortIcon("dayPct")} onClick={onSort} numeric />
        </div>

        {grouped.map(g => {
          const isOpen = openGroups[g.id];
          if (g.rows.length === 0) return null;
          const allocPct = portfolioInvested > 0 ? (g.totalInvested / portfolioInvested) * 100 : 0;
          const colors = CAP_COLORS[g.id];

          return (
            <div key={g.id}>
              <button
                onClick={() => setOpenGroups(s => ({ ...s, [g.id]: !s[g.id] }))}
                style={{
                  display: "grid",
                  gridTemplateColumns: "16px auto 1fr auto auto",
                  alignItems: "center", gap: 8,
                  width: "100%", padding: "0 14px",
                  height: 50,
                  background: "linear-gradient(180deg, var(--bg-secondary), var(--bg-primary))",
                  borderBottom: "1px solid var(--separator-light)",
                  borderTop: "1px solid var(--separator-light)",
                  fontSize: 13, cursor: "pointer", textAlign: "left",
                  border: "0", color: "var(--label-primary)",
                  fontFamily: "inherit", minWidth: 1100,
                }}
                aria-expanded={isOpen}
              >
                <span style={{
                  display: "inline-block",
                  transform: isOpen ? "rotate(180deg)" : "rotate(0deg)",
                  transition: "transform .15s", color: "var(--label-tertiary)", fontSize: 12,
                }}>▾</span>
                <span style={{
                  fontFamily: "var(--font-serif)", fontWeight: 600, fontSize: 16,
                  letterSpacing: "-0.01em", whiteSpace: "nowrap",
                }}>{g.title}</span>
                <span style={{
                  fontSize: 12, color: "var(--label-tertiary)",
                  whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
                }}>
                  {g.rows.length} {g.rows.length === 1 ? "instrument" : "instruments"} · {g.sub}
                </span>
                <span style={{
                  display: "inline-flex", alignItems: "center", gap: 8,
                  minWidth: 110, justifyContent: "flex-end",
                }}>
                  <span style={{
                    position: "relative", width: 60, height: 6,
                    background: "var(--bg-secondary)", borderRadius: 3, overflow: "hidden",
                    border: "1px solid var(--separator-light)",
                  }}>
                    <span style={{
                      position: "absolute", inset: 0, right: "auto",
                      width: `${allocPct}%`, background: colors.bar, borderRadius: 3,
                    }} />
                  </span>
                  <span style={{
                    fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--label-tertiary)",
                    fontWeight: 500,
                  }}>{allocPct.toFixed(0)}%</span>
                </span>
                <span style={{
                  fontFamily: "var(--font-mono)", fontSize: 13.5, fontWeight: 600,
                  minWidth: 130, textAlign: "right", whiteSpace: "nowrap",
                  color: g.totalPL >= 0 ? "var(--buy)" : "var(--act)",
                }}>
                  {mv(`${g.totalPL >= 0 ? "+" : ""}${fmtCompact(g.totalPL)}`)}
                  <span style={{ color: "var(--label-tertiary)", fontWeight: 400, marginLeft: 4 }}>
                    ({pctStr(g.totalPLPct)})
                  </span>
                </span>
              </button>

              {isOpen && g.rows.map(h => {
                const v = VERDICT_PILL[h.action];
                const inst = instrumentLabel(h);
                return (
                  <div
                    key={h.symbol}
                    onClick={() => onClickSymbol?.(h)}
                    style={{
                      display: "grid",
                      gridTemplateColumns: "minmax(180px, 1.6fr) 100px 70px 70px 90px 90px 100px 90px 100px 80px",
                      alignItems: "center", gap: 8, padding: "0 18px", minWidth: 1100,
                      height: 56, fontSize: 13.5,
                      borderBottom: "1px solid var(--separator-light)",
                      cursor: onClickSymbol ? "pointer" : "default",
                      transition: "background .12s",
                    }}
                    onMouseEnter={(e) => (e.currentTarget.style.background = "var(--bg-secondary)")}
                    onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
                  >
                    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                      <div style={{
                        width: 28, height: 28, borderRadius: 6,
                        display: "grid", placeItems: "center",
                        background: `linear-gradient(135deg, ${colors.mark}, color-mix(in srgb, ${colors.mark} 65%, black))`,
                        color: "white", fontWeight: 700, fontSize: 12,
                        fontFamily: "var(--font-mono)",
                      }}>{h.symbol[0]}</div>
                      <div style={{ minWidth: 0 }}>
                        <div style={{ fontWeight: 600, fontSize: 13.5, lineHeight: 1.2, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                          {h.symbol}
                        </div>
                        {inst && (
                          <div style={{ fontSize: 11, color: "var(--label-tertiary)", marginTop: 2 }}>
                            {inst}
                          </div>
                        )}
                      </div>
                    </div>
                    <div>
                      <span style={{
                        fontSize: 10.5, fontWeight: 700, letterSpacing: "0.06em",
                        padding: "3px 8px", borderRadius: 4, whiteSpace: "nowrap",
                        background: v.bg, color: v.color,
                      }}>{v.text}</span>
                    </div>
                    <NumCell value={h.conf == null ? "—" : `${Math.round(h.conf)}%`} muted={h.conf == null} />
                    <NumCell value={priv ? "••" : h.qty.toLocaleString("en-IN")} />
                    <NumCell value={mv(h.avg.toFixed(2))} />
                    <NumCell value={mv(h.ltp.toFixed(2))} />
                    <NumCell value={mv(`${h.pl >= 0 ? "+" : ""}${fmtCompact(h.pl)}`)} color={h.pl >= 0 ? "var(--buy)" : "var(--act)"} />
                    <NumCell value={pctStr(h.plPct)} color={h.plPct >= 0 ? "var(--buy)" : "var(--act)"} />
                    <NumCell value={mv(`${h.dayPl >= 0 ? "+" : ""}${fmtCompact(h.dayPl)}`)} color={h.dayPl >= 0 ? "var(--buy)" : "var(--act)"} />
                    <NumCell value={pctStr(h.dayPct)} color={h.dayPct >= 0 ? "var(--buy)" : "var(--act)"} />
                  </div>
                );
              })}
            </div>
          );
        })}
      </div>
    </section>
  );
}

function HeadCell({ label, sortKey, current, icon, onClick, numeric }: {
  label: string; sortKey: SortKey; current: SortKey; icon: string; onClick: (k: SortKey) => void; numeric?: boolean;
}) {
  return (
    <button
      onClick={() => onClick(sortKey)}
      style={{
        border: 0, background: "transparent", padding: 0,
        font: "inherit", color: "inherit", cursor: "pointer",
        textTransform: "inherit", letterSpacing: "inherit",
        display: "flex", alignItems: "center", gap: 6,
        justifyContent: numeric ? "flex-end" : "flex-start",
        textAlign: numeric ? "right" : "left",
        whiteSpace: "nowrap", minWidth: 0,
      }}
    >
      {label}
      <span style={{
        fontSize: 10, fontWeight: 400,
        color: current === sortKey ? "var(--label-secondary)" : "var(--label-quaternary)",
      }}>{icon}</span>
    </button>
  );
}

function NumCell({ value, color, muted }: { value: string; color?: string; muted?: boolean }) {
  return (
    <div style={{
      display: "flex", alignItems: "center", justifyContent: "flex-end",
      minWidth: 0, fontFamily: "var(--font-mono)",
      color: muted ? "var(--label-quaternary)" : (color || "var(--label-primary)"),
    }}>
      {value}
    </div>
  );
}
