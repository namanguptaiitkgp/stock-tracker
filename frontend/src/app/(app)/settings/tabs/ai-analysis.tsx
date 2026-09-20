"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { useToast } from "@/lib/use-toast";
import SettingsCard from "@/components/settings/SettingsCard";
import SettingsField, { settingsButtonPrimary, settingsButtonSecondary, settingsInputStyle } from "@/components/settings/SettingsField";
import FundamentalRulesSection from "@/components/settings/FundamentalRulesSection";

interface RiskSettings {
  gemini_model: string;
  opus_model: string;
  // We only PUT/GET these; engine carries the rest. The risk endpoint
  // is shared, so we round-trip the whole shape.
  risk_max_position_size_pct: number;
  risk_max_total_exposure_pct: number;
  risk_max_daily_loss_inr: number;
  risk_max_drawdown_pct: number;
  risk_max_orders_per_day: number;
  risk_max_order_value_inr: number;
  risk_kill_switch: boolean;
  opus_max_daily_budget_usd: number;
}

interface GeminiModel {
  id: string;
  name: string;
  description: string;
}

export default function AiAnalysisTab() {
  const [risk, setRisk] = useState<RiskSettings | null>(null);
  const [models, setModels] = useState<GeminiModel[]>([]);
  const [loadingModels, setLoadingModels] = useState(false);
  const [savingModels, setSavingModels] = useState(false);
  const { toast } = useToast();

  const fetchModels = useCallback(async () => {
    setLoadingModels(true);
    try {
      const data = await api.get<GeminiModel[]>("/api/settings/gemini-models");
      setModels(data.filter((m) => m.id !== "error"));
    } catch {
      // ignore
    } finally {
      setLoadingModels(false);
    }
  }, []);

  useEffect(() => {
    api.get<RiskSettings>("/api/settings/risk").then(setRisk).catch(() => {});
    fetchModels();
  }, [fetchModels]);

  async function saveModels(e: React.FormEvent) {
    e.preventDefault();
    if (!risk) return;
    setSavingModels(true);
    try {
      await api.put("/api/settings/risk", risk);
      toast({ kind: "ok", text: "Model selection saved" });
    } catch (err) {
      toast({ kind: "error", text: err instanceof Error ? err.message : "Save failed" });
    } finally {
      setSavingModels(false);
    }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <SettingsCard
        title="How verdicts are decided"
        subtitle="Two independent scorers feed the Should I Invest? verdict on every Researching card."
      >
        <ul style={{ margin: 0, paddingLeft: 18, fontSize: 13, color: "var(--label-secondary)", lineHeight: 1.6 }}>
          <li>
            <strong style={{ color: "var(--label-primary)" }}>Fundamentals</strong> — pure rules engine. Reads the latest metric snapshot
            (Screener.in + yfinance + Google Finance + NSE ownership) and scores it against the rule set below. STRONG ≥ 70, FAIR 40–69, WEAK &lt; 40.
          </li>
          <li>
            <strong style={{ color: "var(--label-primary)" }}>News sentiment</strong> — Gemini classifies headlines from all 18 unified news
            sources (Hindu BL, Moneycontrol, ET, Mint, Reuters, PIB, Google News) plus per-stock Google News searches,
            then emits the per-stock pill (Positive / Neutral / Negative).
          </li>
          <li>
            <strong style={{ color: "var(--label-primary)" }}>Deep verdict</strong> — Gemini runs only on shortlisted holdings. Reads the
            fundamentals, news, and your active rule set, then writes the BUY / HOLD / TRIM / SELL line you see on the card.
          </li>
        </ul>
      </SettingsCard>

      <FundamentalRulesSection />

      <SettingsCard
        title="LLM models"
        subtitle="Default model for screening and deep analysis. All AI calls route through Gemini Vertex."
        actions={
          <button
            type="button"
            onClick={fetchModels}
            disabled={loadingModels}
            style={{ ...settingsButtonSecondary, fontSize: 12, padding: "6px 10px", opacity: loadingModels ? 0.5 : 1 }}
          >
            {loadingModels ? "Refreshing…" : "Refresh available"}
          </button>
        }
      >
        {!risk ? (
          <div style={{ color: "var(--label-tertiary)", fontSize: 13 }}>Loading…</div>
        ) : (
          <form
            onSubmit={saveModels}
            style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14, alignItems: "end" }}
          >
            <SettingsField
              label="Screening model (Gemini)"
              hint={models.length > 0 ? `${models.length} models available` : "Refresh to load from your Gemini key."}
            >
              <select
                value={risk.gemini_model}
                onChange={(e) => setRisk({ ...risk, gemini_model: e.target.value })}
                style={settingsInputStyle}
              >
                {models.length > 0 ? (
                  models.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.name || m.id}
                    </option>
                  ))
                ) : (
                  <>
                    <option value="gemini-2.5-flash-lite">Gemini 2.5 Flash-Lite</option>
                    <option value="gemini-2.5-flash">Gemini 2.5 Flash</option>
                    <option value="gemini-2.5-pro">Gemini 2.5 Pro</option>
                  </>
                )}
              </select>
            </SettingsField>
            <SettingsField label="Deep analysis model" hint="Claude integration is planned but not yet available.">
              <select
                value={risk.gemini_model}
                disabled
                style={{...settingsInputStyle, opacity: 0.6, cursor: "not-allowed"}}
              >
                <option>{risk.gemini_model} (Gemini Vertex)</option>
              </select>
            </SettingsField>
            <div style={{ gridColumn: "1 / -1" }}>
              <button type="submit" disabled={savingModels} style={{ ...settingsButtonPrimary, opacity: savingModels ? 0.5 : 1 }}>
                {savingModels ? "Saving…" : "Save model selection"}
              </button>
            </div>
          </form>
        )}
      </SettingsCard>

      <SettingsCard
        title="Strategy presets"
        subtitle="Pre-built rule sets for common screens (deep value, quality compounders, momentum). Apply or fork them in the editor above."
      >
        <Link
          href="/strategies"
          style={{ ...settingsButtonSecondary, display: "inline-block", textDecoration: "none" }}
        >
          Browse strategies →
        </Link>
      </SettingsCard>
    </div>
  );
}
