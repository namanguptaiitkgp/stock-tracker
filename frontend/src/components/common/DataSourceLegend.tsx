"use client";

const SOURCES: Record<string, { label: string; color: string }> = {
  yfinance: { label: "Yahoo Finance", color: "#6E6E73" },
  tickertape: { label: "Tickertape", color: "#AF52DE" },
  gemini: { label: "Gemini AI", color: "#007AFF" },
};

interface Props {
  dataSources?: Record<string, string> | null;
}

export function DataSourceCaption({ dataSources }: Props) {
  if (!dataSources) return null;
  const unique = [...new Set(Object.values(dataSources))];
  if (unique.length === 0) return null;
  const names = unique.map((s) => SOURCES[s]?.label || s).join(", ");
  return (
    <div className="text-xs mb-2" style={{ color: "var(--label-tertiary)" }}>
      Data from {names}
    </div>
  );
}

export default function DataSourceLegend() {
  return (
    <div
      className="flex items-center gap-3 text-xs py-3 mt-2"
      style={{ color: "var(--label-tertiary)", borderTop: "0.5px solid var(--separator-light)" }}
    >
      {Object.entries(SOURCES).map(([key, { label, color }]) => (
        <span key={key} className="flex items-center gap-1">
          <span className="font-mono text-[9px] px-1 rounded" style={{ color, background: `${color}12` }}>
            {key === "yfinance" ? "yf" : key === "tickertape" ? "tt" : "ai"}
          </span>
          {label}
        </span>
      ))}
    </div>
  );
}
