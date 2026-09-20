"use client";

import React from "react";

interface Props {
  fetchedAt: string | null | undefined;
  /** Minor label, e.g. "Sentiment" — used in the tooltip line. */
  label?: string;
  /** When defined, renders this content next to the freshness icon. Else just the icon. */
  children?: React.ReactNode;
}

function fmtRelative(iso: string): string {
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "unknown";
  const diffSec = (Date.now() - d.getTime()) / 1000;
  if (diffSec < 60) return "just now";
  if (diffSec < 3600) return `${Math.round(diffSec / 60)}m ago`;
  if (diffSec < 86400) return `${Math.round(diffSec / 3600)}h ago`;
  return `${Math.round(diffSec / 86400)}d ago`;
}

function fmtAbsoluteIST(iso: string): string {
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "—";
  return d.toLocaleString("en-IN", {
    day: "numeric", month: "short",
    hour: "2-digit", minute: "2-digit",
    hour12: false, timeZone: "Asia/Kolkata",
  }) + " IST";
}

/**
 * Inline freshness indicator. Shows the children value plus a tiny clock icon
 * that reveals "Fetched 3h ago — 30 Apr, 14:32 IST" on hover. If older than 24h
 * the clock turns amber as a soft "stale" hint.
 */
export default function FreshnessTooltip({ fetchedAt, label, children }: Props) {
  if (!fetchedAt) {
    return <>{children ?? null}</>;
  }
  const d = new Date(fetchedAt);
  const ageHours = isNaN(d.getTime()) ? 0 : (Date.now() - d.getTime()) / 3_600_000;
  const stale = ageHours > 24;
  const tooltip = `${label ? label + " · " : ""}Fetched ${fmtRelative(fetchedAt)} — ${fmtAbsoluteIST(fetchedAt)}`;

  return (
    <span style={{ display: "inline-flex", alignItems: "baseline", gap: 4 }}>
      {children}
      <span
        title={tooltip}
        aria-label={tooltip}
        style={{
          fontSize: 9, lineHeight: 1,
          color: stale ? "var(--system-orange)" : "var(--label-quaternary)",
          cursor: "help", userSelect: "none",
        }}
      >🕒</span>
    </span>
  );
}
