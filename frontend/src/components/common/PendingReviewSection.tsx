"use client";

import React, { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { openStockDetail } from "@/lib/stock-detail";

export interface ReviewAlert {
  id: number;
  symbol: string;
  exchange: string;
  source: "watchlist" | "holding" | "both";
  trigger_type: "rule" | "news" | "valuation" | "verdict" | "sentiment";
  trigger_label: string;
  suggested_action: string | null;
  suggested_lane: string | null;
  payload: Record<string, unknown>;
  status: "pending" | "applied" | "dismissed";
  created_at: string | null;
  resolved_at: string | null;
}

interface ListResp {
  items: ReviewAlert[];
  pending_count: number;
  by_source: { watchlist: number; holding: number; both: number };
}

const TRIGGER_ICONS: Record<ReviewAlert["trigger_type"], string> = {
  rule: "⚡",
  news: "📰",
  valuation: "📉",
  verdict: "🎯",
  sentiment: "💬",
};

function fmtRelative(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "—";
  const sec = (Date.now() - d.getTime()) / 1000;
  if (sec < 60) return "just now";
  if (sec < 3600) return `${Math.round(sec / 60)}m ago`;
  if (sec < 86400) return `${Math.round(sec / 3600)}h ago`;
  return `${Math.round(sec / 86400)}d ago`;
}

interface Props {
  /** Filter alerts by source. "watchlist" includes "both"; "holding" includes "both". */
  source: "watchlist" | "holding";
  /** Optional callback after Apply/Dismiss to refresh the parent list. */
  onResolved?: () => void;
}

export default function PendingReviewSection({ source, onResolved }: Props) {
  const [alerts, setAlerts] = useState<ReviewAlert[]>([]);
  const [loading, setLoading] = useState(true);
  const [collapsed, setCollapsed] = useState(false);
  const [evaluating, setEvaluating] = useState(false);
  const [applyTarget, setApplyTarget] = useState<ReviewAlert | null>(null);
  const [dismissingId, setDismissingId] = useState<number | null>(null);

  async function load() {
    setLoading(true);
    try {
      const resp = await api.get<ListResp>("/api/review-alerts?status=pending&limit=50");
      setAlerts(resp.items.filter(a => a.source === source || a.source === "both"));
    } catch { setAlerts([]); }
    setLoading(false);
  }

  useEffect(() => { load(); }, [source]);

  async function evaluateNow() {
    setEvaluating(true);
    try {
      await api.post("/api/review-alerts/evaluate", {});
      await load();
    } catch { /* ignore */ }
    setEvaluating(false);
  }

  async function dismiss(alert: ReviewAlert) {
    setDismissingId(alert.id);
    try {
      await api.post(`/api/review-alerts/${alert.id}/dismiss`, {});
      setAlerts(prev => prev.filter(a => a.id !== alert.id));
      onResolved?.();
    } catch { /* ignore */ }
    setDismissingId(null);
  }

  async function applyConfirmed(alert: ReviewAlert, lane: string | null) {
    try {
      await api.post(`/api/review-alerts/${alert.id}/apply`, { confirm: true, lane });
      setAlerts(prev => prev.filter(a => a.id !== alert.id));
      onResolved?.();
    } catch { /* ignore */ }
    setApplyTarget(null);
  }

  function reviewClicked(alert: ReviewAlert) {
    // Scroll to the matching card if present, else open detail panel
    const el = document.getElementById(`pcard-${alert.symbol}`);
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "start" });
      el.style.transition = "box-shadow .35s ease";
      el.style.boxShadow = "0 0 0 4px color-mix(in srgb, var(--review) 25%, transparent), var(--shadow-md)";
      setTimeout(() => { el.style.boxShadow = ""; }, 1800);
    } else {
      openStockDetail(alert.symbol, alert.exchange);
    }
  }

  if (loading && alerts.length === 0) return null;
  if (!loading && alerts.length === 0) return null;

  return (
    <section style={{
      border: "1px solid color-mix(in srgb, var(--review) 25%, var(--separator-light))",
      background: "color-mix(in srgb, var(--review-bg) 60%, var(--bg-primary))",
      borderRadius: 12,
      marginBottom: 18,
      padding: collapsed ? "10px 14px" : 14,
      boxShadow: "var(--shadow-sm)",
    }}>
      <div style={{
        display: "flex", justifyContent: "space-between", alignItems: "center",
        cursor: "pointer", marginBottom: collapsed ? 0 : 12,
      }} onClick={() => setCollapsed(c => !c)}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 14 }}>🟡</span>
          <span style={{
            fontFamily: "var(--font-serif)", fontSize: 16, fontWeight: 600,
            color: "var(--label-primary)",
          }}>
            Pending Review
          </span>
          <span style={{
            padding: "2px 8px", borderRadius: 99, fontSize: 11, fontWeight: 600,
            background: "var(--review)", color: "white",
          }}>
            {alerts.length}
          </span>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <button
            onClick={(e) => { e.stopPropagation(); evaluateNow(); }}
            disabled={evaluating}
            title="Re-evaluate triggers"
            style={{
              fontSize: 11, padding: "4px 10px", borderRadius: 6,
              background: "transparent", color: "var(--label-tertiary)",
              border: "1px solid var(--separator)", cursor: evaluating ? "wait" : "pointer",
            }}
          >{evaluating ? "Evaluating…" : "⟳"}</button>
          <span style={{ fontSize: 11, color: "var(--label-tertiary)" }}>{collapsed ? "▾" : "▴"}</span>
        </div>
      </div>

      {!collapsed && (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {alerts.map(a => (
            <article key={a.id} style={{
              background: "var(--bg-primary)",
              border: "1px solid var(--separator-light)",
              borderRadius: 9, padding: "10px 14px",
              display: "flex", flexDirection: "column", gap: 6,
            }}>
              <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                <span style={{ fontSize: 13 }}>{TRIGGER_ICONS[a.trigger_type]}</span>
                <button
                  onClick={() => openStockDetail(a.symbol, a.exchange)}
                  style={{
                    fontFamily: "var(--font-mono)", fontWeight: 700, fontSize: 13,
                    color: "var(--label-primary)", background: "transparent",
                    border: 0, padding: 0, cursor: "pointer",
                  }}
                >{a.symbol}</button>
                <span style={{ fontSize: 12, color: "var(--label-secondary)", flex: 1, minWidth: 200 }}>
                  {a.trigger_label}
                </span>
                <span style={{ fontSize: 11, color: "var(--label-tertiary)" }}>{fmtRelative(a.created_at)}</span>
              </div>
              {a.suggested_action && (
                <div style={{ fontSize: 12, color: "var(--label-tertiary)", paddingLeft: 22 }}>
                  Suggested: <span style={{ color: "var(--label-primary)", fontWeight: 500 }}>{a.suggested_action}</span>
                </div>
              )}
              <div style={{ display: "flex", gap: 8, paddingLeft: 22, marginTop: 2 }}>
                <button
                  onClick={() => reviewClicked(a)}
                  style={{
                    fontSize: 11.5, padding: "4px 10px", borderRadius: 6,
                    background: "transparent", color: "var(--label-tertiary)",
                    border: "1px solid var(--separator)", cursor: "pointer",
                  }}
                >Review</button>
                <button
                  onClick={() => setApplyTarget(a)}
                  style={{
                    fontSize: 11.5, padding: "4px 10px", borderRadius: 6,
                    background: "var(--label-primary)", color: "var(--bg-primary)",
                    border: 0, cursor: "pointer", fontWeight: 600,
                  }}
                >Apply</button>
                <button
                  onClick={() => dismiss(a)}
                  disabled={dismissingId === a.id}
                  style={{
                    fontSize: 11.5, padding: "4px 10px", borderRadius: 6,
                    background: "transparent", color: "var(--act)",
                    border: "1px solid color-mix(in srgb, var(--act) 30%, transparent)",
                    cursor: dismissingId === a.id ? "wait" : "pointer",
                  }}
                >{dismissingId === a.id ? "…" : "Dismiss"}</button>
              </div>
            </article>
          ))}
        </div>
      )}

      {applyTarget && (
        <ApplyDialog
          alert={applyTarget}
          onCancel={() => setApplyTarget(null)}
          onConfirm={(lane) => applyConfirmed(applyTarget, lane)}
        />
      )}
    </section>
  );
}

