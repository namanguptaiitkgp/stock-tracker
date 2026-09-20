"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import SettingsTabBar from "@/components/settings/SettingsTabBar";
import { ToastOutlet, ToastProvider } from "@/lib/use-toast";
import ProfileTab from "./tabs/profile";
import ConnectionsTab from "./tabs/connections";
import AppearanceTab from "./tabs/appearance";
import TradingRiskTab from "./tabs/trading-risk";
import AiAnalysisTab from "./tabs/ai-analysis";
import HoldingsTab from "./tabs/holdings";
import PipelinesDataTab from "./tabs/pipelines-data";
import ArchitectureTab from "./tabs/architecture";
import AboutTab from "./tabs/about";

const TABS = [
  { id: "profile",      label: "Profile" },
  { id: "connections",  label: "Connections" },
  { id: "appearance",   label: "Appearance" },
  { id: "trading-risk", label: "Trading & Risk" },
  { id: "ai-analysis",  label: "AI Analysis" },
  { id: "holdings",     label: "Holdings" },
  { id: "pipelines",    label: "Pipelines & Data" },
  { id: "architecture", label: "Architecture" },
  { id: "about",        label: "About" },
] as const;

type TabId = (typeof TABS)[number]["id"];

const DEFAULT_TAB: TabId = "connections";

export default function SettingsPage() {
  return (
    <ToastProvider>
      <Suspense fallback={null}>
        <SettingsContent />
      </Suspense>
    </ToastProvider>
  );
}

function SettingsContent() {
  const router = useRouter();
  const params = useSearchParams();
  const initial = (params.get("tab") as TabId) || DEFAULT_TAB;
  const [tab, setTab] = useState<TabId>(
    TABS.find((t) => t.id === initial) ? initial : DEFAULT_TAB,
  );

  useEffect(() => {
    const fromUrl = params.get("tab") as TabId | null;
    if (fromUrl && fromUrl !== tab && TABS.find((t) => t.id === fromUrl)) {
      setTab(fromUrl);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params]);

  const onChange = useCallback((id: string) => {
    const next = TABS.find((t) => t.id === id) ? (id as TabId) : DEFAULT_TAB;
    setTab(next);
    const sp = new URLSearchParams(Array.from(params.entries()));
    sp.set("tab", next);
    router.replace(`/settings?${sp.toString()}`, { scroll: false });
  }, [params, router]);

  return (
    <div style={{ maxWidth: 880, margin: "0 auto", padding: "0 16px 48px" }}>
      <header style={{ padding: "8px 0 4px" }}>
        <h1
          style={{
            margin: 0,
            fontFamily: "var(--font-serif)",
            fontSize: 30,
            fontWeight: 600,
            letterSpacing: "-0.02em",
            color: "var(--label-primary)",
          }}
        >
          Settings
        </h1>
        <p style={{ margin: "4px 0 0", fontSize: 13, color: "var(--label-tertiary)" }}>
          Manage your account, integrations, and preferences.
        </p>
      </header>

      <SettingsTabBar
        tabs={TABS as unknown as { id: string; label: string }[]}
        activeId={tab}
        onChange={onChange}
      />

      <ToastOutlet />

      {tab === "profile"      && <ProfileTab />}
      {tab === "connections"  && <ConnectionsTab />}
      {tab === "appearance"   && <AppearanceTab />}
      {tab === "trading-risk" && <TradingRiskTab />}
      {tab === "ai-analysis"  && <AiAnalysisTab />}
      {tab === "holdings"     && <HoldingsTab />}
      {tab === "pipelines"    && <PipelinesDataTab />}
      {tab === "architecture" && <ArchitectureTab />}
      {tab === "about"        && <AboutTab />}
    </div>
  );
}
