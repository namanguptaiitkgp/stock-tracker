"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

interface Peer {
  symbol: string;
  name: string | null;
  cmp: number | null;
  market_cap: number | null;
  pe_ratio: number | null;
  pb_ratio: number | null;
  roe: number | null;
  revenue_growth_1y: number | null;
  promoter_holding: number | null;
}

interface PeerData {
  symbol: string;
  sector: string | null;
  peers: Peer[];
  message?: string;
}

interface Props {
  symbol: string;
  onSelectStock?: (symbol: string) => void;
}

function fmt(v: number | null, decimals = 1): string {
  if (v === null || v === undefined) return "--";
  return v.toFixed(decimals);
}

function mcap(v: number | null): string {
  if (!v) return "--";
  if (v >= 10000000) return `${(v / 10000000).toFixed(0)} Cr`;
  if (v >= 100000) return `${(v / 100000).toFixed(0)} L`;
  return `${(v / 1000).toFixed(0)} K`;
}

export default function PeerComparison({ symbol, onSelectStock }: Props) {
  const [data, setData] = useState<PeerData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    api.get<PeerData>(`/api/market-data/peers/${symbol}?limit=5`)
      .then(setData)
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, [symbol]);

  if (loading) {
    return (
      <div className="py-3">
        <div className="text-xs font-semibold uppercase mb-2" style={{ color: "var(--label-tertiary)", letterSpacing: "0.05em" }}>
          Peer Comparison
        </div>
        <div className="h-20 rounded-lg animate-pulse" style={{ background: "var(--fill-gray)" }} />
      </div>
    );
  }

  if (!data || !data.sector || data.peers.length === 0) {
    return (
      <div className="py-3">
        <div className="text-xs font-semibold uppercase mb-2" style={{ color: "var(--label-tertiary)", letterSpacing: "0.05em" }}>
          Peer Comparison
        </div>
        <div className="text-xs" style={{ color: "var(--label-tertiary)" }}>
          {data?.message || "No sector peers available. Run Analysis to load."}
        </div>
      </div>
    );
  }

  return (
    <div className="py-3">
      <div className="text-xs font-semibold uppercase mb-1" style={{ color: "var(--label-tertiary)", letterSpacing: "0.05em" }}>
        Peer Comparison
      </div>
      <div className="text-xs mb-3" style={{ color: "var(--label-tertiary)" }}>
        Sector: {data.sector}
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-xs" style={{ borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ borderBottom: "0.5px solid var(--separator-light)" }}>
              <th className="text-left py-1.5 font-semibold" style={{ color: "var(--label-tertiary)" }}>Symbol</th>
              <th className="text-right py-1.5 font-semibold" style={{ color: "var(--label-tertiary)" }}>MCap</th>
              <th className="text-right py-1.5 font-semibold" style={{ color: "var(--label-tertiary)" }}>PE</th>
              <th className="text-right py-1.5 font-semibold" style={{ color: "var(--label-tertiary)" }}>ROE</th>
              <th className="text-right py-1.5 font-semibold" style={{ color: "var(--label-tertiary)" }}>Growth</th>
            </tr>
          </thead>
          <tbody>
            {data.peers.map((p) => (
              <tr
                key={p.symbol}
                className="cursor-pointer transition-colors"
                style={{ borderBottom: "0.5px solid var(--separator-light)" }}
                onClick={() => onSelectStock?.(p.symbol)}
                onMouseEnter={(e) => (e.currentTarget.style.background = "var(--fill-gray)")}
                onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
              >
                <td className="py-1.5">
                  <span className="font-mono font-medium" style={{ color: "var(--system-blue)" }}>{p.symbol}</span>
                </td>
                <td className="text-right py-1.5">{mcap(p.market_cap)}</td>
                <td className="text-right py-1.5">{fmt(p.pe_ratio)}</td>
                <td className="text-right py-1.5">{p.roe != null ? `${(p.roe * 100).toFixed(0)}%` : "--"}</td>
                <td className="text-right py-1.5">
                  {p.revenue_growth_1y != null ? (
                    <span style={{ color: p.revenue_growth_1y >= 0 ? "var(--system-green)" : "var(--system-red)" }}>
                      {p.revenue_growth_1y >= 0 ? "+" : ""}{(p.revenue_growth_1y * 100).toFixed(0)}%
                    </span>
                  ) : "--"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
