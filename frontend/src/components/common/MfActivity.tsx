"use client";

import React, { useEffect, useState } from "react";
import { api } from "@/lib/api";

interface HoldingRow {
  date: string;
  promoter_pct: number | null;
  promoter_pledged_pct: number | null;
  pledged_total_pct: number | null;
  mf_pct: number | null;
  fii_pct: number | null;
  di_pct: number | null;
  insurance_pct: number | null;
  retail_pct: number | null;
  other_pct: number | null;
  delta_prev?: Record<string, number | null> | null;
}

interface FundRow {
  fund_name: string;
  fund_full_name: string;
  weight: number | null;
  market_cap_pct: number | null;
  change_3m: number | null;
  current_rank: number | null;
  prev_rank: number | null;
}

interface Narrative {
  title: string | null;
  message: string | null;
  description: string | null;
  mood: string | null;
}

interface MfData {
  symbol: string;
  available: boolean;
  mf_holding_pct: number | null;
  fii_holding_pct: number | null;
  promoter_pct: number | null;
  public_pct: number | null;
  mf_count: number;
  top_mf_holders: string[];
  holding_history?: HoldingRow[] | null;
  top_mf_funds?: FundRow[] | null;
  narratives?: Narrative[] | null;
}

interface MfChange {
  fund_name: string;
  amc: string;
  category: string;
  quantity: number;
  change_qty: number;
  change_pct: number;
  change_type: "added" | "reduced" | "new" | "exited" | "unchanged";
}

interface MfBuySell {
  symbol: string;
  available: boolean;
  stock_name?: string;
  total_mf_holders?: number;
  active_fund_holders?: number;
  month?: string;
  summary?: {
    added: number;
    reduced: number;
    new_entry: number;
    exited: number;
    unchanged: number;
  };
  changes?: MfChange[];
}

function fmtPct(val: number | null | undefined): string {
  if (val === null || val === undefined) return "--";
  return `${val.toFixed(1)}%`;
}

function fmtQty(n: number): string {
  if (Math.abs(n) >= 10000000) return `${(n / 10000000).toFixed(2)} Cr`;
  if (Math.abs(n) >= 100000) return `${(n / 100000).toFixed(1)} L`;
  if (Math.abs(n) >= 1000) return `${(n / 1000).toFixed(1)} K`;
  return n.toLocaleString("en-IN");
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
      <span style={{ color: "#48484A", fontSize: 13 }}>{label}</span>
      <span style={{ color: "#1D1D1F", fontSize: 13, fontWeight: "bold" }}>{value}</span>
    </div>
  );
}

