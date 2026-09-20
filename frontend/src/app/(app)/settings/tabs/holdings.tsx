"use client";

/**
 * Holdings — purchase date + thesis editor.
 *
 * Lists every Kite holding (live, pulled from /api/portfolio/holdings)
 * and lets the user record:
 *   - first_purchase_date (required)
 *   - initial_thesis (free text)
 *   - thesis_tags (chip-style tags)
 *   - target_holding_period_months
 *
 * Holdings without a metadata row appear at the top with an "untagged"
 * pill so the user can quickly see which ones still need entry. Saved
 * rows show a green checkmark.
 *
 * The data feeds the holdings-signal layer ("since you bought" drift)
 * and the upcoming Researching-card view of original thesis vs current
 * smart-money state.
 */

import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { useToast } from "@/lib/use-toast";
import SettingsCard from "@/components/settings/SettingsCard";
import SettingsField, { settingsButtonPrimary, settingsButtonSecondary, settingsInputStyle } from "@/components/settings/SettingsField";

interface KiteHolding {
  tradingsymbol: string;
  exchange: string;
  quantity: number;
  average_price: number;
  last_price: number | null;
}

interface HoldingsMetadataRow {
  symbol: string;
  first_purchase_date: string | null;
  initial_thesis: string | null;
  thesis_tags: string[];
  target_holding_period_months: number | null;
  sector_override: string | null;
  updated_at: string | null;
}

interface EditorState {
  symbol: string;
  first_purchase_date: string;
  initial_thesis: string;
  thesis_tags: string[];
  target_holding_period_months: string;
  sector_override: string;
}

// 11 canonical sectors — must stay in sync with CANONICAL_SECTORS in
// backend/app/services/screener_presets.py. Server validates against the
// same list and returns 400 on mismatch.
const CANONICAL_SECTORS = [
  "Technology",
  "Financial Services",
  "Healthcare",
  "Consumer Cyclical",
  "Consumer Defensive",
  "Industrials",
  "Basic Materials",
  "Communication Services",
  "Energy",
  "Utilities",
  "Real Estate",
] as const;

