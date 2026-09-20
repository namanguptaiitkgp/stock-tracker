"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import SettingsCard from "@/components/settings/SettingsCard";

interface ScrapingService {
  id: string;
  name: string;
  category: string;
  source: string;
  url: string;
  writes_to: string;
  ttl: string;
  schedule: string;
  status: "active" | "stub";
}

interface FallbackStep {
  order: number;
  source: string;
  label: string;
  description: string;
  fields: string[];
  reliability: string;
  notes: string;
}

interface DataSourcesResponse {
  scraping_services: ScrapingService[];
  fundamentals_fallback: FallbackStep[];
}

const CATEGORY_ORDER = ["Market Data", "Fundamentals", "News", "Smart Money", "Scoring"];

const catColor: Record<string, { bg: string; fg: string }> = {
  "Market Data": { bg: "rgba(0,122,255,0.08)", fg: "var(--system-blue)" },
  "Fundamentals": { bg: "rgba(48,209,88,0.08)", fg: "var(--buy)" },
  "News": { bg: "rgba(255,159,10,0.08)", fg: "#BF6A02" },
  "Smart Money": { bg: "rgba(175,82,222,0.08)", fg: "#AF52DE" },
  "Scoring": { bg: "rgba(90,200,250,0.08)", fg: "#32ADE6" },
};

