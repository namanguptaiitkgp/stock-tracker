"use client";

/**
 * Urgency tiers from the handoff redesign:
 *   ACT NOW — red, sell/trim action required today
 *   REVIEW  — amber, mixed signals, look closer
 *   HOLD    — neutral/green, all clear
 *
 * Plus BUY for discover-mode opportunities.
 */

export type Urgency = "ACT_NOW" | "REVIEW" | "HOLD" | "BUY";

const STYLES: Record<Urgency, { bg: string; color: string; label: string; border: string }> = {
  ACT_NOW: {
    bg: "#FEF2F2",
    color: "#DC2626",
    label: "ACT NOW",
    border: "1px solid rgba(220,38,38,0.2)",
  },
  REVIEW: {
    bg: "#FFFBEB",
    color: "#D97706",
    label: "REVIEW",
    border: "1px solid rgba(217,119,6,0.2)",
  },
  HOLD: {
    bg: "#F0FDF4",
    color: "#16A34A",
    label: "HOLD",
    border: "1px solid rgba(22,163,74,0.2)",
  },
  BUY: {
    bg: "#F0FDF4",
    color: "#16A34A",
    label: "BUY",
    border: "1px solid rgba(22,163,74,0.2)",
  },
};

export function actionToUrgency(
  action: "SELL" | "ACCUMULATE" | "WATCHFUL" | "HOLD" | string,
): Urgency {
  if (action === "SELL") return "ACT_NOW";
  if (action === "WATCHFUL") return "REVIEW";
  if (action === "ACCUMULATE") return "BUY";
  return "HOLD";
}

export const URGENCY_COLOR: Record<Urgency, string> = {
  ACT_NOW: "#DC2626",
  REVIEW: "#D97706",
  HOLD: "#16A34A",
  BUY: "#16A34A",
};

export default function UrgencyBadge({
  urgency,
  size = "sm",
}: {
  urgency: Urgency;
  size?: "sm" | "md";
}) {
  const s = STYLES[urgency];
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        padding: size === "md" ? "4px 10px" : "2px 8px",
        borderRadius: 99,
        fontSize: size === "md" ? 12 : 11.5,
        fontWeight: 600,
        background: s.bg,
        color: s.color,
        border: s.border,
        whiteSpace: "nowrap",
        letterSpacing: "0.02em",
      }}
    >
      {s.label}
    </span>
  );
}
