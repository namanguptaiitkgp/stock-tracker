"use client";

import { useEffect, useState } from "react";
import NotesSection from "../NotesSection";
import { api } from "@/lib/api";
import { fmtRelative } from "@/lib/format";

interface Props {
  symbol: string;
  noteText: string;
  setNoteText: (text: string) => void;
  lastUpdated: string | null;
}

interface HistoryItem {
  content: string;
  created_at: string | null;
}

export default function NotesTab({ symbol, noteText, setNoteText, lastUpdated }: Props) {
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [historyOpen, setHistoryOpen] = useState(false);

  // Fetch past versions of this note. Backend exposes them via
  // /api/notes/{symbol}/history with a default limit of 10. Older versions
  // are surfaced collapsed below the editor so the analyst can see what
  // they had previously written without overwriting the current note.
  useEffect(() => {
    let cancelled = false;
    api.get<HistoryItem[]>(`/api/notes/${symbol}/history?limit=10`)
      .then((rows) => {
        if (cancelled) return;
        // The most recent row is the current note — strip it from history
        // to avoid duplicating what's already in the editor above.
        setHistory((rows || []).slice(1));
      })
      .catch(() => { if (!cancelled) setHistory([]); });
    return () => { cancelled = true; };
    // `lastUpdated` changes after a save, prompting a re-fetch.
  }, [symbol, lastUpdated]);

  return (
    <div>
      <NotesSection
        symbol={symbol}
        noteText={noteText}
        setNoteText={setNoteText}
        lastUpdated={lastUpdated}
      />
      {history.length > 0 && (
        <div style={{ marginTop: 18 }}>
          <button
            onClick={() => setHistoryOpen((v) => !v)}
            aria-expanded={historyOpen}
            style={{
              display: "inline-flex", alignItems: "center", gap: 6,
              padding: "6px 10px", borderRadius: 6,
              background: "transparent",
              color: "var(--label-secondary)",
              border: "1px solid var(--separator-light)",
              fontSize: 12, fontWeight: 500, cursor: "pointer",
            }}
          >
            <span style={{ fontSize: 10 }}>{historyOpen ? "▾" : "▸"}</span>
            Previous versions ({history.length})
          </button>
          {historyOpen && (
            <div style={{
              marginTop: 10, display: "flex", flexDirection: "column", gap: 8,
            }}>
              {history.map((h, i) => (
                <div key={i} style={{
                  padding: "10px 12px", borderRadius: 8,
                  background: "var(--bg-secondary)",
                  border: "1px solid var(--separator-light)",
                  fontSize: 12.5, lineHeight: 1.5,
                  color: "var(--label-primary)",
                  whiteSpace: "pre-wrap",
                }}>
                  <div style={{
                    fontSize: 11, color: "var(--label-tertiary)",
                    marginBottom: 6, fontFamily: "var(--font-mono)",
                  }}>
                    {h.created_at ? fmtRelative(h.created_at) : "—"}
                  </div>
                  {h.content}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
