"use client";

/**
 * Full insider-disclosures table — the raw, unfiltered view that used
 * to live inline on /smart-money before the action-summary redesign.
 * Filterable by category, transaction type, and lookback window.
 */

import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { openStockDetail } from "@/lib/stock-detail";

interface InsiderRow {
  id: number;
  symbol: string;
  person_name: string;
  category: string;
  transaction_type: string;
  shares: number;
  value_inr: number | null;
  transaction_date: string | null;
  intimation_date: string | null;
  mode: string | null;
  pre_holding_pct: number | null;
  post_holding_pct: number | null;
  exchange: string;
  is_known_shark: boolean;
}

const CATEGORIES = ["", "Promoter", "Promoter Group", "Director", "Designated Person", "Immediate Relative", "Other"];
const TXN_TYPES = ["", "Buy", "Sale", "Pledge", "Revoke", "Invoke"];

const TXN_COLOR: Record<string, string> = {
  Buy: "var(--buy)",
  Sale: "var(--act)",
  Pledge: "var(--review)",
  Revoke: "var(--review)",
  Invoke: "var(--act)",
};

function fmtInr(n: number | null): string {
  if (n === null || n === undefined) return "—";
  if (Math.abs(n) >= 1e7) return `Rs ${(n / 1e7).toFixed(2)} Cr`;
  if (Math.abs(n) >= 1e5) return `Rs ${(n / 1e5).toFixed(2)} L`;
  return `Rs ${Math.round(n).toLocaleString("en-IN")}`;
}

export default function InsiderPage() {
  const [rows, setRows] = useState<InsiderRow[]>([]);
  const [days, setDays] = useState(30);
  const [category, setCategory] = useState("");
  const [txnType, setTxnType] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const params = new URLSearchParams();
    params.set("days", String(days));
    params.set("limit", "200");
    if (category) params.set("category", category);
    if (txnType) params.set("transaction_type", txnType);
    setLoading(true);
    api
      .get<{ rows: InsiderRow[] }>(`/api/smart-money/insider-activity?${params.toString()}`)
      .then((r) => {
        setRows(r.rows || []);
        setLoading(false);
      })
      .catch(() => {
        setRows([]);
        setLoading(false);
      });
  }, [days, category, txnType]);

  return (
    <div style={{ padding: "32px 40px", maxWidth: 1200, margin: "0 auto" }}>
      <div style={{ marginBottom: 16 }}>
        <Link href="/smart-money" style={{ fontSize: 12, color: "var(--system-blue)", textDecoration: "none" }}>
          ← Smart Money
        </Link>
      </div>

      <header style={{ marginBottom: 20 }}>
        <h1 style={{ fontFamily: "var(--font-serif)", fontSize: 28, fontWeight: 600, letterSpacing: "-0.02em", margin: 0 }}>
          All Insider Disclosures
        </h1>
        <p style={{ fontSize: 13, color: "var(--label-tertiary)", marginTop: 4 }}>
          PIT Reg 7 / SAST filings from NSE. Includes intra-group transfers — see column.
          For the daily-action filtered view, go back to{" "}
          <Link href="/smart-money" style={{ color: "var(--system-blue)" }}>Smart Money</Link>.
        </p>
      </header>

      <div style={{ display: "flex", gap: 12, alignItems: "center", marginBottom: 16, flexWrap: "wrap" }}>
        <FilterSelect label="Window" value={String(days)} options={["7", "14", "30", "60", "90", "180"]} onChange={(v) => setDays(Number(v))} />
        <FilterSelect label="Category" value={category} options={CATEGORIES} onChange={setCategory} placeholder="All categories" />
        <FilterSelect label="Type" value={txnType} options={TXN_TYPES} onChange={setTxnType} placeholder="All types" />
        <span style={{ marginLeft: "auto", fontSize: 12, color: "var(--label-tertiary)" }}>
          {loading ? "Loading…" : `${rows.length} disclosures`}
        </span>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "70px 1fr 110px 70px 110px 110px 100px 80px",
          gap: 8,
          padding: "8px 12px",
          fontSize: 10,
          fontWeight: 600,
          color: "var(--label-tertiary)",
          textTransform: "uppercase",
          letterSpacing: "0.05em",
          borderBottom: "1px solid var(--separator-light)",
        }}
      >
        <span>Symbol</span>
        <span>Who</span>
        <span>Category</span>
        <span>Type</span>
        <span style={{ textAlign: "right" }}>Shares</span>
        <span style={{ textAlign: "right" }}>Value</span>
        <span>Date</span>
        <span>Mode</span>
      </div>
      {rows.map((r) => (
        <button
          key={r.id}
          onClick={() => openStockDetail(r.symbol, "NSE")}
          style={{
            display: "grid",
            gridTemplateColumns: "70px 1fr 110px 70px 110px 110px 100px 80px",
            gap: 8,
            alignItems: "center",
            padding: "8px 12px",
            fontSize: 12,
            background: "var(--bg-primary)",
            border: "1px solid var(--separator-light)",
            borderRadius: 6,
            marginTop: 4,
            cursor: "pointer",
            textAlign: "left",
            width: "100%",
          }}
        >
          <span style={{ fontFamily: "var(--font-mono)", fontWeight: 700, color: "var(--label-primary)" }}>
            {r.symbol}
          </span>
          <span title={r.person_name} style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: "var(--label-secondary)" }}>
            {r.person_name}
          </span>
          <span style={{ fontSize: 11, color: "var(--label-tertiary)" }}>{r.category}</span>
          <span style={{ color: TXN_COLOR[r.transaction_type] || "var(--label-secondary)", fontWeight: 700 }}>
            {r.transaction_type}
          </span>
          <span style={{ textAlign: "right", fontFamily: "var(--font-mono)" }}>
            {r.shares.toLocaleString("en-IN")}
          </span>
          <span style={{ textAlign: "right", fontFamily: "var(--font-mono)", color: "var(--label-secondary)" }}>
            {fmtInr(r.value_inr)}
          </span>
          <span style={{ color: "var(--label-tertiary)", fontSize: 11 }}>{r.transaction_date}</span>
          <span style={{ color: "var(--label-tertiary)", fontSize: 11 }}>{r.mode || "—"}</span>
        </button>
      ))}
    </div>
  );
}

function FilterSelect({
  label,
  value,
  options,
  onChange,
  placeholder,
}: {
  label: string;
  value: string;
  options: string[];
  onChange: (v: string) => void;
  placeholder?: string;
}) {
  return (
    <label style={{ fontSize: 12, display: "inline-flex", alignItems: "center", gap: 6 }}>
      <span style={{ color: "var(--label-tertiary)" }}>{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        style={{
          padding: "4px 10px",
          borderRadius: 6,
          border: "1px solid var(--separator)",
          background: "var(--bg-primary)",
          color: "var(--label-primary)",
          fontSize: 12,
        }}
      >
        {options.map((opt) => (
          <option key={opt} value={opt}>
            {opt === "" ? placeholder || "All" : opt}
          </option>
        ))}
      </select>
    </label>
  );
}
