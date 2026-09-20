"use client";

import SettingsCard from "@/components/settings/SettingsCard";

export default function AboutTab() {
  const commit = process.env.NEXT_PUBLIC_COMMIT_SHA || "dev";
  const shortCommit = commit.slice(0, 7);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <SettingsCard
        title="Session security"
        subtitle="The session ends automatically after a period of inactivity. A 30-second warning appears before logout."
      >
        <div style={infoRow}>
          <span style={infoLabel}>Auto-logout</span>
          <span style={infoValue}>15 minutes idle</span>
        </div>
        <div style={infoRow}>
          <span style={infoLabel}>Privacy mode</span>
          <span style={infoValue}>Cmd / Ctrl + 1</span>
        </div>
      </SettingsCard>

      <SettingsCard
        title="Build"
        subtitle="Version info for support and debugging."
      >
        <div style={infoRow}>
          <span style={infoLabel}>Commit</span>
          <span style={{ ...infoValue, fontFamily: "var(--font-mono)" }}>{shortCommit}</span>
        </div>
        <div style={infoRow}>
          <span style={infoLabel}>Repository</span>
          <a
            href="https://github.com/namanguptaiitkgp/stock-tracker"
            target="_blank"
            rel="noopener noreferrer"
            style={{ ...infoValue, color: "var(--system-blue)", textDecoration: "none" }}
          >
            github.com/namanguptaiitkgp/stock-tracker ↗
          </a>
        </div>
      </SettingsCard>

      <SettingsCard
        title="What this is"
        subtitle="Personal algo-trading platform for Indian equities."
      >
        <p style={{ margin: 0, fontSize: 13, lineHeight: 1.55, color: "var(--label-secondary)" }}>
          Zerodha Kite Connect for market data &amp; execution. Gemini for bulk screening &amp; news sentiment.
          Claude Opus for deep-dive analysis on a curated shortlist. Risk limits, kill switch, and an
          Opus daily cost cap keep both trading and LLM spend bounded.
        </p>
      </SettingsCard>
    </div>
  );
}

const infoRow: React.CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "center",
  padding: "10px 0",
  borderBottom: "1px solid var(--separator-light)",
};

const infoLabel: React.CSSProperties = {
  fontSize: 12,
  color: "var(--label-tertiary)",
};

const infoValue: React.CSSProperties = {
  fontSize: 13,
  fontWeight: 500,
  color: "var(--label-primary)",
};
