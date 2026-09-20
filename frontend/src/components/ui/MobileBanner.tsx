"use client";

import React from "react";

type Variant = "info" | "warn" | "error";

interface Props {
  variant?: Variant;
  children: React.ReactNode;
  onDismiss?: () => void;
  // If true, banner is hidden at >=md (where the same info is already in the
  // header inline). Default true — most callers want this.
  mobileOnly?: boolean;
}

const PALETTE: Record<Variant, { bg: string; border: string; fg: string }> = {
  info: {
    bg: "color-mix(in srgb, var(--system-blue) 14%, var(--bg-primary))",
    border: "color-mix(in srgb, var(--system-blue) 35%, transparent)",
    fg: "var(--label-primary)",
  },
  warn: {
    bg: "color-mix(in srgb, var(--system-yellow) 18%, var(--bg-primary))",
    border: "color-mix(in srgb, var(--system-yellow) 40%, transparent)",
    fg: "var(--label-primary)",
  },
  error: {
    bg: "color-mix(in srgb, var(--system-red) 16%, var(--bg-primary))",
    border: "color-mix(in srgb, var(--system-red) 40%, transparent)",
    fg: "var(--label-primary)",
  },
};

export default function MobileBanner({
  variant = "info",
  children,
  onDismiss,
  mobileOnly = true,
}: Props) {
  const p = PALETTE[variant];
  return (
    <div
      className={mobileOnly ? "mobile-banner" : undefined}
      style={{
        background: p.bg,
        borderBottom: `1px solid ${p.border}`,
        color: p.fg,
        padding: "10px 16px",
        fontSize: 13,
        lineHeight: 1.4,
        display: "flex",
        alignItems: "center",
        gap: 12,
      }}
      role={variant === "error" ? "alert" : "status"}
    >
      <div style={{ flex: 1, minWidth: 0 }}>{children}</div>
      {onDismiss && (
        <button
          onClick={onDismiss}
          aria-label="Dismiss"
          style={{
            background: "transparent",
            border: 0,
            color: "var(--label-tertiary)",
            cursor: "pointer",
            fontSize: 18,
            lineHeight: 1,
            padding: 4,
          }}
        >
          ×
        </button>
      )}
      <style jsx>{`
        @media (min-width: 768px) {
          .mobile-banner {
            display: none !important;
          }
        }
      `}</style>
    </div>
  );
}
