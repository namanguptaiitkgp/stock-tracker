"use client";

import InvestmentDecision from "../InvestmentDecision";

interface Props {
  symbol: string;
  exchange: string;
}

export default function AnalysisTab({ symbol, exchange }: Props) {
  return (
    <div className="space-y-4">
      <InvestmentDecision symbol={symbol} exchange={exchange} />
    </div>
  );
}
