"use client";

import { usePrivacyMode } from "@/lib/privacy-mode";

/**
 * Wraps a sensitive value (portfolio total, P&L, quantity, price). When
 * privacy mode is on, renders a blurred placeholder. Children are still
 * visible to screen readers for accessibility when the mask is off.
 */
export default function Masked({
  children,
  placeholder = "••••",
  inline = true,
}: {
  children: React.ReactNode;
  placeholder?: string;
  inline?: boolean;
}) {
  const on = usePrivacyMode();
  if (!on) return <>{children}</>;

  const Tag = inline ? "span" : "div";
  return (
    <Tag
      style={{
        fontFamily: "monospace",
        color: "#8E8E93",
        letterSpacing: "0.05em",
      }}
    >
      {placeholder}
    </Tag>
  );
}
