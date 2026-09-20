"use client";

import React from "react";
import { fmtRelative } from "@/lib/format";

type Kind = "live" | "snapshot" | "ai";

interface Props {
  // What kind of data is this timestamp for. Drives the default label and
  // the staleness threshold.
  kind: Kind;
  // ISO 8601 timestamp of when the data was produced.
  iso: string | null | undefined;
  // Override the stale threshold (in hours). Defaults: live 5min, snapshot
  // 14d, ai 48h. Pass 0 to never mark stale.
  staleThresholdHours?: number;
  // Optional override of the leading label (defaults to kind).
  label?: string;
  // Extra tooltip text appended after the timestamp.
  tooltip?: string;
}

const DEFAULTS: Record<Kind, { label: string; thresholdHours: number; bg: string; fg: string }> = {
  live: {
    label: "Live",
    thresholdHours: 5 / 60, // 5 minutes
    bg: "color-mix(in srgb, var(--system-green) 12%, transparent)",
    fg: "var(--system-green)",
  },
  snapshot: {
    label: "Snapshot",
    thresholdHours: 14 * 24,
    bg: "var(--bg-secondary)",
    fg: "var(--label-secondary)",
  },
  ai: {
    label: "AI",
    thresholdHours: 48,
    bg: "color-mix(in srgb, var(--system-purple, #af52de) 12%, transparent)",
    fg: "var(--system-purple, #af52de)",
  },
};

const STALE_STYLE = {
  bg: "color-mix(in srgb, var(--review) 14%, transparent)",
  fg: "var(--review)",
};

function ageHours(iso: string): number | null {
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return null;
  return Math.max(0, (Date.now() - t) / 3600000);
}

export default function FreshnessChip({ kind, iso, staleThresholdHours, label, tooltip }: Props) {
  const cfg = DEFAULTS[kind];
  const threshold = staleThresholdHours ?? cfg.thresholdHours;
  const age = iso ? ageHours(iso) : null;
  const stale = threshold > 0 && age != null && age > threshold;

  const style = stale ? STALE_STYLE : { bg: cfg.bg, fg: cfg.fg };
  const displayLabel = label ?? cfg.label;
  const rel = iso ? fmtRelative(iso) : "—";

  // Stale tooltip explains what's actually wrong so the analyst doesn't
  // need to compute the lag themselves.
  let title = `${displayLabel} · ${rel}`;
  if (stale && age != null) {
    const ageLabel = age < 48 ? `${Math.round(age)}h` : `${Math.round(age / 24)}d`;
    title += ` (${ageLabel} old — may be stale)`;
  }
  if (tooltip) title += ` · ${tooltip}`;

  return (
    <span
      title={title}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 5,
        padding: "3px 8px",
        borderRadius: 999,
        background: style.bg,
        color: style.fg,
        fontSize: 11,
        fontWeight: 600,
        lineHeight: 1.2,
        whiteSpace: "nowrap",
        cursor: "help",
      }}
    >
      {kind === "live" && (
        <span
          aria-hidden
          style={{
            width: 6, height: 6, borderRadius: "50%",
            background: style.fg,
            animation: stale ? "none" : "fc-pulse 1.6s infinite",
          }}
        />
      )}
      <span style={{ textTransform: "uppercase", letterSpacing: "0.04em", fontSize: 10 }}>
        {stale ? `${displayLabel} stale` : displayLabel}
      </span>
      <span style={{ fontFamily: "var(--font-mono)", fontWeight: 500, opacity: 0.85 }}>
        {rel}
      </span>
      <style jsx>{`
        @keyframes fc-pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.4; }
        }
      `}</style>
    </span>
  );
}
