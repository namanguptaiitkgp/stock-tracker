"use client";

import { useEffect, useRef } from "react";

const MODAL_OPEN_ATTR = "data-modal-open";
const MODAL_EVENT = "modal:state-change";
let openCount = 0; // module-level so nested/overlapping modals coexist

// Locks body scroll while `open` is true. Multiple consumers can be open
// simultaneously — body is only unlocked after the last one closes.
// Dispatches `modal:state-change` so global UI (e.g. the floating FAB) can
// hide itself without each modal needing to know who's listening.
export function useBodyScrollLock(open: boolean): void {
  useEffect(() => {
    if (!open) return;
    openCount += 1;
    const body = document.body;
    const prevOverflow = body.style.overflow;
    body.style.overflow = "hidden";
    body.setAttribute(MODAL_OPEN_ATTR, "true");
    window.dispatchEvent(new CustomEvent(MODAL_EVENT, { detail: { open: true } }));
    return () => {
      openCount = Math.max(0, openCount - 1);
      if (openCount === 0) {
        body.style.overflow = prevOverflow;
        body.removeAttribute(MODAL_OPEN_ATTR);
        window.dispatchEvent(new CustomEvent(MODAL_EVENT, { detail: { open: false } }));
      }
    };
  }, [open]);
}

// Returns pointer handlers that fire `onTap` only when pointerdown→pointerup
// happens with < 6 px of movement. Touch-drag (intent to scroll the modal
// content) no longer accidentally closes via the backdrop's click handler.
export function useTapNotDrag(onTap: () => void) {
  const start = useRef<{ x: number; y: number } | null>(null);
  return {
    onPointerDown(e: React.PointerEvent) {
      start.current = { x: e.clientX, y: e.clientY };
    },
    onPointerUp(e: React.PointerEvent) {
      const s = start.current;
      start.current = null;
      if (!s) return;
      const dx = Math.abs(e.clientX - s.x);
      const dy = Math.abs(e.clientY - s.y);
      if (dx < 6 && dy < 6) onTap();
    },
    onPointerCancel() {
      start.current = null;
    },
  };
}

// Subscribe to modal open/close transitions globally. Returns the
// unsubscribe function. Lightweight so non-React consumers (or imperative
// effects) can drive UI off the same signal.
export function onModalStateChange(handler: (open: boolean) => void): () => void {
  function listener(e: Event) {
    const ce = e as CustomEvent<{ open: boolean }>;
    handler(Boolean(ce.detail?.open));
  }
  window.addEventListener(MODAL_EVENT, listener);
  return () => window.removeEventListener(MODAL_EVENT, listener);
}

export function isModalOpen(): boolean {
  if (typeof document === "undefined") return false;
  return document.body.hasAttribute(MODAL_OPEN_ATTR);
}
