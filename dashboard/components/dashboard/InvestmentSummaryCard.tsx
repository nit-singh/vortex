"use client";

interface InvestmentSummaryCardProps {
  totalPortfolioValue: string;
  investedAmount: string;
  unrealizedGains: string;
  unrealizedGainsPercent: string;
  todaysChange: string;
  todaysChangePercent: string;
}

export default function InvestmentSummaryCard({
  totalPortfolioValue = "₹8,45,230",
  investedAmount = "₹7,20,000",
  unrealizedGains = "+₹1,25,230",
  unrealizedGainsPercent = "+17.3%",
  todaysChange = "+₹2,450",
  todaysChangePercent = "+0.42%",
}: InvestmentSummaryCardProps) {
  return (
    <div className="bg-[#161616] rounded-lg border border-[#2a2a2a]">
      <div className="border-b border-[#2a2a2a] p-4">
        <h3 className="text-white font-medium text-base mb-1">
          Investment Summary
        </h3>
        <p className="text-[#666666] text-xs">Total portfolio overview</p>
      </div>
      <div className="p-4">
        <div className="mb-4">
          <p className="text-[#666666] text-xs mb-1">Total Portfolio Value</p>
          <p className="text-white text-2xl font-medium">
            {totalPortfolioValue}
          </p>
        </div>
        <div className="space-y-3">
          <div className="flex justify-between items-center border-b border-[#2a2a2a] pb-2">
            <span className="text-[#999999] text-sm">Invested Amount</span>
            <span className="text-white text-sm font-medium">
              {investedAmount}
            </span>
          </div>
          <div className="flex justify-between items-center border-b border-[#2a2a2a] pb-2">
            <span className="text-[#999999] text-sm">
              Unrealized Gains/Loss
            </span>
            <span
              className={`text-sm font-medium ${
                unrealizedGains.startsWith("+") ||
                (unrealizedGains.startsWith("₹") &&
                  !unrealizedGains.startsWith("-"))
                  ? "text-[#00b05e]"
                  : unrealizedGains.startsWith("-")
                  ? "text-[#fb2c36]"
                  : "text-[#00b05e]"
              }`}
            >
              {unrealizedGains} ({unrealizedGainsPercent})
            </span>
          </div>
          <div className="flex justify-between items-center">
            <span className="text-[#999999] text-sm">Today&apos;s Change</span>
            <span
              className={`text-sm font-medium ${
                todaysChange.startsWith("+") ||
                (todaysChange.startsWith("₹") && !todaysChange.startsWith("-"))
                  ? "text-[#00b05e]"
                  : todaysChange.startsWith("-")
                  ? "text-[#fb2c36]"
                  : "text-[#00b05e]"
              }`}
            >
              {todaysChange} ({todaysChangePercent})
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}
