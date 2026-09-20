"use client";

import React, { useEffect, useState, useCallback } from "react";
import { api } from "@/lib/api";

// The per-stock sentiment prompt (v3 — see catalogue entry #2) returns
// `relevance_score` per headline and dropped the old `sentiment` field;
// the old shape kept it. Treat both fields as optional and fall back to
// safe defaults at render time so the component is robust to either.
interface HeadlineItem {
  title: string;
  source?: string | null;
  date?: string | null;
  url?: string | null;
  sentiment?: "bullish" | "bearish" | "neutral" | null;
  impact?: "high" | "medium" | "low" | null;
  relevance_score?: number | null;
}

interface SentimentResult {
  symbol: string;
  sentiment: "bullish" | "bearish" | "neutral";
  score: number; // -100 to +100
  summary: string;
  key_themes: string[];
  headlines: HeadlineItem[];
  analyzed_at: string;
  headline_count: number;
}

interface Props {
  symbol: string;
  exchange?: string;
}

const SENTIMENT_STYLES: Record<
  "bullish" | "bearish" | "neutral",
  React.CSSProperties
> = {
  bullish: {
    backgroundColor: "rgba(52,199,89,0.08)",
    color: "#248A3D",
    border: "1px solid rgba(52,199,89,0.2)",
  },
  bearish: {
    backgroundColor: "rgba(255,59,48,0.08)",
    color: "#D70015",
    border: "1px solid rgba(255,59,48,0.2)",
  },
  neutral: {
    backgroundColor: "rgba(142,142,147,0.08)",
    color: "#6E6E73",
    border: "1px solid rgba(142,142,147,0.2)",
  },
};

function timeAgo(dateStr: string): string {
  const now = Date.now();
  const then = new Date(dateStr).getTime();
  const diffMs = now - then;
  const diffMin = Math.floor(diffMs / 60000);
  if (diffMin < 1) return "just now";
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffH = Math.floor(diffMin / 60);
  if (diffH < 24) return `${diffH}h ago`;
  const diffD = Math.floor(diffH / 24);
  return `${diffD}d ago`;
}

function formatDate(dateStr: string): string {
  const d = new Date(dateStr);
  return d.toLocaleDateString("en-IN", { day: "numeric", month: "short" });
}

function ScoreBar({ score }: { score: number }) {
  // Position: score ranges from -100 to +100, map to 0% to 100%
  const pct = ((score + 100) / 200) * 100;

  return (
    <div style={{ padding: "8px 0" }}>
      <div
        style={{
          position: "relative",
          height: 8,
          borderRadius: 4,
          overflow: "hidden",
          display: "flex",
        }}
      >
        {/* Left half (negative / red) */}
        <div
          style={{
            flex: 1,
            background:
              "linear-gradient(to right, rgba(255,59,48,0.3), rgba(255,59,48,0.08))",
          }}
        />
        {/* Center sliver (gray) */}
        <div style={{ width: 2, backgroundColor: "rgba(142,142,147,0.3)" }} />
        {/* Right half (positive / green) */}
        <div
          style={{
            flex: 1,
            background:
              "linear-gradient(to right, rgba(52,199,89,0.08), rgba(52,199,89,0.3))",
          }}
        />
      </div>
      {/* Dot marker */}
      <div style={{ position: "relative", height: 0 }}>
        <div
          style={{
            position: "absolute",
            top: -14,
            left: `${pct}%`,
            transform: "translateX(-50%)",
            width: 14,
            height: 14,
            borderRadius: "50%",
            backgroundColor:
              score > 0 ? "#248A3D" : score < 0 ? "#D70015" : "#6E6E73",
            border: "2px solid #1D1D1F",
          }}
        />
      </div>
      {/* Labels */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          marginTop: 8,
          fontSize: 10,
          color: "#6E6E73",
          fontFamily: "monospace",
        }}
      >
        <span>-100</span>
        <span>0</span>
        <span>+100</span>
      </div>
    </div>
  );
}

