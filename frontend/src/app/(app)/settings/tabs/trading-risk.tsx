"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useToast } from "@/lib/use-toast";
import SettingsCard from "@/components/settings/SettingsCard";
import SettingsField, { settingsButtonPrimary, settingsInputStyle } from "@/components/settings/SettingsField";

interface RiskSettings {
  risk_max_position_size_pct: number;
  risk_max_total_exposure_pct: number;
  risk_max_daily_loss_inr: number;
  risk_max_drawdown_pct: number;
  risk_max_orders_per_day: number;
  risk_max_order_value_inr: number;
  risk_kill_switch: boolean;
  opus_max_daily_budget_usd: number;
  gemini_model: string;
  opus_model: string;
}

const RISK_FIELDS: {
  key: keyof RiskSettings;
  label: string;
  hint: string;
  step?: string;
  unit?: string;
}[] = [
  { key: "risk_max_position_size_pct", label: "Max position size", hint: "Single position cap as % of portfolio.", unit: "%" },
  { key: "risk_max_total_exposure_pct", label: "Max total exposure", hint: "Sum of all open positions cap.", unit: "%" },
  { key: "risk_max_daily_loss_inr", label: "Max daily loss", hint: "Engine pauses after this realised loss.", unit: "Rs" },
  { key: "risk_max_drawdown_pct", label: "Max drawdown", hint: "Peak-to-trough loss before halt.", unit: "%" },
  { key: "risk_max_orders_per_day", label: "Max orders / day", hint: "Hard cap on order count per session." },
  { key: "risk_max_order_value_inr", label: "Max order value", hint: "Single-order notional cap.", unit: "Rs" },
];

export default function TradingRiskTab() {
  const [risk, setRisk] = useState<RiskSettings | null>(null);
  const [saving, setSaving] = useState(false);
  const { toast } = useToast();

  useEffect(() => {
    api.get<RiskSettings>("/api/settings/risk").then(setRisk).catch(() => {});
  }, []);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (!risk) return;
    setSaving(true);
    try {
      await api.put("/api/settings/risk", risk);
      toast({ kind: "ok", text: "Risk settings saved" });
    } catch (err) {
      toast({ kind: "error", text: err instanceof Error ? err.message : "Save failed" });
    } finally {
      setSaving(false);
    }
  }

  async function toggleKillSwitch(value: boolean) {
    if (!risk) return;
    const next = { ...risk, risk_kill_switch: value };
    setRisk(next);
    try {
      await api.put("/api/settings/risk", next);
      toast({ kind: value ? "warn" : "ok", text: value ? "Kill switch ENGAGED — orders blocked" : "Kill switch released" });
    } catch (err) {
      setRisk(risk);
      toast({ kind: "error", text: err instanceof Error ? err.message : "Save failed" });
    }
  }

  if (!risk) {
    return <div style={{ color: "var(--label-tertiary)", fontSize: 13, padding: 24 }}>Loading risk settings…</div>;
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <SettingsCard
        title="Kill switch"
        subtitle="When engaged, the engine refuses to place any new orders. Use immediately when something looks wrong."
        status={risk.risk_kill_switch ? { kind: "error", label: "Engaged" } : { kind: "ok", label: "Released" }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <button
            onClick={() => toggleKillSwitch(!risk.risk_kill_switch)}
            style={{
              padding: "10px 18px",
              borderRadius: 10,
              border: 0,
              background: risk.risk_kill_switch ? "var(--act)" : "var(--label-primary)",
              color: risk.risk_kill_switch ? "#fff" : "var(--bg-primary)",
              fontSize: 13,
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            {risk.risk_kill_switch ? "Release kill switch" : "Engage kill switch"}
          </button>
          <span style={{ fontSize: 12, color: "var(--label-tertiary)" }}>
            {risk.risk_kill_switch
              ? "All new order placement is blocked at the engine."
              : "Engine will place orders subject to risk limits below."}
          </span>
        </div>
      </SettingsCard>

      <SettingsCard
        title="Risk parameters"
        subtitle="Engine-enforced limits. Order placement is rejected when any of these are breached."
      >
        <form onSubmit={save} style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
              gap: 14,
            }}
          >
            {RISK_FIELDS.map((f) => (
              <SettingsField key={f.key} label={f.label} hint={f.hint}>
                <div style={{ position: "relative", display: "flex", alignItems: "center" }}>
                  <input
                    type="number"
                    step={f.step || "any"}
                    value={risk[f.key] as number}
                    onChange={(e) => setRisk({ ...risk, [f.key]: Number(e.target.value) })}
                    style={{ ...settingsInputStyle, paddingRight: f.unit ? 44 : 12 }}
                  />
                  {f.unit && (
                    <span style={unitBadgeStyle}>{f.unit}</span>
                  )}
                </div>
              </SettingsField>
            ))}
          </div>
          <div>
            <button type="submit" disabled={saving} style={{ ...settingsButtonPrimary, opacity: saving ? 0.5 : 1 }}>
              {saving ? "Saving…" : "Save risk parameters"}
            </button>
          </div>
        </form>
      </SettingsCard>

      <SettingsCard
        title="LLM cost cap"
        subtitle="Daily budget for Opus deep-analysis spend. Prevents runaway cost from a stuck loop."
      >
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            await save(e);
          }}
          style={{ display: "flex", gap: 10, alignItems: "flex-end" }}
        >
          <SettingsField label="Opus daily budget" hint="USD. Engine refuses Opus calls past this.">
            <div style={{ position: "relative", display: "flex", alignItems: "center" }}>
              <span style={{ ...unitBadgeStyle, left: 10, right: "auto" }}>$</span>
              <input
                type="number"
                step="0.1"
                value={risk.opus_max_daily_budget_usd}
                onChange={(e) => setRisk({ ...risk, opus_max_daily_budget_usd: Number(e.target.value) })}
                style={{ ...settingsInputStyle, paddingLeft: 26 }}
              />
            </div>
          </SettingsField>
          <button type="submit" disabled={saving} style={{ ...settingsButtonPrimary, opacity: saving ? 0.5 : 1 }}>
            Save
          </button>
        </form>
      </SettingsCard>
    </div>
  );
}

const unitBadgeStyle: React.CSSProperties = {
  position: "absolute",
  right: 10,
  fontSize: 11,
  color: "var(--label-tertiary)",
  fontFamily: "var(--font-mono)",
  pointerEvents: "none",
};
