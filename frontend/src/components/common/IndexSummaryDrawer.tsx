"use client";

import { useCallback, useEffect, useState } from "react";
import { createPortal } from "react-dom";

interface Driver {
  label: string;
  weight: "high" | "medium" | "low";
}

interface Headline {
  title: string;
  source?: string;
  url?: string;
  date?: string;
}

interface Summary {
  slug: string;
  display_name: string;
  direction: "UP" | "DOWN" | "FLAT" | null;
  magnitude: "SHARP" | "MILD" | "FLAT" | null;
  one_liner: string | null;
  drivers: Driver[] | null;
  what_to_watch: string | null;
  top_headlines: Headline[] | null;
  news_count: number;
  model_used: string | null;
  generated_at: string | null;
  error_message: string | null;
  cached?: boolean;
}

interface IndexRow {
  slug: string;
  display_name: string;
  short_name: string;
  ltp: number | null;
  change_pct: number | null;
}

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const TOKEN_KEY = "algo_trader_token";

function fmtRel(iso: string | null | undefined): string {
  if (!iso) return "never";
  const t = new Date(iso).getTime();
  if (isNaN(t)) return "unknown";
  const diff = (Date.now() - t) / 1000;
  if (diff < 60) return `${Math.max(1, Math.round(diff))}s ago`;
  if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.round(diff / 3600)}h ago`;
  return `${Math.round(diff / 86400)}d ago`;
}

function authHeaders(): Record<string, string> {
  const token = typeof window !== "undefined" ? localStorage.getItem(TOKEN_KEY) : null;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function directionColor(d: Summary["direction"]): string {
  if (d === "UP") return "#248A3D";
  if (d === "DOWN") return "#D70015";
  return "#6E6E73";
}

function directionArrow(d: Summary["direction"]): string {
  if (d === "UP") return "▲";
  if (d === "DOWN") return "▼";
  return "—";
}

function weightBadge(w: Driver["weight"]): { bg: string; fg: string } {
  if (w === "high") return { bg: "rgba(175,82,222,0.12)", fg: "#AF52DE" };
  if (w === "medium") return { bg: "rgba(0,122,255,0.1)", fg: "#007AFF" };
  return { bg: "rgba(142,142,147,0.1)", fg: "#6E6E73" };
}

export default function IndexSummaryDrawer({
  index,
  onClose,
}: {
  index: IndexRow;
  onClose: () => void;
}) {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(
        `${API_URL}/api/market/indices/${encodeURIComponent(index.slug)}/summary`,
        { headers: authHeaders() },
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const d: Summary = await res.json();
      setSummary(d);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [index.slug]);

  const refresh = useCallback(async () => {
    setRefreshing(true);
    setError(null);
    try {
      const res = await fetch(
        `${API_URL}/api/market/indices/${encodeURIComponent(index.slug)}/summary/refresh`,
        { method: "POST", headers: authHeaders() },
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const d: Summary = await res.json();
      setSummary(d);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setRefreshing(false);
    }
  }, [index.slug]);

  useEffect(() => {
    load();
  }, [load]);

  if (typeof window === "undefined") return null;

  const content = (
    <>
      <div
        onClick={onClose}
        style={{
          position: "fixed",
          inset: 0,
          background: "rgba(0,0,0,0.25)",
          zIndex: 1000,
        }}
      />
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          position: "fixed",
          top: 0,
          right: 0,
          bottom: 0,
          width: 460,
          maxWidth: "100vw",
          background: "white",
          overflowY: "auto",
          boxShadow: "-4px 0 12px rgba(0,0,0,0.1)",
          padding: 24,
          zIndex: 1001,
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
          <div>
            <div style={{ fontSize: 11, color: "#6E6E73", textTransform: "uppercase", letterSpacing: "0.05em" }}>
              Index summary
            </div>
            <h2 style={{ fontSize: 20, fontWeight: 700, margin: 0 }}>{index.display_name}</h2>
          </div>
          <button
            onClick={onClose}
            style={{
              background: "none",
              border: "none",
              fontSize: 20,
              cursor: "pointer",
              color: "#6E6E73",
            }}
          >
            ×
          </button>
        </div>

        <div style={{ display: "flex", gap: 12, marginBottom: 20 }}>
          {index.ltp !== null && (
            <div>
              <div style={{ fontSize: 11, color: "#6E6E73" }}>Last</div>
              <div style={{ fontSize: 18, fontWeight: 700 }}>
                {index.ltp.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </div>
            </div>
          )}
          {index.change_pct !== null && (
            <div>
              <div style={{ fontSize: 11, color: "#6E6E73" }}>Change</div>
              <div
                style={{
                  fontSize: 18,
                  fontWeight: 700,
                  color: index.change_pct >= 0 ? "#248A3D" : "#D70015",
                }}
              >
                {index.change_pct >= 0 ? "+" : ""}
                {index.change_pct.toFixed(2)}%
              </div>
            </div>
          )}
        </div>

        {loading && <div style={{ color: "#6E6E73" }}>Loading summary…</div>}
        {error && (
          <div
            style={{
              padding: 10,
              background: "rgba(215,0,21,0.08)",
              border: "1px solid rgba(215,0,21,0.25)",
              borderRadius: 6,
              color: "#B10011",
              fontSize: 13,
              marginBottom: 12,
            }}
          >
            {error}
          </div>
        )}

        {summary && (
          <>
            {summary.error_message && !summary.one_liner && (
              <div
                style={{
                  padding: 10,
                  background: "rgba(245,166,35,0.12)",
                  border: "1px solid rgba(245,166,35,0.4)",
                  borderRadius: 6,
                  color: "#5C3F00",
                  fontSize: 13,
                  marginBottom: 12,
                }}
              >
                {summary.error_message}
              </div>
            )}

            {summary.one_liner && (
              <div
                style={{
                  padding: "14px 16px",
                  background: "rgba(142,142,147,0.05)",
                  border: "1px solid rgba(142,142,147,0.12)",
                  borderRadius: 10,
                  marginBottom: 16,
                }}
              >
                <div
                  style={{
                    display: "flex",
                    alignItems: "baseline",
                    gap: 8,
                    marginBottom: 6,
                  }}
                >
                  <span
                    style={{
                      fontSize: 24,
                      fontWeight: 800,
                      color: directionColor(summary.direction),
                    }}
                  >
                    {directionArrow(summary.direction)}
                  </span>
                  <span style={{ fontSize: 13, color: "#6E6E73", textTransform: "uppercase", fontWeight: 600 }}>
                    {summary.direction} {summary.magnitude}
                  </span>
                </div>
                <div style={{ fontSize: 14, lineHeight: 1.4, color: "#1D1D1F" }}>
                  {summary.one_liner}
                </div>
              </div>
            )}

            {summary.drivers && summary.drivers.length > 0 && (
              <div style={{ marginBottom: 16 }}>
                <h3 style={{ fontSize: 11, fontWeight: 600, color: "#6E6E73", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 8 }}>
                  Drivers
                </h3>
                {summary.drivers.map((d, i) => {
                  const c = weightBadge(d.weight);
                  return (
                    <div
                      key={i}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 8,
                        padding: "6px 0",
                      }}
                    >
                      <span
                        style={{
                          fontSize: 10,
                          fontWeight: 700,
                          textTransform: "uppercase",
                          padding: "2px 8px",
                          borderRadius: 10,
                          background: c.bg,
                          color: c.fg,
                          minWidth: 52,
                          textAlign: "center",
                        }}
                      >
                        {d.weight}
                      </span>
                      <span style={{ fontSize: 13, color: "#1D1D1F" }}>{d.label}</span>
                    </div>
                  );
                })}
              </div>
            )}

            {summary.what_to_watch && (
              <div
                style={{
                  marginBottom: 16,
                  padding: 12,
                  background: "rgba(0,122,255,0.05)",
                  border: "1px solid rgba(0,122,255,0.15)",
                  borderRadius: 8,
                }}
              >
                <div style={{ fontSize: 11, color: "#007AFF", fontWeight: 700, marginBottom: 4, textTransform: "uppercase", letterSpacing: "0.05em" }}>
                  What to watch
                </div>
                <div style={{ fontSize: 13, color: "#003D85", lineHeight: 1.4 }}>
                  {summary.what_to_watch}
                </div>
              </div>
            )}

            {summary.top_headlines && summary.top_headlines.length > 0 && (
              <div style={{ marginBottom: 16 }}>
                <h3 style={{ fontSize: 11, fontWeight: 600, color: "#6E6E73", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 8 }}>
                  Headlines ({summary.top_headlines.length})
                </h3>
                {summary.top_headlines.slice(0, 8).map((h, i) => (
                  <a
                    key={i}
                    href={h.url}
                    target="_blank"
                    rel="noreferrer"
                    style={{
                      display: "block",
                      padding: "6px 0",
                      borderBottom: "1px solid #F2F2F7",
                      textDecoration: "none",
                      color: "#1D1D1F",
                      fontSize: 12,
                    }}
                  >
                    {h.title}
                    <div style={{ fontSize: 10, color: "#8E8E93", marginTop: 2 }}>
                      {h.source} · {h.date}
                    </div>
                  </a>
                ))}
              </div>
            )}

            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                borderTop: "1px solid #E2E8F0",
                paddingTop: 12,
                fontSize: 11,
                color: "#6E6E73",
              }}
            >
              <span>
                Last generated {fmtRel(summary.generated_at)}
                {summary.cached ? " · cached" : " · live"}
                {summary.model_used ? ` · ${summary.model_used}` : ""}
              </span>
              <button
                onClick={refresh}
                disabled={refreshing}
                style={{
                  padding: "4px 12px",
                  borderRadius: 6,
                  background: refreshing ? "#8E8E93" : "#1D1D1F",
                  color: "white",
                  border: "none",
                  fontSize: 11,
                  fontWeight: 600,
                  cursor: refreshing ? "wait" : "pointer",
                }}
              >
                {refreshing ? "Refreshing…" : "Refresh"}
              </button>
            </div>
          </>
        )}
      </div>
    </>
  );

  return createPortal(content, document.body);
}
