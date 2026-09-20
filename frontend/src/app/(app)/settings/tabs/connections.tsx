"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useToast } from "@/lib/use-toast";
import SettingsCard from "@/components/settings/SettingsCard";
import SettingsField, {
  settingsButtonPrimary, settingsInputStyle,
} from "@/components/settings/SettingsField";
import AiInfraSection from "./ai-infra";

interface ApiKeys {
  kite_api_key: string | null;
  kite_api_secret: string | null;
  kite_connected: boolean;
  gemini_api_key: string | null;
  gemini_vertex_ai: boolean;
  anthropic_api_key: string | null;
}

function maskKey(masked: string | null): string {
  if (!masked) return "";
  // Server returns first-4 + **** + last-4 (legacy). Industry convention is
  // last-4 only — keep the suffix as a fingerprint, drop the prefix entirely
  // so the secret can't be partially recovered from a screenshot.
  const trimmed = masked.trim();
  const m = trimmed.match(/(\*{2,})([A-Za-z0-9]{2,8})$/);
  if (m) return `••••${m[2]}`;
  // Fall back: if the server returns a fully-revealed string for some reason
  // (which it shouldn't), mask it client-side to last-4 anyway.
  if (trimmed.length > 8) return `••••${trimmed.slice(-4)}`;
  return "••••";
}

