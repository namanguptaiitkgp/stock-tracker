"use client";

import React from "react";

/**
 * Labelled-input wrapper used inside Settings cards. Standardises
 * label typography, hint copy, and error rendering across the page.
 */

interface Props {
  label: string;
  hint?: React.ReactNode;
  htmlFor?: string;
  error?: string | null;
  children: React.ReactNode;
  /** Side-by-side layout for short fields (label left, input right). */
  inline?: boolean;
}

export default function SettingsField({ label, hint, htmlFor, error, children, inline }: Props) {
  if (inline) {
    return (
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "minmax(140px, 0.6fr) 1fr",
          gap: 14,
          alignItems: "center",
          padding: "8px 0",
          borderBottom: "1px solid var(--separator-light)",
        }}
      >
        <label
          htmlFor={htmlFor}
          style={{
            fontSize: 13,
            color: "var(--label-secondary)",
            fontWeight: 500,
          }}
        >
          {label}
          {hint && (
            <span style={{ display: "block", fontSize: 11, color: "var(--label-tertiary)", marginTop: 2, fontWeight: 400 }}>
              {hint}
            </span>
          )}
        </label>
        <div>{children}{error && <FieldError text={error} />}</div>
      </div>
    );
  }
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <label
        htmlFor={htmlFor}
        style={{
          fontSize: 11,
          fontWeight: 600,
          textTransform: "uppercase",
          letterSpacing: "0.06em",
          color: "var(--label-tertiary)",
        }}
      >
        {label}
      </label>
      {children}
      {hint && (
        <span style={{ fontSize: 11, color: "var(--label-quaternary)" }}>{hint}</span>
      )}
      {error && <FieldError text={error} />}
    </div>
  );
}

function FieldError({ text }: { text: string }) {
  return (
    <span
      role="alert"
      style={{
        fontSize: 11,
        color: "var(--system-red, #D70015)",
        marginTop: 2,
      }}
    >
      {text}
    </span>
  );
}

/** Shared input styling — pull this in when you want a consistent input look. */
export const settingsInputStyle: React.CSSProperties = {
  background: "var(--bg-secondary)",
  border: "1px solid var(--separator)",
  borderRadius: 8,
  padding: "8px 12px",
  fontSize: 13,
  color: "var(--label-primary)",
  outline: "none",
  width: "100%",
};

export const settingsButtonPrimary: React.CSSProperties = {
  padding: "8px 16px",
  borderRadius: 8,
  border: 0,
  background: "var(--label-primary)",
  color: "var(--bg-primary)",
  fontSize: 13,
  fontWeight: 600,
  cursor: "pointer",
};

export const settingsButtonSecondary: React.CSSProperties = {
  padding: "8px 14px",
  borderRadius: 8,
  border: "1px solid var(--separator)",
  background: "transparent",
  color: "var(--label-primary)",
  fontSize: 13,
  fontWeight: 500,
  cursor: "pointer",
};