export default function HoldingsTab() {
  const [holdings, setHoldings] = useState<KiteHolding[]>([]);
  const [meta, setMeta] = useState<HoldingsMetadataRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState<EditorState | null>(null);
  const [saving, setSaving] = useState(false);
  const { toast } = useToast();

  function refresh() {
    setLoading(true);
    Promise.all([
      api.get<{ stocks: KiteHolding[] }>("/api/portfolio/holdings").catch(() => ({ stocks: [] })),
      api.get<{ rows: HoldingsMetadataRow[] }>("/api/holdings-metadata").catch(() => ({ rows: [] })),
    ]).then(([h, m]) => {
      setHoldings(h.stocks || []);
      setMeta(m.rows || []);
      setLoading(false);
    });
  }
  useEffect(refresh, []);

  const metaBySymbol = useMemo(() => {
    const out: Record<string, HoldingsMetadataRow> = {};
    for (const r of meta) out[r.symbol] = r;
    return out;
  }, [meta]);

  function startEdit(symbol: string) {
    const m = metaBySymbol[symbol];
    setEditing(symbol);
    setDraft({
      symbol,
      first_purchase_date: m?.first_purchase_date || "",
      initial_thesis: m?.initial_thesis || "",
      thesis_tags: m?.thesis_tags || [],
      target_holding_period_months: m?.target_holding_period_months?.toString() || "",
      sector_override: m?.sector_override || "",
    });
  }

  async function save() {
    if (!draft) return;
    setSaving(true);
    try {
      await api.put<{ status: string }>(`/api/holdings-metadata/${draft.symbol}`, {
        // All fields optional on the server — pass null for empties.
        first_purchase_date: draft.first_purchase_date || null,
        initial_thesis: draft.initial_thesis || null,
        thesis_tags: draft.thesis_tags.length ? draft.thesis_tags : null,
        target_holding_period_months:
          draft.target_holding_period_months ? Number(draft.target_holding_period_months) : null,
        sector_override: draft.sector_override || null,
      });
      toast({ kind: "ok", text: "Saved" });
      setEditing(null);
      setDraft(null);
      refresh();
    } catch (e) {
      toast({ kind: "error", text: e instanceof Error ? e.message : "Save failed" });
    } finally {
      setSaving(false);
    }
  }

  async function clearMetadata(symbol: string) {
    if (!confirm(`Remove metadata for ${symbol}?`)) return;
    await api.delete<{ status: string }>(`/api/holdings-metadata/${symbol}`);
    refresh();
  }

  // Sort: untagged first, then alphabetical
  const sorted = useMemo(() => {
    return [...holdings].sort((a, b) => {
      const aTagged = !!metaBySymbol[a.tradingsymbol];
      const bTagged = !!metaBySymbol[b.tradingsymbol];
      if (aTagged !== bTagged) return aTagged ? 1 : -1;
      return a.tradingsymbol.localeCompare(b.tradingsymbol);
    });
  }, [holdings, metaBySymbol]);

  const untaggedCount = sorted.filter((h) => !metaBySymbol[h.tradingsymbol]).length;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <SettingsCard
        title="Holdings"
        subtitle={`Record purchase date, thesis, and sector override for each holding. The smart-money holdings signal uses purchase date + thesis to compute "since you bought" drift; the sector override takes precedence over auto-detected sectors (Screener.in / Nifty index / yfinance) when the auto-detection is wrong for an Indian stock.`}
        status={
          untaggedCount > 0
            ? { kind: "warn", label: `${untaggedCount} untagged` }
            : holdings.length > 0
              ? { kind: "ok", label: "All tagged" }
              : null
        }
      >
        {loading ? (
          <div style={{ color: "var(--label-tertiary)", fontSize: 13 }}>Loading…</div>
        ) : holdings.length === 0 ? (
          <div style={{ color: "var(--label-tertiary)", fontSize: 13 }}>
            No Kite holdings found. Connect Kite in the Connections tab to populate this list.
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {sorted.map((h) => {
              const m = metaBySymbol[h.tradingsymbol];
              const isEditing = editing === h.tradingsymbol;
              return (
                <div
                  key={`${h.exchange}:${h.tradingsymbol}`}
                  style={{
                    padding: "10px 12px",
                    borderRadius: 10,
                    background: "var(--bg-secondary)",
                    border: "1px solid var(--separator-light)",
                  }}
                >
                  {/* Header row */}
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <span style={{ fontFamily: "var(--font-mono)", fontWeight: 700, color: "var(--label-primary)" }}>
                        {h.tradingsymbol}
                      </span>
                      <span style={{ fontSize: 11, color: "var(--label-tertiary)" }}>
                        {h.quantity.toLocaleString("en-IN")} @ Rs {h.average_price?.toFixed(2)}
                      </span>
                      {!m && (
                        <span style={tagStyleUntagged}>untagged</span>
                      )}
                    </div>
                    {!isEditing && (
                      <div style={{ display: "flex", gap: 6 }}>
                        <button
                          onClick={() => startEdit(h.tradingsymbol)}
                          style={{ ...settingsButtonSecondary, padding: "4px 10px", fontSize: 12 }}
                        >
                          {m ? "Edit" : "Add metadata"}
                        </button>
                        {m && (
                          <button
                            onClick={() => clearMetadata(h.tradingsymbol)}
                            title="Remove metadata"
                            style={{
                              padding: "4px 8px",
                              border: 0,
                              background: "transparent",
                              color: "var(--act)",
                              cursor: "pointer",
                              fontSize: 14,
                            }}
                          >
                            ×
                          </button>
                        )}
                      </div>
                    )}
                  </div>

                  {/* Saved view */}
                  {!isEditing && m && (
                    <div style={{ marginTop: 6, display: "flex", flexDirection: "column", gap: 4 }}>
                      <div style={{ fontSize: 12, color: "var(--label-secondary)" }}>
                        {m.first_purchase_date ? (
                          <>
                            <span style={{ color: "var(--label-tertiary)" }}>Bought:</span>{" "}
                            {m.first_purchase_date}
                          </>
                        ) : (
                          <span style={{ color: "var(--label-tertiary)" }}>No purchase date</span>
                        )}
                        {m.target_holding_period_months ? (
                          <span style={{ marginLeft: 12, color: "var(--label-tertiary)" }}>
                            target {m.target_holding_period_months}mo
                          </span>
                        ) : null}
                        {m.sector_override ? (
                          <span style={{ marginLeft: 12, color: "var(--label-tertiary)" }}>
                            sector override:{" "}
                            <span style={{ color: "var(--label-secondary)", fontWeight: 500 }}>
                              {m.sector_override}
                            </span>
                          </span>
                        ) : null}
                      </div>
                      {m.thesis_tags.length > 0 && (
                        <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                          {m.thesis_tags.map((t) => (
                            <span key={t} style={tagStyleSet}>{t}</span>
                          ))}
                        </div>
                      )}
                      {m.initial_thesis && (
                        <div style={{ fontSize: 12, color: "var(--label-secondary)", lineHeight: 1.45 }}>
                          {m.initial_thesis}
                        </div>
                      )}
                    </div>
                  )}

                  {/* Editor */}
                  {isEditing && draft && (
                    <div style={{ marginTop: 8, display: "flex", flexDirection: "column", gap: 8 }}>
                      <div style={{ display: "grid", gridTemplateColumns: "180px 1fr 220px", gap: 8 }}>
                        <SettingsField label="Purchase date">
                          <input
                            type="date"
                            value={draft.first_purchase_date}
                            onChange={(e) => setDraft({ ...draft, first_purchase_date: e.target.value })}
                            style={settingsInputStyle}
                          />
                        </SettingsField>
                        <SettingsField label="Target holding (months, optional)">
                          <input
                            type="number"
                            min={0}
                            placeholder="e.g. 24"
                            value={draft.target_holding_period_months}
                            onChange={(e) => setDraft({ ...draft, target_holding_period_months: e.target.value })}
                            style={settingsInputStyle}
                          />
                        </SettingsField>
                        <SettingsField
                          label="Sector override (optional)"
                          hint="Use only if the auto-detected sector on the card is wrong."
                        >
                          <select
                            value={draft.sector_override}
                            onChange={(e) => setDraft({ ...draft, sector_override: e.target.value })}
                            style={settingsInputStyle}
                          >
                            <option value="">— auto-detect —</option>
                            {CANONICAL_SECTORS.map((s) => (
                              <option key={s} value={s}>{s}</option>
                            ))}
                          </select>
                        </SettingsField>
                      </div>
                      <SettingsField label="Thesis tags (comma-separated)" hint="e.g. compounder, turnaround, sector_cycle">
                        <input
                          type="text"
                          value={draft.thesis_tags.join(", ")}
                          onChange={(e) =>
                            setDraft({
                              ...draft,
                              thesis_tags: e.target.value.split(",").map((s) => s.trim()).filter(Boolean),
                            })
                          }
                          style={settingsInputStyle}
                        />
                      </SettingsField>
                      <SettingsField label="Initial thesis (free text)">
                        <textarea
                          rows={3}
                          placeholder="Why I bought this"
                          value={draft.initial_thesis}
                          onChange={(e) => setDraft({ ...draft, initial_thesis: e.target.value })}
                          style={{ ...settingsInputStyle, resize: "vertical" }}
                        />
                      </SettingsField>
                      <div style={{ display: "flex", justifyContent: "flex-end", gap: 6 }}>
                        <button
                          onClick={() => {
                            setEditing(null);
                            setDraft(null);
                          }}
                          style={{ ...settingsButtonSecondary, padding: "5px 12px", fontSize: 12 }}
                        >
                          Cancel
                        </button>
                        <button
                          onClick={save}
                          disabled={saving}
                          style={{ ...settingsButtonPrimary, padding: "5px 14px", fontSize: 12, opacity: saving ? 0.5 : 1 }}
                        >
                          {saving ? "Saving…" : "Save"}
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </SettingsCard>
    </div>
  );
}

const tagStyleUntagged: React.CSSProperties = {
  fontSize: 10,
  fontWeight: 600,
  textTransform: "uppercase",
  letterSpacing: "0.06em",
  padding: "2px 6px",
  borderRadius: 99,
  background: "var(--review-bg, rgba(255,149,0,0.08))",
  color: "var(--review)",
  border: "1px solid var(--review-edge, rgba(255,149,0,0.25))",
};

const tagStyleSet: React.CSSProperties = {
  fontSize: 10,
  padding: "2px 8px",
  borderRadius: 99,
  background: "var(--bg-primary)",
  border: "1px solid var(--separator-light)",
  color: "var(--label-tertiary)",
  fontFamily: "var(--font-mono)",
};
