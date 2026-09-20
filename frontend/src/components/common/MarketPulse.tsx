"use client";

import React, { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { pctStr } from "@/lib/format";
import { SectorListRow } from "@/components/market-brief/SectorListRow";
import type { SectorCard } from "@/lib/market-brief-api";
import { useBodyScrollLock, useTapNotDrag } from "@/lib/modal-utils";

interface IndexComponent {
  slug: string;
  name: string;
  short_name: string;
  ltp: number | null;
  change_pct: number;
  weight: number;
}

interface Driver {
  label: string;
  weight: "high" | "medium" | "low";
  sentiment: "positive" | "negative" | "neutral";
}

interface Headline {
  title: string;
  source: string;
  url: string;
  impact: "high" | "medium" | "low";
}

interface Vix { ltp: number | null; change_pct: number | null; }

interface MarketPulseData {
  direction: "up" | "down" | "flat" | null;
  magnitude: "neutral" | "mild" | "moderate" | "strong" | null;
  label: string | null;
  score: number | null;
  breadth: number | null;
  components: IndexComponent[] | null;
  vix: Vix | null;
  one_liner: string | null;
  summary: string | null;
  drivers: Driver[] | null;
  top_headlines: Headline[] | null;
  news_count: number;
  generated_at: string | null;
  expires_at: string | null;
  cached?: boolean;
  error_message?: string | null;
}

interface FiiDii {
  fii: { buy: number | null; sell: number | null; net: number | null } | null;
  dii: { buy: number | null; sell: number | null; net: number | null } | null;
}

function fmtMinsAgo(iso: string | null): string {
  if (!iso) return "";
  const t = new Date(iso).getTime();
  const mins = Math.max(0, Math.round((Date.now() - t) / 60000));
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  return `${Math.round(mins / 60)}h ago`;
}

function fmtCr(v: number | null): string {
  if (v == null) return "—";
  const abs = Math.abs(v);
  // values in crore from FII/DII data
  return `${v >= 0 ? "+" : "-"}₹${abs.toFixed(0)} Cr`;
}

// ---------- Pill (top, gradient) ----------
function MarketPulsePill({
  data,
  fiiDii,
  onOpenBrief,
}: {
  data: MarketPulseData;
  fiiDii: FiiDii | null;
  onOpenBrief: () => void;
}) {
  const falling = data.direction === "down";
  const rising = data.direction === "up";
  const accent = falling ? "var(--act)" : rising ? "var(--buy)" : "var(--label-secondary)";
  const accentBg = falling ? "var(--act-bg)" : rising ? "var(--buy-bg)" : "var(--bg-secondary)";
  const accentEdge = falling ? "var(--act-edge)" : rising ? "var(--buy-edge)" : "var(--separator-light)";

  // Find Nifty 50 from components for the bench badge
  const nifty = data.components?.find((c) => c.slug === "nifty50");
  const sensex = data.components?.find((c) => c.slug === "sensex");
  const banknifty = data.components?.find((c) => c.slug === "banknifty");

  const arrow = falling ? "▼" : rising ? "▲" : "↔";
  const tagText = falling ? "Markets Falling" : rising ? "Markets Rising" : "Markets Flat";

  return (
    <div style={{
      borderRadius: 12,
      padding: "18px 22px",
      marginBottom: 16,
      display: "flex", alignItems: "center", gap: 24, justifyContent: "space-between",
      flexWrap: "wrap",
      background: `linear-gradient(135deg, ${accentBg}, color-mix(in oklch, ${accentBg} 60%, var(--bg-primary)))`,
      border: `1px solid ${accentEdge}`,
      position: "relative", overflow: "hidden",
    }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 8, minWidth: 0, flex: 1 }}>
        {/* Tag row */}
        <div style={{
          display: "inline-flex", alignItems: "center", gap: 10, flexWrap: "wrap",
          fontSize: 12, fontWeight: 600, letterSpacing: "0.04em", textTransform: "uppercase",
          color: accent,
        }}>
          <span style={{ fontSize: 14 }}>{arrow}</span>
          <span style={{ letterSpacing: "0.06em", whiteSpace: "nowrap" }}>{tagText}</span>
          {nifty && (
            <span style={{
              fontFamily: "var(--font-mono)", fontSize: 11.5, fontWeight: 600,
              background: "color-mix(in srgb, var(--bg-primary) 80%, transparent)",
              padding: "3px 8px", borderRadius: 5, letterSpacing: 0,
              color: "var(--label-primary)",
            }}>
              {nifty.short_name} {pctStr(nifty.change_pct)}
            </span>
          )}
        </div>

        {/* Headline (serif) */}
        {data.one_liner && (
          <div style={{
            fontFamily: "var(--font-serif)", fontSize: 19, fontWeight: 500, lineHeight: 1.35,
            color: "var(--label-primary)", letterSpacing: "-0.01em", maxWidth: 720,
          }}>
            {data.one_liner}
          </div>
        )}

        {/* Context strip */}
        <div style={{
          display: "flex", flexWrap: "wrap", gap: "6px 10px", alignItems: "center",
          fontSize: 12.5, color: "var(--label-secondary)",
        }}>
          {sensex && (
            <span><strong style={{ color: "var(--label-primary)", fontWeight: 600 }}>Sensex</strong>{" "}<span style={{ color: sensex.change_pct < 0 ? "var(--system-red)" : "var(--system-green)" }}>{pctStr(sensex.change_pct)}</span></span>
          )}
          {banknifty && (
            <>
              <span style={{ color: "var(--label-quaternary)" }}>·</span>
              <span><strong style={{ color: "var(--label-primary)", fontWeight: 600 }}>BankNifty</strong>{" "}<span style={{ color: banknifty.change_pct < 0 ? "var(--system-red)" : "var(--system-green)" }}>{pctStr(banknifty.change_pct)}</span></span>
            </>
          )}
          {data.vix?.change_pct != null && (
            <>
              <span style={{ color: "var(--label-quaternary)" }}>·</span>
              <span style={{ color: data.vix.change_pct > 0 ? "var(--system-red)" : "var(--system-green)" }}>
                <strong style={{ fontWeight: 600 }}>VIX</strong>{" "}{pctStr(data.vix.change_pct)}
                {data.vix.change_pct > 5 ? " (fear up)" : data.vix.change_pct < -5 ? " (calm)" : ""}
              </span>
            </>
          )}
          {fiiDii?.fii?.net != null && (
            <>
              <span style={{ color: "var(--label-quaternary)" }}>·</span>
              <span>FII <span style={{ color: fiiDii.fii.net < 0 ? "var(--system-red)" : "var(--system-green)", fontFamily: "var(--font-mono)" }}>{fmtCr(fiiDii.fii.net)}</span></span>
            </>
          )}
          {data.generated_at && (
            <>
              <span style={{ color: "var(--label-quaternary)" }}>·</span>
              <span style={{ color: "var(--label-secondary)", fontSize: 11.5 }}>
                Updated {fmtMinsAgo(data.generated_at)}
              </span>
            </>
          )}
        </div>
      </div>

      <div className="market-pulse-action" style={{ display: "flex", gap: 8, alignItems: "center", flexShrink: 0 }}>
        <button
          onClick={onOpenBrief}
          style={{
            background: "var(--label-primary)",
            color: "var(--bg-primary)",
            border: 0,
            padding: "10px 16px", borderRadius: 9,
            fontSize: 13, fontWeight: 600, cursor: "pointer",
            display: "inline-flex", alignItems: "center", gap: 6,
            whiteSpace: "nowrap",
          }}
        >
          Read market brief
          <span>→</span>
        </button>
        <a
          href="https://www.moneycontrol.com/stocksmarketsindia/360-degree-market-view-heat-map"
          target="_blank"
          rel="noopener noreferrer"
          style={{
            background: "transparent",
            color: "var(--label-primary)",
            border: "1px solid var(--separator-non-opaque)",
            padding: "10px 14px", borderRadius: 9,
            fontSize: 13, fontWeight: 600,
            display: "inline-flex", alignItems: "center", gap: 6,
            whiteSpace: "nowrap",
            textDecoration: "none",
          }}
        >
          View Universe
          <span>↗</span>
        </a>
      </div>
      <style jsx>{`
        @media (max-width: 720px) {
          .market-pulse-action {
            flex-basis: 100% !important;
            width: 100%;
          }
          .market-pulse-action :global(button) {
            width: 100%;
            justify-content: center;
          }
        }
      `}</style>
    </div>
  );
}

