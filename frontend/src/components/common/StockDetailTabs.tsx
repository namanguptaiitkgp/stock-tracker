"use client";

import { useEffect, useRef } from "react";

interface Props {
  tabs: string[];
  activeTab: string;
  onChange: (tab: string) => void;
}

export default function StockDetailTabs({ tabs, activeTab, onChange }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);

  // Auto-scroll the active tab into view on selection — important at <md
  // where the bar scrolls horizontally and the active tab may be off-screen
  // after the user changes tabs via a programmatic call (e.g. switching tab
  // from inside the Overview content via the `onSwitchTab` prop).
  useEffect(() => {
    const wrap = containerRef.current;
    if (!wrap) return;
    const btn = wrap.querySelector<HTMLButtonElement>(`button[data-tab="${CSS.escape(activeTab)}"]`);
    if (btn && typeof btn.scrollIntoView === "function") {
      btn.scrollIntoView({ block: "nearest", inline: "center", behavior: "smooth" });
    }
  }, [activeTab]);

  return (
    <div
      ref={containerRef}
      className="sdp-tab-bar sticky z-10 flex gap-1 px-3 py-2"
      style={{
        top: 0,
        background: "var(--bg-secondary)",
        borderBottom: "0.5px solid var(--separator-light)",
      }}
    >
      {tabs.map((tab) => (
        <button
          key={tab}
          data-tab={tab}
          data-active={activeTab === tab ? "true" : "false"}
          aria-pressed={activeTab === tab}
          onClick={() => onChange(tab)}
          className="sdp-tab flex-1 py-1.5 text-xs font-semibold rounded-md"
          style={{
            // No `transition: all` here — transitioning background between
            // tabs caused the previously-active pill to linger for ~150ms
            // while the newly-active pill faded in, giving the visual
            // impression that two tabs were "active" simultaneously.
            // Color transitions still feel responsive without that bug.
            transition: "color 0.15s, box-shadow 0.15s",
            background: activeTab === tab ? "var(--bg-primary)" : "transparent",
            color: activeTab === tab ? "var(--system-blue)" : "var(--label-tertiary)",
            boxShadow: activeTab === tab ? "0 1px 3px rgba(0,0,0,0.08)" : "none",
            letterSpacing: "0.03em",
            whiteSpace: "nowrap",
            scrollSnapAlign: "start",
          }}
        >
          {tab}
        </button>
      ))}
      <style jsx>{`
        @media (max-width: 720px) {
          .sdp-tab-bar {
            overflow-x: auto;
            flex-wrap: nowrap;
            scroll-snap-type: x mandatory;
            -webkit-overflow-scrolling: touch;
            scrollbar-width: none;
          }
          .sdp-tab-bar::-webkit-scrollbar { display: none; }
          .sdp-tab {
            flex: 0 0 auto;
            padding-left: 14px;
            padding-right: 14px;
            min-height: 36px;
          }
        }
      `}</style>
    </div>
  );
}
