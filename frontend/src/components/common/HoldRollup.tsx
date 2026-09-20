"use client";

import { useState } from "react";
import { HoldingAction } from "./PositionCard";
import { pctStr } from "@/lib/format";

interface Props {
  holdings: HoldingAction[];
  onClickSymbol?: (h: HoldingAction) => void;
}

export default function HoldRollup({ holdings, onClickSymbol }: Props) {
  const [open, setOpen] = useState(false);
  if (!holdings.length) return null;

  return (
    <section style={{
      background: "var(--bg-primary)",
      border: "1px dashed var(--separator)",
      borderRadius: 12,
      marginTop: 8,
    }}>
      <button
        onClick={() => setOpen(o => !o)}
        style={{
          display: "flex", alignItems: "center", gap: 10, width: "100%",
          padding: "14px 18px", background: "transparent", border: 0, cursor: "pointer",
          textAlign: "left", color: "var(--label-secondary)", fontSize: 15,
        }}
      >
        <span style={{ color: "var(--hold)", fontSize: 14 }}>■</span>
        <span style={{ fontWeight: 600, color: "var(--label-primary)" }}>Hold</span>
        <span style={{ fontSize: 14, color: "var(--label-tertiary)", flex: 1, fontWeight: 500 }}>
          {holdings.length} stock{holdings.length !== 1 ? "s" : ""} performing as expected
        </span>
        <span style={{
          display: "inline-block",
          transform: open ? "rotate(180deg)" : "rotate(0deg)",
          transition: "transform .15s", fontSize: 12, color: "var(--label-tertiary)",
        }}>▾</span>
      </button>
      {open && (
        <div style={{
          padding: "8px 18px 18px",
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(150px, 1fr))",
          gap: "6px 14px",
        }}>
          {holdings.map(h => (
            <button
              key={h.symbol}
              onClick={() => onClickSymbol?.(h)}
              style={{
                display: "flex", justifyContent: "space-between",
                padding: "7px 12px",
                background: "var(--bg-secondary)", borderRadius: 6,
                fontSize: 13.5, border: 0, textAlign: "left", cursor: onClickSymbol ? "pointer" : "default",
              }}
            >
              <span style={{ fontFamily: "var(--font-mono)", color: "var(--label-primary)" }}>{h.symbol}</span>
              <span style={{
                fontFamily: "var(--font-mono)",
                color: h.day_change_pct >= 0 ? "var(--buy)" : "var(--act)",
              }}>{pctStr(h.day_change_pct)}</span>
            </button>
          ))}
        </div>
      )}
    </section>
  );
}
