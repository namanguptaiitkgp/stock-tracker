"use client";

import { useState } from "react";
import { api } from "@/lib/api";

/**
 * Rule editor modal for a single WatchlistItem.
 *
 * v2 layout:
 *   - Type picker (% from peak / P/E / P/B / Single-day drop / Price below)
 *   - Operator picker (only shown for P/E + P/B)
 *   - Value input
 *   - Frequency picker (Daily / Hourly during market / Every 15 min)
 *   - Optional label
 *
 * The save handler PATCHes the full rule list — backend swaps the JSON
 * column wholesale, so additions and deletions land in one round-trip.
 */

export type WatchRuleType =
  | "pct_from_52w_high"
  | "pe"
  | "pb"
  | "single_day_drop"
  | "price_below";
export type WatchRuleOperator = "lte" | "gte" | "eq";
export type WatchRuleFrequency = "daily" | "hourly" | "15min";

export interface WatchRule {
  type: WatchRuleType | string;       // string fallback for legacy rows
  value: number;
  operator?: WatchRuleOperator | null;
  label?: string | null;
  check_frequency?: WatchRuleFrequency | null;
}

interface RuleTypeMeta {
  display: string;
  icon: string;
  unit: string;
  defaultValue: number;
  defaultOperator: WatchRuleOperator | null;
  // null operator = the type has an implicit operator (e.g. % from peak
  // is always "fall by N", single-day drop is always "drop by N").
  needsOperator: boolean;
  hint: string;
  buildLabel: (value: number, op: WatchRuleOperator | null) => string;
  fastEval: boolean;  // true → can be evaluated intraday
}

const RULE_TYPES: Record<WatchRuleType, RuleTypeMeta> = {
  pct_from_52w_high: {
    display: "% from 52-week high",
    icon: "▲",
    unit: "%",
    defaultValue: -10,
    defaultOperator: null,
    needsOperator: false,
    hint: "Negative number — fires when price has fallen this much from its 52-week high.",
    buildLabel: (v) =>
      v <= 0 ? `${Math.round(v)}% from peak` : `+${Math.round(v)}% from peak`,
    fastEval: false,
  },
  pe: {
    display: "P/E ratio",
    icon: "💲",
    unit: "×",
    defaultValue: 25,
    defaultOperator: "lte",
    needsOperator: true,
    hint: "Trailing P/E threshold. Fires when the operator condition is met against the latest valuation snapshot.",
    buildLabel: (v, op) => `P/E ${operatorSymbol(op)} ${v.toFixed(0)}×`,
    fastEval: false,
  },
  pb: {
    display: "P/B ratio",
    icon: "💲",
    unit: "×",
    defaultValue: 3,
    defaultOperator: "lte",
    needsOperator: true,
    hint: "Price-to-book threshold against the latest valuation snapshot.",
    buildLabel: (v, op) => `P/B ${operatorSymbol(op)} ${v.toFixed(1)}×`,
    fastEval: false,
  },
  single_day_drop: {
    display: "Single-day price drop",
    icon: "▼",
    unit: "%",
    defaultValue: 5,
    defaultOperator: null,
    needsOperator: false,
    hint: "Magnitude of drop in one trading session (positive %). Fires intraday when the live LTP is at least this much below the previous close.",
    buildLabel: (v) => `−${Math.abs(Math.round(v))}% in a day`,
    fastEval: true,
  },
  price_below: {
    display: "Price below ₹",
    icon: "₹",
    unit: "₹",
    defaultValue: 100,
    defaultOperator: null,
    needsOperator: false,
    hint: "Fires when the live LTP drops to or below this level.",
    buildLabel: (v) => `Price ≤ ₹${v.toFixed(0)}`,
    fastEval: true,
  },
};

const RULE_TYPE_KEYS: WatchRuleType[] = [
  "pct_from_52w_high",
  "pe",
  "pb",
  "single_day_drop",
  "price_below",
];

const FREQUENCY_OPTIONS: Array<{ value: WatchRuleFrequency; label: string; hint: string }> = [
  {
    value: "daily",
    label: "Daily after market close (16:40 IST)",
    hint: "Evaluated once per trading day from the closing snapshot.",
  },
  {
    value: "hourly",
    label: "Every hour during market hours",
    hint: "Re-checked intraday every hour against live quotes (only price-based rules).",
  },
  {
    value: "15min",
    label: "Every 15 min during market hours",
    hint: "Re-checked intraday every 15 minutes against live quotes (only price-based rules).",
  },
];

function operatorSymbol(op: WatchRuleOperator | null | undefined): string {
  if (op === "gte") return "≥";
  if (op === "eq") return "=";
  return "≤";
}

