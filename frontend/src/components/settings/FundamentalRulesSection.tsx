"use client";

import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import SettingsCard from "@/components/settings/SettingsCard";
import { settingsButtonPrimary, settingsInputStyle } from "@/components/settings/SettingsField";
import { useToast } from "@/lib/use-toast";

/**
 * Settings → Fundamental Analysis Rules editor.
 *
 * Categorized metric picker on the left, current rule list on the right.
 * Each rule = metric + operator + threshold (single or pair) + weight.
 * Tooltips render `description_md` from the metric catalog.
 */

type Operator =
  | "gte" | "lte" | "gt" | "lt" | "eq" | "between" | "is_positive";

interface MetricDef {
  key: string;
  display_name: string;
  category: string;
  unit: string | null;
  direction: "higher_better" | "lower_better" | "neutral";
  description_md: string | null;
  formula: string | null;
  default_source: string | null;
}

interface Rule {
  metric_key: string;
  operator: Operator;
  value_num: number | null;
  value_low: number | null;
  value_high: number | null;
  weight: number;
  enabled: boolean;
  is_hard_filter: boolean;
}

interface PresetSummary {
  key: string;
  name: string;
  description: string;
  rule_count: number;
  hard_count: number;
  soft_count: number;
}

interface RuleSet {
  id: number;
  name: string;
  is_default: boolean;
  rules: Rule[];
}

const CATEGORY_LABEL: Record<string, string> = {
  profitability: "Profitability",
  growth: "Growth",
  valuation: "Valuation",
  ownership: "Ownership",
  financial_ratios: "Financial Ratios",
  cash_flow: "Cash Flow",
  trading: "Trading & Technical",
  sector_relative: "Sector-relative",
};

const OPERATOR_LABEL: Record<Operator, string> = {
  gte: "≥",
  lte: "≤",
  gt: ">",
  lt: "<",
  eq: "=",
  between: "between",
  is_positive: "> 0",
};

function defaultOperatorForDirection(d: string): Operator {
  if (d === "higher_better") return "gte";
  if (d === "lower_better") return "lte";
  return "gte";
}

const SMALL_INPUT: React.CSSProperties = {
  ...settingsInputStyle,
  padding: "5px 8px",
  fontSize: 12,
  fontFamily: "var(--font-mono)",
};

const SMALL_SELECT: React.CSSProperties = {
  ...settingsInputStyle,
  padding: "5px 8px",
  fontSize: 12,
};