// ---------- Detail (collapsible: drivers + indices + headlines) ----------
function SectionTitle({ children, right }: { children: React.ReactNode; right?: React.ReactNode }) {
  return (
    <div style={{
      display: "flex", justifyContent: "space-between", alignItems: "baseline",
      marginBottom: 12, paddingBottom: 8,
      borderBottom: "1px solid var(--separator-light)",
    }}>
      <span style={{
        fontFamily: "var(--font-serif)", fontSize: 18, fontWeight: 600,
        color: "var(--label-primary)", letterSpacing: "-0.01em",
      }}>{children}</span>
      {right}
    </div>
  );
}

function DriverChip({ d }: { d: Driver }) {
  const sev =
    d.sentiment === "negative" ? { bg: "var(--act-bg)", color: "var(--act)", icon: "▼" }
    : d.sentiment === "positive" ? { bg: "var(--buy-bg)", color: "var(--buy)", icon: "▲" }
    : { bg: "var(--bg-secondary)", color: "var(--label-secondary)", icon: "→" };
  // Magnitude is rendered in neutral grey across all weights — opacity
  // carries the intensity. Previously HIGH was painted red which read as
  // "negative" even on positive drivers (green ▲), undermining the
  // sentiment arrow. Direction comes from `sev.icon` only.
  const wgtOpacity =
    d.weight === "high" ? 1 : d.weight === "medium" ? 0.8 : 0.6;
  return (
    <div
      title={`Driver impact: ${d.weight.toUpperCase()} — magnitude conveyed via chip opacity, not color.`}
      style={{
        display: "inline-flex", gap: 9, alignItems: "center",
        padding: "9px 12px", borderRadius: 8,
        background: sev.bg, fontSize: 12.5,
      }}
    >
      <span style={{ color: sev.color, fontSize: 13, fontWeight: 700, flexShrink: 0 }}>{sev.icon}</span>
      <span style={{ flex: 1, color: "var(--label-primary)", fontWeight: 500 }}>{d.label}</span>
      <span style={{
        fontFamily: "var(--font-mono)",
        fontSize: 10, fontWeight: 700, letterSpacing: "0.06em",
        padding: "2px 6px", borderRadius: 4,
        background: "var(--bg-secondary)",
        color: "var(--label-secondary)",
        textTransform: "uppercase" as const,
        opacity: wgtOpacity,
      }}>{d.weight}</span>
    </div>
  );
}