const LANE_OPTIONS = [
  { value: "researching", label: "Researching" },
  { value: "awaiting", label: "Awaiting Correction" },
  { value: "exit", label: "Exit Watch" },
  { value: "hold", label: "Hold" },
];

function ApplyDialog({
  alert, onCancel, onConfirm,
}: {
  alert: ReviewAlert;
  onCancel: () => void;
  onConfirm: (lane: string | null) => void;
}) {
  const [lane, setLane] = useState<string>(alert.suggested_lane || "researching");
  const isHoldingOnly = alert.source === "holding";

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onCancel();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onCancel]);

  return (
    <>
      <div onClick={onCancel} style={{
        position: "fixed", inset: 0, zIndex: 70,
        background: "rgba(0,0,0,0.4)", backdropFilter: "blur(2px)",
      }} />
      <div role="dialog" aria-modal="true" style={{
        position: "fixed", top: "50%", left: "50%", transform: "translate(-50%, -50%)",
        zIndex: 71, width: "min(520px, 92vw)",
        background: "var(--bg-primary)",
        border: "1px solid var(--separator-light)",
        borderRadius: 14, boxShadow: "var(--shadow-lg)",
        overflow: "hidden",
      }}>
        <div style={{ padding: "16px 20px", borderBottom: "1px solid var(--separator-light)" }}>
          <div style={{
            fontFamily: "var(--font-serif)", fontSize: 18, fontWeight: 600,
            color: "var(--label-primary)",
          }}>Apply alert</div>
          <div style={{ fontSize: 12.5, color: "var(--label-tertiary)", marginTop: 2 }}>
            {alert.symbol} · {alert.trigger_label}
          </div>
        </div>
        <div style={{ padding: 20, display: "flex", flexDirection: "column", gap: 14 }}>
          {isHoldingOnly ? (
            <div style={{ fontSize: 13, color: "var(--label-secondary)", lineHeight: 1.5 }}>
              This stock is in your portfolio but not in any watchlist — applying will only mark
              the alert as reviewed. No lane to change.
            </div>
          ) : (
            <>
              <div>
                <div style={{
                  fontSize: 11, color: "var(--label-tertiary)",
                  textTransform: "uppercase", letterSpacing: "0.06em", fontWeight: 600,
                  marginBottom: 4,
                }}>Suggested action</div>
                <div style={{ fontSize: 13.5, color: "var(--label-primary)" }}>
                  {alert.suggested_action || "Re-evaluate"}
                </div>
              </div>
              <div>
                <div style={{
                  fontSize: 11, color: "var(--label-tertiary)",
                  textTransform: "uppercase", letterSpacing: "0.06em", fontWeight: 600,
                  marginBottom: 4,
                }}>Move to lane</div>
                <select
                  value={lane}
                  onChange={(e) => setLane(e.target.value)}
                  style={{
                    width: "100%", padding: "8px 12px", fontSize: 13,
                    border: "1px solid var(--separator)",
                    borderRadius: 8, background: "var(--bg-primary)",
                    color: "var(--label-primary)",
                  }}
                >
                  {LANE_OPTIONS.map(o => (
                    <option key={o.value} value={o.value}>{o.label}</option>
                  ))}
                </select>
              </div>
              <div style={{ fontSize: 12, color: "var(--label-tertiary)", lineHeight: 1.5 }}>
                A journal entry will be auto-logged on this stock recording the change.
              </div>
            </>
          )}
        </div>
        <div style={{
          padding: "12px 20px", borderTop: "1px solid var(--separator-light)",
          display: "flex", justifyContent: "flex-end", gap: 8,
        }}>
          <button onClick={onCancel} style={{
            padding: "8px 14px", borderRadius: 8, fontSize: 13,
            background: "transparent", color: "var(--label-secondary)",
            border: "1px solid var(--separator)", cursor: "pointer",
          }}>Cancel</button>
          <button
            onClick={() => onConfirm(isHoldingOnly ? null : lane)}
            style={{
              padding: "8px 16px", borderRadius: 8, fontSize: 13, fontWeight: 600,
              background: "var(--label-primary)", color: "var(--bg-primary)",
              border: 0, cursor: "pointer",
            }}
          >Confirm ✓</button>
        </div>
      </div>
    </>
  );
}