export default function FundamentalRulesSection() {
  const [catalog, setCatalog] = useState<Record<string, MetricDef[]>>({});
  const [ruleSet, setRuleSet] = useState<RuleSet | null>(null);
  const [presets, setPresets] = useState<PresetSummary[]>([]);
  const [openCat, setOpenCat] = useState<string | null>(null);
  const [tooltipKey, setTooltipKey] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [applying, setApplying] = useState(false);
  const { toast } = useToast();

  useEffect(() => {
    api.get<{ categories: Record<string, MetricDef[]> }>("/api/fundamentals/metrics")
      .then((d) => setCatalog(d.categories))
      .catch(() => {});
    api.get<{ rule_sets: RuleSet[] }>("/api/fundamentals/rule-sets")
      .then((d) => setRuleSet(d.rule_sets[0] ?? null))
      .catch(() => {});
    api.get<{ presets: PresetSummary[] }>("/api/fundamentals/presets")
      .then((d) => setPresets(d.presets || []))
      .catch(() => {});
  }, []);

  const metricsByKey = useMemo(() => {
    const out: Record<string, MetricDef> = {};
    for (const list of Object.values(catalog)) for (const m of list) out[m.key] = m;
    return out;
  }, [catalog]);

  function addRule(m: MetricDef) {
    if (!ruleSet) return;
    if (ruleSet.rules.find((r) => r.metric_key === m.key)) return;
    const op = defaultOperatorForDirection(m.direction);
    const newRule: Rule = {
      metric_key: m.key,
      operator: op,
      value_num: 0,
      value_low: null,
      value_high: null,
      weight: 1,
      enabled: true,
      is_hard_filter: false,
    };
    setRuleSet({ ...ruleSet, rules: [...ruleSet.rules, newRule] });
  }

  function removeRule(idx: number) {
    if (!ruleSet) return;
    setRuleSet({ ...ruleSet, rules: ruleSet.rules.filter((_, i) => i !== idx) });
  }

  function updateRule(idx: number, patch: Partial<Rule>) {
    if (!ruleSet) return;
    const next = [...ruleSet.rules];
    next[idx] = { ...next[idx], ...patch };
    setRuleSet({ ...ruleSet, rules: next });
  }

  async function save() {
    if (!ruleSet) return;
    setSaving(true);
    try {
      await api.put(`/api/fundamentals/rule-sets/${ruleSet.id}`, {
        name: ruleSet.name,
        rules: ruleSet.rules,
      });
      toast({ kind: "ok", text: "Rules saved" });
    } catch (e) {
      toast({ kind: "error", text: e instanceof Error ? e.message : "Save failed" });
    } finally {
      setSaving(false);
    }
  }

  async function applyPreset(presetKey: string) {
    if (!ruleSet) return;
    if (!confirm("Replace your current rules with the preset? Your existing rules will be lost.")) return;
    setApplying(true);
    try {
      await api.post(`/api/fundamentals/rule-sets/${ruleSet.id}/apply-preset`, { preset_key: presetKey });
      const fresh = await api.get<{ rule_sets: RuleSet[] }>("/api/fundamentals/rule-sets");
      setRuleSet(fresh.rule_sets[0] ?? null);
      toast({ kind: "ok", text: "Preset loaded" });
    } catch (e) {
      toast({ kind: "error", text: e instanceof Error ? e.message : "Failed to apply preset" });
    } finally {
      setApplying(false);
    }
  }

  if (!ruleSet) {
    return (
      <SettingsCard
        title="Fundamental analysis rules"
        subtitle="Loading…"
      >
        <div style={{ fontSize: 12, color: "var(--label-tertiary)" }}>Loading rules…</div>
      </SettingsCard>
    );
  }

  return (
    <SettingsCard
      title="Fundamental analysis rules"
      subtitle="Platform-wide rule set — drives the STRONG / FAIR / WEAK pill on every Researching card. Hard filters gate the universe; soft filters score and rank inside it."
      actions={
        <>
        {presets.length > 0 && (
          <select
            disabled={applying}
            defaultValue=""
            onChange={(e) => {
              if (e.target.value) {
                applyPreset(e.target.value);
                e.target.value = "";
              }
            }}
            style={{
              padding: "6px 10px",
              borderRadius: 6,
              border: "1px solid var(--separator)",
              background: "var(--bg-primary)",
              color: "var(--label-secondary)",
              fontSize: 12,
              opacity: applying ? 0.5 : 1,
            }}
          >
            <option value="">Load preset…</option>
            {presets.map((p) => (
              <option key={p.key} value={p.key}>
                {p.name} ({p.hard_count}H + {p.soft_count}S)
              </option>
            ))}
          </select>
        )}
        <button
          onClick={save}
          disabled={saving}
          style={{ ...settingsButtonPrimary, padding: "6px 12px", fontSize: 12, opacity: saving ? 0.5 : 1 }}
        >
          {saving ? "Saving…" : "Save changes"}
        </button>
        </>
      }
    >
      <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
        <div>
          <div style={sectionLabel}>
            Active rules ({ruleSet.rules.length})
            {ruleSet.rules.some((r) => r.is_hard_filter) && (
              <>
                {" — "}
                <span style={{ color: "var(--act)" }}>
                  {ruleSet.rules.filter((r) => r.is_hard_filter).length} hard
                </span>
                {" / "}
                <span style={{ color: "var(--label-tertiary)" }}>
                  {ruleSet.rules.filter((r) => !r.is_hard_filter).length} soft
                </span>
              </>
            )}
          </div>
          {ruleSet.rules.length === 0 ? (
            <div
              style={{
                padding: 14,
                border: "1px dashed var(--separator)",
                borderRadius: 8,
                fontSize: 12,
                color: "var(--label-tertiary)",
                textAlign: "center",
              }}
            >
              No rules yet. Pick metrics from the catalog below.
            </div>
          ) : (
            <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 6 }}>
              {ruleSet.rules.map((r, i) => {
                const m = metricsByKey[r.metric_key];
                return (
                  <li
                    key={i}
                    style={{
                      display: "grid",
                      gridTemplateColumns: "1.4fr 56px 1fr 1fr 0.5fr 24px",
                      alignItems: "center",
                      gap: 8,
                      padding: "8px 10px",
                      background: r.is_hard_filter
                        ? "color-mix(in srgb, var(--act-bg, rgba(255,59,48,0.05)) 70%, var(--bg-secondary))"
                        : "var(--bg-secondary)",
                      border: r.is_hard_filter
                        ? "1px solid var(--act-edge, rgba(255,59,48,0.18))"
                        : "1px solid var(--separator-light)",
                      borderRadius: 8,
                      fontSize: 12,
                    }}
                  >
                    <span title={m?.description_md || ""}>
                      <span style={{ color: "var(--label-primary)", fontWeight: 500 }}>
                        {m?.display_name || r.metric_key}
                      </span>
                      <span style={{ color: "var(--label-tertiary)", marginLeft: 6, fontFamily: "var(--font-mono)" }}>
                        {m?.unit || ""}
                      </span>
                    </span>
                    {/* Hard / Soft toggle. Hard rules gate the universe; */}
                    {/* soft rules contribute to the X/N score within it. */}
                    <button
                      onClick={() => updateRule(i, { is_hard_filter: !r.is_hard_filter })}
                      title={r.is_hard_filter
                        ? "Hard filter — must pass; click to make soft"
                        : "Soft filter — contributes to ranking; click to make hard"}
                      style={{
                        padding: "3px 6px",
                        borderRadius: 6,
                        border: 0,
                        cursor: "pointer",
                        fontSize: 10,
                        fontWeight: 700,
                        textTransform: "uppercase",
                        letterSpacing: "0.04em",
                        background: r.is_hard_filter ? "var(--act)" : "var(--fill-gray, rgba(99,99,102,0.12))",
                        color: r.is_hard_filter ? "#fff" : "var(--label-tertiary)",
                      }}
                    >
                      {r.is_hard_filter ? "Hard" : "Soft"}
                    </button>
                    <select
                      value={r.operator}
                      onChange={(e) => updateRule(i, { operator: e.target.value as Operator })}
                      style={SMALL_SELECT}
                    >
                      {(Object.keys(OPERATOR_LABEL) as Operator[]).map((op) => (
                        <option key={op} value={op}>{OPERATOR_LABEL[op]}</option>
                      ))}
                    </select>
                    {r.operator === "between" ? (
                      <span style={{ display: "flex", gap: 4 }}>
                        <input
                          type="number" step="any"
                          value={r.value_low ?? ""}
                          onChange={(e) => updateRule(i, { value_low: e.target.value === "" ? null : Number(e.target.value) })}
                          placeholder="low"
                          style={{ ...SMALL_INPUT, width: "50%" }}
                        />
                        <input
                          type="number" step="any"
                          value={r.value_high ?? ""}
                          onChange={(e) => updateRule(i, { value_high: e.target.value === "" ? null : Number(e.target.value) })}
                          placeholder="high"
                          style={{ ...SMALL_INPUT, width: "50%" }}
                        />
                      </span>
                    ) : r.operator === "is_positive" ? (
                      <span style={{ color: "var(--label-tertiary)", fontStyle: "italic", fontSize: 11 }}>(no value)</span>
                    ) : (
                      <input
                        type="number" step="any"
                        value={r.value_num ?? ""}
                        onChange={(e) => updateRule(i, { value_num: e.target.value === "" ? null : Number(e.target.value) })}
                        style={SMALL_INPUT}
                      />
                    )}
                    <select
                      value={r.weight}
                      onChange={(e) => updateRule(i, { weight: Number(e.target.value) })}
                      title="Weight (1-5)"
                      style={SMALL_SELECT}
                    >
                      {[1, 2, 3, 4, 5].map((w) => (
                        <option key={w} value={w}>w{w}</option>
                      ))}
                    </select>
                    <button
                      onClick={() => removeRule(i)}
                      aria-label="Remove rule"
                      style={{
                        background: "transparent", border: 0, cursor: "pointer",
                        color: "var(--label-tertiary)", fontSize: 18, lineHeight: 1, padding: 0,
                      }}
                    >×</button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        <div>
          <div style={sectionLabel}>Add a rule</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {Object.keys(CATEGORY_LABEL).filter((c) => catalog[c]?.length).map((cat) => {
              const list = catalog[cat] || [];
              const isOpen = openCat === cat;
              return (
                <div
                  key={cat}
                  style={{
                    border: "1px solid var(--separator-light)",
                    borderRadius: 8,
                    overflow: "hidden",
                    background: "var(--bg-secondary)",
                  }}
                >
                  <button
                    onClick={() => setOpenCat(isOpen ? null : cat)}
                    style={{
                      width: "100%",
                      padding: "8px 12px",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                      fontSize: 12,
                      color: "var(--label-secondary)",
                      background: "transparent",
                      border: 0,
                      cursor: "pointer",
                    }}
                  >
                    <span style={{ fontWeight: 500 }}>{CATEGORY_LABEL[cat]}</span>
                    <span style={{ color: "var(--label-tertiary)", fontFamily: "var(--font-mono)" }}>
                      {list.length} · {isOpen ? "▴" : "▾"}
                    </span>
                  </button>
                  {isOpen && (
                    <div
                      style={{
                        padding: "8px 12px 12px",
                        display: "grid",
                        gap: 4,
                        gridTemplateColumns: "1fr 1fr",
                        fontSize: 12,
                        borderTop: "1px solid var(--separator-light)",
                      }}
                    >
                      {list.map((m) => {
                        const added = !!ruleSet.rules.find((r) => r.metric_key === m.key);
                        return (
                          <div
                            key={m.key}
                            style={{
                              display: "flex",
                              alignItems: "center",
                              justifyContent: "space-between",
                              gap: 8,
                              padding: "5px 8px",
                              borderRadius: 6,
                            }}
                          >
                            <span
                              style={{
                                color: "var(--label-secondary)",
                                overflow: "hidden",
                                textOverflow: "ellipsis",
                                whiteSpace: "nowrap",
                                display: "inline-flex",
                                alignItems: "center",
                                gap: 4,
                                minWidth: 0,
                              }}
                            >
                              <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                                {m.display_name}
                              </span>
                              {m.unit && (
                                <span style={{ color: "var(--label-tertiary)", fontFamily: "var(--font-mono)" }}>
                                  {m.unit}
                                </span>
                              )}
                              {m.description_md && (
                                <button
                                  onClick={(e) => { e.stopPropagation(); setTooltipKey(m.key); }}
                                  aria-label={`Definition for ${m.display_name}`}
                                  title="Show definition"
                                  style={{
                                    width: 16,
                                    height: 16,
                                    padding: 0,
                                    borderRadius: 99,
                                    border: "1px solid var(--separator)",
                                    background: "var(--bg-primary)",
                                    color: "var(--label-tertiary)",
                                    fontSize: 10,
                                    fontWeight: 700,
                                    cursor: "pointer",
                                    lineHeight: "14px",
                                    flexShrink: 0,
                                  }}
                                >
                                  ?
                                </button>
                              )}
                            </span>
                            <button
                              onClick={() => addRule(m)}
                              disabled={added}
                              style={{
                                fontSize: 10,
                                padding: "2px 8px",
                                borderRadius: 4,
                                border: 0,
                                background: added ? "var(--fill-gray, rgba(99,99,102,0.12))" : "var(--system-blue)",
                                color: added ? "var(--label-tertiary)" : "#fff",
                                cursor: added ? "default" : "pointer",
                                fontWeight: 500,
                              }}
                            >
                              {added ? "added" : "+ add"}
                            </button>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </div>
      {tooltipKey && metricsByKey[tooltipKey]?.description_md && (
        <MetricDefinitionPopup
          metric={metricsByKey[tooltipKey]}
          onClose={() => setTooltipKey(null)}
        />
      )}
    </SettingsCard>
  );
}

function MetricDefinitionPopup({ metric, onClose }: { metric: MetricDef; onClose: () => void }) {
  // Esc to close. Effect runs once per open.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      role="dialog"
      aria-modal="true"
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        background: "color-mix(in srgb, #000 35%, transparent)",
        backdropFilter: "blur(2px)",
        WebkitBackdropFilter: "blur(2px)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 1000,
        padding: 16,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          maxWidth: 480,
          width: "100%",
          background: "var(--bg-primary)",
          border: "1px solid var(--separator)",
          borderRadius: 12,
          padding: 18,
          boxShadow: "var(--shadow-lg, 0 24px 48px rgba(0,0,0,0.18))",
          color: "var(--label-secondary)",
          fontSize: 13,
          lineHeight: 1.5,
          whiteSpace: "pre-wrap",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "flex-start",
            justifyContent: "space-between",
            gap: 12,
            marginBottom: 8,
          }}
        >
          <div>
            <div
              style={{
                fontFamily: "var(--font-serif)",
                fontSize: 17,
                fontWeight: 600,
                color: "var(--label-primary)",
                letterSpacing: "-0.01em",
              }}
            >
              {metric.display_name}
              {metric.unit && (
                <span
                  style={{
                    marginLeft: 8,
                    fontFamily: "var(--font-mono)",
                    fontSize: 12,
                    color: "var(--label-tertiary)",
                    fontWeight: 400,
                  }}
                >
                  {metric.unit}
                </span>
              )}
            </div>
            <div
              style={{
                marginTop: 2,
                fontSize: 11,
                color: "var(--label-tertiary)",
                textTransform: "uppercase",
                letterSpacing: "0.06em",
              }}
            >
              {metric.category} · {metric.direction.replace(/_/g, " ")}
            </div>
          </div>
          <button
            onClick={onClose}
            aria-label="Close"
            style={{
              background: "transparent",
              border: 0,
              cursor: "pointer",
              fontSize: 18,
              color: "var(--label-tertiary)",
              padding: "0 4px",
              lineHeight: 1,
            }}
          >
            ×
          </button>
        </div>
        {metric.formula && (
          <div
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: 11,
              color: "var(--label-tertiary)",
              padding: "6px 10px",
              borderRadius: 6,
              background: "var(--bg-secondary)",
              border: "1px solid var(--separator-light)",
              marginBottom: 10,
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
            }}
          >
            {metric.formula}
          </div>
        )}
        <div style={{ whiteSpace: "pre-wrap" }}>{metric.description_md}</div>
      </div>
    </div>
  );
}

const sectionLabel: React.CSSProperties = {
  fontSize: 11,
  fontWeight: 600,
  textTransform: "uppercase",
  letterSpacing: "0.06em",
  color: "var(--label-tertiary)",
  marginBottom: 8,
};
