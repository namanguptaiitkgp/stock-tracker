"use client";

import React, { useEffect, useState } from "react";

/* ─── filter / weight metadata ────────────────────────────────── */

interface FilterMeta {
  key: string;
  label: string;
  direction: "max" | "min";
  defaultVal: number;
  fmt: "num" | "pct" | "cap";
  step: number;
  group: "valuation" | "quality" | "growth" | "other";
}

const FILTERS: FilterMeta[] = [
  // Valuation
  { key: "pe_ratio_max",       label: "P/E Ratio",              direction: "max", defaultVal: 20,    fmt: "num", step: 1,     group: "valuation" },
  { key: "pb_ratio_max",       label: "P/B Ratio",              direction: "max", defaultVal: 3,     fmt: "num", step: 0.1,   group: "valuation" },
  { key: "forward_pe_max",     label: "Forward P/E",            direction: "max", defaultVal: 25,    fmt: "num", step: 1,     group: "valuation" },
  { key: "ttm_pe_max",         label: "TTM P/E",                direction: "max", defaultVal: 25,    fmt: "num", step: 1,     group: "valuation" },
  // Quality
  { key: "roe_min",            label: "Return on Equity",       direction: "min", defaultVal: 0.15,  fmt: "pct", step: 0.01,  group: "quality" },
  { key: "net_profit_margin_min", label: "Net Profit Margin",   direction: "min", defaultVal: 0.08,  fmt: "pct", step: 0.01,  group: "quality" },
  { key: "debt_to_equity_max", label: "Debt / Equity",          direction: "max", defaultVal: 1.0,   fmt: "num", step: 0.1,   group: "quality" },
  { key: "promoter_holding_min", label: "Promoter Holding",     direction: "min", defaultVal: 0.50,  fmt: "pct", step: 0.05,  group: "quality" },
  // Growth
  { key: "revenue_growth_1y_min", label: "Revenue Growth 1Y",   direction: "min", defaultVal: 0.10,  fmt: "pct", step: 0.01,  group: "growth" },
  { key: "eps_growth_1y_min",  label: "EPS Growth 1Y",          direction: "min", defaultVal: 0.10,  fmt: "pct", step: 0.01,  group: "growth" },
  { key: "earnings_growth_forward_min", label: "Forward Earnings Growth", direction: "min", defaultVal: 0.10, fmt: "pct", step: 0.01, group: "growth" },
  // Other
  { key: "dividend_yield_min", label: "Dividend Yield",         direction: "min", defaultVal: 0.02,  fmt: "pct", step: 0.005, group: "other" },
  { key: "near_52w_high_pct",  label: "Near 52W High (%)",      direction: "min", defaultVal: 0.85,  fmt: "pct", step: 0.05,  group: "other" },
  { key: "market_cap_min_cr",  label: "Market Cap Min (Cr)",    direction: "min", defaultVal: 1000,  fmt: "cap", step: 500,   group: "other" },
  { key: "market_cap_max_cr",  label: "Market Cap Max (Cr)",    direction: "max", defaultVal: 50000, fmt: "cap", step: 1000,  group: "other" },
];

interface WeightMeta {
  key: string;
  label: string;
}

const WEIGHTS: WeightMeta[] = [
  { key: "pe",               label: "P/E Ratio" },
  { key: "pb",               label: "P/B Ratio" },
  { key: "forward_pe",       label: "Forward P/E" },
  { key: "roe",              label: "ROE" },
  { key: "margin",           label: "Profit Margin" },
  { key: "debt",             label: "Low Debt" },
  { key: "revenue_growth",   label: "Revenue Growth" },
  { key: "eps_growth",       label: "EPS Growth" },
  { key: "dividend_yield",   label: "Dividend Yield" },
  { key: "promoter_holding", label: "Promoter Holding" },
  { key: "near_52w_high",    label: "Near 52W High" },
];

const STRATEGY_TYPES = [
  { value: "value",    label: "Value" },
  { value: "growth",   label: "Growth" },
  { value: "quality",  label: "Quality" },
  { value: "momentum", label: "Momentum" },
  { value: "dividend", label: "Dividend" },
  { value: "custom",   label: "Custom" },
];

const GROUP_LABELS: Record<string, string> = {
  valuation: "Valuation",
  quality: "Quality & Stability",
  growth: "Growth",
  other: "Income, Momentum & Size",
};

/* ─── component ───────────────────────────────────────────────── */

export interface StrategyFormData {
  name: string;
  description: string;
  strategy_type: string;
  config_json: {
    filters: Record<string, number>;
    weights: Record<string, number>;
    signal_rules: string;
  };
}

interface StrategyBuilderProps {
  initial?: StrategyFormData | null;
  editId?: number | null;
  onSave: (data: StrategyFormData, editId: number | null) => Promise<void>;
  onCancel: () => void;
  saving: boolean;
}

