"use client";

type Kind = "bullish" | "bearish" | "neutral";

const STYLES: Record<Kind, { bg: string; color: string; border: string; label: string }> = {
  bullish: {
    bg: "rgba(52,199,89,0.08)",
    color: "#248A3D",
    border: "1px solid rgba(52,199,89,0.35)",
    label: "BULLISH",
  },
  bearish: {
    bg: "rgba(255,59,48,0.08)",
    color: "#D70015",
    border: "1px solid rgba(255,59,48,0.35)",
    label: "BEARISH",
  },
  neutral: {
    bg: "rgba(255,204,0,0.08)",
    color: "#A05A00",
    border: "1px solid rgba(255,204,0,0.35)",
    label: "NEUTRAL",
  },
};

export default function SentimentBadge({
  sentiment,
  score,
  size = "sm",
}: {
  sentiment: string | null | undefined;
  score?: number | null;
  size?: "sm" | "md";
}) {
  if (!sentiment) {
    return <span style={{ color: "#8E8E93", fontSize: 11 }}>—</span>;
  }
  const key = (sentiment || "").toLowerCase();
  const s = STYLES[(["bullish", "bearish", "neutral"].includes(key) ? key : "neutral") as Kind];
  const fontSize = size === "md" ? 12 : 11;
  return (
    <span
      style={{
        display: "inline-block",
        padding: size === "md" ? "3px 10px" : "2px 8px",
        fontSize,
        fontWeight: 700,
        letterSpacing: 0.5,
        borderRadius: 4,
        backgroundColor: s.bg,
        color: s.color,
        border: s.border,
        whiteSpace: "nowrap",
      }}
    >
      {s.label}
      {score !== null && score !== undefined && (
        <span style={{ marginLeft: 5, opacity: 0.75, fontWeight: 600 }}>
          {score >= 0 ? "+" : ""}
          {score}
        </span>
      )}
    </span>
  );
}
