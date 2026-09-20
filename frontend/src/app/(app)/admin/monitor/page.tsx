"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { fmtRelative } from "@/lib/format";

interface ActiveTask {
  name: string;
  id: string;
  args?: unknown;
  time_start?: number | null;
}
interface IngestRun {
  source: string;
  status: string;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  records_fetched: number | null;
  records_inserted: number | null;
}
interface PurposeStat {
  count: number;
  cost_usd: number;
  avg_ms: number;
  fail_count: number;
}
interface CredStat { count: number; fail_rate: number }
interface SourceStat { count: number; avg_ms: number; fail_rate: number }

interface Activity {
  active_celery: ActiveTask[];
  queued_celery: ActiveTask[];
  recent_ingestion_runs: IngestRun[];
  llm_summary_24h: {
    by_purpose: Record<string, PurposeStat>;
    by_credential: Record<string, CredStat>;
    total_calls: number;
    total_cost_usd: number;
    fail_rate: number;
  };
  scrape_summary_24h: {
    by_source: Record<string, SourceStat>;
    total_fetches: number;
    fail_rate: number;
  };
  as_of: string;
}

const POLL_MS = 10_000;

export default function ActivityMonitor() {
  const [data, setData] = useState<Activity | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await api.get<Activity>("/api/system/activity");
      setData(res);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load activity");
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, POLL_MS);
    return () => clearInterval(id);
  }, [load]);

  if (error && !data) {
    return <div style={{ padding: 24, color: "var(--act)" }}>Error: {error}</div>;
  }
  if (!data) {
    return <div style={{ padding: 24, color: "var(--label-tertiary)" }}>Loading…</div>;
  }

  const llm = data.llm_summary_24h;
  const scrape = data.scrape_summary_24h;
  const purposes = Object.entries(llm.by_purpose).sort((a, b) => b[1].count - a[1].count);
  const sources = Object.entries(scrape.by_source).sort((a, b) => b[1].count - a[1].count);
  const credentials = Object.entries(llm.by_credential).sort((a, b) => b[1].count - a[1].count);

  const cellStyle: React.CSSProperties = {
    padding: "6px 10px",
    borderBottom: "1px solid var(--separator-light)",
    fontSize: 13,
  };
  const headerStyle: React.CSSProperties = {
    ...cellStyle,
    fontSize: 11,
    fontWeight: 600,
    color: "var(--label-tertiary)",
    textTransform: "uppercase",
    letterSpacing: "0.06em",
  };

  return (
    <div style={{ maxWidth: 1200, margin: "0 auto", padding: 24 }}>
      <h1 style={{ fontSize: 28, fontFamily: "var(--font-serif)", fontWeight: 600, margin: 0 }}>
        Activity monitor
      </h1>
      <p style={{ margin: "6px 0 24px", fontSize: 13, color: "var(--label-tertiary)" }}>
        Auto-refreshes every 10s · as of {fmtRelative(data.as_of)}
      </p>

      {/* Top KPI strip */}
      <div style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
        gap: 12,
        marginBottom: 24,
      }}>
        <Tile label="LLM calls (24h)" value={llm.total_calls.toLocaleString()} sub={`$${llm.total_cost_usd.toFixed(2)} · ${(llm.fail_rate * 100).toFixed(1)}% fail`} />
        <Tile label="Scrapes (24h)" value={scrape.total_fetches.toLocaleString()} sub={`${(scrape.fail_rate * 100).toFixed(1)}% fail`} />
        <Tile label="Active tasks" value={String(data.active_celery.length)} sub={`${data.queued_celery.length} queued`} />
        <Tile label="Ingestion runs (24h)" value={String(data.recent_ingestion_runs.length)} sub="see table below" />
      </div>

      {/* Active Celery tasks */}
      <Section title="Running now">
        {data.active_celery.length === 0 ? (
          <Empty text="No tasks running" />
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead><tr><th style={{ ...headerStyle, textAlign: "left" }}>Task</th><th style={{ ...headerStyle, textAlign: "left" }}>ID</th><th style={{ ...headerStyle, textAlign: "right" }}>Started</th></tr></thead>
            <tbody>
              {data.active_celery.map((t, i) => (
                <tr key={i}>
                  <td style={cellStyle}>{t.name}</td>
                  <td style={{ ...cellStyle, fontFamily: "var(--font-mono)", color: "var(--label-tertiary)", fontSize: 11 }}>{t.id?.slice(0, 8) || "—"}</td>
                  <td style={{ ...cellStyle, textAlign: "right", fontFamily: "var(--font-mono)", fontSize: 12 }}>
                    {t.time_start ? `${Math.round(Date.now() / 1000 - t.time_start)}s` : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>

      {/* LLM by purpose */}
      <Section title="LLM spend by purpose (24h)">
        {purposes.length === 0 ? <Empty text="No LLM calls in the last 24h" /> : (
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead><tr>
              <th style={{ ...headerStyle, textAlign: "left" }}>Purpose</th>
              <th style={{ ...headerStyle, textAlign: "right" }}>Calls</th>
              <th style={{ ...headerStyle, textAlign: "right" }}>Cost USD</th>
              <th style={{ ...headerStyle, textAlign: "right" }}>Avg latency</th>
              <th style={{ ...headerStyle, textAlign: "right" }}>Fails</th>
            </tr></thead>
            <tbody>
              {purposes.map(([p, s]) => (
                <tr key={p}>
                  <td style={cellStyle}><code>{p}</code></td>
                  <td style={{ ...cellStyle, textAlign: "right", fontFamily: "var(--font-mono)" }}>{s.count}</td>
                  <td style={{ ...cellStyle, textAlign: "right", fontFamily: "var(--font-mono)" }}>${s.cost_usd.toFixed(4)}</td>
                  <td style={{ ...cellStyle, textAlign: "right", fontFamily: "var(--font-mono)", color: s.avg_ms > 10000 ? "var(--act)" : s.avg_ms > 3000 ? "var(--review)" : "var(--label-primary)" }}>
                    {(s.avg_ms / 1000).toFixed(1)}s
                  </td>
                  <td style={{ ...cellStyle, textAlign: "right", fontFamily: "var(--font-mono)", color: s.fail_count > 0 ? "var(--act)" : "var(--label-tertiary)" }}>{s.fail_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>

      {/* LLM by credential */}
      <Section title="LLM credentials (24h)">
        {credentials.length === 0 ? <Empty text="No LLM calls" /> : (
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead><tr>
              <th style={{ ...headerStyle, textAlign: "left" }}>Credential ID</th>
              <th style={{ ...headerStyle, textAlign: "right" }}>Calls</th>
              <th style={{ ...headerStyle, textAlign: "right" }}>Fail rate</th>
            </tr></thead>
            <tbody>
              {credentials.map(([c, s]) => (
                <tr key={c}>
                  <td style={cellStyle}>{c}</td>
                  <td style={{ ...cellStyle, textAlign: "right", fontFamily: "var(--font-mono)" }}>{s.count}</td>
                  <td style={{ ...cellStyle, textAlign: "right", fontFamily: "var(--font-mono)", color: s.fail_rate > 0.1 ? "var(--act)" : "var(--label-primary)" }}>
                    {(s.fail_rate * 100).toFixed(1)}%
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>

      {/* Scrapes by source */}
      <Section title="Scrapes by source (24h)">
        {sources.length === 0 ? <Empty text="No scrapes in the last 24h" /> : (
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead><tr>
              <th style={{ ...headerStyle, textAlign: "left" }}>Source</th>
              <th style={{ ...headerStyle, textAlign: "right" }}>Fetches</th>
              <th style={{ ...headerStyle, textAlign: "right" }}>Avg latency</th>
              <th style={{ ...headerStyle, textAlign: "right" }}>Fail rate</th>
            </tr></thead>
            <tbody>
              {sources.map(([s, v]) => (
                <tr key={s}>
                  <td style={cellStyle}><code>{s}</code></td>
                  <td style={{ ...cellStyle, textAlign: "right", fontFamily: "var(--font-mono)" }}>{v.count}</td>
                  <td style={{ ...cellStyle, textAlign: "right", fontFamily: "var(--font-mono)", color: v.avg_ms > 5000 ? "var(--review)" : "var(--label-primary)" }}>
                    {v.avg_ms.toLocaleString()}ms
                  </td>
                  <td style={{ ...cellStyle, textAlign: "right", fontFamily: "var(--font-mono)", color: v.fail_rate > 0.1 ? "var(--act)" : "var(--label-primary)" }}>
                    {(v.fail_rate * 100).toFixed(1)}%
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>

      {/* Recent ingestion runs */}
      <Section title="Ingestion runs (24h)">
        {data.recent_ingestion_runs.length === 0 ? <Empty text="No ingestion runs" /> : (
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead><tr>
              <th style={{ ...headerStyle, textAlign: "left" }}>Source</th>
              <th style={{ ...headerStyle, textAlign: "left" }}>Status</th>
              <th style={{ ...headerStyle, textAlign: "right" }}>Duration</th>
              <th style={{ ...headerStyle, textAlign: "right" }}>Fetched / Inserted</th>
              <th style={{ ...headerStyle, textAlign: "right" }}>Started</th>
            </tr></thead>
            <tbody>
              {data.recent_ingestion_runs.map((r, i) => (
                <tr key={i}>
                  <td style={cellStyle}>{r.source}</td>
                  <td style={{ ...cellStyle, color: r.status === "success" ? "var(--buy)" : r.status === "failed" ? "var(--act)" : r.status === "partial" ? "var(--review)" : "var(--label-tertiary)" }}>{r.status}</td>
                  <td style={{ ...cellStyle, textAlign: "right", fontFamily: "var(--font-mono)" }}>{r.duration_ms != null ? `${(r.duration_ms / 1000).toFixed(1)}s` : "—"}</td>
                  <td style={{ ...cellStyle, textAlign: "right", fontFamily: "var(--font-mono)" }}>
                    {r.records_fetched ?? "—"} / {r.records_inserted ?? "—"}
                  </td>
                  <td style={{ ...cellStyle, textAlign: "right", fontFamily: "var(--font-mono)", fontSize: 11 }}>
                    {r.started_at ? fmtRelative(r.started_at) : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>
    </div>
  );
}

function Tile({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div style={{
      background: "var(--bg-primary)",
      border: "1px solid var(--separator-light)",
      borderRadius: 10,
      padding: "12px 14px",
    }}>
      <div style={{ fontSize: 10.5, fontWeight: 600, color: "var(--label-tertiary)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
        {label}
      </div>
      <div style={{ fontFamily: "var(--font-mono)", fontSize: 22, fontWeight: 700, marginTop: 4 }}>
        {value}
      </div>
      {sub && <div style={{ fontSize: 11, color: "var(--label-tertiary)", marginTop: 2 }}>{sub}</div>}
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section style={{
      background: "var(--bg-primary)",
      border: "1px solid var(--separator-light)",
      borderRadius: 12,
      marginBottom: 18,
      overflow: "hidden",
    }}>
      <h2 style={{
        margin: 0, padding: "12px 16px",
        fontSize: 14, fontFamily: "var(--font-serif)", fontWeight: 600,
        borderBottom: "1px solid var(--separator-light)",
      }}>
        {title}
      </h2>
      <div style={{ padding: 4 }}>{children}</div>
    </section>
  );
}

function Empty({ text }: { text: string }) {
  return <div style={{ padding: "12px 16px", fontSize: 12, color: "var(--label-tertiary)" }}>{text}</div>;
}
