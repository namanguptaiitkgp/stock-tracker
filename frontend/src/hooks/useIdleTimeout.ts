"use client";

import { useCallback, useEffect, useRef, useState } from "react";

interface Options {
  timeoutMs: number;
  warningMs: number;
  onTimeout: () => void;
}

const ACTIVITY_EVENTS = [
  "mousedown",
  "mousemove",
  "keydown",
  "scroll",
  "touchstart",
  "click",
] as const;

export function useIdleTimeout({ timeoutMs, warningMs, onTimeout }: Options) {
  const [showWarning, setShowWarning] = useState(false);
  const [secondsLeft, setSecondsLeft] = useState(0);

  const timeoutRef = useRef<NodeJS.Timeout | null>(null);
  const warningRef = useRef<NodeJS.Timeout | null>(null);
  const countdownRef = useRef<NodeJS.Timeout | null>(null);

  const reset = useCallback(() => {
    if (timeoutRef.current) clearTimeout(timeoutRef.current);
    if (warningRef.current) clearTimeout(warningRef.current);
    if (countdownRef.current) clearInterval(countdownRef.current);

    setShowWarning(false);

    warningRef.current = setTimeout(() => {
      setShowWarning(true);
      setSecondsLeft(Math.ceil((timeoutMs - warningMs) / 1000));

      countdownRef.current = setInterval(() => {
        setSecondsLeft((s) => Math.max(0, s - 1));
      }, 1000);
    }, warningMs);

    timeoutRef.current = setTimeout(() => {
      if (countdownRef.current) clearInterval(countdownRef.current);
      onTimeout();
    }, timeoutMs);
  }, [timeoutMs, warningMs, onTimeout]);

  useEffect(() => {
    reset();

    const handler = () => reset();
    ACTIVITY_EVENTS.forEach((e) => window.addEventListener(e, handler));

    return () => {
      ACTIVITY_EVENTS.forEach((e) => window.removeEventListener(e, handler));
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
      if (warningRef.current) clearTimeout(warningRef.current);
      if (countdownRef.current) clearInterval(countdownRef.current);
    };
  }, [reset]);

  return { showWarning, secondsLeft, stayActive: reset };
}
