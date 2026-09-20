"use client";

import React from "react";

interface State {
  hasError: boolean;
  errorMessage: string | null;
}

interface Props {
  children: React.ReactNode;
  onClose?: () => void;
}

/**
 * Catches runtime rendering errors in any subtree — instead of propagating
 * the exception up to the root (which crashes the whole page / tab), shows
 * a readable message with a reset button. Used for the Stock Detail panel
 * so a single bad data shape from Tickertape / Kite can't take down /fno.
 */
export default class PanelErrorBoundary extends React.Component<Props, State> {
  state: State = { hasError: false, errorMessage: null };

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, errorMessage: error.message || String(error) };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo): void {
    // eslint-disable-next-line no-console
    console.error("Panel render error:", error, info.componentStack);
  }

  render() {
    if (!this.state.hasError) return this.props.children;
    return (
      <div
        style={{
          padding: 20,
          background: "rgba(215,0,21,0.08)",
          border: "1px solid rgba(215,0,21,0.25)",
          borderRadius: 8,
          color: "#B10011",
          margin: 16,
        }}
      >
        <div style={{ fontWeight: 700, marginBottom: 6 }}>
          Could not render this panel
        </div>
        <div style={{ fontSize: 12, fontFamily: "monospace", marginBottom: 12, wordBreak: "break-word" }}>
          {this.state.errorMessage || "Unknown render error"}
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button
            onClick={() => this.setState({ hasError: false, errorMessage: null })}
            style={{
              padding: "4px 12px",
              background: "#1D1D1F",
              color: "white",
              border: "none",
              borderRadius: 6,
              fontSize: 12,
              cursor: "pointer",
            }}
          >
            Retry
          </button>
          {this.props.onClose && (
            <button
              onClick={this.props.onClose}
              style={{
                padding: "4px 12px",
                background: "white",
                color: "#1D1D1F",
                border: "1px solid #E2E8F0",
                borderRadius: 6,
                fontSize: 12,
                cursor: "pointer",
              }}
            >
              Close
            </button>
          )}
        </div>
      </div>
    );
  }
}