function HeadlineCard({ h }: { h: Headline }) {
  const impactColor =
    h.impact === "high" ? "var(--act)"
    : h.impact === "medium" ? "var(--review)"
    : "var(--label-tertiary)";
  return (
    <a
      href={h.url || "#"}
      target="_blank"
      rel="noreferrer"
      style={{
        display: "block",
        padding: "14px 16px",
        background: "var(--bg-primary)",
        border: "1px solid var(--separator-light)",
        borderRadius: 10,
        textDecoration: "none",
        color: "inherit",
        boxShadow: "var(--shadow-xs)",
      }}
    >
      <div style={{
        fontFamily: "var(--font-serif)",
        fontSize: 14.5, fontWeight: 500,
        color: "var(--label-primary)", lineHeight: 1.4, marginBottom: 10,
        letterSpacing: "-0.005em",
      }}>
        {h.title}
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: 11 }}>
        <span style={{ color: "var(--label-tertiary)", fontWeight: 500 }}>{h.source}</span>
        {h.impact && (
          <span style={{
            color: impactColor, fontWeight: 600,
            textTransform: "uppercase" as const, letterSpacing: "0.05em",
            fontSize: 10.5,
          }}>
            {h.impact} impact
          </span>
        )}
      </div>
    </a>
  );
}

