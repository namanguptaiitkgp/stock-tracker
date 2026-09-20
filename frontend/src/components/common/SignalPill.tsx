"use client";

export type SignalSource = "FII" | "DII" | "MF" | "INS" | "PRO" | "RET";
export type SignalDirection = "accumulating" | "distributing" | "neutral";

const SOURCE_STYLES: Record<SignalSource, { bg: string; color: string; label: string }> = {
  FII: { bg: "var(--fill-blue)",   color: "var(--system-blue)",   label: "FII" },
  DII: { bg: "var(--fill-purple)", color: "var(--system-purple)", label: "DII" },
  MF:  { bg: "var(--fill-blue)",   color: "var(--system-teal)",   label: "MF" },
  INS: { bg: "var(--fill-green)",  color: "var(--system-green)",  label: "INS" },
  PRO: { bg: "var(--fill-orange)", color: "var(--system-orange)", label: "PRO" },
  RET: { bg: "var(--fill-yellow)", color: "var(--system-yellow)", label: "RET" },
};

function arrowFor(dir: SignalDirection): string {
  if (dir === "accumulating") return "↑";
  if (dir === "distributing") return "↓";
  return "→";
}

export function fmtRecency(iso: string | Date | null | undefined): string {
  if (!iso) return "?";
  const t = typeof iso === "string" ? new Date(iso).getTime() : iso.getTime();
  if (isNaN(t)) return "?";
  const diffS = (Date.now() - t) / 1000;
  if (diffS < 60) return "now";
  if (diffS < 3600) return `${Math.max(1, Math.round(diffS / 60))}m`;
  if (diffS < 86400) return `${Math.max(1, Math.round(diffS / 3600))}h`;
  if (diffS < 86400 * 14) return `${Math.max(1, Math.round(diffS / 86400))}d`;
  if (diffS < 86400 * 60) return `${Math.max(1, Math.round(diffS / (86400 * 7)))}w`;
  return `${Math.max(1, Math.round(diffS / (86400 * 30)))}mo`;
}

export default function SignalPill({
  source,
  direction = "neutral",
  recency,
  title,
}: {
  source: SignalSource;
  direction?: SignalDirection;
  recency?: string | Date | null;
  title?: string;
}) {
  const s = SOURCE_STYLES[source];
  return (
    <span
      title={title}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        padding: "3px 8px",
        borderRadius: 6,
        fontSize: 10.5,
        fontWeight: 600,
        fontFamily: "var(--font-mono)",
        whiteSpace: "nowrap",
        background: s.bg,
        color: s.color,
      }}
    >
      {s.label} {arrowFor(direction)} · {fmtRecency(recency || null)}
    </span>
  );
}
