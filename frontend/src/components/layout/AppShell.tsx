"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { useTheme } from "@/lib/theme";
import { useIdleTimeout } from "@/hooks/useIdleTimeout";
import { api } from "@/lib/api";
import StockSearch from "@/components/common/StockSearch";
import StockDetailPanel from "@/components/common/StockDetailPanel";
import IndicesStrip from "@/components/common/IndicesStrip";
import FinanceWidget from "@/components/common/FinanceWidget";
import PanelErrorBoundary from "@/components/common/PanelErrorBoundary";
import AvatarMenu from "@/components/ui/AvatarMenu";
import MobileBanner from "@/components/ui/MobileBanner";
import { onOpenStockDetail } from "@/lib/stock-detail";
import { PageActionsProvider, usePageActionsRender } from "@/lib/page-actions";
import { togglePrivacy, usePrivacyMode } from "@/lib/privacy-mode";

// Navigation is mode-aware — see ModeSidebar for the actual items.

const IDLE_TIMEOUT_MS = 15 * 60 * 1000;
const WARNING_AT_MS = 14.5 * 60 * 1000;

interface Appearance {
  wallpaper_url?: string;
  wallpaper_upload?: string;
  wallpaper_preset?: string;
  wallpaper_opacity?: number;
}

const GRADIENT_PRESETS: Record<string, string> = {
  none: "",
  midnight: "linear-gradient(135deg, #0f172a 0%, #1e293b 50%, #0f172a 100%)",
  aurora: "linear-gradient(135deg, #1e1b4b 0%, #312e81 25%, #4c1d95 50%, #1e1b4b 100%)",
  sunset: "linear-gradient(135deg, #1a1a2e 0%, #16213e 40%, #3a1c47 70%, #1a1a2e 100%)",
  forest: "linear-gradient(135deg, #0a2518 0%, #0f3d2e 50%, #0a2518 100%)",
  ocean: "linear-gradient(135deg, #0a1929 0%, #123456 40%, #1e3a5f 100%)",
  graphite: "linear-gradient(135deg, #1a1a1a 0%, #2d2d2d 50%, #1a1a1a 100%)",
  mesh: "radial-gradient(at 20% 30%, #1e3a8a 0%, transparent 50%), radial-gradient(at 80% 70%, #4c1d95 0%, transparent 50%), #0a0a0a",
};

function resolvePrivacyBackground(preset: string, url?: string, upload?: string): string {
  if (url && url.startsWith("data:")) return `url("${url}") center/cover no-repeat fixed`;
  if (upload) return `url("${upload}") center/cover no-repeat fixed`;
  if (url) return `url("${url}") center/cover no-repeat fixed`;
  if (preset && preset !== "none" && GRADIENT_PRESETS[preset]) {
    return GRADIENT_PRESETS[preset];
  }
  return GRADIENT_PRESETS.midnight;
}

export default function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <PageActionsProvider>
      <AppShellInner>{children}</AppShellInner>
    </PageActionsProvider>
  );
}

