// Lightweight pub/sub for opening stock detail panel from any component.
// Avoids threading context through the entire component tree.

type Listener = (symbol: string, exchange: string, initialTab?: string) => void;
type Request = { symbol: string; exchange: string; initialTab?: string };

let listener: Listener | null = null;
// Replay queue: if `openStockDetail` is called before AppShell has had a
// chance to register its listener (e.g. during a route transition or a
// late-mounting layout effect), buffer the request and fire it when the
// subscriber registers. Fixes the QA report's "tapping ASHOKLEY from
// /watchlist did nothing" intermittent — the call site fired, but the
// subscriber wasn't yet mounted.
const pending: Request[] = [];

export function onOpenStockDetail(fn: Listener) {
  listener = fn;
  // Flush any buffered requests now that a subscriber exists.
  while (pending.length > 0) {
    const r = pending.shift()!;
    try {
      fn(r.symbol, r.exchange, r.initialTab);
    } catch {
      // Ignore — a single handler failure shouldn't drop the rest.
    }
  }
  return () => { listener = null; };
}

export function openStockDetail(symbol: string, exchange: string = "NSE", initialTab?: string) {
  if (listener) {
    listener(symbol, exchange, initialTab);
    return;
  }
  // Cap the queue so a misbehaving caller can't grow it unbounded.
  if (pending.length < 8) {
    pending.push({ symbol, exchange, initialTab });
  }
}