function chipLabel(rule: WatchRule): string {
  if (rule.label) return rule.label;
  const meta = RULE_TYPES[rule.type as WatchRuleType];
  if (meta) return meta.buildLabel(rule.value, rule.operator ?? meta.defaultOperator);
  return `${rule.type} ${rule.value}`;
}

interface Props {
  itemId: number;
  symbol: string;
  rules: WatchRule[];
  onClose: () => void;
  onSaved: (newRules: WatchRule[]) => void;
}

export default function RuleEditorModal({
  itemId,
  symbol,
  rules: initialRules,
  onClose,
  onSaved,
}: Props) {
  const [rules, setRules] = useState<WatchRule[]>(() =>
    initialRules.map((r) => ({ ...r })),
  );
  const [newType, setNewType] = useState<WatchRuleType>("pct_from_52w_high");
  const [newValue, setNewValue] = useState<string>(
    String(RULE_TYPES["pct_from_52w_high"].defaultValue),
  );
  const [newOperator, setNewOperator] = useState<WatchRuleOperator>("lte");
  const [newLabel, setNewLabel] = useState<string>("");
  const [newFrequency, setNewFrequency] = useState<WatchRuleFrequency>("daily");
  const [saving, setSaving] = useState(false);
  const [recheckBusy, setRecheckBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [recheckMsg, setRecheckMsg] = useState<string | null>(null);

  function pickType(t: WatchRuleType) {
    setNewType(t);
    const meta = RULE_TYPES[t];
    setNewValue(String(meta.defaultValue));
    if (meta.defaultOperator) setNewOperator(meta.defaultOperator);
    setNewLabel("");
    // Fast types default to 15-min; slow types reset to daily.
    setNewFrequency(meta.fastEval ? "15min" : "daily");
  }

  function addRule() {
    setError(null);
    const value = Number(newValue);
    if (!Number.isFinite(value)) {
      setError("Value must be a number.");
      return;
    }
    const meta = RULE_TYPES[newType];
    const op = meta.needsOperator ? newOperator : null;
    const rule: WatchRule = {
      type: newType,
      value,
      operator: op,
      label: newLabel.trim() ? newLabel.trim() : meta.buildLabel(value, op),
      check_frequency: newFrequency,
    };
    setRules((rs) => [...rs, rule]);
    // Reset value to default so adding another of the same kind is one click.
    setNewValue(String(meta.defaultValue));
    setNewLabel("");
  }

  function removeRule(idx: number) {
    setRules((rs) => rs.filter((_, i) => i !== idx));
  }

  async function saveAll() {
    setSaving(true);
    setError(null);
    try {
      // Strip nulls — backend accepts the optional fields but rejects
      // unknown keys, so we keep the payload clean.
      const payload = rules.map((r) => {
        const out: Record<string, unknown> = {
          type: r.type,
          value: r.value,
        };
        if (r.operator) out.operator = r.operator;
        if (r.label) out.label = r.label;
        if (r.check_frequency) out.check_frequency = r.check_frequency;
        return out;
      });
      await api.patch(`/api/watchlists/items/${itemId}`, { watch_rules: payload });
      onSaved(rules);
      onClose();
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Failed to save rules.";
      setError(msg);
      // Keep the modal open so the user can see the error and retry.
    } finally {
      setSaving(false);
    }
  }

  async function recheckNow() {
    setRecheckBusy(true);
    setRecheckMsg(null);
    setError(null);
    try {
      const r = await api.post<{ alerts_created: number }>(
        "/api/review-alerts/evaluate",
      );
      setRecheckMsg(
        r.alerts_created > 0
          ? `Re-checked. ${r.alerts_created} new alert${r.alerts_created === 1 ? "" : "s"} created.`
          : "Re-checked. No new alerts — rules didn't fire.",
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Re-check failed.");
    } finally {
      setRecheckBusy(false);
    }
  }

  const meta = RULE_TYPES[newType];

  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 80,
        background: "rgba(0,0,0,0.45)",
        backdropFilter: "blur(2px)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 20,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: "var(--bg-primary)",
          color: "var(--label-primary)",
          width: "min(620px, 100%)",
          maxHeight: "min(720px, 92vh)",
          display: "flex",
          flexDirection: "column",
          borderRadius: 14,
          boxShadow: "0 30px 60px rgba(0,0,0,0.25)",
          border: "1px solid var(--separator-light)",
          overflow: "hidden",
        }}
      >
        {/* Header */}
        <header
          style={{
            padding: "16px 20px",
            borderBottom: "1px solid var(--separator-light)",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
          }}
        >
          <div>
            <div style={{ fontSize: 11.5, color: "var(--label-tertiary)", textTransform: "uppercase", letterSpacing: "0.08em", fontWeight: 600 }}>
              Watching for
            </div>
            <div style={{ fontFamily: "var(--font-serif)", fontSize: 19, fontWeight: 600, marginTop: 2 }}>
              Rules for {symbol}
            </div>
          </div>
          <button
            onClick={onClose}
            aria-label="Close"
            style={{
              border: 0,
              background: "transparent",
              cursor: "pointer",
              fontSize: 22,
              lineHeight: 1,
              color: "var(--label-tertiary)",
              padding: 4,
            }}
          >
            ×
          </button>
        </header>

        {/* Body */}
        <div style={{ padding: 20, overflowY: "auto", flex: 1 }}>
          {/* Existing rules */}
          <div style={{ marginBottom: 18 }}>
            <div style={{ fontSize: 11.5, fontWeight: 600, color: "var(--label-tertiary)", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 8 }}>
              Existing rules
            </div>
            {rules.length === 0 ? (
              <div style={{
                padding: "16px",
                border: "1px dashed var(--separator)",
                borderRadius: 8,
                color: "var(--label-tertiary)",
                fontSize: 13,
                textAlign: "center",
              }}>
                No rules yet. Add one below.
              </div>
            ) : (
              <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "flex", flexDirection: "column", gap: 6 }}>
                {rules.map((r, i) => {
                  const m = RULE_TYPES[r.type as WatchRuleType];
                  const freq = r.check_frequency || "daily";
                  return (
                    <li
                      key={i}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 10,
                        padding: "8px 12px",
                        background: "var(--bg-secondary)",
                        border: "1px solid var(--separator-light)",
                        borderRadius: 8,
                      }}
                    >
                      <span style={{ fontSize: 13 }}>{m?.icon || "→"}</span>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontSize: 13, fontWeight: 500 }}>{chipLabel(r)}</div>
                        <div style={{ fontSize: 11, color: "var(--label-tertiary)", fontFamily: "var(--font-mono)" }}>
                          {r.type}
                          {freq !== "daily" && <> · {freq}</>}
                        </div>
                      </div>
                      <button
                        onClick={() => removeRule(i)}
                        aria-label={`Remove rule ${chipLabel(r)}`}
                        title="Remove rule"
                        style={{
                          border: 0,
                          background: "transparent",
                          cursor: "pointer",
                          fontSize: 18,
                          lineHeight: 1,
                          color: "var(--label-tertiary)",
                          padding: "0 4px",
                        }}
                      >
                        ×
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>

          {/* Add new */}
          <div
            style={{
              padding: 14,
              borderRadius: 10,
              border: "1px solid var(--separator-light)",
              background: "var(--bg-secondary)",
            }}
          >
            <div style={{ fontSize: 11.5, fontWeight: 600, color: "var(--label-tertiary)", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 10 }}>
              Add a new rule
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {/* Row 1: Type + Operator (operator only when needed) */}
              <div style={{ display: "grid", gridTemplateColumns: meta.needsOperator ? "1fr 0.6fr" : "1fr", gap: 10 }}>
                <label style={{ display: "flex", flexDirection: "column", gap: 4, minWidth: 0 }}>
                  <span style={{ fontSize: 11, color: "var(--label-tertiary)" }}>Type</span>
                  <select
                    value={newType}
                    onChange={(e) => pickType(e.target.value as WatchRuleType)}
                    style={selectStyle}
                  >
                    {RULE_TYPE_KEYS.map((k) => (
                      <option key={k} value={k}>
                        {RULE_TYPES[k].display}
                      </option>
                    ))}
                  </select>
                </label>
                {meta.needsOperator && (
                  <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                    <span style={{ fontSize: 11, color: "var(--label-tertiary)" }}>Operator</span>
                    <select
                      value={newOperator}
                      onChange={(e) => setNewOperator(e.target.value as WatchRuleOperator)}
                      style={selectStyle}
                    >
                      <option value="lte">Less than or equal (≤)</option>
                      <option value="gte">Greater than or equal (≥)</option>
                      <option value="eq">Equal to (=)</option>
                    </select>
                  </label>
                )}
              </div>

              {/* Row 2: Value */}
              <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                <span style={{ fontSize: 11, color: "var(--label-tertiary)" }}>
                  Value <span style={{ color: "var(--label-quaternary)" }}>({meta.unit})</span>
                </span>
                <input
                  type="number"
                  value={newValue}
                  step="any"
                  onChange={(e) => setNewValue(e.target.value)}
                  style={inputStyle}
                />
                <span style={{ fontSize: 11, color: "var(--label-quaternary)" }}>{meta.hint}</span>
              </label>

              {/* Row 3: Frequency */}
              <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                <span style={{ fontSize: 11, color: "var(--label-tertiary)" }}>Check frequency</span>
                <select
                  value={newFrequency}
                  onChange={(e) => setNewFrequency(e.target.value as WatchRuleFrequency)}
                  style={selectStyle}
                  disabled={!meta.fastEval && newFrequency !== "daily"}
                  title={!meta.fastEval ? "This rule type only updates after the daily 16:30 snapshot." : undefined}
                >
                  {FREQUENCY_OPTIONS.map((f) => (
                    <option
                      key={f.value}
                      value={f.value}
                      disabled={!meta.fastEval && f.value !== "daily"}
                    >
                      {f.label}
                    </option>
                  ))}
                </select>
                <span style={{ fontSize: 11, color: "var(--label-quaternary)" }}>
                  {meta.fastEval
                    ? FREQUENCY_OPTIONS.find((f) => f.value === newFrequency)?.hint
                    : "Snapshot-driven rules are evaluated once a day. Intraday checks are only available for price-based rules."}
                </span>
              </label>

              {/* Row 4: Label */}
              <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                <span style={{ fontSize: 11, color: "var(--label-tertiary)" }}>
                  Label <span style={{ color: "var(--label-quaternary)" }}>(optional, shown on chip)</span>
                </span>
                <input
                  type="text"
                  value={newLabel}
                  placeholder={meta.buildLabel(
                    Number(newValue) || meta.defaultValue,
                    meta.needsOperator ? newOperator : null,
                  )}
                  onChange={(e) => setNewLabel(e.target.value)}
                  style={inputStyle}
                />
              </label>

              <button onClick={addRule} style={addBtnStyle}>+ Add rule</button>
            </div>
          </div>

          {error && (
            <div role="alert" style={{
              marginTop: 14, padding: "8px 12px",
              background: "var(--fill-red, rgba(255,59,48,0.08))",
              color: "var(--system-red, #d70015)",
              borderRadius: 6, fontSize: 12.5,
            }}>{error}</div>
          )}
          {recheckMsg && (
            <div style={{
              marginTop: 14, padding: "8px 12px",
              background: "var(--fill-blue, rgba(0,122,255,0.08))",
              color: "var(--system-blue, #007aff)",
              borderRadius: 6, fontSize: 12.5,
            }}>{recheckMsg}</div>
          )}
        </div>

        {/* Footer */}
        <footer style={{
          padding: "12px 20px",
          borderTop: "1px solid var(--separator-light)",
          display: "flex", alignItems: "center", gap: 10,
        }}>
          <button
            onClick={recheckNow}
            disabled={recheckBusy}
            style={{
              border: 0, background: "transparent",
              color: "var(--system-blue, #007aff)",
              cursor: recheckBusy ? "wait" : "pointer",
              fontSize: 12.5, fontWeight: 500, padding: "6px 8px",
            }}
            title="Run the alert evaluator now instead of waiting for tomorrow's 16:40 IST run"
          >
            {recheckBusy ? "Re-checking…" : "Re-check now"}
          </button>
          <div style={{ flex: 1 }} />
          <button
            onClick={onClose}
            style={{
              padding: "8px 14px", borderRadius: 7,
              border: "1px solid var(--separator)",
              background: "transparent",
              color: "var(--label-primary)",
              cursor: "pointer", fontSize: 13, fontWeight: 500,
            }}
          >
            Cancel
          </button>
          <button
            onClick={saveAll}
            disabled={saving}
            style={{
              padding: "8px 16px", borderRadius: 7, border: 0,
              background: "var(--label-primary)",
              color: "var(--bg-primary)",
              cursor: saving ? "wait" : "pointer",
              fontSize: 13, fontWeight: 600,
            }}
          >
            {saving ? "Saving…" : "Save changes"}
          </button>
        </footer>
      </div>
    </div>
  );
}

const selectStyle: React.CSSProperties = {
  padding: "8px 10px",
  border: "1px solid var(--separator)",
  borderRadius: 6,
  background: "var(--bg-primary)",
  color: "var(--label-primary)",
  fontSize: 13,
};

const inputStyle: React.CSSProperties = {
  padding: "8px 10px",
  border: "1px solid var(--separator)",
  borderRadius: 6,
  background: "var(--bg-primary)",
  color: "var(--label-primary)",
  fontSize: 13,
  fontFamily: "var(--font-mono)",
};

const addBtnStyle: React.CSSProperties = {
  alignSelf: "flex-start",
  padding: "7px 14px",
  borderRadius: 6,
  background: "var(--label-primary)",
  color: "var(--bg-primary)",
  border: 0,
  cursor: "pointer",
  fontSize: 12.5,
  fontWeight: 600,
};
