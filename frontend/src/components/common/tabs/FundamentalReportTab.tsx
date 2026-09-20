"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useLatestDecision } from "@/hooks/useLatestDecision";
import FreshnessChip from "@/components/ui/FreshnessChip";
import NarrativeStaleChip from "@/components/ui/NarrativeStaleChip";

/**
 * Stock Detail → "Fundamentals" tab.
 *
 * Shows:
 *  - Verdict pill (STRONG / FAIR / WEAK / NA + score)
 *  - "↻ Refresh" button (POST /api/fundamentals/refresh stock-scope)
 *  - Categorized table of every metric with current value, source,
 *    last-fetched timestamp.
 *  - Pencil icon to add a manual override on missing/wrong values.
 */

interface MetricDef {
  key: string;
  display_name: string;
  category: string;
  unit: string | null;
  description_md: string | null;
  formula: string | null;
}

interface VerdictResp {
  verdict: "STRONG" | "FAIR" | "WEAK" | "NA";
  score: number | null;
  rules_total: number;
  rules_passed: number;
  rules_failed: number;
  rules_missing: number;
  breakdown: Array<{
    metric_key: string;
    operator: string;
    threshold: { value?: number; low?: number; high?: number };
    weight: number;
    actual: number | string | null;
    status: "passed" | "failed" | "missing";
  }>;
  evaluated_at: string;
  snapshot_run_id: number | null;
  snapshot_fetched_at: string | null;
  snapshot_values?: Record<string, unknown>;
  snapshot_sources?: Record<string, string>;
}

const CATEGORY_LABEL: Record<string, string> = {
  profitability: "Profitability",
  growth: "Growth",
  valuation: "Valuation",
  ownership: "Ownership",
  financial_ratios: "Financial Ratios",
  cash_flow: "Cash Flow",
  trading: "Trading & Technical",
  sector_relative: "Sector-relative",
};

