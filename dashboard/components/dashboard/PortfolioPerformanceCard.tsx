"use client";

import { useRouter } from "next/navigation";

interface Performer {
  ticker: string;
  change: string;
  changePercent: string;
}

interface PortfolioPerformanceCardProps {
  bestPerformers?: Performer[];
}

const defaultPerformers: Performer[] = [
  { ticker: "RELIANCE", change: "+1.23%", changePercent: "+1.23%" },
  { ticker: "ABC Finance", change: "+3.11%", changePercent: "+3.11%" },
  { ticker: "INFY", change: "+0.92%", changePercent: "+0.92%" },
  { ticker: "ICICI Bank", change: "+1.92%", changePercent: "+1.92%" },
];

export default function PortfolioPerformanceCard({
  bestPerformers = defaultPerformers,
}: PortfolioPerformanceCardProps) {
  const router = useRouter();

  const handleViewAll = () => {
    router.push("/consumer/portfolio");
  };

  // Show best performers if available, otherwise show default
  const performersToShow =
    bestPerformers.length > 0 ? bestPerformers : defaultPerformers;

  return (
    <div className="bg-[#161616] rounded-lg border border-[#2a2a2a] h-full">
      <div className="p-4">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-white font-medium text-base">
            Portfolio Performance
          </h3>
          <button
            onClick={handleViewAll}
            className="text-[#00b05e] text-xs hover:underline"
          >
            View All →
          </button>
        </div>
        <div>
          <p className="text-[#999999] text-xs mb-2 uppercase">
            BEST PERFORMERS
          </p>
          <div className="space-y-2">
            {performersToShow.length > 0 ? (
              performersToShow.map((performer, idx) => {
                const isPositive = performer.changePercent.startsWith("+");
                return (
                  <div
                    key={idx}
                    className="flex items-center justify-between py-1"
                  >
                    <span className="text-[#cccccc] text-sm">
                      {performer.ticker}
                    </span>
                    <div
                      className={`px-2 py-1 rounded text-xs ${
                        isPositive
                          ? "bg-[rgba(0,176,94,0.1)] text-[#00b05e]"
                          : "bg-[rgba(239,68,68,0.1)] text-[#ef4444]"
                      }`}
                    >
                      {performer.changePercent}
                    </div>
                  </div>
                );
              })
            ) : (
              <div className="text-[#666666] text-xs py-2">
                No performance data available
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
