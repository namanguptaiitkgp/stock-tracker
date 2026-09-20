"use client";

/**
 * Coverage callout — rendered above the SmartMoneyPanel when a stock
 * has thin smart-money data. Tells the user *why* the panel below
 * might be showing limited or empty signals: rather than the panel
 * silently producing nothing useful, the user gets a factual list of
 * what's missing and a numeric reliability score.
 *
 * Friendly + factual; no judgment about whether to trust the panel
 * (the user decides). Hidden when coverage_score ≥ 50.
 */

interface Props {
  score: number;
  sourcesWithData: string[];
  sourcesMissing: string[];
  gapExplanation: string | null;
}

export default function SmartMoneyCoverageCallout({
  score,
  sourcesWithData,
  sourcesMissing,
  gapExplanation,
}: Props) {
  return (
    <div
      style={{
        marginBottom: 12,
        padding: "10px 14px",
        borderRadius: 10,
        background: "var(--review-bg, rgba(255,149,0,0.06))",
        border: "1px solid var(--review-edge, rgba(255,149,0,0.22))",
        fontSize: 12,
        color: "var(--label-secondary)",
        display: "flex",
        flexDirection: "column",
        gap: 8,
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 8,
        }}
      >
        <span
          style={{
            fontWeight: 600,
            color: "var(--review)",
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
          }}
        >
          <span style={{ fontSize: 14 }}>⚠</span>
          Limited smart-money data for this stock
        </span>
        <span
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 11,
            color: "var(--review)",
            fontWeight: 700,
          }}
          title="Coverage score 0–100. Below 50 means the panel below has thin data to work with."
        >
          {score}/100
        </span>
      </div>

      {gapExplanation && (
        <div
          style={{
            fontSize: 11.5,
            color: "var(--label-secondary)",
            whiteSpace: "pre-line",
            lineHeight: 1.5,
          }}
        >
          {gapExplanation}
        </div>
      )}

      {sourcesWithData.length > 0 && (
        <div style={{ fontSize: 11, color: "var(--label-tertiary)" }}>
          Available: {sourcesWithData.join(", ")}
        </div>
      )}
    </div>
  );
}
