"use client";

type Severity = "red" | "amber" | "blue";

const STYLES: Record<Severity, { bg: string; color: string }> = {
  red:   { bg: "var(--fill-red)",    color: "var(--system-red)" },
  amber: { bg: "var(--fill-orange)", color: "var(--system-orange)" },
  blue:  { bg: "var(--fill-blue)",   color: "var(--system-blue)" },
};

export default function RiskFlag({
  severity,
  icon,
  label,
}: {
  severity: Severity;
  icon?: string;
  label: string;
}) {
  const s = STYLES[severity];
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        padding: "3px 8px",
        borderRadius: 6,
        fontSize: 10.5,
        fontWeight: 600,
        background: s.bg,
        color: s.color,
        whiteSpace: "nowrap",
      }}
    >
      {icon && <span style={{ fontSize: 12 }}>{icon}</span>}
      {label}
    </span>
  );
}
