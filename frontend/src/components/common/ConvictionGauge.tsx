"use client";

/**
 * Single-line score bar -100..+100. Used three-up in `SmartMoneyPanel`
 * for the Conviction / Flow / Red-Flag triple gauge, and standalone
 * elsewhere when only one score is shown.
 *
 * Coloring follows the same semantic palette as the rest of the app:
 * green = positive / accumulation, amber = mild concern, red = warning.
 * For red-flag scores (always 0..-100) we lock the colour to the
 * negative side regardless of the value — `kind="red_flag"`.
 */

interface Props {
  label: string;
  value: number | null;
  // Locks the colour direction. "neutral" follows sign; "red_flag"
  // is always red when value < 0, grey when 0.
  kind?: "neutral" | "red_flag";
  // Tooltip text — shown on hover via the `title` attribute.
  hint?: string;
}

export default function ConvictionGauge({ label, value, kind = "neutral", hint }: Props) {
  const v = value ?? 0;
  const pct = (v + 100) / 2;
  const color = scoreColor(value, kind);

  return (
    <div style={{ width: "100%" }} title={hint}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 4 }}>
        <span style={{ fontSize: 11, color: "var(--label-tertiary)", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.04em" }}>
          {label}
        </span>
        <span style={{ fontSize: 14, fontWeight: 700, color, fontFamily: "var(--font-mono)" }}>
          {value === null || value === undefined ? "—" : `${v >= 0 ? "+" : ""}${Math.round(v)}`}
        </span>
      </div>
      <div
        style={{
          position: "relative",
          height: 6,
          borderRadius: 3,
          background: "linear-gradient(90deg, var(--act-bg) 0%, color-mix(in srgb, var(--label-quaternary) 12%, transparent) 50%, var(--buy-bg) 100%)",
        }}
      >
        <div
          style={{
            position: "absolute",
            left: `${pct}%`,
            top: -3,
            width: 3,
            height: 12,
            borderRadius: 1,
            background: color,
            transform: "translateX(-1.5px)",
            boxShadow: `0 0 0 2px color-mix(in srgb, ${color} 18%, transparent)`,
          }}
        />
      </div>
    </div>
  );
}

function scoreColor(v: number | null | undefined, kind: "neutral" | "red_flag"): string {
  if (v === null || v === undefined) return "var(--label-quaternary)";
  if (kind === "red_flag") {
    if (v <= -50) return "var(--act)";
    if (v < 0) return "var(--review)";
    return "var(--label-quaternary)";
  }
  if (v >= 40) return "var(--buy)";
  if (v >= 15) return "var(--buy)";
  if (v <= -40) return "var(--act)";
  if (v <= -15) return "var(--review)";
  return "var(--label-tertiary)";
}
