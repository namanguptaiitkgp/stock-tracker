"use client";

/**
 * Full active-traders page (addendum §A2d). Same data as the
 * /net-traders endpoint but with category filter, broker toggle,
 * and per-row "edit category" override.
 */

import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import NetTradersTable, { NetTraderRow } from "@/components/common/NetTradersTable";

const CATEGORIES = [
  "QUALITY_MF_FPI",
  "VC_PE",
  "PROMOTER",
  "INSIDER_OTHER",
  "OTHER_FUND",
  "PROP_HFT",
  "BROKER",
  "CORP_OTHER",
  "INDIVIDUAL",
];

interface Override {
  client_name_norm: string;
  override_category: string;
  notes: string | null;
  created_at: string | null;
}

export default function TradersPage() {
  const [rows, setRows] = useState<NetTraderRow[]>([]);
  const [overrides, setOverrides] = useState<Override[]>([]);
  const [showBrokers, setShowBrokers] = useState(false);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<{ name: string; current: string | null } | null>(null);
  const [editCategory, setEditCategory] = useState("");
  const [saving, setSaving] = useState(false);

  const refresh = () => {
    setLoading(true);
    Promise.all([
      api.get<{ rows: NetTraderRow[] }>(
        `/api/smart-money/net-traders?days=30&limit=100${showBrokers ? "&show_brokers=true" : ""}`,
      ).catch(() => ({ rows: [] })),
      api.get<{ rows: Override[] }>(`/api/smart-money/client-overrides`).catch(() => ({ rows: [] })),
    ]).then(([t, o]) => {
      setRows(t.rows);
      setOverrides(o.rows);
      setLoading(false);
    });
  };

  useEffect(refresh, [showBrokers]);

  async function saveOverride() {
    if (!editing) return;
    setSaving(true);
    try {
      await api.put<{ status: string }>("/api/smart-money/client-override", {
        client_name_norm: editing.name,
        override_category: editCategory,
      });
      setEditing(null);
      refresh();
    } finally {
      setSaving(false);
    }
  }

  async function clearOverride(name: string) {
    await api.delete<{ status: string }>(`/api/smart-money/client-override/${encodeURIComponent(name)}`);
    refresh();
  }

  return (
    <div style={{ padding: "32px 40px", maxWidth: 1200, margin: "0 auto" }}>
      <div style={{ marginBottom: 16 }}>
        <Link href="/smart-money" style={{ fontSize: 12, color: "var(--system-blue)", textDecoration: "none" }}>
          ← Smart Money
        </Link>
      </div>

      <header style={{ marginBottom: 20 }}>
        <h1 style={{ fontFamily: "var(--font-serif)", fontSize: 28, fontWeight: 600, letterSpacing: "-0.02em", margin: 0 }}>
          All Active Traders
        </h1>
        <p style={{ fontSize: 13, color: "var(--label-tertiary)", marginTop: 4 }}>
          Every client we&apos;ve seen in NSE/BSE bulk &amp; block deals. Sorted by directional
          conviction. Click a row to see their trade timeline. Click &ldquo;⋯&rdquo; to reclassify a
          client whose category the heuristic got wrong — your overrides are stored per-user
          and the classifier reads them first.
        </p>
      </header>

      {/* Active overrides */}
      {overrides.length > 0 && (
        <section
          style={{
            marginBottom: 20,
            padding: 12,
            border: "1px solid var(--separator-light)",
            borderRadius: 10,
            background: "var(--bg-secondary)",
          }}
        >
          <div
            style={{
              fontSize: 11,
              fontWeight: 600,
              textTransform: "uppercase",
              letterSpacing: "0.05em",
              color: "var(--label-tertiary)",
              marginBottom: 8,
            }}
          >
            Your overrides ({overrides.length})
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {overrides.map((o) => (
              <span
                key={o.client_name_norm}
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 6,
                  padding: "4px 10px",
                  fontSize: 11,
                  borderRadius: 99,
                  background: "var(--bg-primary)",
                  border: "1px solid var(--separator-light)",
                }}
              >
                <strong style={{ fontFamily: "var(--font-mono)" }}>{o.client_name_norm}</strong>
                <span style={{ color: "var(--label-tertiary)" }}>→ {o.override_category}</span>
                <button
                  onClick={() => clearOverride(o.client_name_norm)}
                  style={{
                    background: "transparent",
                    border: 0,
                    color: "var(--act)",
                    cursor: "pointer",
                    fontSize: 12,
                    padding: 0,
                  }}
                  title="Remove override"
                >
                  ×
                </button>
              </span>
            ))}
          </div>
        </section>
      )}

      {/* The traders table — augmented with override-edit affordance */}
      {loading && <div style={{ color: "var(--label-tertiary)", fontSize: 13 }}>Loading…</div>}
      {!loading && (
        <>
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <NetTradersTable rows={rows} showBrokers={showBrokers} onToggleBrokers={setShowBrokers} />
          </div>

          <details style={{ marginTop: 16, fontSize: 12, color: "var(--label-tertiary)" }}>
            <summary style={{ cursor: "pointer" }}>Reclassify a client</summary>
            <div style={{ marginTop: 8, padding: 12, border: "1px solid var(--separator-light)", borderRadius: 8, background: "var(--bg-secondary)" }}>
              <p style={{ marginTop: 0, marginBottom: 8 }}>
                Pick a client by their normalized name (visible in the table) and assign a new category.
                Your override applies to your view only.
              </p>
              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <select
                  value={editing?.name || ""}
                  onChange={(e) => {
                    const r = rows.find((x) => x.client_name_norm === e.target.value);
                    setEditing(e.target.value ? { name: e.target.value, current: r?.client_category ?? null } : null);
                    setEditCategory(r?.client_category || "INDIVIDUAL");
                  }}
                  style={selectStyle}
                >
                  <option value="">— pick a client —</option>
                  {rows.map((r) => (
                    <option key={r.client_name_norm} value={r.client_name_norm}>
                      {r.display_name} ({r.client_category || "—"})
                    </option>
                  ))}
                </select>
                <select
                  value={editCategory}
                  onChange={(e) => setEditCategory(e.target.value)}
                  style={selectStyle}
                  disabled={!editing}
                >
                  {CATEGORIES.map((c) => (
                    <option key={c} value={c}>{c}</option>
                  ))}
                </select>
                <button
                  onClick={saveOverride}
                  disabled={!editing || saving}
                  style={{
                    padding: "6px 14px",
                    borderRadius: 6,
                    border: 0,
                    background: "var(--label-primary)",
                    color: "var(--bg-primary)",
                    fontSize: 12,
                    fontWeight: 600,
                    cursor: editing && !saving ? "pointer" : "default",
                    opacity: editing && !saving ? 1 : 0.4,
                  }}
                >
                  {saving ? "Saving…" : "Override"}
                </button>
              </div>
            </div>
          </details>
        </>
      )}
    </div>
  );
}

const selectStyle: React.CSSProperties = {
  padding: "5px 10px",
  borderRadius: 6,
  border: "1px solid var(--separator)",
  background: "var(--bg-primary)",
  color: "var(--label-primary)",
  fontSize: 12,
  flex: "0 1 auto",
  minWidth: 0,
};
