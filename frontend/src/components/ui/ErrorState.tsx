"use client";

import React from "react";

interface Props {
  message?: string | null;
  detail?: string | null;
  onRetry?: () => void;
  compact?: boolean;
}

/**
 * Inline error state shown in widgets when a fetch fails. Designed to slot
 * into the same space a loading spinner / skeleton occupies, so callers
 * just swap one for the other on `error` / `loading` state.
 */
export default function ErrorState({
  message = "Couldn't load data.",
  detail,
  onRetry,
  compact = false,
}: Props) {
  return (
    <div
      role="alert"
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "flex-start",
        gap: 8,
        padding: compact ? "10px 12px" : "16px 18px",
        borderRadius: 10,
        border: "1px solid var(--separator-light, rgba(127,127,127,0.2))",
        background: "var(--fill-red, rgba(255,59,48,0.08))",
        color: "var(--label-primary, inherit)",
        fontSize: compact ? 12 : 13,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span
          aria-hidden
          style={{
            display: "inline-flex",
            width: 18,
            height: 18,
            borderRadius: 99,
            background: "var(--system-red, #ff3b30)",
            color: "#fff",
            alignItems: "center",
            justifyContent: "center",
            fontSize: 11,
            fontWeight: 700,
          }}
        >
          !
        </span>
        <span style={{ fontWeight: 600 }}>{message}</span>
      </div>
      {detail && (
        <div style={{ fontSize: 11, color: "var(--label-secondary, #8e8e93)" }}>
          {detail}
        </div>
      )}
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          style={{
            marginTop: 2,
            padding: "5px 10px",
            borderRadius: 6,
            border: "1px solid var(--separator-light, rgba(127,127,127,0.25))",
            background: "var(--bg-primary, transparent)",
            color: "var(--label-primary, inherit)",
            fontSize: 12,
            fontWeight: 500,
            cursor: "pointer",
          }}
        >
          Retry
        </button>
      )}
    </div>
  );
}