export default function FundamentalReportTab({ symbol, exchange }: { symbol: string; exchange: string }) {
  const [verdict, setVerdict] = useState<VerdictResp | null>(null);
  const [snapshot, setSnapshot] = useState<{ values: Record<string, unknown>; sources: Record<string, string>; fetched_at: string | null } | null>(null);
  const [catalog, setCatalog] = useState<Record<string, MetricDef[]>>({});
  const [refreshing, setRefreshing] = useState(false);
  const [manualOpen, setManualOpen] = useState<string | null>(null);
  const [manualValue, setManualValue] = useState("");
  const [manualSaving, setManualSaving] = useState(false);
  const [refreshingOwnership, setRefreshingOwnership] = useState(false);
  const { decision } = useLatestDecision(symbol);

  async function loadAll() {
    // Fetch verdict, metric catalog, and the technicals endpoint in
    // parallel. Technicals is the same source the Overview tab uses for
    // return_1m / return_3m / return_6m / return_1y, so falling back to
    // it ensures the two tabs report the same number instead of one
    // showing "-2.14%" and the other showing "—" for the same period.
    const [v, c, t] = await Promise.all([
      api.get<VerdictResp>(`/api/fundamentals/${symbol}/verdict`).catch(() => null),
      api.get<{ categories: Record<string, MetricDef[]> }>("/api/fundamentals/metrics").catch(() => null),
      api.get<Record<string, number | null>>(`/api/market-data/technicals/${symbol}?exchange=${exchange}`).catch(() => null),
    ]);
    if (v) setVerdict(v);
    if (c) setCatalog(c.categories);
    if (v) {
      // Use full snapshot values from the verdict response (includes all
      // metrics, not just the ones with rules).
      const values: Record<string, unknown> = v.snapshot_values ?? {};
      // Fallback: fill from breakdown for any metrics not in snapshot
      for (const b of v.breakdown) {
        if (b.actual !== null && b.actual !== undefined && !(b.metric_key in values)) {
          values[b.metric_key] = b.actual;
        }
      }
      // Technicals fallback: when the metric_engine snapshot is missing
      // a return field, populate it from the technicals endpoint that
      // the Overview tab uses. Eliminates the cross-tab divergence the
      // QA report flagged (Overview "-2.14%" vs Fundamentals "—").
      if (t) {
        const FALLBACK_MAP: Record<string, string> = {
          ret_1m: "return_1m",
          ret_3m: "return_3m",
          ret_6m: "return_6m",
          ret_1y: "return_1y",
          ret_1d: "return_1d", // technicals doesn't currently expose this
        };
        for (const [snapKey, techKey] of Object.entries(FALLBACK_MAP)) {
          if (values[snapKey] == null && t[techKey] != null) {
            values[snapKey] = t[techKey];
          }
        }
      }
      setSnapshot({ values, sources: v.snapshot_sources ?? {}, fetched_at: v.snapshot_fetched_at });
    }
  }

  useEffect(() => {
    loadAll();
  }, [symbol]);

  async function refresh() {
    setRefreshing(true);
    try {
      await Promise.all([
        api.post("/api/fundamentals/refresh", { scope: "stock", symbol }),
        api.post(`/api/smart-money/shareholding/${symbol}/refresh`).catch(() => null),
      ]);
      await loadAll();
    } finally {
      setRefreshing(false);
    }
  }

  async function saveManual(metricKey: string) {
    setManualSaving(true);
    try {
      const num = Number(manualValue);
      const body = Number.isFinite(num) && manualValue.trim() !== ""
        ? { metric_key: metricKey, value_num: num }
        : { metric_key: metricKey, value_str: manualValue };
      await api.post(`/api/fundamentals/${symbol}/manual-entry`, body);
      setManualOpen(null);
      setManualValue("");
      await refresh(); // re-run engine so the override surfaces
    } finally {
      setManualSaving(false);
    }
  }

  async function refreshOwnership() {
    setRefreshingOwnership(true);
    try {
      await api.post(`/api/smart-money/shareholding/${symbol}/refresh`).catch(() => null);
      await refresh();
    } finally {
      setRefreshingOwnership(false);
    }
  }

  const ownershipQuarterEnd = snapshot?.values["_ownership_quarter_end"] as string | undefined;

  const ruleStatus: Record<string, "passed" | "failed" | "missing"> = {};
  if (verdict) {
    for (const b of verdict.breakdown) ruleStatus[b.metric_key] = b.status;
  }

  const verdictColor =
    verdict?.verdict === "STRONG" ? "var(--buy)"
    : verdict?.verdict === "FAIR" ? "var(--review)"
    : verdict?.verdict === "WEAK" ? "var(--act)"
    : "var(--label-tertiary)";
  const verdictBg =
    verdict?.verdict === "STRONG" ? "rgba(48,209,88,0.10)"
    : verdict?.verdict === "FAIR" ? "var(--review-bg)"
    : verdict?.verdict === "WEAK" ? "var(--act-bg)"
    : "var(--bg-secondary)";

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {/* Verdict header */}
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        gap: 12, flexWrap: "wrap", padding: "12px 14px",
        background: verdictBg, border: `1px solid ${verdictColor}33`,
        borderRadius: 10,
      }}>
        <div>
          <div style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: "0.08em", color: "var(--label-tertiary)" }}>
            Fundamental Analysis
          </div>
          <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginTop: 4 }}>
            <span style={{ fontSize: 22, fontWeight: 700, fontFamily: "var(--font-serif)", color: verdictColor }}>
              {verdict?.verdict ?? "—"}
            </span>
            {verdict?.score != null && (
              <span style={{ fontFamily: "var(--font-mono)", fontSize: 14, color: "var(--label-secondary)" }}>
                {verdict.score}/100
              </span>
            )}
          </div>
          {verdict && (
            <div style={{ fontSize: 11, color: "var(--label-tertiary)", marginTop: 4, display: "flex", flexWrap: "wrap", alignItems: "center", gap: 8 }}>
              <span
                title={`Weighted score — high-importance rules count more. Raw pass rate: ${verdict.rules_passed}/${verdict.rules_total - verdict.rules_missing} of evaluable rules (${verdict.rules_missing} missing).`}
                style={{ cursor: "help" }}
              >
                {verdict.rules_passed} passed · {verdict.rules_failed} failed · {verdict.rules_missing} missing
              </span>
              {verdict.snapshot_fetched_at && (
                <FreshnessChip kind="snapshot" iso={verdict.snapshot_fetched_at} />
              )}
            </div>
          )}
        </div>
        <button
          onClick={refresh}
          disabled={refreshing}
          style={{
            padding: "6px 14px", borderRadius: 7,
            background: "var(--label-primary)", color: "var(--bg-primary)",
            border: 0, cursor: refreshing ? "wait" : "pointer",
            fontSize: 12.5, fontWeight: 600, whiteSpace: "nowrap",
          }}
        >
          {refreshing ? "Refreshing…" : "↻ Refresh fundamentals"}
        </button>
      </div>

      {/* AI Valuation View — from latest deep analysis. Surfaces a
          NarrativeStaleChip when the analysis is meaningfully older than
          the fundamentals snapshot so the analyst sees why the prose may
          reference different numbers than the structured cards below. */}
      {decision?.valuation_view && (() => {
        let lagHours: number | null = null;
        if (decision.created_at && verdict?.snapshot_fetched_at) {
          const lag = (new Date(verdict.snapshot_fetched_at).getTime()
            - new Date(decision.created_at).getTime()) / 3600000;
          if (Number.isFinite(lag) && lag > 24) lagHours = lag;
        }
        return (
          <div style={{
            padding: "12px 14px", borderRadius: 10,
            background: "var(--bg-secondary)", border: "1px solid var(--separator-light)",
          }}>
            <div style={{
              display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap",
              marginBottom: 6,
            }}>
              <span style={{
                fontSize: 11, fontWeight: 600, textTransform: "uppercase",
                letterSpacing: "0.06em", color: "var(--label-tertiary)",
              }}>AI Valuation Notes</span>
              {decision.created_at && (
                <FreshnessChip kind="ai" iso={decision.created_at} />
              )}
              {lagHours != null && <NarrativeStaleChip lagHours={lagHours} />}
            </div>
            <p style={{
              fontSize: 13, lineHeight: 1.55, color: "var(--label-primary)", margin: 0,
            }}>{decision.valuation_view}</p>
          </div>
        );
      })()}

      {/* Categorized tables — two columns at desktop, single column at
          <md so multi-word labels like "PE Premium vs Sector %" no longer
          tower one-word-per-line in a ~130 px right column. */}
      <div className="frt-category-grid" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
        <style jsx>{`
          @media (max-width: 720px) {
            .frt-category-grid { grid-template-columns: 1fr !important; }
          }
        `}</style>
        {Object.keys(CATEGORY_LABEL).filter((c) => catalog[c]?.length).map((cat) => (
          <div key={cat} style={{ border: "1px solid var(--separator-light)", borderRadius: 8, overflow: "hidden" }}>
            <div style={{
              padding: "8px 12px", background: "var(--bg-secondary)",
              fontSize: 11, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.06em",
              color: "var(--label-tertiary)", borderBottom: "1px solid var(--separator-light)",
              display: "flex", alignItems: "center", justifyContent: "space-between",
            }}>
              <span>{CATEGORY_LABEL[cat]}</span>
              {cat === "ownership" && (
                <span style={{ display: "inline-flex", alignItems: "center", gap: 6, textTransform: "none", fontWeight: 400, letterSpacing: "0" }}>
                  {ownershipQuarterEnd && (
                    <span style={{ fontSize: 10, color: "var(--label-quaternary)" }}>
                      as of {new Date(ownershipQuarterEnd + "T00:00:00").toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })}
                    </span>
                  )}
                  <button
                    onClick={refreshOwnership}
                    disabled={refreshingOwnership}
                    title="Re-fetch from NSE"
                    style={{
                      background: "transparent", border: 0, cursor: refreshingOwnership ? "wait" : "pointer",
                      color: "var(--label-tertiary)", fontSize: 13, padding: "0 2px", lineHeight: 1,
                    }}
                  >{refreshingOwnership ? "…" : "↻"}</button>
                </span>
              )}
            </div>
            <table style={{ width: "100%", fontSize: 12.5, borderCollapse: "collapse" }}>
              <tbody>
                {(catalog[cat] || []).map((m) => {
                  const v = snapshot?.values[m.key];
                  const has = v !== undefined && v !== null;
                  const st = ruleStatus[m.key];
                  const rowBg = st === "passed" ? "rgba(52,199,89,0.06)"
                    : st === "failed" ? "rgba(255,59,48,0.06)"
                    : undefined;
                  const valColor = st === "passed" ? "var(--system-green)"
                    : st === "failed" ? "var(--system-red)"
                    : has ? "var(--label-primary)" : "var(--label-quaternary)";
                  return (
                    <tr key={m.key} style={{ borderTop: "1px solid var(--separator-light)", background: rowBg }}>
                      <td style={{ padding: "6px 10px", color: "var(--label-primary)" }} title={m.description_md || ""}>
                        {/* Wrap label+unit in a nowrap span so "1-Day Return"
                            and "%" don't split across two lines at narrow
                            widths. The whole atomic pair either fits on one
                            line or wraps as a unit. */}
                        <span style={{ whiteSpace: "nowrap" }}>
                          {m.display_name}
                          {m.unit && <span style={{ color: "var(--label-quaternary)", marginLeft: 4, fontFamily: "var(--font-mono)", fontSize: 11 }}>{m.unit}</span>}
                        </span>
                      </td>
                      <td style={{ padding: "6px 10px", textAlign: "right", fontFamily: "var(--font-mono)", fontWeight: 600, color: valColor }}>
                        {has ? (typeof v === "number" ? (m.unit === "%" && Math.abs(v) < 1 ? (v * 100).toFixed(2) : v.toFixed(2)) : String(v)) : "—"}
                      </td>
                      <td style={{ padding: "6px 4px", textAlign: "right", width: 40 }}>
                        {manualOpen === m.key ? (
                          <span style={{ display: "inline-flex", gap: 4 }}>
                            <input
                              type="text" value={manualValue}
                              onChange={(e) => setManualValue(e.target.value)}
                              placeholder="value"
                              autoFocus
                              style={{
                                width: 60, padding: "3px 6px", fontSize: 12,
                                border: "1px solid var(--separator)", borderRadius: 4,
                                background: "var(--bg-primary)", color: "var(--label-primary)",
                                fontFamily: "var(--font-mono)",
                              }}
                            />
                            <button
                              onClick={() => saveManual(m.key)}
                              disabled={manualSaving}
                              style={{ fontSize: 11, padding: "3px 6px", borderRadius: 4, background: "var(--label-primary)", color: "var(--bg-primary)", border: 0, cursor: "pointer" }}
                            >Save</button>
                            <button
                              onClick={() => { setManualOpen(null); setManualValue(""); }}
                              style={{ fontSize: 11, padding: "3px 6px", borderRadius: 4, background: "transparent", color: "var(--label-tertiary)", border: "1px solid var(--separator)", cursor: "pointer" }}
                            >×</button>
                          </span>
                        ) : (
                          <button
                            onClick={() => { setManualOpen(m.key); setManualValue(has ? String(v) : ""); }}
                            aria-label={`Edit ${m.display_name}`}
                            style={{ fontSize: 11, color: "var(--label-tertiary)", background: "transparent", border: 0, cursor: "pointer" }}
                            title={has ? "Override value" : "Add manual value"}
                          >✎</button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ))}
      </div>
    </div>
  );
}
