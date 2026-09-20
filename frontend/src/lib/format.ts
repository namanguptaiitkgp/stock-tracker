import React from "react";

// ─── Number / currency formatters ────────────────────────────────────
// All accept null/undefined and return "—" so callers don't need their own
// nullish guard. Naming: `fmtN` / `fmtINR` are the canonical names; older
// callers also alias as `fmtNum` and `pctStr` (re-exported below).

export function fmtN(n: number | null | undefined, d = 2): string {
  if (n == null || (typeof n === "number" && Number.isNaN(n))) return "—";
  return n.toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d });
}

export function fmtINR(n: number | null | undefined, d = 0): string {
  if (n == null || (typeof n === "number" && Number.isNaN(n))) return "—";
  return n.toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d });
}

export function pctStr(n: number | null | undefined, d = 2): string {
  if (n == null || (typeof n === "number" && Number.isNaN(n))) return "—";
  return `${n >= 0 ? "+" : ""}${n.toFixed(d)}%`;
}

export function fmtCr(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return "—";
  if (Math.abs(v) >= 100) return `${(v / 100).toFixed(1)}K Cr`;
  return `${v.toFixed(0)} Cr`;
}

// Volume / count formatter: 1.2 Cr, 80 L, 12 K, 540
export function fmtVol(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return "—";
  if (Math.abs(v) >= 10000000) return `${(v / 10000000).toFixed(2)} Cr`;
  if (Math.abs(v) >= 100000) return `${(v / 100000).toFixed(2)} L`;
  if (Math.abs(v) >= 1000) return `${(v / 1000).toFixed(1)} K`;
  return v.toLocaleString("en-IN");
}

// ─── Date formatters ─────────────────────────────────────────────────

export function fmtDateShort(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "—";
  return d.toLocaleDateString("en-CA");
}

export function fmtRelative(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "—";
  const now = new Date();
  const sameDay = d.toDateString() === now.toDateString();
  const yesterday = new Date(now); yesterday.setDate(now.getDate() - 1);
  const isYesterday = d.toDateString() === yesterday.toDateString();
  const time = d.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", hour12: false });
  if (sameDay) return `Today, ${time}`;
  if (isYesterday) return `Yesterday, ${time}`;
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short" }) + " " + time;
}

// Label for data that legitimately lags one trading day (e.g. smart-money
// rollups that run after market close). Renders "Trading day: 2026-05-18
// (last close)". Pages titled "today" should never just print the raw
// `as_of` string — it misleads when the rollup hasn't run yet.
export function fmtTradingDay(iso: string | null | undefined): string {
  if (!iso) return "Trading day: —";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "Trading day: —";
  return `Trading day: ${d.toLocaleDateString("en-CA")} (last close)`;
}

// Percent formatter that auto-scales raw decimals. Some upstream sources
// return ROE as 0.124 (= 12.4%) while others return 12.4 already. Heuristic:
// `|v| < 1` is treated as a raw decimal and multiplied by 100; otherwise
// taken as already in percent. Pass `assumePercent: true` to disable scaling
// when the call site knows the value is already in percent (e.g. growth
// figures that can legitimately be < 1%).
export function fmtPctSafe(
  n: number | null | undefined,
  opts: { d?: number; assumePercent?: boolean; signed?: boolean } = {},
): string {
  if (n == null || (typeof n === "number" && Number.isNaN(n))) return "—";
  const { d = 1, assumePercent = false, signed = false } = opts;
  const scaled = assumePercent || Math.abs(n) >= 1 ? n : n * 100;
  const sign = signed && scaled >= 0 ? "+" : "";
  return `${sign}${scaled.toFixed(d)}%`;
}

// ─── Aliases (kept so existing callers don't have to rename) ─────────

export const fmtNum = fmtN;
export const formatDate = fmtDateShort;

// ─── React-rendering helpers (legacy) ────────────────────────────────
// Returns a span with a built-in green/red class; callers that want plain
// strings should use `pctStr` directly.

export function N(v: unknown, suffix = ""): string {
  if (v === null || v === undefined) return "--";
  const n = Number(v);
  if (isNaN(n)) return "--";
  return n.toLocaleString("en-IN", { maximumFractionDigits: 2 }) + suffix;
}

export function Pct(v: number | null): React.ReactNode {
  if (v === null) return React.createElement("span", { className: "text-gray-500" }, "--");
  const color = v >= 0 ? "text-green-400" : "text-red-400";
  return React.createElement("span", { className: color }, `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`);
}

export function Vol(v: number | null): string {
  return fmtVol(v);
}