export default function DataSourcesSection() {
  const [data, setData] = useState<DataSourcesResponse | null>(null);
  const [expandedCat, setExpandedCat] = useState<string | null>(null);

  useEffect(() => {
    api.get<DataSourcesResponse>("/api/system/data-sources").then(setData).catch(() => {});
  }, []);

  if (!data) return null;

  const grouped: Record<string, ScrapingService[]> = {};
  for (const s of data.scraping_services) {
    (grouped[s.category] ??= []).push(s);
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <SettingsCard
        title="Data sources"
        subtitle="All external services scraped for market data, news, fundamentals, and smart-money signals."
      >
        <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          {CATEGORY_ORDER.filter((c) => grouped[c]).map((cat) => {
            const services = grouped[cat];
            const isOpen = expandedCat === cat;
            const activeCount = services.filter((s) => s.status === "active").length;
            const stubCount = services.length - activeCount;
            const cc = catColor[cat] || catColor["Scoring"];

            return (
              <div key={cat}>
                <button
                  onClick={() => setExpandedCat(isOpen ? null : cat)}
                  style={{
                    width: "100%", display: "flex", alignItems: "center",
                    justifyContent: "space-between", gap: 10,
                    padding: "10px 12px", border: "none", borderRadius: 8,
                    background: isOpen ? "var(--fill-secondary)" : "transparent",
                    cursor: "pointer", textAlign: "left",
                  }}
                >
                  <span style={{ display: "flex", alignItems: "center", gap: 10 }}>
                    <span style={{
                      fontSize: 14, fontWeight: 600,
                      color: "var(--label-primary)",
                    }}>{cat}</span>
                    <span style={{
                      fontSize: 11, fontWeight: 600, padding: "1px 7px",
                      borderRadius: 99, background: cc.bg, color: cc.fg,
                    }}>
                      {activeCount} active{stubCount > 0 ? ` · ${stubCount} stub` : ""}
                    </span>
                  </span>
                  <span style={{
                    fontSize: 12, color: "var(--label-quaternary)",
                    transform: isOpen ? "rotate(90deg)" : "none",
                    transition: "transform 0.15s",
                  }}>▸</span>
                </button>

                {isOpen && (
                  <div style={{ padding: "4px 0 8px" }}>
                    <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12.5 }}>
                      <thead>
                        <tr style={{ borderBottom: "1px solid var(--separator-light)" }}>
                          {["Service", "Source", "Writes To", "TTL", "Schedule", "Status"].map((h) => (
                            <th key={h} style={{
                              ...thStyle,
                              textAlign: h === "Status" ? "center" : "left",
                            }}>{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {services.map((s) => (
                          <tr key={s.id} style={{ borderBottom: "1px solid var(--separator-light)" }}>
                            <td style={tdStyle}>
                              <span style={{ fontWeight: 600, color: "var(--label-primary)" }}>{s.name}</span>
                            </td>
                            <td style={{ ...tdStyle, maxWidth: 220 }}>
                              <span style={{ color: "var(--label-secondary)" }}>{s.source}</span>
                              {s.url !== "—" && (
                                <div style={{ fontSize: 11, color: "var(--label-quaternary)", fontFamily: "var(--font-mono)" }}>
                                  {s.url}
                                </div>
                              )}
                            </td>
                            <td style={tdStyle}>
                              <span style={{ fontFamily: "var(--font-mono)", fontSize: 11.5, color: "var(--label-secondary)" }}>
                                {s.writes_to}
                              </span>
                            </td>
                            <td style={tdStyle}>
                              <span style={{ fontFamily: "var(--font-mono)", fontSize: 12 }}>{s.ttl}</span>
                            </td>
                            <td style={{ ...tdStyle, fontSize: 11.5, color: "var(--label-tertiary)" }}>{s.schedule}</td>
                            <td style={{ ...tdStyle, textAlign: "center" }}>
                              <span style={{
                                fontSize: 10, fontWeight: 600, textTransform: "uppercase",
                                letterSpacing: "0.05em", padding: "2px 6px", borderRadius: 99,
                                ...(s.status === "active"
                                  ? { background: "rgba(48,209,88,0.1)", color: "var(--buy)" }
                                  : { background: "rgba(142,142,147,0.1)", color: "var(--label-quaternary)" }),
                              }}>{s.status}</span>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </SettingsCard>

      <SettingsCard
        title="Fundamentals fallback chain"
        subtitle="Sources are tried in order. First non-null value wins for each field. Manual overrides always take priority."
      >
        <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
          {data.fundamentals_fallback.map((step, i) => {
            const isLast = i === data.fundamentals_fallback.length - 1;
            return (
              <div key={step.source} style={{
                display: "grid",
                gridTemplateColumns: "36px 1fr",
                gap: 0,
              }}>
                {/* step indicator */}
                <div style={{
                  display: "flex", flexDirection: "column", alignItems: "center",
                  paddingTop: 2,
                }}>
                  <span style={{
                    width: 24, height: 24, borderRadius: 99,
                    display: "flex", alignItems: "center", justifyContent: "center",
                    fontSize: 12, fontWeight: 700, fontFamily: "var(--font-mono)",
                    background: "var(--label-primary)", color: "var(--bg-primary)",
                    flexShrink: 0,
                  }}>{step.order}</span>
                  {!isLast && (
                    <div style={{
                      width: 1, flex: 1, minHeight: 16,
                      background: "var(--separator-light)",
                    }} />
                  )}
                </div>

                {/* content */}
                <div style={{ padding: "0 0 16px 8px" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                    <span style={{ fontSize: 14, fontWeight: 600, color: "var(--label-primary)" }}>
                      {step.label}
                    </span>
                    <span style={{
                      fontSize: 10, fontWeight: 600, textTransform: "uppercase",
                      letterSpacing: "0.05em", padding: "1px 6px", borderRadius: 99,
                      ...(step.reliability === "high"
                        ? { background: "rgba(48,209,88,0.1)", color: "var(--buy)" }
                        : step.reliability === "medium"
                          ? { background: "rgba(255,159,10,0.08)", color: "#BF6A02" }
                          : { background: "rgba(142,142,147,0.1)", color: "var(--label-tertiary)" }),
                    }}>{step.reliability}</span>
                  </div>
                  <div style={{ fontSize: 12.5, color: "var(--label-secondary)", lineHeight: 1.45, marginTop: 3 }}>
                    {step.description}
                  </div>
                  <div style={{
                    display: "flex", flexWrap: "wrap", gap: 4, marginTop: 6,
                  }}>
                    {step.fields.map((f) => (
                      <span key={f} style={{
                        fontSize: 11, fontFamily: "var(--font-mono)",
                        padding: "1px 6px", borderRadius: 4,
                        background: "var(--fill-secondary)",
                        color: "var(--label-secondary)",
                      }}>{f}</span>
                    ))}
                  </div>
                  {step.notes && (
                    <div style={{ fontSize: 11.5, color: "var(--label-quaternary)", marginTop: 5, lineHeight: 1.4 }}>
                      {step.notes}
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </SettingsCard>
    </div>
  );
}

const thStyle: React.CSSProperties = {
  padding: "6px 8px",
  fontSize: 10.5,
  fontWeight: 600,
  textTransform: "uppercase",
  letterSpacing: "0.06em",
  color: "var(--label-quaternary)",
};

const tdStyle: React.CSSProperties = {
  padding: "8px 8px",
  verticalAlign: "top",
  color: "var(--label-secondary)",
};
