"use client";

import React from "react";
import { usePrivacyMode } from "@/lib/privacy-mode";
import { pctStr } from "@/lib/format";

// Compact currency formatter — keeps the ₹ prefix and 1-2 decimal precision
// the hero card needs. Centralised here rather than fmt.ts because every other
// caller uses fmtCr/fmtINR; this one variant is specific to the hero design.
function fmtINRCompact(n: number): string {
  const sign = n < 0 ? "-" : "";
  const abs = Math.abs(n);
  if (abs >= 10_000_000) return `${sign}₹${(abs / 10_000_000).toFixed(2)} Cr`;
  if (abs >= 100_000) return `${sign}₹${(abs / 100_000).toFixed(2)} L`;
  if (abs >= 1000) return `${sign}₹${(abs / 1000).toFixed(1)}K`;
  return `${sign}₹${abs.toFixed(0)}`;
}

interface PortfolioSummary {
  total_invested: number;
  total_current: number;
  total_pnl: number;
  total_pnl_pct: number;
  total_day_pnl: number;
  stock_count: number;
}

interface Props {
  username: string | null;
  summary: PortfolioSummary;
  actCount: number;       // SELL count
  reviewCount: number;    // WATCHFUL count
  topActSymbol: string | null;  // first SELL or REVIEW symbol
  marketStatus: "open" | "closed" | "pre_open" | "weekend" | string;
  lastRefreshIso: string | null;
}



function fmtRefresh(iso: string | null): string {
  if (!iso) return "never";
  const t = new Date(iso).getTime();
  const mins = Math.max(0, Math.round((Date.now() - t) / 60000));
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  return `${Math.round(mins / 60)}h ago`;
}

function greeting(): string {
  const h = new Date().getHours();
  if (h < 5) return "Good evening";
  if (h < 12) return "Good morning";
  if (h < 17) return "Good afternoon";
  return "Good evening";
}

function StatusDot({ status }: { status: string }) {
  const isOpen = status === "open";
  return (
    <span style={{
      width: 8, height: 8, borderRadius: 99,
      background: isOpen ? "var(--system-green)" : "var(--label-quaternary)",
      boxShadow: isOpen ? "0 0 0 3px color-mix(in srgb, var(--system-green) 22%, transparent)" : "none",
      display: "inline-block",
    }} />
  );
}

function Stat({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 8 }}>
      <span style={{
        fontSize: 12, color: "var(--label-tertiary)",
        textTransform: "uppercase", letterSpacing: "0.06em", fontWeight: 500,
      }}>{label}</span>
      <span style={{
        fontFamily: "var(--font-mono)", fontSize: 15, fontWeight: 600,
        color: color || "var(--label-primary)",
      }}>{value}</span>
    </div>
  );
}

