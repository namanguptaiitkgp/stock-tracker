"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { onModalStateChange, isModalOpen } from "@/lib/modal-utils";

interface Quote {
  query: string;
  symbol: string;
  exchange: string;
  name: string | null;
  url: string;
  last_price: number | null;
  currency: string | null;
  change: number | null;
  change_pct: number | null;
  prev_close: number | null;
  day_range: string | null;
  year_range: string | null;
  market_cap: string | null;
  pe_ratio: string | null;
  dividend_yield: string | null;
  avg_volume: string | null;
  about: string | null;
  error?: string;
  cached?: boolean;
}

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const TOKEN_KEY = "algo_trader_token";
const STATE_KEY = "algo_trader_finance_widget_open";
const HISTORY_KEY = "algo_trader_finance_widget_history";

function authHeaders(): Record<string, string> {
  const t = typeof window !== "undefined" ? localStorage.getItem(TOKEN_KEY) : null;
  return t ? { Authorization: `Bearer ${t}` } : {};
}

function color(cp: number | null): string {
  if (cp === null) return "#6E6E73";
  if (cp > 0) return "#248A3D";
  if (cp < 0) return "#D70015";
  return "#6E6E73";
}

export default function FinanceWidget() {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [quote, setQuote] = useState<Quote | null>(null);
  const [loading, setLoading] = useState(false);
  const [history, setHistory] = useState<string[]>([]);
  // Hide the floating FAB while any modal (Market Brief, Stock Detail Panel,
  // etc.) is open — they sit above the FAB's z-index but the FAB still
  // overlays modal contents at the bottom-right corner.
  const [modalOpen, setModalOpen] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    try {
      setOpen(localStorage.getItem(STATE_KEY) === "1");
      const h = localStorage.getItem(HISTORY_KEY);
      if (h) setHistory(JSON.parse(h));
    } catch {}
    setModalOpen(isModalOpen());
    return onModalStateChange(setModalOpen);
  }, []);

  useEffect(() => {
    try {
      localStorage.setItem(STATE_KEY, open ? "1" : "0");
    } catch {}
  }, [open]);

  useEffect(() => {
    if (open) {
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [open]);

  const runSearch = useCallback(async (q: string) => {
    const raw = q.trim();
    if (!raw) return;
    setLoading(true);
    setQuote(null);
    try {
      const res = await fetch(
        `${API_URL}/api/finance/quote?q=${encodeURIComponent(raw)}`,
        { headers: authHeaders() },
      );
      const data: Quote = await res.json();
      setQuote(data);
      if (!data.error) {
        const entry = data.symbol + ":" + data.exchange;
        setHistory((h) => {
          const next = [entry, ...h.filter((x) => x !== entry)].slice(0, 6);
          try {
            localStorage.setItem(HISTORY_KEY, JSON.stringify(next));
          } catch {}
          return next;
        });
      }
    } catch (e) {
      setQuote({
        query: raw,
        symbol: raw.toUpperCase(),
        exchange: "",
        name: null,
        url: "",
        last_price: null,
        currency: null,
        change: null,
        change_pct: null,
        prev_close: null,
        day_range: null,
        year_range: null,
        market_cap: null,
        pe_ratio: null,
        dividend_yield: null,
        avg_volume: null,
        about: null,
        error: (e as Error).message,
      });
    } finally {
      setLoading(false);
    }
  }, []);

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    runSearch(query);
  }

  if (typeof window === "undefined") return null;

  if (modalOpen) return null;

  const content = (
    <>
      {!open && (
        <button
          onClick={() => setOpen(true)}
          title="Finance (Google Finance lookup)"
          style={{
            position: "fixed",
            right: 20,
            bottom: 20,
            width: 48,
            height: 48,
            borderRadius: 24,
            background: "#1D1D1F",
            color: "white",
            border: "none",
            boxShadow: "0 6px 18px rgba(0,0,0,0.18)",
            cursor: "pointer",
            zIndex: 900,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontSize: 18,
            fontWeight: 800,
          }}
        >
          $
        </button>
      )}

      {open && (
        <div
          style={{
            position: "fixed",
            right: 20,
            bottom: 20,
            width: 380,
            maxHeight: "min(560px, calc(100vh - 40px))",
            background: "white",
            borderRadius: 14,
            boxShadow: "0 12px 32px rgba(0,0,0,0.2)",
            border: "1px solid rgba(0,0,0,0.08)",
            overflow: "hidden",
            zIndex: 900,
            display: "flex",
            flexDirection: "column",
          }}
        >
          {/* Header */}
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              padding: "10px 14px",
              background: "#1D1D1F",
              color: "white",
            }}
          >
            <span style={{ fontSize: 13, fontWeight: 700, flex: 1 }}>
              Finance lookup
            </span>
            <span style={{ fontSize: 10, color: "#8E8E93" }}>Google Finance</span>
            <button
              onClick={() => setOpen(false)}
              title="Minimize"
              style={{
                width: 22,
                height: 22,
                borderRadius: 11,
                background: "rgba(255,255,255,0.1)",
                color: "white",
                border: "none",
                cursor: "pointer",
                fontSize: 14,
                lineHeight: 1,
              }}
            >
              −
            </button>
          </div>

          {/* Search input */}
          <form onSubmit={onSubmit} style={{ padding: "10px 12px", background: "#F8F9FA", borderBottom: "1px solid #E2E8F0" }}>
            <input
              ref={inputRef}
              type="text"
              placeholder="RELIANCE, TCS:NSE, AAPL:NASDAQ…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              style={{
                width: "100%",
                padding: "8px 10px",
                borderRadius: 8,
                border: "1px solid #E2E8F0",
                fontSize: 13,
                outline: "none",
              }}
            />
            {history.length > 0 && (
              <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginTop: 8 }}>
                {history.map((h) => (
                  <button
                    key={h}
                    type="button"
                    onClick={() => {
                      setQuery(h);
                      runSearch(h);
                    }}
                    style={{
                      fontSize: 10,
                      padding: "2px 8px",
                      borderRadius: 10,
                      background: "white",
                      border: "1px solid #E2E8F0",
                      color: "#48484A",
                      cursor: "pointer",
                    }}
                  >
                    {h}
                  </button>
                ))}
              </div>
            )}
          </form>

          {/* Results */}
          <div style={{ overflowY: "auto", padding: 14, flex: 1 }}>
            {loading && <div style={{ color: "#6E6E73", fontSize: 13 }}>Looking up…</div>}

            {!loading && !quote && (
              <div style={{ color: "#8E8E93", fontSize: 12, lineHeight: 1.5 }}>
                Quick Google Finance quote — type a ticker or <code>SYM:EXCH</code> to search.
                Supports NSE, BSE, NASDAQ, NYSE, LON, TYO, HKG.
              </div>
            )}

            {!loading && quote?.error && (
              <div
                style={{
                  padding: 10,
                  background: "rgba(245,166,35,0.12)",
                  borderRadius: 6,
                  color: "#5C3F00",
                  fontSize: 12,
                }}
              >
                No match for <b>{quote.query}</b>. Try with an exchange suffix like <code>:NASDAQ</code>.
              </div>
            )}

            {!loading && quote && !quote.error && (
              <div>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 6, marginBottom: 8 }}>
                  <div style={{ minWidth: 0 }}>
                    <div style={{ fontSize: 11, color: "#6E6E73", fontWeight: 600 }}>
                      {quote.symbol}:{quote.exchange}
                    </div>
                    <div style={{ fontSize: 14, fontWeight: 700, color: "#1D1D1F", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {quote.name}
                    </div>
                  </div>
                  <div style={{ textAlign: "right" }}>
                    <div style={{ fontSize: 20, fontWeight: 800, color: "#1D1D1F" }}>
                      {quote.currency || ""}
                      {quote.last_price?.toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                    </div>
                    {quote.change_pct !== null && (
                      <div style={{ fontSize: 12, fontWeight: 600, color: color(quote.change_pct) }}>
                        {quote.change_pct >= 0 ? "+" : ""}
                        {quote.change_pct.toFixed(2)}%
                        {quote.change !== null && (
                          <span style={{ color: "#8E8E93", marginLeft: 6 }}>
                            ({quote.change >= 0 ? "+" : ""}
                            {quote.change.toFixed(2)})
                          </span>
                        )}
                      </div>
                    )}
                  </div>
                </div>

                <div style={{ fontSize: 12, color: "#48484A", display: "grid", gridTemplateColumns: "1fr 1fr", gap: "6px 12px", marginTop: 8 }}>
                  {quote.prev_close !== null && (
                    <Stat label="Prev close" value={quote.prev_close.toLocaleString("en-IN", { minimumFractionDigits: 2 })} />
                  )}
                  {quote.day_range && <Stat label="Day range" value={quote.day_range} />}
                  {quote.year_range && <Stat label="52W range" value={quote.year_range} />}
                  {quote.market_cap && <Stat label="Market cap" value={quote.market_cap} />}
                  {quote.pe_ratio && <Stat label="P/E" value={quote.pe_ratio} />}
                  {quote.dividend_yield && <Stat label="Div yield" value={quote.dividend_yield} />}
                  {quote.avg_volume && <Stat label="Avg vol" value={quote.avg_volume} />}
                </div>

                {quote.about && (
                  <div style={{ marginTop: 10, fontSize: 11, color: "#6E6E73", lineHeight: 1.4 }}>
                    {quote.about}
                  </div>
                )}

                <div style={{ marginTop: 12, paddingTop: 10, borderTop: "1px solid #E2E8F0", display: "flex", justifyContent: "space-between", fontSize: 10, color: "#8E8E93" }}>
                  <a
                    href={quote.url}
                    target="_blank"
                    rel="noreferrer"
                    style={{ color: "#007AFF", textDecoration: "none" }}
                  >
                    Open on Google Finance ↗
                  </a>
                  <span>{quote.cached ? "cached" : "live"}</span>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </>
  );

  return createPortal(content, document.body);
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between" }}>
      <span style={{ color: "#8E8E93" }}>{label}</span>
      <span style={{ color: "#1D1D1F", fontWeight: 500, marginLeft: 8, textAlign: "right" }}>{value}</span>
    </div>
  );
}
