"use client";

import { createContext, createElement, ReactNode, useCallback, useContext, useEffect, useRef, useState } from "react";

/**
 * One toast at a time. Mount `<ToastProvider>` once at the page root,
 * then call `useToast().toast({ kind, text })` from any descendant.
 *
 * The 3-second auto-dismiss is built-in. Manual dismiss via `clear()`.
 * Replaces the duplicated `setMsg` patterns scattered across Settings
 * subsections.
 */

export type ToastKind = "ok" | "error" | "warn" | "info";
interface Toast {
  kind: ToastKind;
  text: string;
}

interface Ctx {
  active: Toast | null;
  toast: (t: Toast) => void;
  clear: () => void;
}

const ToastContext = createContext<Ctx | null>(null);

export function useToast(): Ctx {
  const ctx = useContext(ToastContext);
  if (!ctx) {
    // Non-throwing fallback so unit tests don't blow up — toast() becomes a no-op.
    return {
      active: null,
      toast: () => {},
      clear: () => {},
    };
  }
  return ctx;
}

export function ToastProvider({ children, autoDismissMs = 3000 }: { children: ReactNode; autoDismissMs?: number }) {
  const [active, setActive] = useState<Toast | null>(null);
  const timerRef = useRef<number | null>(null);

  const clear = useCallback(() => {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    setActive(null);
  }, []);

  const toast = useCallback((t: Toast) => {
    if (timerRef.current !== null) window.clearTimeout(timerRef.current);
    setActive(t);
    timerRef.current = window.setTimeout(() => {
      setActive(null);
      timerRef.current = null;
    }, autoDismissMs);
  }, [autoDismissMs]);

  useEffect(() => () => {
    if (timerRef.current !== null) window.clearTimeout(timerRef.current);
  }, []);

  // eslint-disable-next-line react-hooks/refs
  return createElement(ToastContext.Provider, { value: { active, toast, clear } }, children);
}

/**
 * Render this where you want the toast to appear. The component reads
 * `current` from context and renders nothing if no toast is active.
 */
export function ToastOutlet() {
  const { active, clear } = useToast();
  if (!active) return null;
  const isOk = active.kind === "ok";
  const isError = active.kind === "error";
  const isWarn = active.kind === "warn";
  const bg = isOk ? "var(--fill-green, rgba(48,209,88,0.1))"
    : isError ? "var(--fill-red, rgba(255,59,48,0.08))"
    : isWarn ? "var(--fill-orange, rgba(255,149,0,0.1))"
    : "var(--fill-blue, rgba(0,122,255,0.08))";
  const fg = isOk ? "var(--system-green, #248A3D)"
    : isError ? "var(--system-red, #D70015)"
    : isWarn ? "var(--system-orange, #C77800)"
    : "var(--system-blue, #007AFF)";
  const border = isOk ? "rgba(52,199,89,0.25)"
    : isError ? "rgba(255,59,48,0.2)"
    : isWarn ? "rgba(255,149,0,0.25)"
    : "rgba(0,122,255,0.2)";

  return createElement(
    "div",
    {
      role: "alert",
      onClick: clear,
      style: {
        position: "sticky",
        top: 12,
        marginBottom: 12,
        padding: "10px 14px",
        borderRadius: 10,
        background: bg,
        color: fg,
        border: `1px solid ${border}`,
        fontSize: 13,
        fontWeight: 500,
        cursor: "pointer",
        zIndex: 10,
      },
    },
    active.text,
  );
}