function LoadingSkeleton() {
  const barStyle: React.CSSProperties = {
    height: 12,
    borderRadius: 4,
    backgroundColor: "rgba(142,142,147,0.12)",
    animation: "pulse 1.5s ease-in-out infinite",
  };

  return (
    <div style={{ padding: "12px 0" }}>
      <div style={{ ...barStyle, width: "100%", height: 8, marginBottom: 16 }} />
      <div
        style={{ ...barStyle, width: 100, height: 24, marginBottom: 12 }}
      />
      <div style={{ ...barStyle, width: "90%", marginBottom: 8 }} />
      <div style={{ ...barStyle, width: "75%", marginBottom: 8 }} />
      <div style={{ ...barStyle, width: "60%", marginBottom: 16 }} />
      <div style={{ ...barStyle, width: "40%", marginBottom: 12 }} />
      <div style={{ ...barStyle, width: "100%", height: 48, marginBottom: 8 }} />
      <div style={{ ...barStyle, width: "100%", height: 48 }} />
      <style>{`@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }`}</style>
    </div>
  );
}

export default function NewsSentiment({ symbol, exchange }: Props) {
  const [data, setData] = useState<SentimentResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [customQuery, setCustomQuery] = useState("");
  const [showCustom, setShowCustom] = useState(false);

  const fetchSentiment = useCallback(() => {
    setLoading(true);
    setError(null);
    api
      .get<SentimentResult>(`/api/market-data/sentiment/${symbol}?days=7&cache_only=true`)
      .then((d) => setData(d))
      .catch((e) =>
        setError(e instanceof Error ? e.message : "Failed to load sentiment"),
      )
      .finally(() => setLoading(false));
  }, [symbol]);

  useEffect(() => {
    fetchSentiment();
  }, [fetchSentiment]);

  async function handleRefresh(query?: string) {
    setRefreshing(true);
    setError(null);
    try {
      let url = `/api/market-data/sentiment/${symbol}?days=3&force=true`;
      if (query) {
        url += `&custom_query=${encodeURIComponent(query)}`;
      }
      const result = await api.get<SentimentResult>(url);
      setData(result);
      setShowCustom(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to refresh sentiment");
    } finally {
      setRefreshing(false);
    }
  }

  return (
    <div
      style={{
        borderTop: "1px solid rgba(142,142,147,0.15)",
        paddingTop: 12,
      }}
    >
      <h3
        style={{
          fontSize: 11,
          fontWeight: 600,
          textTransform: "uppercase",
          letterSpacing: "0.05em",
          marginBottom: 8,
          color: "#6E6E73",
        }}
      >
        News Sentiment
      </h3>

      {loading && <LoadingSkeleton />}

      {!loading && error && (
        <div
          style={{
            padding: 12,
            borderRadius: 8,
            backgroundColor: "rgba(255,59,48,0.08)",
            color: "#D70015",
            fontSize: 13,
            marginBottom: 8,
          }}
        >
          <div>{error}</div>
          <button
            onClick={fetchSentiment}
            style={{
              marginTop: 8,
              padding: "4px 12px",
              borderRadius: 6,
              border: "none",
              cursor: "pointer",
              fontSize: 12,
              backgroundColor: "#007AFF",
              color: "#FFFFFF",
            }}
          >
            Retry
          </button>
        </div>
      )}

      {!loading && !error && data && (!data.headline_count || data.headline_count === 0) && (
        <div
          style={{
            padding: 12,
            fontSize: 13,
            color: "#6E6E73",
            textAlign: "center",
          }}
        >
          No cached news analysis for {symbol}.
          <button
            onClick={() => handleRefresh()}
            disabled={refreshing}
            style={{
              marginLeft: 8,
              padding: "4px 12px",
              borderRadius: 6,
              border: "none",
              cursor: refreshing ? "not-allowed" : "pointer",
              fontSize: 12,
              fontWeight: 500,
              backgroundColor: "#007AFF",
              color: "#FFFFFF",
              opacity: refreshing ? 0.6 : 1,
            }}
          >
            {refreshing ? "Analyzing…" : "Analyze now"}
          </button>
        </div>
      )}

      {!loading && !error && data && data.headline_count > 0 && (() => {
        // Defensive defaults for the v3 sentiment shape — any of these
        // top-level fields can be null on legacy rows or partial parses.
        const sentimentKey: "bullish" | "bearish" | "neutral" =
          data.sentiment === "bullish" || data.sentiment === "bearish" || data.sentiment === "neutral"
            ? data.sentiment
            : "neutral";
        const score = typeof data.score === "number" ? data.score : 0;
        return (
        <div>
          {/* Score bar */}
          <ScoreBar score={score} />

          {/* Sentiment badge + confidence */}
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 10,
              marginTop: 8,
              marginBottom: 12,
            }}
          >
            <span
              style={{
                ...SENTIMENT_STYLES[sentimentKey],
                display: "inline-block",
                padding: "3px 10px",
                borderRadius: 6,
                fontSize: 12,
                fontWeight: 600,
                textTransform: "uppercase",
                letterSpacing: "0.03em",
              }}
            >
              {sentimentKey}
            </span>
            <span
              style={{
                fontSize: 13,
                color: "#48484A",
              }}
            >
              Confidence:{" "}
              <span style={{ fontWeight: 600, color: "#1D1D1F" }}>
                {score >= 0 ? "+" : ""}
                {score}
              </span>
            </span>
          </div>

          {/* Summary */}
          {data.summary && (
            <p
              style={{
                fontSize: 13,
                lineHeight: 1.5,
                color: "#1D1D1F",
                margin: "0 0 12px 0",
                fontStyle: "italic",
              }}
            >
              &ldquo;{data.summary}&rdquo;
            </p>
          )}

          {/* Themes */}
          {(data.key_themes?.length ?? 0) > 0 && (
            <div style={{ marginBottom: 14 }}>
              <span style={{ fontSize: 12, color: "#48484A" }}>Themes: </span>
              {(data.key_themes || []).map((theme, i) => (
                <span
                  key={i}
                  style={{
                    display: "inline-block",
                    padding: "2px 8px",
                    marginRight: 4,
                    marginBottom: 4,
                    borderRadius: 4,
                    fontSize: 11,
                    backgroundColor: "rgba(142,142,147,0.1)",
                    color: "#48484A",
                    border: "1px solid rgba(142,142,147,0.15)",
                  }}
                >
                  {theme}
                </span>
              ))}
            </div>
          )}

          {/* Headlines */}
          <div style={{ marginBottom: 12 }}>
            <div
              style={{
                fontSize: 12,
                color: "#6E6E73",
                marginBottom: 8,
                fontWeight: 500,
              }}
            >
              Headlines ({data.headline_count})
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {(data.headlines || []).map((h, i) => {
                // Safe defaults — the v3 prompt drops `sentiment` per
                // headline and may emit `impact` as null. Render with
                // fallbacks instead of accessing undefined properties.
                const sentimentKey: "bullish" | "bearish" | "neutral" =
                  h.sentiment === "bullish" || h.sentiment === "bearish" || h.sentiment === "neutral"
                    ? h.sentiment
                    : "neutral";
                const sentimentLabel = h.sentiment
                  ? h.sentiment.charAt(0).toUpperCase() + h.sentiment.slice(1)
                  : null;
                const impactKey: "high" | "medium" | "low" =
                  h.impact === "high" || h.impact === "medium" || h.impact === "low"
                    ? h.impact
                    : "medium";
                const impactLabel = h.impact
                  ? h.impact.charAt(0).toUpperCase() + h.impact.slice(1)
                  : null;
                const dateLabel = h.date ? formatDate(h.date) : null;
                return (
                  <a
                    key={i}
                    href={h.url || "#"}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{
                      display: "block",
                      padding: "8px 10px",
                      borderRadius: 6,
                      backgroundColor: "rgba(142,142,147,0.05)",
                      border: "1px solid rgba(142,142,147,0.1)",
                      textDecoration: "none",
                      transition: "background-color 0.15s",
                      pointerEvents: h.url ? "auto" : "none",
                    }}
                    onMouseEnter={(e) =>
                      (e.currentTarget.style.backgroundColor =
                        "rgba(142,142,147,0.1)")
                    }
                    onMouseLeave={(e) =>
                      (e.currentTarget.style.backgroundColor =
                        "rgba(142,142,147,0.05)")
                    }
                  >
                    <div
                      style={{
                        fontSize: 13,
                        color: "#1D1D1F",
                        fontWeight: impactKey === "high" ? 600 : 400,
                        lineHeight: 1.4,
                        marginBottom: 4,
                      }}
                    >
                      {h.title}
                    </div>
                    <div
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 6,
                        fontSize: 11,
                        flexWrap: "wrap",
                      }}
                    >
                      {h.source && <span style={{ color: "#48484A" }}>{h.source}</span>}
                      {h.source && dateLabel && <span style={{ color: "#6E6E73" }}>&middot;</span>}
                      {dateLabel && <span style={{ color: "#48484A" }}>{dateLabel}</span>}
                      {sentimentLabel && (
                        <>
                          <span style={{ color: "#6E6E73" }}>&middot;</span>
                          <span
                            style={{
                              color: SENTIMENT_STYLES[sentimentKey].color as string,
                              fontWeight: 500,
                            }}
                          >
                            {sentimentLabel}
                          </span>
                        </>
                      )}
                      {impactLabel && (
                        <>
                          <span style={{ color: "#6E6E73" }}>&middot;</span>
                          <span
                            style={{
                              color:
                                impactKey === "high"
                                  ? "#1D1D1F"
                                  : impactKey === "medium"
                                    ? "#48484A"
                                    : "#8E8E93",
                              fontWeight: impactKey === "high" ? 600 : 400,
                            }}
                          >
                            {impactLabel} impact
                          </span>
                        </>
                      )}
                      {h.relevance_score != null && (
                        <>
                          <span style={{ color: "#6E6E73" }}>&middot;</span>
                          <span style={{
                            color: h.relevance_score >= 70 ? "#1D1D1F"
                              : h.relevance_score >= 40 ? "#48484A"
                              : "#8E8E93",
                            fontFamily: "var(--font-mono)", fontSize: 10.5,
                          }}>
                            rel {h.relevance_score}
                          </span>
                        </>
                      )}
                    </div>
                  </a>
                );
              })}
            </div>
          </div>

          {/* Refresh + Custom Search + last updated */}
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <button
                onClick={() => handleRefresh()}
                disabled={refreshing}
                style={{
                  padding: "5px 14px",
                  borderRadius: 6,
                  border: "none",
                  cursor: refreshing ? "not-allowed" : "pointer",
                  fontSize: 12,
                  fontWeight: 500,
                  backgroundColor: "#007AFF",
                  color: "#FFFFFF",
                  opacity: refreshing ? 0.6 : 1,
                }}
              >
                {refreshing ? "Searching..." : "Refresh"}
              </button>
              <button
                onClick={() => setShowCustom(!showCustom)}
                style={{
                  padding: "5px 10px",
                  borderRadius: 6,
                  border: "1px solid #C6C6C8",
                  cursor: "pointer",
                  fontSize: 12,
                  backgroundColor: "transparent",
                  color: "#48484A",
                }}
              >
                {showCustom ? "Hide" : "Custom Search"}
              </button>
              <span style={{ fontSize: 11, color: "#6E6E73" }}>
                Last updated {timeAgo(data.analyzed_at)}
              </span>
            </div>

            {showCustom && (
              <div style={{ display: "flex", gap: 8 }}>
                <input
                  type="text"
                  value={customQuery}
                  onChange={(e) => setCustomQuery(e.target.value)}
                  placeholder={`e.g., "Zomato share price" or "HDFC Bank results"`}
                  onKeyDown={(e) => { if (e.key === "Enter" && customQuery.trim()) handleRefresh(customQuery.trim()); }}
                  style={{
                    flex: 1,
                    padding: "6px 10px",
                    borderRadius: 6,
                    border: "1px solid #C6C6C8",
                    fontSize: 13,
                    color: "#1D1D1F",
                    outline: "none",
                  }}
                />
                <button
                  onClick={() => customQuery.trim() && handleRefresh(customQuery.trim())}
                  disabled={refreshing || !customQuery.trim()}
                  style={{
                    padding: "6px 14px",
                    borderRadius: 6,
                    border: "none",
                    cursor: !customQuery.trim() ? "not-allowed" : "pointer",
                    fontSize: 12,
                    fontWeight: 500,
                    backgroundColor: "#007AFF",
                    color: "#FFFFFF",
                    opacity: !customQuery.trim() ? 0.4 : 1,
                  }}
                >
                  Search
                </button>
              </div>
            )}
          </div>
        </div>
        );
      })()}
    </div>
  );
}
