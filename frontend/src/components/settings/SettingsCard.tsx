"use client";

import React from "react";

/**
 * Apple-HIG card chrome — single source of truth for every Settings
 * card. Replaces the dark Tailwind `bg-gray-900 border-gray-800` blocks
 * with the same `var(--bg-primary)` / `var(--separator-light)` /
 * `var(--shadow-sm)` palette used by the polished Researching and
 * Dashboard pages.
 */

interface Props {
  title: string;
  subtitle?: string;
  status?: { kind: "ok" | "warn" | "error" | "info"; label: string } | null;
  actions?: React.ReactNode;
  children: React.ReactNode;
  /** Reduces internal padding for cards that wrap dense components. */
  dense?: boolean;
}

export default function SettingsCard({ title, subtitle, status, actions, children, dense }: Props) {
  return (
    <section
      style={{
        background: "var(--bg-primary)",
        border: "1px solid var(--separator-light)",
        borderRadius: 16,
        padding: dense ? "16px 18px" : "20px 24px",
        boxShadow: "var(--shadow-sm)",
        display: "flex",
        flexDirection: "column",
        gap: 14,
      }}
    >
      <header
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 12,
          flexWrap: "wrap",
        }}
      >
        <div style={{ minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
            <h3
              style={{
                margin: 0,
                fontFamily: "var(--font-serif)",
                fontSize: 18,
                fontWeight: 600,
                letterSpacing: "-0.01em",
                color: "var(--label-primary)",
              }}
            >
              {title}
            </h3>
            {status && <StatusPill kind={status.kind} label={status.label} />}
          </div>
          {subtitle && (
            <div
              style={{
                marginTop: 2,
                fontSize: 13,
                color: "var(--label-tertiary)",
                lineHeight: 1.45,
              }}
            >
              {subtitle}
            </div>
          )}
        </div>
        {actions && (
          <div style={{ display: "inline-flex", alignItems: "center", gap: 8, flexShrink: 0 }}>
            {actions}
          </div>
        )}
      </header>
      <div>{children}</div>
    </section>
  );
}

function StatusPill({ kind, label }: { kind: "ok" | "warn" | "error" | "info"; label: string }) {
  const palette = {
    ok:    { bg: "var(--buy-bg, rgba(48,209,88,0.08))", fg: "var(--buy)",    edge: "var(--buy-edge, rgba(48,209,88,0.25))" },
    warn:  { bg: "var(--review-bg)",                    fg: "var(--review)", edge: "var(--review-edge)" },
    error: { bg: "var(--act-bg)",                       fg: "var(--act)",    edge: "var(--act-edge)" },
    info:  { bg: "var(--fill-blue)",                    fg: "var(--system-blue)", edge: "rgba(0,122,255,0.2)" },
  }[kind];
  return (
    <span
      style={{
        fontSize: 11,
        fontWeight: 600,
        textTransform: "uppercase",
        letterSpacing: "0.06em",
        padding: "2px 8px",
        borderRadius: 99,
        background: palette.bg,
        color: palette.fg,
        border: `1px solid ${palette.edge}`,
        whiteSpace: "nowrap",
      }}
    >
      {label}
    </span>
  );
}
