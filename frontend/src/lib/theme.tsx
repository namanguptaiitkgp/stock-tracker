"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api } from "./api";

type Theme = "dark" | "light";

interface ThemeContextType {
  theme: Theme;
  setTheme: (t: Theme) => void;
  toggle: () => void;
}

const ThemeContext = createContext<ThemeContextType | null>(null);

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setThemeState] = useState<Theme>("light");
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    // Load from localStorage first for instant render, then sync from server
    const stored = localStorage.getItem("algo_trader_theme") as Theme | null;
    if (stored === "light" || stored === "dark") {
      setThemeState(stored);
      applyTheme(stored);
    }
    setLoaded(true);

    const token = localStorage.getItem("algo_trader_token");
    if (token) {
      api.get<{ theme?: string }>("/api/settings/appearance")
        .then((data) => {
          const t = (data as Record<string, unknown>).theme as Theme | undefined;
          if (t === "light" || t === "dark") {
            setThemeState(t);
            applyTheme(t);
            localStorage.setItem("algo_trader_theme", t);
          }
        })
        .catch(() => {});
    }
  }, []);

  const setTheme = useCallback((t: Theme) => {
    setThemeState(t);
    applyTheme(t);
    localStorage.setItem("algo_trader_theme", t);
    api.put("/api/settings/appearance", { theme: t }).catch(() => {});
  }, []);

  const toggle = useCallback(() => {
    setTheme(theme === "dark" ? "light" : "dark");
  }, [theme, setTheme]);

  if (!loaded) return null;

  return (
    <ThemeContext.Provider value={{ theme, setTheme, toggle }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme() {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme must be inside ThemeProvider");
  return ctx;
}

function applyTheme(t: Theme) {
  const html = document.documentElement;
  if (t === "dark") {
    html.classList.add("dark");
    html.classList.remove("light");
  } else {
    html.classList.add("light");
    html.classList.remove("dark");
  }
}
