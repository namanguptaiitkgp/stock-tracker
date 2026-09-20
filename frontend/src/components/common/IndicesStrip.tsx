"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import IndexSummaryDrawer from "./IndexSummaryDrawer";

interface IndexRow {
  slug: string;
  display_name: string;
  short_name: string;
  provider: string;
  ltp: number | null;
  prev_close: number | null;
  change: number | null;
  change_pct: number | null;
  status: string;
  error_message: string | null;
  fetched_at: string | null;
}

interface IndicesResponse {
  indices: IndexRow[];
  count: number;
  fetched_at: string | null;
}

const POLL_MS = 60_000;

function fmt(n: number | null): string {
  if (n === null || n === undefined) return "—";
  return n.toLocaleString("en-IN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function chipColor(cp: number | null): { bg: string; fg: string; arrow: string } {
  if (cp === null || cp === undefined) {
    return { bg: "rgba(142,142,147,0.1)", fg: "#6E6E73", arrow: "·" };
  }
  if (cp > 0.02) return { bg: "rgba(36,138,61,0.08)", fg: "#248A3D", arrow: "▲" };
  if (cp < -0.02) return { bg: "rgba(215,0,21,0.08)", fg: "#D70015", arrow: "▼" };
  return { bg: "rgba(142,142,147,0.08)", fg: "#6E6E73", arrow: "·" };
}

export default function IndicesStrip() {
  const [data, setData] = useState<IndicesResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [selectedSlug, setSelectedSlug] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const d = await api.get<IndicesResponse>("/api/market/indices");
      setData(d);
    } catch {
      // silent — previous data stays visible
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, POLL_MS);
    return () => clearInterval(id);
  }, [load]);

  const selected = data?.indices.find((i) => i.slug === selectedSlug) || null;

  return (
    <>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          overflowX: "auto",
          paddingRight: 4,
          scrollbarWidth: "thin",
        }}
      >
        {loading && !data && (
          <span style={{ fontSize: 11, color: "#8E8E93", whiteSpace: "nowrap" }}>
            Loading indices…
          </span>
        )}

        {data?.indices.map((idx) => {
          const colors = chipColor(idx.change_pct);
          const unavailable = idx.ltp === null;
          return (
            <button
              key={idx.slug}
              onClick={() => setSelectedSlug(idx.slug)}
              title={
                unavailable
                  ? `${idx.display_name} — ${idx.error_message || "unavailable"}`
                  : `${idx.display_name} · last ${fmt(idx.ltp)}`
              }
              style={{
                flexShrink: 0,
                display: "inline-flex",
                alignItems: "center",
                gap: 6,
                padding: "4px 10px",
                borderRadius: 14,
                background: colors.bg,
                border: "1px solid rgba(0,0,0,0.04)",
                color: unavailable ? "#8E8E93" : colors.fg,
                fontSize: 11,
                fontWeight: 600,
                cursor: "pointer",
                whiteSpace: "nowrap",
                fontFamily:
                  "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
              }}
            >
              <span style={{ color: "#1D1D1F", fontWeight: 700 }}>{idx.short_name}</span>
              <span style={{ color: unavailable ? "#8E8E93" : "#1D1D1F" }}>{fmt(idx.ltp)}</span>
              {idx.change_pct !== null && (
                <span>
                  {colors.arrow} {idx.change_pct >= 0 ? "+" : ""}
                  {idx.change_pct.toFixed(2)}%
                </span>
              )}
              {unavailable && <span style={{ fontSize: 10 }}>—</span>}
            </button>
          );
        })}
      </div>

      {selected && (
        <IndexSummaryDrawer
          index={selected}
          onClose={() => setSelectedSlug(null)}
        />
      )}
    </>
  );
}
