"use client";

import React, { useEffect, useState } from "react";
import { api } from "@/lib/api";

interface FiiDiiEntry {
  buy: number | null;
  sell: number | null;
  net: number | null;
}

interface FiiDiiData {
  date: string | null;
  fii: FiiDiiEntry | null;
  dii: FiiDiiEntry | null;
}

function formatAmount(val: number | null): string {
  if (val === null || val === undefined) return "--";
  const abs = Math.abs(val);
  if (abs >= 100) {
    return `${val >= 0 ? "+" : ""}${val.toLocaleString("en-IN", { maximumFractionDigits: 2 })} Cr`;
  }
  return `${val >= 0 ? "+" : ""}${val.toLocaleString("en-IN", { maximumFractionDigits: 2 })} Cr`;
}

function NetLabel({ net }: { net: number | null }) {
  if (net === null || net === undefined) {
    return <span style={{ color: "#6E6E73" }}>--</span>;
  }
  const isPositive = net >= 0;
  return (
    <span>
      <span style={{ color: "#1D1D1F", fontWeight: "bold" }}>
        Net {formatAmount(net)}
      </span>{" "}
      <span style={{ color: isPositive ? "#248A3D" : "#D70015", fontWeight: 600, fontSize: 12 }}>
        ({isPositive ? "Buying" : "Selling"})
      </span>
    </span>
  );
}

export default function FiiDiiActivity() {
  const [data, setData] = useState<FiiDiiData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    api
      .get<FiiDiiData>("/api/market-data/fii-dii")
      .then((d) => setData(d))
      .catch((e) =>
        setError(e instanceof Error ? e.message : "Failed to load FII/DII data"),
      )
      .finally(() => setLoading(false));
  }, []);

  return (
    <div
      style={{
        borderTop: "1px solid rgba(142,142,147,0.15)",
        paddingTop: 12,
      }}
    >
      <h3
        style={{
          fontSize: 11,
          fontWeight: 600,
          textTransform: "uppercase",
          letterSpacing: "0.05em",
          marginBottom: 8,
          color: "#6E6E73",
        }}
      >
        FII / DII Activity
      </h3>

      {loading && (
        <div style={{ padding: "8px 0" }}>
          <div
            style={{
              height: 12,
              borderRadius: 4,
              backgroundColor: "rgba(142,142,147,0.12)",
              animation: "fiiPulse 1.5s ease-in-out infinite",
              width: "80%",
              marginBottom: 8,
            }}
          />
          <div
            style={{
              height: 12,
              borderRadius: 4,
              backgroundColor: "rgba(142,142,147,0.12)",
              animation: "fiiPulse 1.5s ease-in-out infinite",
              width: "70%",
            }}
          />
          <style>{`@keyframes fiiPulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }`}</style>
        </div>
      )}

      {!loading && error && (
        <div
          style={{
            padding: 12,
            borderRadius: 8,
            backgroundColor: "rgba(255,59,48,0.08)",
            color: "#D70015",
            fontSize: 13,
            marginBottom: 8,
          }}
        >
          <div>{error}</div>
          <button
            onClick={() => {
              setLoading(true);
              setError(null);
              api
                .get<FiiDiiData>("/api/market-data/fii-dii")
                .then((d) => setData(d))
                .catch((e) =>
                  setError(
                    e instanceof Error ? e.message : "Failed to load FII/DII data",
                  ),
                )
                .finally(() => setLoading(false));
            }}
            style={{
              marginTop: 8,
              padding: "4px 12px",
              borderRadius: 6,
              border: "none",
              cursor: "pointer",
              fontSize: 12,
              backgroundColor: "#007AFF",
              color: "#FFFFFF",
            }}
          >
            Retry
          </button>
        </div>
      )}

      {!loading && !error && data && (
        <div
          style={{
            padding: 12,
            borderRadius: 8,
            backgroundColor: "rgba(142,142,147,0.05)",
            border: "1px solid rgba(142,142,147,0.1)",
          }}
        >
          {/* FII Row */}
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              marginBottom: 10,
            }}
          >
            <span style={{ color: "#6E6E73", fontSize: 13, fontWeight: 500, minWidth: 60 }}>
              FII/FPI
            </span>
            <span style={{ fontSize: 13, textAlign: "right" }}>
              <NetLabel net={data.fii?.net ?? null} />
            </span>
          </div>

          {/* DII Row */}
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              marginBottom: 10,
            }}
          >
            <span style={{ color: "#6E6E73", fontSize: 13, fontWeight: 500, minWidth: 60 }}>
              DII
            </span>
            <span style={{ fontSize: 13, textAlign: "right" }}>
              <NetLabel net={data.dii?.net ?? null} />
            </span>
          </div>

          {/* Date */}
          {data.date && (
            <div
              style={{
                fontSize: 11,
                color: "#6E6E73",
                borderTop: "1px solid rgba(142,142,147,0.1)",
                paddingTop: 8,
              }}
            >
              Date: {data.date}
            </div>
          )}
        </div>
      )}

      {!loading && !error && !data && (
        <div
          style={{
            padding: 12,
            fontSize: 13,
            color: "#6E6E73",
            textAlign: "center",
          }}
        >
          FII/DII data unavailable
        </div>
      )}
    </div>
  );
}