export default function PortfolioHero({
  username,
  summary,
  actCount,
  reviewCount,
  topActSymbol,
  marketStatus,
  lastRefreshIso,
}: Props) {
  const isPositive = summary.total_pnl >= 0;
  const isDayPositive = summary.total_day_pnl >= 0;
  const mask = usePrivacyMode();
  const masked = (v: string) => (mask ? "••••" : v);

  // Day pct: approx using day_pnl / current invested
  const dayPnlPct = summary.total_invested > 0
    ? (summary.total_day_pnl / summary.total_invested) * 100
    : 0;

  function scrollToSymbol() {
    if (!topActSymbol) return;
    const el = document.getElementById(`pcard-${topActSymbol}`);
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "start" });
      // brief highlight
      el.style.transition = "box-shadow 0.4s ease";
      el.style.boxShadow = "0 0 0 4px color-mix(in srgb, var(--act) 22%, transparent), var(--shadow-md)";
      setTimeout(() => { el.style.boxShadow = ""; }, 1800);
    }
  }

  // Build the summary sentence based on counts
  let summarySentence: React.ReactNode;
  if (actCount > 0 && reviewCount > 0) {
    summarySentence = (
      <>
        <span style={{ color: "var(--act)", fontWeight: 700 }}>{actCount}</span> position{actCount !== 1 ? "s" : ""} need{actCount === 1 ? "s" : ""} immediate action,{" "}
        <span style={{ color: "var(--review)", fontWeight: 700 }}>{reviewCount}</span> need review.
      </>
    );
  } else if (actCount > 0) {
    summarySentence = (
      <>
        <span style={{ color: "var(--act)", fontWeight: 700 }}>{actCount}</span> position{actCount !== 1 ? "s" : ""} need{actCount === 1 ? "s" : ""} immediate action.
      </>
    );
  } else if (reviewCount > 0) {
    summarySentence = (
      <>
        <span style={{ color: "var(--review)", fontWeight: 700 }}>{reviewCount}</span> position{reviewCount !== 1 ? "s" : ""} need{reviewCount === 1 ? "s" : ""} review today.
      </>
    );
  } else {
    summarySentence = <>Portfolio looks calm — no urgent actions today.</>;
  }

  return (
    <section className="portfolio-hero" style={{
      background: "var(--bg-primary)",
      border: "1px solid var(--separator-light)",
      borderRadius: 16,
      padding: "28px 32px",
      display: "grid",
      gridTemplateColumns: "1.4fr 1fr",
      gap: 32,
      marginBottom: 28,
      boxShadow: "var(--shadow-sm)",
      position: "relative",
      overflow: "hidden",
    }}>
      {/* radial corner accent */}
      <div style={{
        position: "absolute", right: -80, top: -80,
        width: 280, height: 280, borderRadius: "50%",
        background: "radial-gradient(circle, color-mix(in srgb, var(--act) 8%, transparent), transparent 70%)",
        pointerEvents: "none",
      }} />

      {/* Left */}
      <div style={{ position: "relative", zIndex: 1, minWidth: 0 }}>
        <div style={{
          display: "inline-flex", alignItems: "center", gap: 8,
          fontSize: 13, color: "var(--label-tertiary)", marginBottom: 14,
        }}>
          <StatusDot status={marketStatus} />
          <span>
            {marketStatus === "open" ? "Market open" : marketStatus === "weekend" ? "Weekend · market closed" : marketStatus === "pre_open" ? "Pre-open" : "Market closed"}
            {" · last refresh "}
            {fmtRefresh(lastRefreshIso)}
          </span>
        </div>

        <h2 style={{ margin: "0 0 22px", lineHeight: 1.15, fontFamily: "var(--font-serif)", fontWeight: 500 }}>
          <span style={{
            display: "block", fontFamily: "var(--font-sans)",
            fontSize: 14, fontWeight: 500, color: "var(--label-tertiary)",
            marginBottom: 10, letterSpacing: "0.04em", textTransform: "uppercase",
          }}>
            {greeting()}, {username || "there"}.
          </span>
          <span className="hero-summary" style={{
            display: "block", fontFamily: "var(--font-serif)",
            fontSize: 34, fontWeight: 500, lineHeight: 1.2, letterSpacing: "-0.025em",
            maxWidth: 560, color: "var(--label-primary)",
          }}>
            {summarySentence}
          </span>
        </h2>

        {topActSymbol ? (
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
            <button
              onClick={scrollToSymbol}
              style={{
                background: "var(--label-primary)", color: "var(--bg-primary)",
                border: 0, padding: "13px 20px", borderRadius: 10,
                fontSize: 15, fontWeight: 600, cursor: "pointer",
                display: "inline-flex", alignItems: "center", gap: 8,
              }}
            >
              Start with {topActSymbol} <span>→</span>
            </button>
          </div>
        ) : null}
      </div>

      {/* Right */}
      <div className="hero-right" style={{
        display: "flex", flexDirection: "column", gap: 14, alignItems: "flex-end",
        position: "relative", zIndex: 1, minWidth: 0,
      }}>
        <div className="hero-pnl-block" style={{ textAlign: "right" }}>
          <div style={{
            fontSize: 12, color: "var(--label-tertiary)",
            textTransform: "uppercase", letterSpacing: "0.08em", fontWeight: 500,
          }}>Portfolio P&L</div>
          <div className="hero-pnl" style={{
            fontFamily: "var(--font-serif)", fontSize: 42, fontWeight: 600, lineHeight: 1.15,
            marginTop: 6, letterSpacing: "-0.02em", whiteSpace: "nowrap",
            color: isPositive ? "var(--buy)" : "var(--act)",
          }}>
            {masked(`${isPositive ? "+" : ""}${fmtINRCompact(summary.total_pnl)}`)}
          </div>
          <div style={{
            fontSize: 14, fontWeight: 500, marginTop: 4,
            color: isPositive ? "var(--buy)" : "var(--act)",
          }}>
            {pctStr(summary.total_pnl_pct)} all time
          </div>
        </div>

        <div className="hero-stats-grid" style={{
          display: "grid", gridTemplateColumns: "1fr 1fr",
          gap: "8px 24px", width: "100%",
          paddingTop: 14,
          borderTop: "1px solid var(--separator-light)",
        }}>
          <Stat label="Invested" value={masked(fmtINRCompact(summary.total_invested))} />
          <Stat label="Current" value={masked(fmtINRCompact(summary.total_current))} />
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 8 }}>
            <span style={{
              fontSize: 12, color: "var(--label-tertiary)",
              textTransform: "uppercase", letterSpacing: "0.06em", fontWeight: 500,
            }}>Today</span>
            <span style={{
              fontFamily: "var(--font-mono)", fontSize: 15, fontWeight: 600,
              color: isDayPositive ? "var(--buy)" : "var(--act)",
              whiteSpace: "nowrap",
            }}>
              {pctStr(dayPnlPct)}{" "}
              <span style={{ fontWeight: 400, fontSize: 12, opacity: 0.8 }}>({masked(fmtINRCompact(summary.total_day_pnl))})</span>
            </span>
          </div>
          <Stat label="Stocks" value={String(summary.stock_count)} />
        </div>
      </div>

      <style jsx>{`
        @media (max-width: 720px) {
          .portfolio-hero {
            grid-template-columns: 1fr !important;
            padding: 20px 16px !important;
            gap: 20px !important;
          }
          .hero-summary { font-size: 24px !important; }
          .hero-pnl { font-size: 32px !important; white-space: normal !important; }
          .hero-right { align-items: flex-start !important; }
          .hero-pnl-block { text-align: left !important; }
        }
        @media (max-width: 480px) {
          .hero-stats-grid {
            grid-template-columns: 1fr !important;
            gap: 10px 0 !important;
          }
          .hero-pnl { font-size: 28px !important; }
        }
      `}</style>
    </section>
  );
}
