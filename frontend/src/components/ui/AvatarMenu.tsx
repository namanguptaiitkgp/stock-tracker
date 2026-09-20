"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";

interface KiteStatus {
  authenticated?: boolean;
  has_keys?: boolean;
}

interface Props {
  username: string;
  kiteStatus: KiteStatus | null;
  onLogout: () => void;
}

export default function AvatarMenu({ username, kiteStatus, onLogout }: Props) {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onDocClick(e: MouseEvent) {
      if (!wrapRef.current?.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [open]);

  const initial = (username || "?").trim().charAt(0).toUpperCase();
  const kiteOk = kiteStatus?.authenticated;
  const kiteNeedsReconnect = kiteStatus && !kiteStatus.authenticated && kiteStatus.has_keys;

  return (
    <div ref={wrapRef} style={{ position: "relative" }}>
      <button
        onClick={() => setOpen((v) => !v)}
        aria-label="User menu"
        aria-expanded={open}
        style={{
          width: 36,
          height: 36,
          borderRadius: "50%",
          border: "1px solid var(--separator-light)",
          background: "var(--bg-secondary)",
          color: "var(--label-primary)",
          fontSize: 14,
          fontWeight: 600,
          cursor: "pointer",
          position: "relative",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        {initial}
        {kiteNeedsReconnect && (
          <span
            aria-hidden
            style={{
              position: "absolute",
              top: -2,
              right: -2,
              width: 10,
              height: 10,
              borderRadius: "50%",
              background: "var(--system-red)",
              border: "2px solid var(--bg-primary)",
            }}
          />
        )}
      </button>
      {open && (
        <div
          role="menu"
          style={{
            position: "absolute",
            top: "calc(100% + 8px)",
            right: 0,
            minWidth: 220,
            background: "var(--bg-primary)",
            border: "1px solid var(--separator-light)",
            borderRadius: 10,
            boxShadow: "var(--shadow-md)",
            padding: 8,
            zIndex: 50,
          }}
        >
          <div
            style={{
              padding: "8px 12px",
              borderBottom: "1px solid var(--separator-light)",
              marginBottom: 6,
            }}
          >
            <div style={{ fontSize: 13, fontWeight: 600, color: "var(--label-primary)" }}>
              {username}
            </div>
            <div style={{ fontSize: 11, marginTop: 2 }}>
              {kiteOk ? (
                <span style={{ color: "var(--system-green)" }}>● Kite connected</span>
              ) : kiteNeedsReconnect ? (
                <Link
                  href="/settings"
                  onClick={() => setOpen(false)}
                  style={{ color: "var(--system-red)", textDecoration: "none" }}
                >
                  ● Reconnect Kite →
                </Link>
              ) : (
                <span style={{ color: "var(--label-tertiary)" }}>Kite not configured</span>
              )}
            </div>
          </div>
          <Link
            href="/settings"
            onClick={() => setOpen(false)}
            style={{
              display: "block",
              padding: "8px 12px",
              borderRadius: 6,
              fontSize: 13,
              color: "var(--label-primary)",
              textDecoration: "none",
            }}
          >
            Settings
          </Link>
          <button
            onClick={() => {
              setOpen(false);
              onLogout();
            }}
            style={{
              display: "block",
              width: "100%",
              textAlign: "left",
              padding: "8px 12px",
              borderRadius: 6,
              fontSize: 13,
              color: "var(--system-red)",
              background: "transparent",
              border: 0,
              cursor: "pointer",
            }}
          >
            Sign out
          </button>
        </div>
      )}
    </div>
  );
}
