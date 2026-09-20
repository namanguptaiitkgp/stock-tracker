"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";

export interface PipelineStatus {
  running: boolean;
  active: {
    source: string;
    task_id: string | null;
    started_at: string | null;
  } | null;
  news_available: boolean;
  brief_refreshed_at: string | null;
}

const POLL_INTERVAL_IDLE = 30_000;
const POLL_INTERVAL_ACTIVE = 5_000;

export function usePipelineStatus() {
  const [status, setStatus] = useState<PipelineStatus>({
    running: false,
    active: null,
    news_available: false,
    brief_refreshed_at: null,
  });
  const [dispatching, setDispatching] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const fetch = useCallback(async () => {
    try {
      const data = await api.get<PipelineStatus>("/api/today/pipeline/status");
      setStatus(data);
      return data;
    } catch {
      return null;
    }
  }, []);

  useEffect(() => {
    fetch();

    function schedule() {
      timerRef.current = setTimeout(async () => {
        const data = await fetch();
        const interval = data?.running ? POLL_INTERVAL_ACTIVE : POLL_INTERVAL_IDLE;
        timerRef.current = setTimeout(schedule, interval);
      }, status.running ? POLL_INTERVAL_ACTIVE : POLL_INTERVAL_IDLE);
    }
    schedule();

    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [fetch, status.running]);

  const dispatch = useCallback(
    async (mode: "full" | "refresh" | "news" | "cards") => {
      setDispatching(true);
      try {
        const endpoint =
          mode === "full"
            ? "/api/today/pipeline/run"
            : mode === "news"
              ? "/api/today/news/scan"
              : mode === "cards"
                ? "/api/today/cards/refresh"
                : "/api/today/brief/refresh";
        const res = await api.post<{ task_id: string }>(endpoint);
        setStatus((prev) => ({
          ...prev,
          running: true,
          active: {
            source:
              mode === "full" ? "morning_pipeline"
              : mode === "news" ? "news_scan"
              : mode === "cards" ? "cards_refresh"
              : "brief_refresh",
            task_id: res.task_id,
            started_at: new Date().toISOString(),
          },
        }));
        return res.task_id;
      } catch (err: unknown) {
        if (err && typeof err === "object" && "status" in err && (err as { status: number }).status === 409) {
          await fetch();
        }
        throw err;
      } finally {
        setDispatching(false);
      }
    },
    [fetch],
  );

  return { ...status, dispatching, dispatch, refetch: fetch };
}
