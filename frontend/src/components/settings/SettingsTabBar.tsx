"use client";

import React from "react";

interface TabDef {
  id: string;
  label: string;
}

interface Props {
  tabs: TabDef[];
  activeId: string;
  onChange: (id: string) => void;
}

export default function SettingsTabBar({ tabs, activeId, onChange }: Props) {
  return (
    <nav
      role="tablist"
      style={{
        position: "sticky",
        top: 100,
        zIndex: 5,
        marginBottom: 18,
        padding: "10px 6px",
        background: "color-mix(in srgb, var(--bg-grouped) 85%, transparent)",
        backdropFilter: "blur(10px)",
        WebkitBackdropFilter: "blur(10px)",
        borderBottom: "1px solid var(--separator-light)",
      }}
    >
      <div
        className="settings-tab-row"
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: 4,
        }}
      >
        <style jsx>{`
          @media (max-width: 720px) {
            .settings-tab-row {
              flex-wrap: nowrap !important;
              overflow-x: auto;
              -webkit-overflow-scrolling: touch;
              scrollbar-width: none;
            }
            .settings-tab-row::-webkit-scrollbar { display: none; }
          }
        `}</style>
        {tabs.map((t) => {
          const active = activeId === t.id;
          return (
            <button
              key={t.id}
              role="tab"
              aria-selected={active}
              onClick={() => onChange(t.id)}
              style={{
                padding: "7px 14px",
                borderRadius: 99,
                border: 0,
                background: active ? "var(--label-primary)" : "transparent",
                color: active ? "var(--bg-primary)" : "var(--label-tertiary)",
                fontSize: 13,
                fontWeight: active ? 600 : 500,
                cursor: "pointer",
                whiteSpace: "nowrap",
                transition: "background .12s, color .12s",
              }}
              onMouseEnter={(e) => {
                if (!active) e.currentTarget.style.background = "var(--fill-gray, rgba(99,99,102,0.08))";
              }}
              onMouseLeave={(e) => {
                if (!active) e.currentTarget.style.background = "transparent";
              }}
            >
              {t.label}
            </button>
          );
        })}
      </div>
    </nav>
  );
}
