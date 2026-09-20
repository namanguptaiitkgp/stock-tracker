"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

interface Note {
  symbol: string;
  content: string;
  created_at: string | null;
  updated_at: string | null;
}

interface Props {
  symbol: string;
  onClose: () => void;
  onSaved?: (note: Note | null) => void;
}

export function StockNoteModal({ symbol, onClose, onSaved }: Props) {
  const [content, setContent] = useState("");
  const [note, setNote] = useState<Note | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.get<Note>(`/api/notes/${symbol}`)
      .then((data) => {
        setNote(data);
        setContent(data.content || "");
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load"))
      .finally(() => setLoading(false));
  }, [symbol]);

  async function save() {
    setSaving(true);
    setError(null);
    try {
      const saved = await api.put<Note>(`/api/notes/${symbol}`, { content });
      onSaved?.(saved.content ? saved : null);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  }

  async function clear() {
    if (!note?.content) {
      onClose();
      return;
    }
    setSaving(true);
    try {
      await api.delete(`/api/notes/${symbol}`);
      onSaved?.(null);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/70 z-50 flex items-center justify-center p-6" onClick={onClose}>
      <div
        className="bg-gray-900 border border-gray-800 rounded-lg w-full max-w-lg shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="p-4 border-b border-gray-800 flex items-start justify-between">
          <div>
            <h2 className="text-lg font-semibold text-white flex items-center gap-2">
              <span className="font-mono">{symbol}</span>
              <span className="text-xs text-gray-500">Notes</span>
            </h2>
            {note?.updated_at && (
              <p className="text-xs text-gray-600 mt-1">
                Last updated: {new Date(note.updated_at).toLocaleString("en-IN")}
              </p>
            )}
          </div>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-white text-xl leading-none"
          >
            ×
          </button>
        </div>

        <div className="p-4">
          {loading ? (
            <div className="text-sm text-gray-500">Loading...</div>
          ) : (
            <>
              <textarea
                value={content}
                onChange={(e) => setContent(e.target.value)}
                placeholder="Write your thoughts, observations, or reminders about this stock..."
                rows={8}
                className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-md text-white text-sm focus:outline-none focus:border-blue-500 resize-none"
                autoFocus
              />
              <div className="text-xs text-gray-600 mt-1 text-right">
                {content.length} characters
              </div>
            </>
          )}

          {error && (
            <div className="mt-3 p-2 bg-red-950 border border-red-800 rounded text-xs text-red-300">
              {error}
            </div>
          )}
        </div>

        <div className="p-4 border-t border-gray-800 flex gap-2 justify-end">
          {note?.content && (
            <button
              onClick={clear}
              disabled={saving}
              className="px-4 py-2 bg-red-900/50 hover:bg-red-900 text-red-300 text-sm rounded-md transition-colors"
            >
              Delete Note
            </button>
          )}
          <button
            onClick={onClose}
            className="px-4 py-2 bg-gray-800 hover:bg-gray-700 text-gray-300 text-sm rounded-md transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={save}
            disabled={saving || loading}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white text-sm rounded-md transition-colors"
          >
            {saving ? "Saving..." : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}


interface NoteIconProps {
  symbol: string;
  hasNote: boolean;
  onClick: (symbol: string) => void;
}

export function NoteIcon({ symbol, hasNote, onClick }: NoteIconProps) {
  return (
    <button
      onClick={(e) => { e.stopPropagation(); onClick(symbol); }}
      title={hasNote ? "View/edit your note" : "Add a note"}
      className={`inline-flex items-center justify-center w-6 h-6 rounded transition-colors ${
        hasNote
          ? "text-yellow-400 hover:text-yellow-300 bg-yellow-950/30"
          : "text-gray-600 hover:text-gray-400 hover:bg-gray-800"
      }`}
    >
      <svg xmlns="http://www.w3.org/2000/svg" className="w-3.5 h-3.5" fill={hasNote ? "currentColor" : "none"} viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
      </svg>
    </button>
  );
}
