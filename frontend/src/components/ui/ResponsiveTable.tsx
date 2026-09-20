"use client";

import React from "react";

export interface RTColumn<R> {
  key: string;
  label: string;
  // Cell renderer. Defaults to (row) => String(row[key]).
  render?: (row: R) => React.ReactNode;
  // Which column becomes the card's title at <md. Exactly one column should
  // set this; if none do, the first column is used.
  primary?: boolean;
  // Right-align numeric columns in the table view. No effect on cards.
  align?: "left" | "right" | "center";
  // Hide on mobile cards (e.g. icon-only columns whose value is duplicated).
  hideOnMobile?: boolean;
  // Optional className applied to the <th>/<td> on desktop.
  thClassName?: string;
  tdClassName?: string;
}

interface Props<R> {
  columns: RTColumn<R>[];
  rows: R[];
  rowKey: (row: R) => string | number;
  // Optional row click handler (e.g. open detail panel).
  onRowClick?: (row: R) => void;
  // Empty-state node.
  empty?: React.ReactNode;
  // Apply to the outer wrapper.
  className?: string;
}

export default function ResponsiveTable<R>({
  columns,
  rows,
  rowKey,
  onRowClick,
  empty,
  className,
}: Props<R>) {
  if (rows.length === 0) {
    return (
      <div
        className={className}
        style={{
          padding: 24,
          textAlign: "center",
          color: "var(--label-tertiary)",
          fontSize: 13,
        }}
      >
        {empty ?? "No rows"}
      </div>
    );
  }

  const primaryIdx = Math.max(
    0,
    columns.findIndex((c) => c.primary),
  );

  return (
    <div className={className}>
      {/* Desktop table */}
      <div className="rt-table">
        <table style={{ width: "100%", fontSize: 13, borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ borderBottom: "1px solid var(--separator-light)" }}>
              {columns.map((c) => (
                <th
                  key={c.key}
                  className={c.thClassName}
                  style={{
                    textAlign: c.align ?? "left",
                    padding: "10px 12px",
                    fontSize: 11,
                    fontWeight: 600,
                    textTransform: "uppercase",
                    letterSpacing: "0.04em",
                    color: "var(--label-tertiary)",
                  }}
                >
                  {c.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr
                key={rowKey(row)}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
                style={{
                  borderBottom: "1px solid var(--separator-light)",
                  cursor: onRowClick ? "pointer" : undefined,
                }}
              >
                {columns.map((c) => (
                  <td
                    key={c.key}
                    className={c.tdClassName}
                    style={{
                      textAlign: c.align ?? "left",
                      padding: "10px 12px",
                      color: "var(--label-primary)",
                    }}
                  >
                    {c.render ? c.render(row) : (row as Record<string, unknown>)[c.key] as React.ReactNode}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Mobile cards */}
      <div className="rt-cards">
        {rows.map((row) => {
          const primary = columns[primaryIdx];
          const rest = columns.filter((_, i) => i !== primaryIdx && !columns[i].hideOnMobile);
          return (
            <div
              key={rowKey(row)}
              onClick={onRowClick ? () => onRowClick(row) : undefined}
              style={{
                border: "1px solid var(--separator-light)",
                borderRadius: 10,
                padding: "12px 14px",
                marginBottom: 8,
                background: "var(--bg-primary)",
                cursor: onRowClick ? "pointer" : undefined,
              }}
            >
              <div
                style={{
                  fontSize: 14,
                  fontWeight: 600,
                  color: "var(--label-primary)",
                  marginBottom: 8,
                }}
              >
                {primary.render
                  ? primary.render(row)
                  : ((row as Record<string, unknown>)[primary.key] as React.ReactNode)}
              </div>
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "1fr 1fr",
                  gap: "6px 12px",
                  fontSize: 12,
                }}
              >
                {rest.map((c) => (
                  <div key={c.key} style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                    <span
                      style={{
                        color: "var(--label-tertiary)",
                        fontSize: 10,
                        textTransform: "uppercase",
                        letterSpacing: "0.04em",
                      }}
                    >
                      {c.label}
                    </span>
                    <span
                      style={{
                        color: "var(--label-primary)",
                        fontFamily: "var(--font-mono)",
                        textAlign: "right",
                      }}
                    >
                      {c.render
                        ? c.render(row)
                        : ((row as Record<string, unknown>)[c.key] as React.ReactNode)}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          );
        })}
      </div>

      <style jsx>{`
        .rt-cards {
          display: none;
        }
        @media (max-width: 720px) {
          .rt-table {
            display: none;
          }
          .rt-cards {
            display: block;
          }
        }
      `}</style>
    </div>
  );
}
