"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { api } from "@/lib/api";

interface SearchResult {
  tradingsymbol: string;
  name: string | null;
  exchange: string;
  instrument_token: number;
  match_type: string;
}

interface Props {
  onSelect: (stock: SearchResult) => void;
  placeholder?: string;
  className?: string;
  autoFocus?: boolean;
}

export default function StockSearch({ onSelect, placeholder, className, autoFocus }: Props) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const ref = useRef<HTMLDivElement>(null);
  const portalRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const debounceRef = useRef<NodeJS.Timeout | null>(null);
  const [dropdownRect, setDropdownRect] = useState<{ top: number; left: number; width: number } | null>(null);

  // Recompute dropdown position when open / on scroll / on resize.
  useEffect(() => {
    if (!open) {
      setDropdownRect(null);
      return;
    }
    function measure() {
      const el = ref.current;
      if (!el) return;
      const r = el.getBoundingClientRect();
      setDropdownRect({ top: r.bottom + 4, left: r.left, width: r.width });
    }
    measure();
    window.addEventListener("scroll", measure, true);
    window.addEventListener("resize", measure);
    return () => {
      window.removeEventListener("scroll", measure, true);
      window.removeEventListener("resize", measure);
    };
  }, [open]);

  const search = useCallback(async (q: string) => {
    if (q.length < 1) {
      setResults([]);
      setOpen(false);
      return;
    }
    setLoading(true);
    try {
      const data = await api.get<SearchResult[]>(`/api/stocks/search?q=${encodeURIComponent(q)}&limit=12`);
      setResults(data);
      setOpen(data.length > 0);
      setActiveIndex(-1);
    } catch {
      setResults([]);
    } finally {
      setLoading(false);
    }
  }, []);

  function onInputChange(value: string) {
    setQuery(value);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => search(value), 200);
  }

  function selectItem(item: SearchResult) {
    setQuery("");
    setOpen(false);
    setResults([]);
    onSelect(item);
  }

  function onKeyDown(e: React.KeyboardEvent) {
    if (!open) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIndex((i) => Math.min(i + 1, results.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIndex((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter" && activeIndex >= 0) {
      e.preventDefault();
      selectItem(results[activeIndex]);
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  }

  // Close dropdown when clicking outside (check both the input wrapper and the portal)
  useEffect(() => {
    function handler(e: MouseEvent) {
      const target = e.target as Node;
      if (
        ref.current && !ref.current.contains(target) &&
        (!portalRef.current || !portalRef.current.contains(target))
      ) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  return (
    <div ref={ref} className={`relative ${className || ""}`}>
      <div className="relative">
        <svg className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-4.35-4.35M17 10a7 7 0 11-14 0 7 7 0 0114 0z" />
        </svg>
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={(e) => onInputChange(e.target.value)}
          onFocus={() => results.length > 0 && setOpen(true)}
          onKeyDown={onKeyDown}
          placeholder={placeholder || "Search stocks by name or ticker..."}
          autoFocus={autoFocus}
          className="w-full pl-9 pr-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm focus:outline-none focus:border-blue-500"
        />
        {loading && (
          <div className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 border-2 border-gray-400 border-t-transparent rounded-full animate-spin" />
        )}
      </div>

      {typeof window !== "undefined" && open && dropdownRect && results.length > 0 && createPortal(
        <div
          ref={portalRef}
          style={{
            position: "fixed",
            top: dropdownRect.top,
            left: dropdownRect.left,
            width: dropdownRect.width,
            zIndex: 2000,
          }}
          className="bg-gray-900 border border-gray-800 rounded-lg shadow-xl max-h-80 overflow-auto"
        >
          {results.map((item, i) => (
            <button
              key={`${item.tradingsymbol}-${item.exchange}`}
              onClick={() => selectItem(item)}
              onMouseEnter={() => setActiveIndex(i)}
              className={`w-full text-left px-3 py-2.5 flex items-center gap-3 text-sm transition-colors ${
                i === activeIndex ? "bg-gray-800" : "hover:bg-gray-800"
              }`}
            >
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="font-mono font-medium text-gray-200">{item.tradingsymbol}</span>
                  <span className="text-xs text-gray-500">{item.exchange}</span>
                </div>
                {item.name && (
                  <div className="text-xs text-gray-400 truncate">{item.name}</div>
                )}
              </div>
              {item.match_type === "exact" && (
                <span className="text-xs text-blue-400">exact</span>
              )}
            </button>
          ))}
        </div>,
        document.body,
      )}

      {typeof window !== "undefined" && open && dropdownRect && query.length >= 1 && results.length === 0 && !loading && createPortal(
        <div
          style={{
            position: "fixed",
            top: dropdownRect.top,
            left: dropdownRect.left,
            width: dropdownRect.width,
            zIndex: 2000,
          }}
          className="bg-gray-900 border border-gray-800 rounded-lg shadow-xl p-4 text-center"
        >
          <div className="text-sm text-gray-400">No stocks found for &quot;{query}&quot;</div>
          <div className="text-xs text-gray-500 mt-1">
            Try syncing the stock list from Settings if you haven&apos;t already
          </div>
        </div>,
        document.body,
      )}
    </div>
  );
}
