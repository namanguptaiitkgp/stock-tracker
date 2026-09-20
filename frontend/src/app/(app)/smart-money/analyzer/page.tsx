"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { openStockDetail } from "@/lib/stock-detail";

interface TopParty {
  party: string;
  category: string;
  trades: number;
  net_cr: number;
  gross_cr: number;
}

interface Signal {
  stock: string;
  signal: string;
  direction: "BUY" | "SELL" | "NEUTRAL" | "NOISE";
  tier: string | null;
  confidence: string;
  net_cr: number;
  days: number;
  primary_evidence: string;
  modifiers: string[];
  gross_cr: number;
  prop_share: number;
  top_parties: TopParty[];
  reason_notes: string[];
}

interface Report {
  window_start: string | null;
  window_end: string | null;
  total_rows: number;
  stocks_seen: number;
  files: string[];
  warnings: string[];
  signals: Signal[];
  neutral: Signal[];
  noise: Signal[];
  session_id?: number;
  session_created_at?: string;
  label?: string;
}

interface SessionSummary {
  id: number;
  label: string | null;
  created_at: string;
  window_start: string | null;
  window_end: string | null;
  total_rows: number;
  stocks_seen: number;
  signal_count: number;
  neutral_count: number;
  noise_count: number;
  files_meta: Array<{ filename: string; size_bytes: number }>;
}

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const TOKEN_KEY = "algo_trader_token";

const SIGNAL_BG: Record<string, string> = {
  STRONG_BUY_PROMOTER_ACCUMULATION: "#248A3D",
  STRONG_BUY_INSTITUTIONAL_CONSENSUS: "#2F7E33",
  MODERATE_BUY_SINGLE_NAME_QUALITY: "#5CB85C",
  WEAK_BUY: "rgba(36,138,61,0.4)",
  VC_PE_EXIT_BLOCK: "#AF52DE",
  STRONG_SELL_PROMOTER_DISTRIBUTION: "#D70015",
  STRONG_SELL_QUALITY_DISTRIBUTION: "#B10011",
  WEAK_SELL: "rgba(215,0,21,0.45)",
  NEUTRAL: "#8E8E93",
  NOISE: "#48484A",
};

const SIGNAL_LABEL: Record<string, string> = {
  STRONG_BUY_PROMOTER_ACCUMULATION: "STRONG BUY — Promoter",
  STRONG_BUY_INSTITUTIONAL_CONSENSUS: "STRONG BUY — Consensus",
  MODERATE_BUY_SINGLE_NAME_QUALITY: "MODERATE BUY",
  WEAK_BUY: "WEAK BUY",
  VC_PE_EXIT_BLOCK: "VC/PE Exit (info only)",
  STRONG_SELL_PROMOTER_DISTRIBUTION: "STRONG SELL — Promoter",
  STRONG_SELL_QUALITY_DISTRIBUTION: "STRONG SELL — Quality",
  WEAK_SELL: "WEAK SELL",
  NEUTRAL: "Neutral",
  NOISE: "Noise",
};

function SignalBadge({ signal }: { signal: string }) {
  return (
    <span
      style={{
        display: "inline-block",
        padding: "3px 10px",
        borderRadius: 10,
        backgroundColor: SIGNAL_BG[signal] || "#8E8E93",
        color: "white",
        fontSize: 11,
        fontWeight: 700,
        textTransform: "uppercase",
        letterSpacing: "0.03em",
        whiteSpace: "nowrap",
      }}
    >
      {SIGNAL_LABEL[signal] || signal}
    </span>
  );
}

function fmtCr(v: number): string {
  return `${v >= 0 ? "+" : ""}${v.toFixed(2)} Cr`;
}

