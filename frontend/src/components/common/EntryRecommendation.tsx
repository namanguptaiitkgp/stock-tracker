"use client";

import { N } from "@/lib/format";

interface EntryRecommendationData {
  entry_price_low: number;
  entry_price_high: number;
  stop_loss: number;
  target_price: number;
  time_horizon: string;
}

interface Props {
  data: EntryRecommendationData;
  analyzedAt?: string;
}

export default function EntryRecommendation({ data, analyzedAt }: Props) {
  return (
    <section style={{
      background: "var(--bg-primary)",
      border: "1px solid var(--separator-light)",
      borderRadius: 12,
      padding: 16,
      boxShadow: "var(--shadow-card)",
    }}>
      <div style={{
        display: "flex", justifyContent: "space-between", alignItems: "center",
        marginBottom: 10,
      }}>
        <span style={{
          fontSize: 11, fontWeight: 600, textTransform: "uppercase",
          letterSpacing: "0.08em", color: "var(--label-tertiary)",
        }}>
          Entry Recommendation
        </span>
        {analyzedAt && (
          <span style={{ fontSize: 11, color: "var(--label-quaternary)" }}>
            {new Date(analyzedAt).toLocaleDateString("en-IN", { day: "numeric", month: "short" })}
          </span>
        )}
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", columnGap: 24 }}>
        <div>
          <Row label="Entry Range" value={`₹${N(data.entry_price_low)} — ₹${N(data.entry_price_high)}`} />
          <Row label="Stop Loss" value={`₹${N(data.stop_loss)}`} accent="var(--system-red)" last />
        </div>
        <div>
          <Row label="Target" value={`₹${N(data.target_price)}`} accent="var(--system-green)" />
          <Row label="Time Horizon" value={data.time_horizon} last />
        </div>
      </div>
    </section>
  );
}

function Row({ label, value, last, accent }: { label: string; value: string; last?: boolean; accent?: string }) {
  return (
    <div style={{
      display: "flex", justifyContent: "space-between", alignItems: "center",
      padding: "9px 0",
      borderBottom: last ? "none" : "1px dashed var(--separator-light)",
    }}>
      <span style={{ fontSize: 13, color: "var(--label-tertiary)" }}>{label}</span>
      <span style={{
        fontSize: 13, fontWeight: 500,
        fontFamily: "var(--font-mono)",
        color: accent || "var(--label-primary)",
      }}>{value}</span>
    </div>
  );
}
