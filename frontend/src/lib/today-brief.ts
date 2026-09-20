"use client";

import { api } from "@/lib/api";

/**
 * Tiny module-level dedup for `/api/today/brief`.
 *
 * The dashboard page and ModeSidebar both need the brief on `/dashboard`,
 * and they used to fan out two parallel requests. This memoizes the
 * in-flight promise (and a short result cache) so concurrent callers share
 * one network round-trip. After 60s the cache is stale and the next call
 * triggers a fresh fetch.
 */

interface CacheEntry<T> {
  at: number;
  data: T;
}

const CACHE_TTL_MS = 60_000;
let inflight: Promise<unknown> | null = null;
let cache: CacheEntry<unknown> | null = null;

export async function getTodayBrief<T = unknown>(force = false): Promise<T> {
  if (!force && cache && Date.now() - cache.at < CACHE_TTL_MS) {
    return cache.data as T;
  }
  if (!force && inflight) return inflight as Promise<T>;
  const p = api
    .get<T>("/api/today/brief")
    .then((data) => {
      cache = { at: Date.now(), data };
      return data;
    })
    .finally(() => {
      inflight = null;
    });
  inflight = p as Promise<unknown>;
  return p;
}

export function invalidateTodayBrief(): void {
  cache = null;
  inflight = null;
}

export async function refreshTodayBrief<T = unknown>(): Promise<T> {
  const data = await api.post<T>("/api/today/brief/refresh");
  cache = { at: Date.now(), data };
  return data;
}

export async function pollNewsTaskStatus(taskId: string): Promise<{ status: string; ready: boolean }> {
  return api.get<{ status: string; ready: boolean }>(`/api/today/brief/refresh/status/${taskId}`);
}