export default function StrategyBuilder({ initial, editId, onSave, onCancel, saving }: StrategyBuilderProps) {
  const [name, setName] = useState(initial?.name ?? "");
  const [description, setDescription] = useState(initial?.description ?? "");
  const [strategyType, setStrategyType] = useState(initial?.strategy_type ?? "custom");
  const [signalRules, setSignalRules] = useState(initial?.config_json?.signal_rules ?? "");

  const [enabledFilters, setEnabledFilters] = useState<Record<string, boolean>>({});
  const [filterValues, setFilterValues] = useState<Record<string, number>>({});
  const [weightValues, setWeightValues] = useState<Record<string, number>>({});

  useEffect(() => {
    const initFilters = initial?.config_json?.filters ?? {};
    const initWeights = initial?.config_json?.weights ?? {};

    const enabled: Record<string, boolean> = {};
    const vals: Record<string, number> = {};
    for (const f of FILTERS) {
      if (f.key in initFilters) {
        enabled[f.key] = true;
        vals[f.key] = initFilters[f.key];
      } else {
        enabled[f.key] = false;
        vals[f.key] = f.defaultVal;
      }
    }
    setEnabledFilters(enabled);
    setFilterValues(vals);

    const rawWv: Record<string, number> = {};
    for (const w of WEIGHTS) {
      rawWv[w.key] = initWeights[w.key] ?? 0;
    }
    if (initWeights["growth"] && !initWeights["revenue_growth"] && !initWeights["eps_growth"]) {
      const half = initWeights["growth"] / 2;
      rawWv["revenue_growth"] = half;
      rawWv["eps_growth"] = half;
    }
    const maxRaw = Math.max(...Object.values(rawWv), 0.01);
    const wv: Record<string, number> = {};
    for (const w of WEIGHTS) {
      wv[w.key] = rawWv[w.key] > 0 ? Math.max(1, Math.round((rawWv[w.key] / maxRaw) * 10)) : 0;
    }
    setWeightValues(wv);
  }, [initial]);

  const totalWeight = Object.values(weightValues).reduce((s, v) => s + v, 0);

  function handleSave() {
    const filters: Record<string, number> = {};
    for (const f of FILTERS) {
      if (enabledFilters[f.key]) filters[f.key] = filterValues[f.key];
    }
    const weights: Record<string, number> = {};
    for (const w of WEIGHTS) {
      if (weightValues[w.key] > 0 && totalWeight > 0) {
        weights[w.key] = Math.round((weightValues[w.key] / totalWeight) * 1000) / 1000;
      }
    }
    onSave({
      name,
      description,
      strategy_type: strategyType,
      config_json: { filters, weights, signal_rules: signalRules },
    }, editId ?? null);
  }

  const groups = ["valuation", "quality", "growth", "other"] as const;

  return (
    <div className="fixed inset-0 bg-black/70 z-50 flex items-start justify-center p-4 overflow-auto">
      <div className="bg-gray-900 border border-gray-800 rounded-lg max-w-3xl w-full my-4">
        {/* Header */}
        <div className="p-4 border-b border-gray-800 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-white">
            {editId ? "Edit Strategy" : "Create Strategy"}
          </h2>
          <button onClick={onCancel} className="text-gray-400 hover:text-white text-xl leading-none">×</button>
        </div>

        <div className="p-4 space-y-6 max-h-[calc(100vh-160px)] overflow-y-auto">
          {/* Section 1: Basics */}
          <div>
            <h3 className="text-sm font-semibold text-gray-300 mb-3 uppercase tracking-wide">Basics</h3>
            <div className="space-y-3">
              <div>
                <label className="block text-xs text-gray-400 mb-1">Name *</label>
                <input
                  value={name}
                  onChange={e => setName(e.target.value)}
                  placeholder="e.g. My Value Strategy"
                  className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded text-sm text-white placeholder-gray-600 focus:border-blue-500 focus:outline-none"
                />
              </div>
              <div>
                <label className="block text-xs text-gray-400 mb-1">Description</label>
                <textarea
                  value={description}
                  onChange={e => setDescription(e.target.value)}
                  rows={2}
                  placeholder="Describe your investment philosophy..."
                  className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded text-sm text-white placeholder-gray-600 focus:border-blue-500 focus:outline-none resize-none"
                />
              </div>
              <div>
                <label className="block text-xs text-gray-400 mb-1">Type</label>
                <div className="flex flex-wrap gap-2">
                  {STRATEGY_TYPES.map(t => (
                    <button
                      key={t.value}
                      onClick={() => setStrategyType(t.value)}
                      className={`px-3 py-1.5 text-xs rounded-full border transition-colors ${
                        strategyType === t.value
                          ? "bg-blue-600 border-blue-500 text-white"
                          : "bg-gray-800 border-gray-700 text-gray-400 hover:border-gray-600"
                      }`}
                    >
                      {t.label}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          </div>

          {/* Section 2: Filters */}
          <div>
            <h3 className="text-sm font-semibold text-gray-300 mb-1 uppercase tracking-wide">Filters</h3>
            <p className="text-xs text-gray-500 mb-3">Toggle on filters to screen stocks. Only enabled filters are applied.</p>
            {groups.map(group => (
              <div key={group} className="mb-4">
                <div className="text-xs font-medium text-gray-500 uppercase mb-2">{GROUP_LABELS[group]}</div>
                <div className="space-y-1.5">
                  {FILTERS.filter(f => f.group === group).map(f => (
                    <div
                      key={f.key}
                      className={`flex items-center gap-3 px-3 py-2 rounded border transition-colors ${
                        enabledFilters[f.key]
                          ? "bg-gray-800/80 border-gray-700"
                          : "bg-gray-900/50 border-gray-800/50"
                      }`}
                    >
                      <input
                        type="checkbox"
                        checked={enabledFilters[f.key] || false}
                        onChange={() => setEnabledFilters(prev => ({ ...prev, [f.key]: !prev[f.key] }))}
                        className="accent-blue-500"
                      />
                      <span className={`text-sm flex-1 ${enabledFilters[f.key] ? "text-gray-200" : "text-gray-500"}`}>
                        {f.label}
                      </span>
                      <span className="text-xs text-gray-500 w-6 text-center">
                        {f.direction === "max" ? "≤" : "≥"}
                      </span>
                      <input
                        type="number"
                        disabled={!enabledFilters[f.key]}
                        value={f.fmt === "pct" ? Math.round(filterValues[f.key] * 1000) / 10 : filterValues[f.key]}
                        onChange={e => {
                          const raw = parseFloat(e.target.value);
                          if (isNaN(raw)) return;
                          setFilterValues(prev => ({
                            ...prev,
                            [f.key]: f.fmt === "pct" ? raw / 100 : raw,
                          }));
                        }}
                        step={f.fmt === "pct" ? (f.step * 100) : f.step}
                        className="w-24 px-2 py-1 bg-gray-700 border border-gray-600 rounded text-sm text-right text-white disabled:opacity-30 focus:border-blue-500 focus:outline-none"
                      />
                      <span className="text-xs text-gray-500 w-8">
                        {f.fmt === "pct" ? "%" : f.fmt === "cap" ? "Cr" : ""}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>

          {/* Section 3: Scoring Weights */}
          <div>
            <h3 className="text-sm font-semibold text-gray-300 mb-1 uppercase tracking-wide">Scoring Weights</h3>
            <p className="text-xs text-gray-500 mb-3">
              Set relative importance for each metric (0 = excluded). Weights are normalized automatically.
            </p>
            <div className="space-y-2">
              {WEIGHTS.map(w => {
                const val = weightValues[w.key] ?? 0;
                const pct = totalWeight > 0 ? Math.round((val / totalWeight) * 100) : 0;
                return (
                  <div key={w.key} className="flex items-center gap-3">
                    <span className="text-sm text-gray-300 w-36 shrink-0">{w.label}</span>
                    <input
                      type="range"
                      min={0}
                      max={10}
                      step={1}
                      value={val}
                      onChange={e => setWeightValues(prev => ({ ...prev, [w.key]: parseInt(e.target.value) }))}
                      className="flex-1 accent-blue-500"
                    />
                    <span className="text-xs text-gray-400 w-8 text-right font-mono">{val}</span>
                    {val > 0 && totalWeight > 0 && (
                      <span className="text-xs text-blue-400 w-10 text-right font-mono">{pct}%</span>
                    )}
                    {(val === 0 || totalWeight === 0) && (
                      <span className="text-xs text-gray-600 w-10 text-right">--</span>
                    )}
                  </div>
                );
              })}
            </div>
            {totalWeight > 0 && (
              <div className="mt-3 flex gap-0.5 h-2 rounded overflow-hidden">
                {WEIGHTS.filter(w => weightValues[w.key] > 0).map(w => {
                  const pct = (weightValues[w.key] / totalWeight) * 100;
                  return (
                    <div
                      key={w.key}
                      style={{ width: `${pct}%` }}
                      className="bg-blue-600 first:rounded-l last:rounded-r"
                      title={`${w.label}: ${pct.toFixed(0)}%`}
                    />
                  );
                })}
              </div>
            )}
          </div>

          {/* Section 4: Signal Rules */}
          <div>
            <h3 className="text-sm font-semibold text-gray-300 mb-1 uppercase tracking-wide">AI Signal Rules</h3>
            <p className="text-xs text-gray-500 mb-3">
              Describe your buy/sell logic in plain English. The AI uses this when ranking stocks that pass your filters.
            </p>
            <textarea
              value={signalRules}
              onChange={e => setSignalRules(e.target.value)}
              rows={3}
              placeholder='e.g. BUY if PE < 15 AND PB < 1.5 AND D/E < 0.5. SELL if PE > 25 or fundamentals deteriorate.'
              className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded text-sm text-white placeholder-gray-600 focus:border-blue-500 focus:outline-none resize-none font-mono"
            />
          </div>
        </div>

        {/* Footer */}
        <div className="p-4 border-t border-gray-800 flex items-center justify-between">
          <button
            onClick={onCancel}
            className="px-4 py-2 text-sm text-gray-400 hover:text-white transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={saving || !name.trim()}
            className="px-6 py-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-40 text-white text-sm rounded-md transition-colors"
          >
            {saving ? "Saving..." : editId ? "Update Strategy" : "Create Strategy"}
          </button>
        </div>
      </div>
    </div>
  );
}