export default function ConnectionsTab() {
  const [keys, setKeys] = useState<ApiKeys | null>(null);
  const [kiteKey, setKiteKey] = useState("");
  const [kiteSecret, setKiteSecret] = useState("");
  const [geminiKey, setGeminiKey] = useState("");
  const [anthropicKey, setAnthropicKey] = useState("");
  const { toast } = useToast();

  async function reload() {
    try {
      const k = await api.get<ApiKeys>("/api/settings/api-keys");
      setKeys(k);
    } catch { /* ignore */ }
  }

  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { reload(); }, []);

  async function saveKite(e: React.FormEvent) {
    e.preventDefault();
    try {
      await api.put("/api/settings/kite", { kite_api_key: kiteKey, kite_api_secret: kiteSecret });
      setKiteKey(""); setKiteSecret("");
      await reload();
      toast({ kind: "ok", text: "Kite API keys saved" });
    } catch (err) {
      toast({ kind: "error", text: err instanceof Error ? err.message : "Save failed" });
    }
  }

  async function saveGemini(e: React.FormEvent) {
    e.preventDefault();
    try {
      await api.put("/api/settings/gemini", { gemini_api_key: geminiKey });
      setGeminiKey("");
      await reload();
      toast({ kind: "ok", text: "Gemini API key saved" });
    } catch (err) {
      toast({ kind: "error", text: err instanceof Error ? err.message : "Save failed" });
    }
  }

  async function saveAnthropic(e: React.FormEvent) {
    e.preventDefault();
    try {
      await api.put("/api/settings/anthropic", { anthropic_api_key: anthropicKey });
      setAnthropicKey("");
      await reload();
      toast({ kind: "ok", text: "Anthropic API key saved" });
    } catch (err) {
      toast({ kind: "error", text: err instanceof Error ? err.message : "Save failed" });
    }
  }

  async function connectKite() {
    try {
      const data = await api.get<{ login_url: string }>("/api/auth/login");
      window.location.href = data.login_url;
    } catch {
      toast({ kind: "error", text: "Set Kite API keys first" });
    }
  }

  // Status pill copy
  const kiteStatus = !keys?.kite_api_key
    ? { kind: "warn" as const, label: "Not configured" }
    : keys.kite_connected
      ? { kind: "ok" as const, label: "Connected" }
      : { kind: "warn" as const, label: "Token expired" };

  const geminiStatus = keys?.gemini_vertex_ai
    ? { kind: "ok" as const, label: "Vertex AI" }
    : keys?.gemini_api_key
      ? { kind: "ok" as const, label: "Configured" }
      : { kind: "warn" as const, label: "Not configured" };

  const anthropicStatus = keys?.anthropic_api_key
    ? { kind: "ok" as const, label: "Configured" }
    : { kind: "warn" as const, label: "Not configured" };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <SettingsCard
        title="Zerodha Kite Connect"
        subtitle={<>Get your API key from <a href="https://developers.kite.trade" target="_blank" rel="noopener noreferrer" style={{ color: "var(--system-blue)" }}>developers.kite.trade</a>. Required for live quotes, holdings, and order placement.</> as unknown as string}
        status={kiteStatus}
        actions={keys?.kite_api_key && !keys.kite_connected ? (
          <button onClick={connectKite} style={{ ...settingsButtonPrimary, background: "var(--buy)" }}>
            Connect to Kite
          </button>
        ) : null}
      >
        {keys?.kite_api_key && (
          <div style={{
            marginBottom: 12, padding: "10px 12px", borderRadius: 8,
            background: "var(--bg-secondary)", border: "1px solid var(--separator-light)",
            fontSize: 12, color: "var(--label-tertiary)", fontFamily: "var(--font-mono)",
          }}>
            <div>API key: {maskKey(keys.kite_api_key)}</div>
            <div>API secret: {maskKey(keys.kite_api_secret)}</div>
          </div>
        )}
        <form onSubmit={saveKite} style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <SettingsField label="API key">
            <input
              type="text"
              value={kiteKey}
              onChange={(e) => setKiteKey(e.target.value)}
              placeholder={keys?.kite_api_key ? "Enter new key to update" : "Enter API key"}
              style={settingsInputStyle}
            />
          </SettingsField>
          <SettingsField label="API secret">
            <input
              type="password"
              value={kiteSecret}
              onChange={(e) => setKiteSecret(e.target.value)}
              placeholder={keys?.kite_api_secret ? "Enter new secret to update" : "Enter API secret"}
              style={settingsInputStyle}
            />
          </SettingsField>
          <div>
            <button
              type="submit"
              disabled={!kiteKey || !kiteSecret}
              style={{ ...settingsButtonPrimary, opacity: (!kiteKey || !kiteSecret) ? 0.4 : 1 }}
            >
              Save keys
            </button>
          </div>
        </form>
      </SettingsCard>

      <SettingsCard
        title="Google Gemini API"
        subtitle="Legacy — credentials have moved to AI Infra below. This key is kept for backward compatibility."
        status={geminiStatus}
      >
        {keys?.gemini_api_key && (
          <div style={{
            marginBottom: 12, padding: "10px 12px", borderRadius: 8,
            background: "var(--bg-secondary)", border: "1px solid var(--separator-light)",
            fontSize: 12, color: "var(--label-tertiary)", fontFamily: "var(--font-mono)",
          }}>
            API key: {maskKey(keys.gemini_api_key)}
          </div>
        )}
        <form onSubmit={saveGemini} style={{ display: "flex", gap: 8 }}>
          <input
            type="password"
            value={geminiKey}
            onChange={(e) => setGeminiKey(e.target.value)}
            placeholder={keys?.gemini_api_key ? "Enter new key to update" : "Enter Gemini API key"}
            style={{ ...settingsInputStyle, flex: 1 }}
          />
          <button
            type="submit"
            disabled={!geminiKey}
            style={{ ...settingsButtonPrimary, opacity: !geminiKey ? 0.4 : 1 }}
          >
            Save
          </button>
        </form>
      </SettingsCard>

      <SettingsCard
        title="Anthropic Claude API"
        subtitle={<>Get your key from <a href="https://console.anthropic.com/settings/keys" target="_blank" rel="noopener noreferrer" style={{ color: "var(--system-blue)" }}>Anthropic Console</a>. Used for deep stock analysis (Opus, selectively).</> as unknown as string}
        status={anthropicStatus}
      >
        {keys?.anthropic_api_key && (
          <div style={{
            marginBottom: 12, padding: "10px 12px", borderRadius: 8,
            background: "var(--bg-secondary)", border: "1px solid var(--separator-light)",
            fontSize: 12, color: "var(--label-tertiary)", fontFamily: "var(--font-mono)",
          }}>
            API key: {maskKey(keys.anthropic_api_key)}
          </div>
        )}
        <form onSubmit={saveAnthropic} style={{ display: "flex", gap: 8 }}>
          <input
            type="password"
            value={anthropicKey}
            onChange={(e) => setAnthropicKey(e.target.value)}
            placeholder={keys?.anthropic_api_key ? "Enter new key to update" : "Enter Anthropic API key"}
            style={{ ...settingsInputStyle, flex: 1 }}
          />
          <button
            type="submit"
            disabled={!anthropicKey}
            style={{ ...settingsButtonPrimary, opacity: !anthropicKey ? 0.4 : 1 }}
          >
            Save
          </button>
        </form>
      </SettingsCard>

      <AiInfraSection />
    </div>
  );
}
