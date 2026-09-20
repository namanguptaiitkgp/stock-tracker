"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

interface HistoryEntry {
  content: string;
  created_at: string | null;
}

interface Props {
  symbol: string;
  noteText: string;
  setNoteText: (text: string) => void;
  lastUpdated: string | null;
}

export default function NotesSection({ symbol, noteText, setNoteText, lastUpdated }: Props) {
  const [saving, setSaving] = useState(false);
  const [savedText, setSavedText] = useState(noteText);
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [showHistory, setShowHistory] = useState(false);
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null);

  // Sync savedText only when the parent loads note data for a (new) symbol —
  // NOT on every keystroke. Without this guard, `noteText` echoes back on every
  // change, making isDirty permanently false and the Save button always disabled.
  useEffect(() => {
    setSavedText(noteText);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbol, lastUpdated]);

  useEffect(() => {
    api.get<HistoryEntry[]>(`/api/notes/${symbol}/history?limit=10`)
      .then(setHistory)
      .catch(() => setHistory([]));
  }, [symbol]);

  async function save() {
    setSaving(true);
    try {
      await api.put(`/api/notes/${symbol}`, { content: noteText });
      setSavedText(noteText);
      const fresh = await api.get<HistoryEntry[]>(`/api/notes/${symbol}/history?limit=10`);
      setHistory(fresh);
    } catch { /* ignore */ }
    setSaving(false);
  }

  const isDirty = noteText !== savedText;

  return (
    <div className="py-3">
      <div className="text-xs font-semibold uppercase mb-2" style={{ color: "var(--label-tertiary)", letterSpacing: "0.05em" }}>
        Your Notes
      </div>
      <textarea
        value={noteText}
        onChange={(e) => setNoteText(e.target.value)}
        placeholder="Write your thoughts about this stock..."
        rows={4}
        className="w-full px-3 py-2 text-sm rounded-lg resize-none focus:outline-none"
        style={{
          background: "var(--bg-secondary)",
          border: "1px solid var(--separator-light)",
          color: "var(--label-primary)",
        }}
      />
      <div className="flex items-center gap-2 mt-2">
        <button
          onClick={save}
          disabled={saving || !isDirty}
          className="px-3 py-1.5 text-xs font-medium rounded-md transition-colors text-white disabled:opacity-30"
          style={{ background: "var(--system-blue)" }}
        >
          {saving ? "Saving..." : "Save Note"}
        </button>
        {lastUpdated && (
          <span className="text-xs" style={{ color: "var(--label-tertiary)" }}>
            Last saved {new Date(lastUpdated).toLocaleString("en-IN")}
          </span>
        )}
      </div>

      {history.length > 0 && (
        <div className="mt-4">
          <button
            onClick={() => setShowHistory(!showHistory)}
            className="text-xs font-medium flex items-center gap-1"
            style={{ color: "var(--system-blue)" }}
          >
            <span style={{ display: "inline-block", transform: showHistory ? "rotate(90deg)" : "rotate(0deg)", transition: "transform 0.15s" }}>
              ▶
            </span>
            Previous Notes ({history.length})
          </button>
          {showHistory && (
            <div className="mt-2 space-y-2">
              {history.map((entry, i) => (
                <div
                  key={i}
                  className="rounded-lg px-3 py-2 cursor-pointer"
                  style={{ background: "var(--bg-secondary)", border: "0.5px solid var(--separator-light)" }}
                  onClick={() => setExpandedIdx(expandedIdx === i ? null : i)}
                >
                  <div className="text-xs" style={{ color: "var(--label-tertiary)" }}>
                    {entry.created_at ? new Date(entry.created_at).toLocaleString("en-IN") : "Unknown date"}
                  </div>
                  <div
                    className="text-xs mt-1"
                    style={{
                      color: "var(--label-secondary)",
                      overflow: expandedIdx === i ? "visible" : "hidden",
                      display: expandedIdx === i ? "block" : "-webkit-box",
                      WebkitLineClamp: expandedIdx === i ? undefined : 2,
                      WebkitBoxOrient: "vertical",
                    }}
                  >
                    {entry.content}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
