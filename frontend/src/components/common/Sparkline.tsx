"use client";

import React, { useRef, useState, useCallback } from "react";

interface Props {
  data: number[];
  labels?: string[];
  width?: number;
  height?: number;
  prevClose?: number | null;
  showGrid?: boolean;
  color?: string;
}

export default function Sparkline({
  data,
  labels,
  width = 720,
  height = 200,
  prevClose,
  showGrid = true,
  color,
}: Props) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);

  if (!data || data.length < 2) {
    return (
      <div
        style={{
          width: "100%",
          height,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          color: "var(--label-tertiary)",
          fontSize: 12,
          background: "var(--bg-secondary)",
          borderRadius: 8,
        }}
      >
        No chart data available
      </div>
    );
  }

  const min = Math.min(...data);
  const max = Math.max(...data);
  const includesRef = prevClose != null;
  const lo = includesRef ? Math.min(min, prevClose!) : min;
  const hi = includesRef ? Math.max(max, prevClose!) : max;
  const pad = (hi - lo) * 0.15 || 1;
  const yLo = lo - pad;
  const yHi = hi + pad;

  const px = (i: number) => (i / (data.length - 1)) * width;
  const py = (v: number) => height - ((v - yLo) / (yHi - yLo)) * height;

  const path = data.map((v, i) => `${i === 0 ? "M" : "L"} ${px(i).toFixed(2)} ${py(v).toFixed(2)}`).join(" ");
  const area = `${path} L ${width} ${height} L 0 ${height} Z`;

  const first = data[0];
  const last = data[data.length - 1];
  const up = last >= first;
  const stroke = color || (up ? "var(--system-green)" : "var(--system-red)");

  const gridYs = showGrid ? [0.25, 0.5, 0.75].map((g) => height * g) : [];

  const gradientId = React.useId();
  const interactive = labels && labels.length === data.length;

  const handleMouse = useCallback((e: React.MouseEvent<SVGSVGElement>) => {
    if (!interactive || !svgRef.current) return;
    const rect = svgRef.current.getBoundingClientRect();
    const xRatio = (e.clientX - rect.left) / rect.width;
    const idx = Math.round(xRatio * (data.length - 1));
    setHoverIdx(Math.max(0, Math.min(idx, data.length - 1)));
  }, [interactive, data.length]);

  const hx = hoverIdx != null ? px(hoverIdx) : 0;
  const hy = hoverIdx != null ? py(data[hoverIdx]) : 0;
  const hVal = hoverIdx != null ? data[hoverIdx] : 0;
  const hLabel = hoverIdx != null && labels ? labels[hoverIdx] : "";
  const tooltipW = 130;
  const tooltipFlip = hoverIdx != null && hx > width * 0.75;

  return (
    <svg
      ref={svgRef}
      viewBox={`0 0 ${width} ${height}`}
      width="100%"
      height={height}
      preserveAspectRatio="none"
      style={{ display: "block", cursor: interactive ? "crosshair" : undefined }}
      onMouseMove={handleMouse}
      onMouseLeave={() => setHoverIdx(null)}
    >
      <defs>
        <linearGradient id={gradientId} x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor={stroke} stopOpacity="0.22" />
          <stop offset="100%" stopColor={stroke} stopOpacity="0" />
        </linearGradient>
      </defs>

      {gridYs.map((y, i) => (
        <line
          key={i}
          x1="0"
          x2={width}
          y1={y}
          y2={y}
          stroke="var(--separator-light)"
          strokeDasharray="2 4"
        />
      ))}

      {includesRef && (
        <>
          <line
            x1="0"
            x2={width}
            y1={py(prevClose!)}
            y2={py(prevClose!)}
            stroke="var(--label-tertiary)"
            strokeDasharray="3 3"
            strokeWidth="1"
          />
          <text
            x={width - 4}
            y={py(prevClose!) - 4}
            textAnchor="end"
            fontSize="10"
            fill="var(--label-tertiary)"
            fontFamily="var(--font-mono)"
          >
            prev {prevClose!.toFixed(2)}
          </text>
        </>
      )}

      <path d={area} fill={`url(#${gradientId})`} />
      <path
        d={path}
        fill="none"
        stroke={stroke}
        strokeWidth="1.75"
        strokeLinejoin="round"
        strokeLinecap="round"
      />

      {hoverIdx == null && (
        <>
          <circle cx={px(data.length - 1)} cy={py(last)} r="3.5" fill={stroke} />
          <circle cx={px(data.length - 1)} cy={py(last)} r="7" fill={stroke} fillOpacity="0.18" />
        </>
      )}

      {hoverIdx != null && interactive && (
        <>
          <line x1={hx} x2={hx} y1={0} y2={height} stroke="var(--label-tertiary)" strokeWidth="0.75" strokeDasharray="3 2" />
          <circle cx={hx} cy={hy} r="4" fill={stroke} />
          <circle cx={hx} cy={hy} r="8" fill={stroke} fillOpacity="0.15" />
          <g transform={`translate(${tooltipFlip ? hx - tooltipW - 10 : hx + 10}, ${Math.max(4, Math.min(hy - 22, height - 44))})`}>
            <rect width={tooltipW} height={40} rx="6" fill="var(--bg-primary)" stroke="var(--separator)" strokeWidth="0.75" fillOpacity="0.92" />
            <text x="8" y="15" fontSize="11" fill="var(--label-primary)" fontFamily="var(--font-mono)" fontWeight="600">
              {hVal.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </text>
            <text x="8" y="31" fontSize="9.5" fill="var(--label-tertiary)" fontFamily="var(--font-mono)">
              {hLabel}
            </text>
          </g>
        </>
      )}
    </svg>
  );
}