function AppShellInner({ children }: { children: React.ReactNode }) {
  const { user, logout, isLoading } = useAuth();
  const { theme, toggle: toggleTheme } = useTheme();
  const pathname = usePathname();
  const router = useRouter();
  const [searchResult, setSearchResult] = useState<{ tradingsymbol: string; name: string | null; exchange: string } | null>(null);
  const [detailPanel, setDetailPanel] = useState<{ symbol: string; exchange: string; initialTab?: string } | null>(null);

  // Allow any component to open the detail panel via openStockDetail()
  useEffect(() => {
    return onOpenStockDetail((symbol, exchange, initialTab) => {
      setDetailPanel({ symbol, exchange, initialTab });
    });
  }, []);
  const [appearance, setAppearance] = useState<Appearance | null>(null);
  const [privacyMode, setPrivacyMode] = useState(false);
  const maskMode = usePrivacyMode();
  const [kiteStatus, setKiteStatus] = useState<{ authenticated: boolean; has_keys: boolean } | null>(null);

  const handleTimeout = useCallback(() => { logout(); }, [logout]);

  const { showWarning, secondsLeft, stayActive } = useIdleTimeout({
    timeoutMs: IDLE_TIMEOUT_MS,
    warningMs: WARNING_AT_MS,
    onTimeout: handleTimeout,
  });

  // Pending review alert counts for tab badges (refreshed every 60s)
  const [alertCounts, setAlertCounts] = useState<{ watchlist: number; holding: number; both: number }>({
    watchlist: 0, holding: 0, both: 0,
  });
  useEffect(() => {
    if (!user) return;
    let cancelled = false;
    async function load() {
      try {
        const data = await api.get<{ pending: number; by_source: { watchlist: number; holding: number; both: number } }>("/api/review-alerts/count");
        if (!cancelled) setAlertCounts(data.by_source);
      } catch { /* ignore */ }
    }
    load();
    const id = setInterval(load, 60_000);
    return () => { cancelled = true; clearInterval(id); };
  }, [user]);

  useEffect(() => {
    if (!user) return;
    api.get<Appearance>("/api/settings/appearance").then(setAppearance).catch(() => {});
    api.get<{ authenticated: boolean; has_keys: boolean }>("/api/auth/status")
      .then(setKiteStatus).catch(() => {});
  }, [user]);

  // Keyboard shortcut: Cmd/Ctrl + 1 = toggle privacy mode
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === "1") {
        e.preventDefault();
        setPrivacyMode((p) => !p);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-gray-500">Loading...</div>
      </div>
    );
  }

  if (!user) return null;

  const privacyBg = resolvePrivacyBackground(
    appearance?.wallpaper_preset || "midnight",
    appearance?.wallpaper_url,
    appearance?.wallpaper_upload,
  );

  const isDark = theme === "dark";

  // Top-level navigation tabs
  const TABS: Array<{ label: string; href: string; match: (p: string) => boolean }> = [
    { label: "Today", href: "/dashboard", match: (p) => p === "/dashboard" || p === "/" },
    { label: "News", href: "/news", match: (p) => p === "/news" || p.startsWith("/news/") },
    { label: "Researching", href: "/watchlist", match: (p) => p === "/watchlist" || p.startsWith("/watchlist/") },
    { label: "Awaiting Correction", href: "/awaiting-correction", match: (p) => p === "/awaiting-correction" || p.startsWith("/awaiting-correction/") },
    { label: "Smart Money", href: "/smart-money", match: (p) => p === "/smart-money" || p.startsWith("/smart-money/") },
    { label: "F&O", href: "/fno", match: (p) => p === "/fno" || p.startsWith("/fno/") },
  ];

  return (
    <div className="relative min-h-screen">
      <div className="flex min-h-screen">
        {/* Page scroll lives on <body> so the sticky header + tab nav
            below pin to the viewport. (Earlier this column had
            overflow:hidden and <main> had overflow-auto, which created
            an inner scroll context that sticky couldn't see.) */}
        <div className="flex-1 flex flex-col" style={{ minWidth: 0, maxWidth: "100vw" }}>
          {/* Top header with search */}
          <header className={`sticky top-0 z-20 px-4 md:px-6 py-3 flex items-center gap-2 md:gap-4 border-b ${
            isDark ? "bg-gray-900/95 border-gray-800" : "bg-white/95 border-gray-200"
          } backdrop-blur-sm`} style={{ minWidth: 0 }}>
            <div style={{ flexShrink: 0 }}>
              <StockSearch
                placeholder="Search stocks..."
                className="w-40 sm:w-64"
                onSelect={(stock) => {
                  setDetailPanel({ symbol: stock.tradingsymbol, exchange: stock.exchange });
                }}
              />
            </div>
            <div className="hidden md:block" style={{ flex: "1 1 0", minWidth: 0, overflow: "hidden" }}>
              <IndicesStrip />
            </div>
            <div className="md:hidden" style={{ flex: 1 }} />
            <button
              onClick={() => togglePrivacy()}
              title={maskMode ? "Unmask numbers" : "Mask portfolio numbers"}
              className={`shrink-0 w-9 h-9 rounded-full flex items-center justify-center border transition-colors ${
                maskMode
                  ? isDark
                    ? "bg-purple-900/40 border-purple-700 text-purple-300"
                    : "bg-purple-100 border-purple-300 text-purple-700"
                  : isDark
                  ? "bg-gray-800/70 border-gray-700 text-gray-400 hover:text-white"
                  : "bg-white border-gray-200 text-gray-500 hover:text-gray-900"
              }`}
              aria-label={maskMode ? "Disable mask" : "Enable mask"}
            >
              <svg xmlns="http://www.w3.org/2000/svg" className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                {maskMode ? (
                  <path strokeLinecap="round" strokeLinejoin="round" d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21" />
                ) : (
                  <>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                    <path strokeLinecap="round" strokeLinejoin="round" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                  </>
                )}
              </svg>
            </button>
            {/* Theme toggle */}
            <button
              onClick={toggleTheme}
              title={isDark ? "Light mode" : "Dark mode"}
              className={`shrink-0 w-9 h-9 rounded-full flex items-center justify-center border transition-colors ${
                isDark ? "bg-gray-800/70 border-gray-700 text-gray-400 hover:text-white" : "bg-white border-gray-200 text-gray-500 hover:text-gray-900"
              }`}
            >
              {isDark ? (
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z" />
                </svg>
              ) : (
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" />
                </svg>
              )}
            </button>
            {/* User menu — inline at >=md, AvatarMenu at <md */}
            <div className={`hidden md:flex shrink-0 items-center gap-2 pl-3 border-l ${isDark ? "border-gray-800" : "border-gray-200"}`}>
              <div className="text-xs">
                <div className={`font-medium ${isDark ? "text-gray-200" : "text-gray-700"}`}>{user.username}</div>
                {kiteStatus?.authenticated ? (
                  <div className="flex items-center gap-1 text-[10px] text-green-500">
                    <span className="inline-flex rounded-full h-1 w-1 bg-green-500"></span>
                    Kite connected
                  </div>
                ) : kiteStatus && !kiteStatus.authenticated && kiteStatus.has_keys ? (
                  <Link href="/settings" className="text-[10px] text-red-500 hover:text-red-600">
                    Reconnect Kite →
                  </Link>
                ) : null}
              </div>
              <button
                onClick={logout}
                title="Sign out"
                className={`text-xs px-2 py-1 rounded transition-colors ${
                  isDark ? "text-gray-500 hover:text-red-400 hover:bg-gray-800" : "text-gray-400 hover:text-red-500 hover:bg-gray-100"
                }`}
              >
                ⏻
              </button>
            </div>
            <div className="md:hidden shrink-0">
              <AvatarMenu username={user.username} kiteStatus={kiteStatus} onLogout={logout} />
            </div>
          </header>
          {/* Mobile-only Reconnect-Kite banner — the inline link inside the
              header is hidden at <md, so surface it here so the analyst sees
              the prompt without scrolling or opening the avatar menu. */}
          {kiteStatus && !kiteStatus.authenticated && kiteStatus.has_keys && (
            <MobileBanner variant="error">
              <Link href="/settings" style={{ color: "inherit", textDecoration: "none", fontWeight: 600 }}>
                Reconnect Kite to load live prices →
              </Link>
            </MobileBanner>
          )}

          {/* Top tab bar — primary navigation */}
          <nav
            className={`sticky z-10 px-6 border-b overflow-x-auto ${
              isDark ? "bg-gray-900/95 border-gray-800" : "bg-white/95 border-gray-200"
            } backdrop-blur-sm`}
            style={{ top: 56 }}
          >
            <div className="flex items-center gap-1">
              {TABS.map((t) => {
                const active = t.match(pathname);
                let count = 0;
                if (t.label === "Researching") count = (alertCounts.watchlist || 0) + (alertCounts.both || 0);
                if (t.label === "Today") count = (alertCounts.holding || 0) + (alertCounts.both || 0);
                return (
                  <Link
                    key={t.label}
                    href={t.href}
                    style={{
                      padding: "12px 18px",
                      fontSize: 13.5,
                      fontWeight: active ? 600 : 500,
                      color: active ? (isDark ? "#FFFFFF" : "#111827") : isDark ? "#9CA3AF" : "#6B7280",
                      borderBottom: active ? `2px solid ${isDark ? "#FFFFFF" : "#111827"}` : "2px solid transparent",
                      marginBottom: -1,
                      whiteSpace: "nowrap",
                      textDecoration: "none",
                      transition: "color .15s",
                      display: "inline-flex",
                      alignItems: "center",
                      gap: 6,
                    }}
                  >
                    {t.label}
                    {count > 0 && (
                      <span style={{
                        display: "inline-flex", alignItems: "center", justifyContent: "center",
                        minWidth: 18, height: 18, padding: "0 6px", borderRadius: 99,
                        background: "#D72424", color: "white",
                        fontSize: 10.5, fontWeight: 700, fontFamily: "var(--font-mono)",
                      }}>{count}</span>
                    )}
                  </Link>
                );
              })}
              <div className="flex-1" />
              {/* Page-supplied actions (e.g. Refresh + MarketClock for Today) */}
              <PageActionsSlot />
              <Link href="/orders" className={`text-xs px-3 py-2 ${isDark ? "text-gray-400 hover:text-white" : "text-gray-500 hover:text-gray-900"}`}>Orders</Link>
              <Link href="/strategies" className={`text-xs px-3 py-2 ${isDark ? "text-gray-400 hover:text-white" : "text-gray-500 hover:text-gray-900"}`}>Strategies</Link>
              <Link href="/paper-trading" className={`text-xs px-3 py-2 ${isDark ? "text-gray-400 hover:text-white" : "text-gray-500 hover:text-gray-900"}`}>Paper Trading</Link>
              <Link href="/settings" className={`text-xs px-3 py-2 ${isDark ? "text-gray-400 hover:text-white" : "text-gray-500 hover:text-gray-900"}`}>Settings</Link>
            </div>
          </nav>

          <main className="flex-1 p-4 md:p-6" style={{ paddingBottom: 96 }}>{children}</main>
        </div>
      </div>

      {/* Privacy Curtain buttons removed — the mask-numbers toggle in the
          header covers the portfolio-hide use case. Full-screen curtain
          is still available via Cmd/Ctrl+1 keyboard shortcut. */}

      {/* Stock Detail Slide-out Panel — wrapped so a render error
          doesn't crash the whole page. */}
      {detailPanel && (
        <PanelErrorBoundary
          key={`${detailPanel.symbol}:${detailPanel.exchange}`}
          onClose={() => setDetailPanel(null)}
        >
          <StockDetailPanel
            symbol={detailPanel.symbol}
            exchange={detailPanel.exchange}
            initialTab={detailPanel.initialTab}
            onClose={() => setDetailPanel(null)}
          />
        </PanelErrorBoundary>
      )}

      {/* Floating Finance lookup widget — bottom-right, all pages */}
      <FinanceWidget />

      {/* Privacy Mode Overlay — wallpaper ONLY shows here, dismiss via Cmd/Ctrl+1 */}
      {privacyMode && (
        <div
          className="fixed inset-0 z-[60]"
          style={{ background: privacyBg, backgroundSize: "cover" }}
        />
      )}

      {/* Idle warning modal */}
      {showWarning && (
        <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center">
          <div className={`border rounded-lg p-6 max-w-sm w-full mx-4 shadow-2xl ${
            isDark ? "bg-gray-900 border-yellow-700" : "bg-white border-yellow-400"
          }`}>
            <div className="flex items-center gap-3 mb-4">
              <div className="w-10 h-10 rounded-full bg-yellow-100 dark:bg-yellow-900/50 flex items-center justify-center text-yellow-600 dark:text-yellow-400 text-xl font-bold">
                !
              </div>
              <div>
                <h2 className="font-semibold">Session Timeout</h2>
                <p className="text-xs text-gray-500">You&apos;ll be logged out soon</p>
              </div>
            </div>
            <p className="text-sm text-gray-600 dark:text-gray-300 mb-4">
              You&apos;ve been inactive. Logging out in{" "}
              <span className="font-mono font-bold text-yellow-600 dark:text-yellow-400">{secondsLeft}s</span>.
            </p>
            <div className="flex gap-2">
              <button
                onClick={stayActive}
                className="flex-1 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm rounded-md transition-colors"
              >
                Stay Signed In
              </button>
              <button
                onClick={logout}
                className={`px-4 py-2 text-sm rounded-md transition-colors ${
                  isDark ? "bg-gray-800 hover:bg-gray-700 text-gray-300" : "bg-gray-100 hover:bg-gray-200 text-gray-700"
                }`}
              >
                Sign Out
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function PageActionsSlot() {
  const node = usePageActionsRender();
  if (!node) return null;
  return <div className="flex items-center gap-2">{node}</div>;
}

export { GRADIENT_PRESETS };