function MarketPulseDetail({ data, sectors, initialExpandedSector }: {
  data: MarketPulseData;
  sectors?: SectorCard[];
  initialExpandedSector?: string | null;
}) {
  const [expandedSector, setExpandedSector] = useState<string | null>(initialExpandedSector ?? null);
  const [sectorsLocal, setSectorsLocal] = useState<SectorCard[] | undefined>(sectors);
  const sectorsContainerRef = React.useRef<HTMLDivElement | null>(null);

  // Keep local state in sync when the parent re-passes brief.sectors after
  // a dashboard refresh. Only replaces the list — per-sector edits via the
  // inline refresh button go through the onUpdated callback below.
  useEffect(() => { setSectorsLocal(sectors); }, [sectors]);

  // Deep-link: when MarketPulseDetail mounts (or initialExpandedSector
  // changes) via a "market-brief:open" event, expand that sector and
  // scroll it into view so the user lands on the right row.
  useEffect(() => {
    if (!initialExpandedSector) return;
    setExpandedSector(initialExpandedSector);
    const t = setTimeout(() => {
      const el = sectorsContainerRef.current?.querySelector(
        `[data-sector="${CSS.escape(initialExpandedSector)}"]`
      );
      (el as HTMLElement | null)?.scrollIntoView({ behavior: "smooth", block: "center" });
    }, 80);
    return () => clearTimeout(t);
  }, [initialExpandedSector]);

  const handleSectorUpdated = (next: SectorCard) => {
    setSectorsLocal((prev) => prev ? prev.map((s) => s.sector === next.sector ? next : s) : prev);
  };

  // Show every registered index — the auto-fit grid wraps multi-row so
  // the larger set (sectorals + broad) lays out naturally. Sort by
  // absolute change_pct so today's biggest movers surface first.
  const movers = (data.components || [])
    .slice()
    .sort((a, b) => Math.abs(b.change_pct) - Math.abs(a.change_pct));

  return (
    <section style={{
      padding: 22,
      background: "var(--bg-primary)",
      borderRadius: 12,
      display: "flex", flexDirection: "column", gap: 22,
    }}>
      {/* Drivers */}
      {data.drivers && data.drivers.length > 0 && (
        <div>
          <SectionTitle>Drivers</SectionTitle>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 10 }}>
            {data.drivers.map((d, i) => <DriverChip key={i} d={d} />)}
          </div>
        </div>
      )}

      {/* Top Headlines */}
      {data.top_headlines && data.top_headlines.length > 0 && (
        <div>
          <SectionTitle right={
            <span style={{ fontSize: 12, color: "var(--label-tertiary)" }}>
              {data.news_count} headlines analyzed
            </span>
          }>Top Headlines</SectionTitle>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 10 }}>
            {data.top_headlines.slice(0, 4).map((h, i) => <HeadlineCard key={i} h={h} />)}
          </div>
        </div>
      )}

      {/* Indices */}
      {movers.length > 0 && (
        <div>
          <SectionTitle right={
            <span style={{ fontSize: 12, color: "var(--label-tertiary)" }}>
              Breadth: {Math.round((data.breadth ?? 0) * 100)}%
              {data.vix?.change_pct != null && ` · VIX ${pctStr(data.vix.change_pct)}`}
            </span>
          }>Indices</SectionTitle>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(110px, 1fr))", gap: 8 }}>
            {movers.map((c) => {
              const cp = c.change_pct;
              const up = cp >= 0;
              return (
                <div key={c.slug} style={{
                  padding: "10px 12px",
                  background: "var(--bg-secondary)",
                  borderRadius: 8,
                  border: "1px solid var(--separator-light)",
                }}>
                  <div style={{ fontSize: 11, color: "var(--label-tertiary)", fontWeight: 500, marginBottom: 4 }}>
                    {c.short_name}
                  </div>
                  <div style={{
                    fontFamily: "var(--font-mono)", fontSize: 14, fontWeight: 600,
                    color: up ? "var(--system-green)" : "var(--system-red)",
                  }}>
                    {pctStr(cp)}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Sectors — per-sector sentiment (score, drivers, what-to-watch),
          sourced from brief.sectors. Click a row to expand the inline
          detail panel below it. */}
      <div>
        <SectionTitle right={
          <span style={{ fontSize: 12, color: "var(--label-tertiary)" }}>
            {sectorsLocal && sectorsLocal.length > 0
              ? `${sectorsLocal.length} ${sectorsLocal.length === 1 ? "sector" : "sectors"}`
              : "auto-refreshes 08:15 IST"}
          </span>
        }>Sectors</SectionTitle>
        {!sectorsLocal || sectorsLocal.length === 0 ? (
          <div style={{
            padding: "14px 12px", fontSize: 12.5, color: "var(--label-tertiary)",
            background: "var(--bg-secondary)", border: "1px solid var(--separator-light)",
            borderRadius: 8,
          }}>
            No sector analysis yet — runs daily at 08:15 IST. You can also
            trigger a refresh per sector once one is listed here.
          </div>
        ) : (
          <div
            ref={sectorsContainerRef}
            style={{
              border: "1px solid var(--separator-light)",
              borderRadius: 8, overflow: "hidden",
              background: "var(--bg-primary)",
            }}
          >
            {sectorsLocal.map((s, i) => (
              <div key={s.sector} data-sector={s.sector}>
                <SectorListRow
                  card={s}
                  expanded={expandedSector === s.sector}
                  onToggle={() => setExpandedSector((prev) => prev === s.sector ? null : s.sector)}
                  onUpdated={handleSectorUpdated}
                  isFirst={i === 0}
                />
              </div>
            ))}
          </div>
        )}
      </div>

      {data.cached && data.generated_at && (
        <div style={{ fontSize: 11, color: "var(--label-tertiary)", textAlign: "right" }}>
          Cached · generated {fmtMinsAgo(data.generated_at)}
        </div>
      )}
    </section>
  );
}

// ---------- Skeleton ----------
function PulseSkeleton() {
  return (
    <div className="animate-pulse" style={{
      borderRadius: 12, padding: "18px 22px", marginBottom: 16,
      background: "var(--bg-secondary)",
      border: "1px solid var(--separator-light)",
    }}>
      <div style={{ height: 14, width: 180, background: "var(--fill-gray)", borderRadius: 4, marginBottom: 10 }} />
      <div style={{ height: 22, width: "70%", background: "var(--fill-gray)", borderRadius: 4, marginBottom: 8 }} />
      <div style={{ height: 12, width: "50%", background: "var(--fill-gray)", borderRadius: 4 }} />
    </div>
  );
}

// ---------- Main ----------
export default function MarketPulse({ sectors }: { sectors?: SectorCard[] } = {}) {
  const [data, setData] = useState<MarketPulseData | null>(null);
  const [fiiDii, setFiiDii] = useState<FiiDii | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  async function load() {
    setLoading(true);
    try {
      const [d, fd] = await Promise.all([
        api.get<MarketPulseData>("/api/market/pulse").catch(() => null),
        api.get<FiiDii>("/api/market-data/fii-dii").catch(() => null),
      ]);
      setData(d);
      setFiiDii(fd);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, []);

  async function refresh() {
    setRefreshing(true);
    try {
      const d = await api.post<MarketPulseData>("/api/market/pulse/refresh", {});
      setData(d);
    } catch { /* ignore */ }
    setRefreshing(false);
  }

  const [briefOpen, setBriefOpen] = useState(false);
  // When opened via a "market-brief:open" event from elsewhere on the
  // page (e.g. the sector chip on a holding card), this carries the
  // sector to auto-expand inside the modal's Sectors section. Cleared
  // after consumption so subsequent opens don't auto-expand stale state.
  const [pendingSector, setPendingSector] = useState<string | null>(null);

  // Cross-component navigation: a holding card's sector chip dispatches
  // CustomEvent "market-brief:open" with `detail.sector` so this modal
  // opens with that sector pre-expanded. Decoupled — no prop drilling.
  useEffect(() => {
    function onOpen(e: Event) {
      const detail = (e as CustomEvent).detail || {};
      if (detail.sector) setPendingSector(detail.sector);
      setBriefOpen(true);
    }
    window.addEventListener("market-brief:open", onOpen);
    return () => window.removeEventListener("market-brief:open", onOpen);
  }, []);

  // ESC closes the brief modal
  useEffect(() => {
    if (!briefOpen) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setBriefOpen(false);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [briefOpen]);

  if (loading && !data) return <PulseSkeleton />;
  if (!data) return null;

  return (
    <div>
      <MarketPulsePill
        data={data}
        fiiDii={fiiDii}
        onOpenBrief={() => setBriefOpen(true)}
      />
      {data.error_message && (
        <div style={{
          padding: "10px 14px", marginBottom: 16,
          background: "var(--fill-red)", borderRadius: 8,
          fontSize: 12, color: "var(--system-red)",
        }}>
          {data.error_message}
        </div>
      )}

      {briefOpen && (
        <BriefModal
          data={data}
          sectors={sectors}
          initialExpandedSector={pendingSector}
          onClose={() => { setBriefOpen(false); setPendingSector(null); }}
          onRefresh={refresh}
          refreshing={refreshing}
        />
      )}
    </div>
  );
}

// ---------- Modal ----------
function BriefModal({
  data, sectors, initialExpandedSector, onClose, onRefresh, refreshing,
}: {
  data: MarketPulseData;
  sectors?: SectorCard[];
  initialExpandedSector?: string | null;
  onClose: () => void;
  onRefresh: () => void;
  refreshing: boolean;
}) {
  const falling = data.direction === "down";
  const rising = data.direction === "up";
  const accent = falling ? "var(--act)" : rising ? "var(--buy)" : "var(--label-secondary)";

  // Lock body scroll + emit modal:state-change so the floating $ FAB hides.
  useBodyScrollLock(true);
  // Tap-not-drag: dragging the backdrop while trying to scroll modal
  // contents no longer fires close.
  const backdropTapHandlers = useTapNotDrag(onClose);

  return (
    <>
      {/* Backdrop */}
      <div
        {...backdropTapHandlers}
        style={{
          position: "fixed", inset: 0, zIndex: 60,
          background: "rgba(0,0,0,0.4)",
          backdropFilter: "blur(4px)",
          animation: "marketBriefFade 0.2s ease-out",
          touchAction: "none",
        }}
        aria-hidden="true"
      />
      {/* Modal */}
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Market Brief"
        className="brief-modal"
        style={{
          position: "fixed", zIndex: 61,
          top: "50%", left: "50%", transform: "translate(-50%, -50%)",
          width: "min(900px, 92vw)",
          maxHeight: "88vh", display: "flex", flexDirection: "column",
          background: "var(--bg-primary)",
          border: "1px solid var(--separator-light)",
          borderRadius: 16,
          boxShadow: "var(--shadow-lg)",
          overflow: "hidden",
          animation: "marketBriefPop 0.22s cubic-bezier(.2,.9,.3,1.2)",
        }}
      >
        {/* Modal header — title/intensity left, × right on row 1;
            Refresh stacks to row 2 on mobile so the title doesn't wrap. */}
        <div className="brief-modal-header" style={{
          padding: "16px 22px",
          display: "flex", alignItems: "center", justifyContent: "space-between",
          gap: 12,
          borderBottom: "1px solid var(--separator-light)",
          flexShrink: 0,
        }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 10, flexWrap: "wrap", minWidth: 0 }}>
            <span style={{
              fontFamily: "var(--font-serif)", fontSize: 22, fontWeight: 600,
              letterSpacing: "-0.015em", color: "var(--label-primary)",
              whiteSpace: "nowrap",
            }}>Market Brief</span>
            <span style={{
              fontSize: 11, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.06em",
              color: accent,
            }}>
              {data.label || (rising ? "Markets Rising" : falling ? "Markets Falling" : "Markets Flat")}
            </span>
          </div>
          <div className="brief-modal-actions" style={{ display: "flex", gap: 8, alignItems: "center", flexShrink: 0 }}>
            <button
              className="brief-modal-refresh"
              onClick={onRefresh}
              disabled={refreshing}
              title="Refresh"
              style={{
                background: "transparent", color: "var(--label-secondary)",
                border: "1px solid var(--separator)",
                padding: "7px 12px", borderRadius: 8,
                fontSize: 12.5, fontWeight: 500, cursor: refreshing ? "wait" : "pointer",
                display: "inline-flex", alignItems: "center", gap: 5,
              }}
            >
              <span style={{ fontSize: 13 }}>⟳</span>
              {refreshing ? "Refreshing…" : "Refresh"}
            </button>
            <button
              onClick={onClose}
              style={{
                display: "grid", placeItems: "center",
                width: 44, height: 44, borderRadius: 8,
                background: "transparent", color: "var(--label-tertiary)",
                border: "1px solid var(--separator)",
                cursor: "pointer", fontSize: 18,
              }}
              onMouseEnter={(e) => (e.currentTarget.style.background = "var(--bg-secondary)")}
              onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
              aria-label="Close"
            >×</button>
          </div>
        </div>

        {/* Scrollable content */}
        <div style={{ overflowY: "auto", overscrollBehavior: "contain" }}>
          <MarketPulseDetail data={data} sectors={sectors} initialExpandedSector={initialExpandedSector} />
        </div>
      </div>

      <style jsx global>{`
        @keyframes marketBriefFade {
          from { opacity: 0; }
          to { opacity: 1; }
        }
        @keyframes marketBriefPop {
          from { opacity: 0; transform: translate(-50%, -50%) scale(0.96); }
          to { opacity: 1; transform: translate(-50%, -50%) scale(1); }
        }
        @media (max-width: 720px) {
          .brief-modal {
            width: 100vw !important;
            max-height: 100vh !important;
            height: 100vh;
            top: 0 !important;
            left: 0 !important;
            transform: none !important;
            border-radius: 0 !important;
            border: 0 !important;
            animation: brief-modal-up 0.22s cubic-bezier(.2,.9,.3,1.2) !important;
          }
          @keyframes brief-modal-up {
            from { transform: translateY(100%); }
            to { transform: translateY(0); }
          }
          .brief-modal-header {
            flex-wrap: wrap;
            padding: 12px 16px !important;
          }
          .brief-modal-refresh {
            order: 99;
            flex-basis: 100%;
          }
        }
      `}</style>
    </>
  );
}
