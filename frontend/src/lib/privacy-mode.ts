"use client";

import { useEffect, useState } from "react";

const STORAGE_KEY = "algo_trader_privacy_mode";
const EVENT = "algo-trader:privacy-mode";

function readStorage(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return window.localStorage.getItem(STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

export function isPrivacyOn(): boolean {
  return readStorage();
}

export function setPrivacy(on: boolean): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, on ? "1" : "0");
  } catch {
    // ignore — older browsers or quota full
  }
  window.dispatchEvent(new CustomEvent(EVENT, { detail: on }));
}

export function togglePrivacy(): boolean {
  const next = !isPrivacyOn();
  setPrivacy(next);
  return next;
}

/**
 * React hook returning the current privacy-mode state, live-updating
 * across tabs and components.
 */
export function usePrivacyMode(): boolean {
  const [on, setOn] = useState<boolean>(false);

  useEffect(() => {
    setOn(readStorage());
    const handler = (e: Event) => {
      const ce = e as CustomEvent<boolean>;
      setOn(Boolean(ce.detail));
    };
    const storageHandler = (e: StorageEvent) => {
      if (e.key === STORAGE_KEY) setOn(e.newValue === "1");
    };
    window.addEventListener(EVENT, handler);
    window.addEventListener("storage", storageHandler);
    return () => {
      window.removeEventListener(EVENT, handler);
      window.removeEventListener("storage", storageHandler);
    };
  }, []);

  return on;
}

/** Returns the value unchanged, or a masked placeholder when privacy is on. */
export function mask<T extends string | number>(value: T, on: boolean, replacement: string = "••••"): string {
  if (!on) return String(value);
  return replacement;
}
