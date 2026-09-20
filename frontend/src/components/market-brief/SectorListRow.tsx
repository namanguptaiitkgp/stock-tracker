"use client";

import React, { useState } from "react";
import { refreshSector, type SectorCard } from "@/lib/market-brief-api";

// One sector inside the Market Pulse "Sectors" section. 3-col row +
// optional inline expansion panel directly below it. No clamp on the
// summary — the 5-sentence prompt output wraps naturally.
//
// Visual language matches the surrounding MarketPulseDetail (sans,
// existing var(--*) tokens). The earlier editorial-serif modal styling
// has been removed.

const MOOD_COLOR: Record<string, string> = {
  BULLISH: "var(--system-green)",
  BEARISH: "var(--system-red)",
  NEUTRAL: "var(--label-tertiary)",
};

// Confidence chip — small pill, distinct from the sector name so the
// row doesn't read as wrapped text. Background tone is muted so the
// chip recedes; the sector name and score stay the foreground signal.
const CONF_STYLE: Record<string, { bg: string; fg: string }> = {
  HIGH:   { bg: "color-mix(in srgb, var(--system-green) 12%, transparent)", fg: "var(--system-green)" },
  MEDIUM: { bg: "var(--bg-secondary)", fg: "var(--label-secondary)" },
  LOW:    { bg: "var(--bg-secondary)", fg: "var(--label-tertiary)" },
};