export default function MfActivity({ symbol }: { symbol: string }) {
  const [data, setData] = useState<MfData | null>(null);
  const [buysell, setBuysell] = useState<MfBuySell | null>(null);
  const [loading, setLoading] = useState(true);
  const [showChanges, setShowChanges] = useState(false);

  useEffect(() => {
    setLoading(true);
    Promise.all([
      api.get<MfData>(`/api/market-data/mf-activity/${symbol}`).catch(() => null),
      api.get<MfBuySell>(`/api/market-data/mf-buysell/${symbol}`).catch(() => null),
    ]).then(([mf, bs]) => {
      setData(mf);
      setBuysell(bs);
      setLoading(false);
    });
  }, [symbol]);

  const s = buysell?.summary;

  return (
    <div style={{ borderTop: "1px solid rgba(142,142,147,0.15)", paddingTop: 12 }}>
      <h3 style={{ fontSize: 11, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 8, color: "#6E6E73" }}>
        Mutual Fund Activity
      </h3>

      {loading && (
        <div style={{ padding: "8px 0" }}>
          <div style={{ height: 12, borderRadius: 4, backgroundColor: "rgba(142,142,147,0.12)", width: "80%", marginBottom: 8 }} />
          <div style={{ height: 12, borderRadius: 4, backgroundColor: "rgba(142,142,147,0.12)", width: "60%" }} />
        </div>
      )}

      {!loading && (
        <div style={{ padding: 12, borderRadius: 8, backgroundColor: "rgba(142,142,147,0.05)", border: "1px solid rgba(142,142,147,0.1)" }}>

          {/* Shareholding pattern from Tickertape */}
          {data?.available && (
            <div style={{ marginBottom: 10 }}>
              <Row label="MF Holding" value={fmtPct(data.mf_holding_pct)} />
              <Row label="FII/FPI" value={fmtPct(data.fii_holding_pct)} />
              <Row label="Promoter" value={fmtPct(data.promoter_pct)} />
              {data.public_pct != null && <Row label="Public" value={fmtPct(data.public_pct)} />}
            </div>
          )}

          {/* MF Buy/Sell from mfdata.in */}
          {s && (
            <div style={{ borderTop: data?.available ? "1px solid rgba(142,142,147,0.1)" : "none", paddingTop: data?.available ? 10 : 0 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: "#1D1D1F", marginBottom: 8 }}>
                Last Month Changes
                {buysell?.month && <span style={{ color: "#6E6E73", fontWeight: 400 }}> ({buysell.month})</span>}
              </div>

              <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 10 }}>
                {s.added > 0 && (
                  <span style={{ fontSize: 12, padding: "3px 10px", borderRadius: 12, backgroundColor: "rgba(52,199,89,0.08)", color: "#248A3D", fontWeight: 600 }}>
                    {s.added} added
                  </span>
                )}
                {s.new_entry > 0 && (
                  <span style={{ fontSize: 12, padding: "3px 10px", borderRadius: 12, backgroundColor: "rgba(0,122,255,0.08)", color: "#007AFF", fontWeight: 600 }}>
                    {s.new_entry} new entry
                  </span>
                )}
                {s.reduced > 0 && (
                  <span style={{ fontSize: 12, padding: "3px 10px", borderRadius: 12, backgroundColor: "rgba(255,59,48,0.08)", color: "#D70015", fontWeight: 600 }}>
                    {s.reduced} reduced
                  </span>
                )}
                {s.exited > 0 && (
                  <span style={{ fontSize: 12, padding: "3px 10px", borderRadius: 12, backgroundColor: "rgba(255,59,48,0.08)", color: "#D70015", fontWeight: 600 }}>
                    {s.exited} exited
                  </span>
                )}
                {s.unchanged > 0 && (
                  <span style={{ fontSize: 12, padding: "3px 10px", borderRadius: 12, backgroundColor: "#F2F2F7", color: "#6E6E73" }}>
                    {s.unchanged} unchanged
                  </span>
                )}
              </div>

              {buysell?.total_mf_holders && (
                <div style={{ fontSize: 12, color: "#6E6E73", marginBottom: 6 }}>
                  Held by {buysell.total_mf_holders} mutual fund schemes
                </div>
              )}

              {/* Detailed changes */}
              {buysell?.changes && buysell.changes.length > 0 && (
                <div>
                  <button
                    onClick={() => setShowChanges(!showChanges)}
                    style={{ fontSize: 12, color: "#007AFF", background: "none", border: "none", cursor: "pointer", padding: 0 }}
                  >
                    {showChanges ? "Hide details" : "Show fund-wise changes"}
                  </button>

                  {showChanges && (
                    <div style={{ marginTop: 8 }}>
                      {buysell.changes.filter(c => c.change_type !== "unchanged").map((c, i) => (
                        <div key={i} style={{ display: "flex", alignItems: "flex-start", gap: 6, marginBottom: 6, paddingLeft: 4 }}>
                          <span style={{
                            flexShrink: 0, marginTop: 2, fontSize: 10,
                            color: c.change_type === "added" || c.change_type === "new" ? "#248A3D"
                              : c.change_type === "reduced" || c.change_type === "exited" ? "#D70015"
                              : "#6E6E73",
                          }}>
                            {c.change_type === "added" || c.change_type === "new" ? "▲" : c.change_type === "reduced" || c.change_type === "exited" ? "▼" : "●"}
                          </span>
                          <div style={{ flex: 1, minWidth: 0 }}>
                            <div style={{ fontSize: 12, color: "#1D1D1F" }}>{c.fund_name}</div>
                            <div style={{ fontSize: 11, color: "#6E6E73" }}>
                              {c.change_type === "added" && `Added ${fmtQty(c.change_qty)} shares (+${c.change_pct}%)`}
                              {c.change_type === "reduced" && `Reduced ${fmtQty(Math.abs(c.change_qty))} shares (${c.change_pct}%)`}
                              {c.change_type === "new" && `New entry — ${fmtQty(c.quantity)} shares`}
                              {c.change_type === "exited" && "Exited position"}
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {/* Narratives (Tickertape's insight bullets) */}
          {data?.narratives && data.narratives.length > 0 && (
            <div style={{ borderTop: "1px solid rgba(142,142,147,0.1)", marginTop: 10, paddingTop: 10 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: "#1D1D1F", marginBottom: 6 }}>
                Shareholding insights
              </div>
              {data.narratives.slice(0, 4).map((n, i) => {
                const mood = (n.mood || "").toLowerCase();
                const bg =
                  mood === "positive" ? "rgba(36,138,61,0.08)"
                  : mood === "negative" ? "rgba(215,0,21,0.08)"
                  : "rgba(142,142,147,0.05)";
                const fg =
                  mood === "positive" ? "#248A3D"
                  : mood === "negative" ? "#D70015"
                  : "#6E6E73";
                return (
                  <div key={i} style={{ padding: 8, background: bg, borderRadius: 6, marginBottom: 4 }}>
                    <div style={{ fontSize: 11, fontWeight: 600, color: fg, marginBottom: 2 }}>
                      {n.title}
                    </div>
                    <div style={{ fontSize: 11, color: "#48484A", lineHeight: 1.35 }}>
                      {n.message}
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          {/* Quarterly history table */}
          {data?.holding_history && data.holding_history.length > 0 && (
            <div style={{ borderTop: "1px solid rgba(142,142,147,0.1)", marginTop: 10, paddingTop: 10 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: "#1D1D1F", marginBottom: 6 }}>
                Shareholding by quarter
              </div>
              <div style={{ overflowX: "auto" }}>
                <table style={{ width: "100%", fontSize: 11, borderCollapse: "collapse" }}>
                  <thead>
                    <tr style={{ color: "#6E6E73", textAlign: "right" }}>
                      <th style={{ textAlign: "left", padding: "3px 6px" }}>Quarter</th>
                      <th style={{ padding: "3px 6px" }}>Promoter</th>
                      <th style={{ padding: "3px 6px" }}>MF</th>
                      <th style={{ padding: "3px 6px" }}>FII</th>
                      <th style={{ padding: "3px 6px" }}>DII</th>
                      <th style={{ padding: "3px 6px" }}>Retail</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.holding_history.slice(0, 6).map((row, i) => (
                      <tr key={row.date} style={{ borderTop: i > 0 ? "1px solid rgba(142,142,147,0.08)" : undefined }}>
                        <td style={{ textAlign: "left", padding: "4px 6px", color: "#48484A" }}>
                          {row.date}
                        </td>
                        <HistCell val={row.promoter_pct} delta={row.delta_prev?.promoter ?? null} />
                        <HistCell val={row.mf_pct} delta={row.delta_prev?.mf ?? null} />
                        <HistCell val={row.fii_pct} delta={row.delta_prev?.fii ?? null} />
                        <HistCell val={row.di_pct} delta={row.delta_prev?.di ?? null} />
                        <HistCell val={row.retail_pct} delta={row.delta_prev?.retail ?? null} />
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Top MF rankings */}
          {data?.top_mf_funds && data.top_mf_funds.length > 0 && (
            <div style={{ borderTop: "1px solid rgba(142,142,147,0.1)", marginTop: 10, paddingTop: 10 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: "#1D1D1F", marginBottom: 6 }}>
                Top MF holders (by 3m change)
              </div>
              {data.top_mf_funds.slice(0, 8).map((f, i) => {
                const c3 = f.change_3m;
                const rankMove = f.current_rank != null && f.prev_rank != null ? f.prev_rank - f.current_rank : null;
                return (
                  <div key={i} style={{ display: "flex", alignItems: "flex-start", gap: 6, padding: "4px 0", fontSize: 11 }}>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ color: "#1D1D1F", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {f.fund_name}
                      </div>
                      <div style={{ color: "#6E6E73", fontSize: 10 }}>
                        weight {f.weight?.toFixed(2)}%
                        {f.current_rank != null && (
                          <>
                            {" · "}rank {f.current_rank}
                            {rankMove != null && rankMove !== 0 && (
                              <span style={{ color: rankMove > 0 ? "#248A3D" : "#D70015", marginLeft: 4 }}>
                                {rankMove > 0 ? `↑${rankMove}` : `↓${Math.abs(rankMove)}`}
                              </span>
                            )}
                          </>
                        )}
                      </div>
                    </div>
                    {c3 != null && (
                      <span
                        style={{
                          fontFamily: "monospace",
                          fontSize: 11,
                          fontWeight: 600,
                          color: c3 > 0 ? "#248A3D" : c3 < 0 ? "#D70015" : "#6E6E73",
                          whiteSpace: "nowrap",
                        }}
                      >
                        {c3 > 0 ? "+" : ""}
                        {c3.toFixed(2)}%
                      </span>
                    )}
                  </div>
                );
              })}
            </div>
          )}

          {/* No data */}
          {!data?.available && !s && (
            <div style={{ fontSize: 13, color: "#6E6E73", textAlign: "center", padding: 8 }}>
              MF data not available
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function HistCell({ val, delta }: { val: number | null; delta: number | null }) {
  return (
    <td style={{ textAlign: "right", padding: "4px 6px", color: "#1D1D1F" }}>
      {val === null || val === undefined ? "—" : val.toFixed(2)}
      {delta !== null && delta !== undefined && Math.abs(delta) >= 0.005 && (
        <span
          style={{
            marginLeft: 4,
            fontSize: 9,
            color: delta > 0 ? "#248A3D" : "#D70015",
            fontWeight: 600,
          }}
        >
          {delta > 0 ? "+" : ""}
          {delta.toFixed(2)}
        </span>
      )}
    </td>
  );
}
