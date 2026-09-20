"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

export interface LatestDecision {
  id?: number;
  created_at?: string;
  verdict?: string;
  confidence?: number;
  reasoning?: string;
  entry_recommendation?: {
    entry_price_low: number;
    entry_price_high: number;
    stop_loss: number;
    target_price: number;
    time_horizon: string;
  } | null;
  market_sentiment?: {
    nifty_trend: string;
    sector_outlook: string;
    sentiment_summary: string;
  } | null;
  valuation_view?: string | null;
  technical_view?: string | null;
  news_sentiment_context?: string | null;
}

interface HistoryItem {
  id: number;
  created_at: string;
  symbol: string;
  verdict: string;
  confidence: number;
}

export function useLatestDecision(symbol: string) {
  const [decision, setDecision] = useState<LatestDecision | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setDecision(null);

    api
      .get<HistoryItem[]>(`/api/investment/history?symbol=${symbol}&limit=1`)
      .then((items) => {
        if (cancelled || !items || items.length === 0) return null;
        return api.get<LatestDecision>(`/api/investment/history/${items[0].id}`);
      })
      .then((full) => {
        if (!cancelled && full) setDecision(full);
      })
      .catch(() => {})
      .finally(() => { if (!cancelled) setLoading(false); });

    return () => { cancelled = true; };
  }, [symbol]);

  return { decision, loading };
}