export function SectorListRow({
  card,
  expanded,
  onToggle,
  onUpdated,
  isFirst = false,
}: {
  card: SectorCard;
  expanded: boolean;
  onToggle: () => void;
  onUpdated: (next: SectorCard) => void;
  isFirst?: boolean;
}) {
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const mood = (card.mood || "NEUTRAL").toUpperCase();
  const moodColor = MOOD_COLOR[mood] || MOOD_COLOR.NEUTRAL;
  const score = card.score;

  const onRefresh = async () => {
    setRefreshing(true);
    setError(null);
    try {
      const next = await refreshSector(card.sector);
      onUpdated(next);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Refresh failed");
    } finally {
      setRefreshing(false);
    }
  };

  return (
    <div
      style={{
        borderTop: isFirst ? "0" : "1px solid var(--separator-light)",
        background: "var(--bg-primary)",
      }}
    >
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={expanded}
        className="slr-row"
        style={{
          all: "unset",
          cursor: "pointer",
          width: "100%",
          display: "grid",
          // 4-col rhythm: meta block · score · summary · chevron. The
          // meta block is a fixed width so sector names of any length
          // line up vertically across rows; the score column is a
          // narrow fixed-width tabular cell; summary flexes; chevron
          // is parked at the right edge instead of floating inside col 1.
          gridTemplateColumns: "minmax(0, 220px) 56px minmax(0, 1fr) 20px",
          alignItems: "start",
          columnGap: 20,
          padding: "16px 18px",
          transition: "background .12s ease",
          boxSizing: "border-box",
        }}
        onMouseEnter={(e) => { e.currentTarget.style.background = "var(--bg-secondary)"; }}
        onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}
      >
        <style jsx>{`
          @media (max-width: 720px) {
            .slr-row {
              grid-template-columns: 1fr auto auto !important;
              grid-template-areas:
                "meta score chevron"
                "summary summary summary" !important;
              row-gap: 8px;
              column-gap: 12px !important;
              padding: 14px 14px !important;
            }
            .slr-row :global(.slr-meta) { grid-area: meta; min-width: 0; }
            .slr-row :global(.slr-score) { grid-area: score; }
            .slr-row :global(.slr-chevron) { grid-area: chevron; padding-top: 1px !important; }
            .slr-row :global(.slr-summary) { grid-area: summary; }
            .slr-row :global(.slr-sector-name) {
              white-space: normal !important;
              text-overflow: clip !important;
            }
          }
        `}</style>
        {/* Col 1: mood-dot + sector name stacked above a confidence chip */}
        <div className="slr-meta" style={{ display: "flex", flexDirection: "column", gap: 6, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
            <span
              aria-hidden
              style={{
                width: 8, height: 8, borderRadius: 2, flexShrink: 0,
                background: moodColor,
              }}
            />
            <span className="slr-sector-name" style={{
              fontSize: 14, fontWeight: 600, color: "var(--label-primary)",
              lineHeight: 1.25, whiteSpace: "nowrap",
              overflow: "hidden", textOverflow: "ellipsis",
            }}>
              {card.sector}
            </span>
          </div>
          {card.confidence && (
            <span style={{
              fontFamily: "var(--font-mono)", fontSize: 10,
              fontWeight: 600, letterSpacing: ".08em",
              padding: "2px 7px", borderRadius: 4,
              alignSelf: "flex-start",
              background: (CONF_STYLE[card.confidence] || CONF_STYLE.MEDIUM).bg,
              color: (CONF_STYLE[card.confidence] || CONF_STYLE.MEDIUM).fg,
              textTransform: "uppercase",
            }}>
              {card.confidence}
            </span>
          )}
        </div>

        {/* Col 2: numeric score — tabular, right-aligned */}
        <span
          className="slr-score"
          title="Sector momentum score (−100 to +100). Combines breadth and sentiment over the past 5 trading days."
          style={{
            fontFamily: "var(--font-mono)", fontSize: 15, fontWeight: 600,
            textAlign: "right", lineHeight: 1.25,
            paddingTop: 1,
            fontVariantNumeric: "tabular-nums",
            cursor: "help",
            color: score == null ? "var(--label-tertiary)"
              : score > 0 ? "var(--system-green)"
              : score < 0 ? "var(--system-red)"
              : "var(--label-tertiary)",
          }}
        >
          {score == null ? "—" : `${score > 0 ? "+" : ""}${score}`}
        </span>

        {/* Col 3: full 5-sentence summary, no clamp */}
        <div className="slr-summary" style={{
          fontSize: 13.5, lineHeight: 1.55,
          color: card.summary ? "var(--label-secondary)" : "var(--label-tertiary)",
          fontStyle: card.summary ? "normal" : "italic",
          textAlign: "left", paddingTop: 1,
        }}>
          {card.summary
            ? card.summary
            : "No summary yet for this sector — expand and click ↻ refresh to generate."}
        </div>

        {/* Col 4: expand chevron, parked at the right edge */}
        <span className="slr-chevron" style={{
          color: "var(--label-tertiary)", fontSize: 11,
          textAlign: "right", paddingTop: 4,
          transition: "transform .15s ease, color .15s ease",
          transform: expanded ? "rotate(180deg)" : "rotate(0deg)",
        }}>
          ▾
        </span>
      </button>

      {expanded && (
        <div style={{
          padding: "14px 18px 18px 44px",
          background: "var(--bg-secondary)",
          display: "flex", flexDirection: "column", gap: 16,
          fontSize: 12.5, color: "var(--label-secondary)",
          borderTop: "1px solid var(--separator-light)",
        }}>
          {error && (
            <div style={{
              padding: "8px 10px", borderRadius: 6,
              background: "color-mix(in srgb, var(--system-red) 8%, transparent)",
              color: "var(--system-red)", fontSize: 12,
            }}>
              {error}
            </div>
          )}

          {/* Bellwethers */}
          {card.bellwethers && card.bellwethers.length > 0 && (
            <Block label="Bellwethers">
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                {card.bellwethers.map((b) => (
                  <span key={b} style={{
                    fontFamily: "var(--font-mono)", fontSize: 11,
                    padding: "2px 8px", borderRadius: 99,
                    background: "var(--bg-primary)",
                    color: "var(--label-secondary)",
                    border: "1px solid var(--separator-light)",
                  }}>
                    {b}
                  </span>
                ))}
              </div>
            </Block>
          )}

          {/* Macro drivers */}
          {card.macro_drivers && card.macro_drivers.length > 0 && (
            <Block label="Macro drivers">
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {card.macro_drivers.map((d, i) => {
                  const tilt = d.tilt === "+" ? "up" : d.tilt === "-" ? "down" : "flat";
                  const tiltColor = tilt === "up" ? "var(--system-green)"
                    : tilt === "down" ? "var(--system-red)"
                    : "var(--label-tertiary)";
                  return (
                    <div key={`${d.factor}-${i}`} style={{
                      display: "grid", gridTemplateColumns: "auto 1fr", columnGap: 10,
                      padding: "8px 10px", borderRadius: 6,
                      background: "var(--bg-primary)",
                      border: "1px solid var(--separator-light)",
                    }}>
                      <span style={{
                        fontFamily: "var(--font-mono)", fontWeight: 700, fontSize: 13,
                        color: tiltColor, width: 12, textAlign: "center",
                      }}>
                        {d.tilt === "+" ? "▲" : d.tilt === "-" ? "▼" : "—"}
                      </span>
                      <div>
                        <div style={{ fontSize: 13, fontWeight: 600, color: "var(--label-primary)" }}>
                          {d.factor}
                        </div>
                        <div style={{ fontSize: 12, color: "var(--label-secondary)", marginTop: 2, lineHeight: 1.4 }}>
                          {d.rationale}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </Block>
          )}

          {/* Key themes */}
          {card.signals && card.signals.length > 0 && (
            <Block label="Key themes">
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                {card.signals.map((t, i) => (
                  <span key={`${t}-${i}`} style={{
                    fontSize: 11.5, padding: "2px 8px", borderRadius: 99,
                    background: "var(--bg-primary)",
                    color: "var(--label-secondary)",
                    border: "1px solid var(--separator-light)",
                  }}>
                    {t}
                  </span>
                ))}
              </div>
            </Block>
          )}

          {/* What to watch */}
          {card.what_to_watch && card.what_to_watch.length > 0 && (
            <Block label="What to watch">
              <ol style={{ margin: 0, paddingLeft: 18, display: "flex", flexDirection: "column", gap: 4 }}>
                {card.what_to_watch.map((ev, i) => (
                  <li key={`${ev}-${i}`} style={{ fontSize: 12.5, lineHeight: 1.45, color: "var(--label-secondary)" }}>
                    {ev}
                  </li>
                ))}
              </ol>
            </Block>
          )}

          {/* Top headlines */}
          {card.top_headlines && card.top_headlines.length > 0 && (
            <Block label="Headlines that fed this analysis">
              <div style={{ display: "flex", flexDirection: "column" }}>
                {card.top_headlines.map((h, i) => (
                  <div key={`${h.url || h.title}-${i}`} style={{
                    display: "grid", gridTemplateColumns: "70px 1fr",
                    columnGap: 12, padding: "6px 0",
                    borderTop: i === 0 ? "0" : "1px solid var(--separator-light)",
                  }}>
                    <span style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--label-tertiary)", paddingTop: 2 }}>
                      {h.date || "—"}
                    </span>
                    <div>
                      {h.url ? (
                        <a
                          href={h.url}
                          target="_blank"
                          rel="noreferrer noopener"
                          style={{
                            fontSize: 12.5, color: "var(--label-primary)",
                            textDecoration: "none", lineHeight: 1.4,
                          }}
                        >
                          {h.title}
                        </a>
                      ) : (
                        <span style={{ fontSize: 12.5, color: "var(--label-primary)", lineHeight: 1.4 }}>
                          {h.title}
                        </span>
                      )}
                      {h.source && (
                        <div style={{ fontSize: 11, color: "var(--label-tertiary)", marginTop: 1 }}>
                          {h.source}
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </Block>
          )}

          {/* Footer: last_run + refresh */}
          <div style={{
            display: "flex", alignItems: "center", justifyContent: "space-between",
            marginTop: 4, paddingTop: 10, borderTop: "1px solid var(--separator-light)",
          }}>
            <span style={{ fontSize: 11, color: "var(--label-tertiary)", fontFamily: "var(--font-mono)" }}>
              {card.last_run_at ? `last run · ${new Date(card.last_run_at).toLocaleString()}` : "never run"}
            </span>
            <button
              onClick={onRefresh}
              disabled={refreshing}
              style={{
                all: "unset", cursor: refreshing ? "wait" : "pointer",
                padding: "4px 10px", borderRadius: 6,
                border: "1px solid var(--separator-light)",
                background: "var(--bg-primary)",
                fontSize: 11.5, fontWeight: 500, color: "var(--label-primary)",
                opacity: refreshing ? 0.6 : 1,
              }}
            >
              {refreshing ? "↻ refreshing…" : "↻ refresh"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function Block({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div style={{
        fontSize: 10.5, fontWeight: 600, letterSpacing: ".08em",
        textTransform: "uppercase", color: "var(--label-tertiary)",
        marginBottom: 6,
      }}>
        {label}
      </div>
      {children}
    </div>
  );
}