function SignalRow({ s }: { s: Signal }) {
  const [open, setOpen] = useState(false);

  return (
    <>
      <div
        onClick={() => setOpen(!open)}
        style={{
          display: "grid",
          gridTemplateColumns: "100px 210px 70px 100px 60px 1fr",
          gap: 12,
          alignItems: "center",
          padding: "10px 12px",
          background: "white",
          border: "1px solid #F2F2F7",
          borderRadius: 6,
          marginBottom: 4,
          cursor: "pointer",
          fontSize: 13,
        }}
      >
        <span
          style={{
            fontFamily: "monospace",
            fontWeight: 700,
            color: "#007AFF",
          }}
          onClick={(e) => {
            e.stopPropagation();
            openStockDetail(s.stock, "NSE");
          }}
        >
          {s.stock}
        </span>
        <SignalBadge signal={s.signal} />
        <span style={{ fontSize: 11, color: "#6E6E73" }}>{s.tier || "—"}</span>
        <span
          style={{
            textAlign: "right",
            fontWeight: 600,
            color: s.net_cr >= 0 ? "#248A3D" : "#D70015",
          }}
        >
          {fmtCr(s.net_cr)}
        </span>
        <span style={{ textAlign: "center", color: "#48484A" }}>{s.days}d</span>
        <span style={{ color: "#48484A", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {s.primary_evidence}
        </span>
      </div>
      {open && (
        <div style={{ padding: "8px 14px 16px", fontSize: 12, color: "#48484A", marginLeft: 12 }}>
          <div style={{ marginBottom: 6 }}>
            <b>Confidence:</b> {s.confidence} &nbsp;·&nbsp; <b>Gross traded:</b> {s.gross_cr.toFixed(2)} Cr &nbsp;·&nbsp;{" "}
            <b>Prop share:</b> {(s.prop_share * 100).toFixed(0)}%
          </div>
          {s.modifiers.length > 0 && (
            <div style={{ marginBottom: 6 }}>
              <b>Modifiers:</b>
              <ul style={{ margin: "4px 0 0 18px" }}>
                {s.modifiers.map((m, i) => (
                  <li key={i}>{m}</li>
                ))}
              </ul>
            </div>
          )}
          {s.top_parties && s.top_parties.length > 0 && (
            <div style={{ marginTop: 8 }}>
              <b>Top parties:</b>
              <table style={{ marginTop: 4, fontSize: 12, width: "100%" }}>
                <thead>
                  <tr style={{ color: "#6E6E73", textAlign: "left" }}>
                    <th style={{ padding: "2px 8px" }}>Party</th>
                    <th style={{ padding: "2px 8px" }}>Category</th>
                    <th style={{ padding: "2px 8px", textAlign: "right" }}>Trades</th>
                    <th style={{ padding: "2px 8px", textAlign: "right" }}>Net Cr</th>
                    <th style={{ padding: "2px 8px", textAlign: "right" }}>Gross Cr</th>
                  </tr>
                </thead>
                <tbody>
                  {s.top_parties.map((p, i) => (
                    <tr key={i}>
                      <td style={{ padding: "2px 8px" }}>{p.party}</td>
                      <td style={{ padding: "2px 8px", fontFamily: "monospace", fontSize: 11, color: "#6E6E73" }}>
                        {p.category}
                      </td>
                      <td style={{ padding: "2px 8px", textAlign: "right" }}>{p.trades}</td>
                      <td
                        style={{
                          padding: "2px 8px",
                          textAlign: "right",
                          color: p.net_cr >= 0 ? "#248A3D" : "#D70015",
                        }}
                      >
                        {fmtCr(p.net_cr)}
                      </td>
                      <td style={{ padding: "2px 8px", textAlign: "right" }}>{p.gross_cr.toFixed(2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </>
  );
}

function fmtRel(iso: string): string {
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60) return `${Math.round(diff)}s ago`;
  if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.round(diff / 3600)}h ago`;
  return `${Math.round(diff / 86400)}d ago`;
}

export default function AnalyzerPage() {
  const [files, setFiles] = useState<FileList | null>(null);
  const [report, setReport] = useState<Report | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showNeutral, setShowNeutral] = useState(false);
  const [showNoise, setShowNoise] = useState(false);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);

  const loadSessions = useCallback(async () => {
    try {
      const data = await api.get<{ sessions: SessionSummary[] }>("/api/smart-money/analyzer/sessions");
      setSessions(data.sessions);
    } catch {
      setSessions([]);
    }
  }, []);

  useEffect(() => {
    loadSessions();
  }, [loadSessions]);

  async function viewSession(id: number) {
    setLoading(true);
    setError(null);
    try {
      const data = await api.get<Report>(`/api/smart-money/analyzer/sessions/${id}`);
      setReport(data);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  async function deleteSession(id: number) {
    if (!confirm("Delete this past analysis?")) return;
    try {
      await api.delete(`/api/smart-money/analyzer/sessions/${id}`);
      await loadSessions();
      if (report && report.session_id === id) setReport(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function handleAnalyze() {
    if (!files || files.length === 0) return;
    setLoading(true);
    setError(null);
    setReport(null);
    try {
      const fd = new FormData();
      Array.from(files).forEach((f) => fd.append("files", f));
      const token = typeof window !== "undefined" ? localStorage.getItem(TOKEN_KEY) : null;
      const res = await fetch(`${API_URL}/api/smart-money/analyzer/upload`, {
        method: "POST",
        body: fd,
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `Upload failed: ${res.status}`);
      }
      const data: Report = await res.json();
      setReport(data);
      await loadSessions();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  const buySignals = report?.signals.filter((s) => s.direction === "BUY") || [];
  const sellSignals = report?.signals.filter((s) => s.direction === "SELL") || [];
  const neutralFromSignals = report?.signals.filter((s) => s.direction === "NEUTRAL") || [];

  return (
    <div style={{ padding: "32px 40px", maxWidth: 1200, margin: "0 auto" }}>
      <div style={{ marginBottom: 12 }}>
        <Link href="/smart-money" style={{ fontSize: 12, color: "#007AFF", textDecoration: "none" }}>
          ← Smart Money
        </Link>
      </div>
      <h1 style={{ fontSize: 24, fontWeight: 700, marginBottom: 4 }}>Deal Analyzer</h1>
      <p style={{ fontSize: 13, color: "#6E6E73", marginBottom: 12 }}>
        Upload NSE bulk/block or SEBI insider disclosure CSVs. Output is a Signal Grade per stock across 6 layers:
        data hygiene → noise gate → priority-ordered signal detection → tier → confidence modifiers. Default is to
        reject more than accept.
      </p>
      <div
        style={{
          padding: 12,
          background: "rgba(0,122,255,0.06)",
          border: "1px solid rgba(0,122,255,0.2)",
          borderRadius: 8,
          marginBottom: 20,
          fontSize: 12,
          color: "#003D85",
        }}
      >
        <b>What this expects:</b> a CSV with <i>Date</i>, <i>Symbol</i>, <i>Client/Party Name</i>,{" "}
        <i>Buy/Sell</i>, <i>Quantity</i>, <i>Price</i>. Supported sources:
        <ul style={{ margin: "4px 0 0 20px" }}>
          <li>
            NSE bulk/block deals — <a href="https://www.nseindia.com/market-data/large-deals" target="_blank" rel="noreferrer" style={{ color: "#007AFF" }}>nseindia.com/market-data/large-deals</a>{" "}(Export → CSV)
          </li>
          <li>
            BSE bulk/block deals — <a href="https://www.bseindia.com/markets/equity/EQReports/bulk_deals.aspx" target="_blank" rel="noreferrer" style={{ color: "#007AFF" }}>bseindia.com → Bulk Deals</a>
          </li>
          <li>
            SEBI PIT Reg 7 insider disclosures — company-wise CSV from SEBI or the exchange site
          </li>
        </ul>
        <b>Not supported:</b> price-only files like <i>Market Movers</i>, <i>Gainers/Losers</i>, OHLC bhavcopy —
        these have no party / side information.
      </div>

      <div
        style={{
          padding: 16,
          background: "white",
          border: "1px dashed #8E8E93",
          borderRadius: 10,
          marginBottom: 20,
        }}
      >
        <input
          type="file"
          accept=".csv,.txt"
          multiple
          onChange={(e) => setFiles(e.target.files)}
          style={{ fontSize: 13 }}
        />
        <button
          onClick={handleAnalyze}
          disabled={loading || !files || files.length === 0}
          style={{
            marginLeft: 12,
            padding: "6px 16px",
            borderRadius: 8,
            background: "#1D1D1F",
            color: "white",
            border: "none",
            fontSize: 13,
            fontWeight: 600,
            cursor: loading ? "wait" : "pointer",
            opacity: !files || files.length === 0 ? 0.4 : 1,
          }}
        >
          {loading ? "Analyzing…" : "Analyze"}
        </button>
        {files && files.length > 0 && (
          <div style={{ marginTop: 8, fontSize: 12, color: "#6E6E73" }}>
            Ready to upload: {Array.from(files).map((f) => f.name).join(", ")}
          </div>
        )}
      </div>

      {sessions.length > 0 && (
        <div style={{ marginBottom: 24 }}>
          <h2 style={{ fontSize: 14, fontWeight: 600, color: "#1D1D1F", marginBottom: 8 }}>
            Past analyses ({sessions.length})
          </h2>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "140px 1fr 80px 80px 80px 80px 150px",
              gap: 8,
              padding: "6px 10px",
              fontSize: 10,
              fontWeight: 600,
              color: "#6E6E73",
              textTransform: "uppercase",
              letterSpacing: "0.05em",
              borderBottom: "1px solid #E2E8F0",
            }}
          >
            <span>When</span>
            <span>Window / Files</span>
            <span style={{ textAlign: "right" }}>Rows</span>
            <span style={{ textAlign: "right" }}>Stocks</span>
            <span style={{ textAlign: "right" }}>Signals</span>
            <span style={{ textAlign: "right" }}>Noise</span>
            <span></span>
          </div>
          {sessions.map((sess) => (
            <div
              key={sess.id}
              style={{
                display: "grid",
                gridTemplateColumns: "140px 1fr 80px 80px 80px 80px 150px",
                gap: 8,
                alignItems: "center",
                padding: "8px 10px",
                background: "white",
                border: "1px solid #F2F2F7",
                borderRadius: 6,
                marginBottom: 4,
                fontSize: 12,
              }}
            >
              <span style={{ color: "#48484A" }}>
                {fmtRel(sess.created_at)}
                <div style={{ fontSize: 10, color: "#8E8E93" }}>
                  {new Date(sess.created_at).toLocaleDateString("en-IN")}
                </div>
              </span>
              <span style={{ minWidth: 0, overflow: "hidden" }}>
                <div style={{ fontWeight: 500 }}>
                  {sess.window_start && sess.window_end
                    ? sess.window_start === sess.window_end
                      ? sess.window_start
                      : `${sess.window_start} → ${sess.window_end}`
                    : "—"}
                </div>
                <div
                  style={{
                    fontSize: 10,
                    color: "#8E8E93",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {(sess.files_meta || []).map((f) => f.filename).join(", ")}
                </div>
              </span>
              <span style={{ textAlign: "right", color: "#48484A" }}>{sess.total_rows}</span>
              <span style={{ textAlign: "right", color: "#48484A" }}>{sess.stocks_seen}</span>
              <span style={{ textAlign: "right", color: "#248A3D", fontWeight: 600 }}>
                {sess.signal_count}
              </span>
              <span style={{ textAlign: "right", color: "#6E6E73" }}>{sess.noise_count}</span>
              <span style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
                <button
                  onClick={() => viewSession(sess.id)}
                  style={{
                    padding: "3px 10px",
                    borderRadius: 6,
                    background: "#1D1D1F",
                    color: "white",
                    border: "none",
                    fontSize: 11,
                    cursor: "pointer",
                  }}
                >
                  View
                </button>
                <button
                  onClick={() => deleteSession(sess.id)}
                  style={{
                    padding: "3px 10px",
                    borderRadius: 6,
                    background: "white",
                    color: "#D70015",
                    border: "1px solid rgba(215,0,21,0.3)",
                    fontSize: 11,
                    cursor: "pointer",
                  }}
                >
                  Delete
                </button>
              </span>
            </div>
          ))}
        </div>
      )}

      {error && (
        <div
          style={{
            padding: 12,
            background: "rgba(215,0,21,0.1)",
            border: "1px solid rgba(215,0,21,0.3)",
            borderRadius: 8,
            color: "#B10011",
            marginBottom: 16,
            fontSize: 13,
          }}
        >
          {error}
        </div>
      )}

      {report && (
        <>
          <div
            style={{
              padding: 14,
              background: "rgba(142,142,147,0.05)",
              border: "1px solid #E2E8F0",
              borderRadius: 8,
              marginBottom: 20,
              fontSize: 13,
            }}
          >
            <div>
              <b>Window:</b> {report.window_start || "—"} → {report.window_end || "—"}
            </div>
            <div>
              <b>{report.total_rows}</b> rows across <b>{report.stocks_seen}</b> stocks. &nbsp;
              <b>{report.signals.length}</b> real signals, <b>{report.neutral.length}</b> neutral,{" "}
              <b>{report.noise.length}</b> noise-gated.
            </div>
            {report.files.length > 0 && (
              <div style={{ marginTop: 4, color: "#6E6E73" }}>
                Files: {report.files.join(", ")}
              </div>
            )}
            {report.warnings.length > 0 && (
              <div
                style={{
                  marginTop: 10,
                  padding: 10,
                  background: "rgba(245,166,35,0.12)",
                  border: "1px solid rgba(245,166,35,0.4)",
                  borderRadius: 6,
                  color: "#5C3F00",
                  fontSize: 12,
                }}
              >
                <b>Parsing warnings:</b>
                <ul style={{ margin: "4px 0 0 18px" }}>
                  {report.warnings.map((w, i) => (
                    <li key={i}>{w}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>

          {/* Header row */}
          {(buySignals.length > 0 || sellSignals.length > 0) && (
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "100px 210px 70px 100px 60px 1fr",
                gap: 12,
                padding: "8px 12px",
                fontSize: 10,
                fontWeight: 600,
                color: "#6E6E73",
                textTransform: "uppercase",
                letterSpacing: "0.05em",
                borderBottom: "1px solid #E2E8F0",
                marginBottom: 4,
              }}
            >
              <span>Stock</span>
              <span>Signal</span>
              <span>Tier</span>
              <span style={{ textAlign: "right" }}>Net</span>
              <span style={{ textAlign: "center" }}>Days</span>
              <span>Primary evidence</span>
            </div>
          )}

          {buySignals.length > 0 && (
            <div style={{ marginBottom: 24 }}>
              <h2 style={{ fontSize: 14, fontWeight: 600, color: "#248A3D", marginBottom: 8 }}>
                BUY signals ({buySignals.length})
              </h2>
              {buySignals.map((s) => (
                <SignalRow key={s.stock} s={s} />
              ))}
            </div>
          )}

          {sellSignals.length > 0 && (
            <div style={{ marginBottom: 24 }}>
              <h2 style={{ fontSize: 14, fontWeight: 600, color: "#D70015", marginBottom: 8 }}>
                SELL signals ({sellSignals.length})
              </h2>
              {sellSignals.map((s) => (
                <SignalRow key={s.stock} s={s} />
              ))}
            </div>
          )}

          {neutralFromSignals.length > 0 && (
            <div style={{ marginBottom: 24 }}>
              <h2 style={{ fontSize: 14, fontWeight: 600, color: "#AF52DE", marginBottom: 8 }}>
                VC/PE exit anchors ({neutralFromSignals.length})
              </h2>
              {neutralFromSignals.map((s) => (
                <SignalRow key={s.stock} s={s} />
              ))}
            </div>
          )}

          {report.neutral.length > 0 && (
            <div style={{ marginBottom: 20 }}>
              <button
                onClick={() => setShowNeutral(!showNeutral)}
                style={{
                  fontSize: 13,
                  color: "#007AFF",
                  background: "none",
                  border: "none",
                  cursor: "pointer",
                  padding: 0,
                  fontWeight: 600,
                }}
              >
                {showNeutral ? "Hide" : "Show"} neutral audit ({report.neutral.length})
              </button>
              {showNeutral && (
                <div style={{ marginTop: 8 }}>
                  {report.neutral.map((s) => (
                    <SignalRow key={s.stock} s={s} />
                  ))}
                </div>
              )}
            </div>
          )}

          {report.noise.length > 0 && (
            <div>
              <button
                onClick={() => setShowNoise(!showNoise)}
                style={{
                  fontSize: 13,
                  color: "#007AFF",
                  background: "none",
                  border: "none",
                  cursor: "pointer",
                  padding: 0,
                  fontWeight: 600,
                }}
              >
                {showNoise ? "Hide" : "Show"} noise audit ({report.noise.length})
              </button>
              {showNoise && (
                <div style={{ marginTop: 8 }}>
                  {report.noise.map((s) => (
                    <SignalRow key={s.stock} s={s} />
                  ))}
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
