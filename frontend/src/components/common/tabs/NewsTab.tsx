"use client";

import NewsSentiment from "../NewsSentiment";
import { useLatestDecision } from "@/hooks/useLatestDecision";
import { fmtRelative } from "@/lib/format";
import FreshnessChip from "@/components/ui/FreshnessChip";

interface Props {
  symbol: string;
  exchange: string;
}

// Reformat any ISO 8601 timestamps inline in the LLM body to human-readable
// form so we never leak "analyzed at 2026-05-14T17:58:15.546776+00:00".
// Tolerates microseconds, optional timezone, and the `Z` suffix.
const ISO_RE = /(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)/g;
function humanizeIsoTimestamps(text: string): string {
  return text.replace(ISO_RE, (match) => {
    const human = fmtRelative(match);
    return human === "—" ? match : human;
  });
}

export default function NewsTab({ symbol, exchange }: Props) {
  const { decision } = useLatestDecision(symbol);
  const body = decision?.news_sentiment_context
    ? humanizeIsoTimestamps(decision.news_sentiment_context)
    : null;

  return (
    <div className="space-y-4">
      {body && (
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
            }}>AI News Analysis</span>
            {decision?.created_at && (
              <FreshnessChip kind="ai" iso={decision.created_at} />
            )}
          </div>
          <p style={{
            fontSize: 13, lineHeight: 1.55, color: "var(--label-primary)",
            // Removed `fontStyle: italic` — italic body copy at 13px on a
            // 390px viewport hurts legibility. Reserve italics for actual
            // quotations.
            margin: 0,
          }}>{body}</p>
          <div style={{
            marginTop: 8,
            fontSize: 11, color: "var(--label-tertiary)",
            cursor: "help",
          }}
            title="News sentiment scale: −100 (very bearish) to +100 (very bullish). +40 is moderately bullish; the verdict text already qualifies the strength."
          >
            ⓘ Sentiment scale: −100 to +100
          </div>
        </div>
      )}
      <NewsSentiment symbol={symbol} exchange={exchange} />
    </div>
  );
}
