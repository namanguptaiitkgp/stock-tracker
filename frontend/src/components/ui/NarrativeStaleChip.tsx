"use client";

import React from "react";

interface Props {
  // Hours by which the narrative trails the fundamentals it references.
  // Pass null when only a binary "stale" flag is known.
  lagHours: number | null | undefined;
  // Optional override of the tooltip body — useful when the stale narrative
  // sits next to an explicit "Re-evaluate" affordance with different copy.
  tooltip?: string;
}

const DEFAULT_TOOLTIP =
  "Narrative paragraph was generated against an older fundamentals snapshot; " +
  "the structured cards reflect current numbers. Re-run analysis to refresh the narrative.";

export default function NarrativeStaleChip({ lagHours, tooltip }: Props) {
  const lagText =
    lagHours == null ? "older snapshot"
      : lagHours < 48 ? `${Math.round(lagHours)}h older`
        : `${Math.round(lagHours / 24)}d older`;
  return (
    <span
      title={tooltip ?? DEFAULT_TOOLTIP}
      style={{
        display: "inline-flex", alignItems: "center", gap: 6,
        padding: "5px 10px", borderRadius: 6,
        background: "var(--review-bg)",
        border: "1px solid color-mix(in srgb, var(--review) 35%, transparent)",
        fontSize: 12,
        cursor: "help",
      }}
    >
      <span style={{
        fontFamily: "var(--font-mono)", fontWeight: 600,
        color: "var(--review)", fontSize: 11, letterSpacing: "0.05em",
      }}>NARRATIVE</span>
      <span style={{
        fontFamily: "var(--font-mono)", color: "var(--review)", fontSize: 11.5,
      }}>{lagText}</span>
    </span>
  );
}
