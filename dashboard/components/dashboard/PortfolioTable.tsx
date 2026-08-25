"use client";

import { useRouter } from "next/navigation";
import { TrendingUp, TrendingDown } from "lucide-react";

interface PortfolioRow {
  company: string;
  sector: string;
  exchange: string;
  riskRating: "Low" | "Medium" | "High";
  price: string;
  dailyChange: string;
  dailyChangePercent: string;
  returns: string;
  trend?: "up" | "down";
}

interface PortfolioTableProps {
  rows?: PortfolioRow[];
  showPartial?: boolean; // If true, show only 3 rows with "View more" link
}

const defaultRows: PortfolioRow[] = [
  {
    company: "RELIANCE",
    sector: "Energy",
    exchange: "NSE",
    riskRating: "Medium",
    price: "₹2,659.55",
    dailyChange: "+1.23%",
    dailyChangePercent: "+1.23%",
    returns: "+15.8%",
    trend: "up",
  },
  {
    company: "ABC Finance",
    sector: "Fintech",
    exchange: "NSE",
    riskRating: "Low",
    price: "₹148.3",
    dailyChange: "+0.64%",
    dailyChangePercent: "+0.64%",
    returns: "+8.2%",
    trend: "up",
  },
  {
    company: "INFY",
    sector: "IT",
    exchange: "BSE",
    riskRating: "Medium",
    price: "₹1,535.2",
    dailyChange: "-0.35%",
    dailyChangePercent: "-0.35%",
    returns: "-2.1%",
    trend: "down",
  },
  {
    company: "TCS",
    sector: "IT",
    exchange: "NSE",
    riskRating: "Low",
    price: "₹3,842.1",
    dailyChange: "+3.34%",
    dailyChangePercent: "+3.34%",
    returns: "+22.6%",
    trend: "up",
  },
  {
    company: "ADANI PORT",
    sector: "Infrastructure",
    exchange: "BSE",
    riskRating: "High",
    price: "₹1,234.75",
    dailyChange: "-1.89%",
    dailyChangePercent: "-1.89%",
    returns: "-5.3%",
    trend: "down",
  },
  {
    company: "HDFC BANK",
    sector: "Banking",
    exchange: "NSE",
    riskRating: "Low",
    price: "₹1,654.8",
    dailyChange: "+2.15%",
    dailyChangePercent: "+2.15%",
    returns: "+12.4%",
    trend: "up",
  },
];

const getRiskColor = (rating: string) => {
  switch (rating) {
    case "Low":
      return "bg-[rgba(0,176,94,0.1)] text-[#00b05e]";
    case "Medium":
      return "bg-[rgba(240,177,0,0.1)] text-[#f0b100]";
    case "High":
      return "bg-[rgba(251,44,54,0.1)] text-[#fb2c36]";
    default:
      return "bg-[#1a1a1a] text-[#999999]";
  }
};

const getChangeColor = (change: string) => {
  return change.startsWith("+") ? "text-[#00b05e]" : "text-[#fb2c36]";
};

export default function PortfolioTable({
  rows = defaultRows,
  showPartial = false,
}: PortfolioTableProps) {
  const router = useRouter();
  const MAX_ROWS_TO_SHOW = 3; // Show only 3 rows on dashboard
  const displayedRows = showPartial ? rows.slice(0, MAX_ROWS_TO_SHOW) : rows;
  const hasMore = showPartial && rows.length > MAX_ROWS_TO_SHOW;

  const handleStockClick = (company: string) => {
    // Convert company name to ticker/symbol for URL
    const ticker = company.replace(/\s+/g, "-").toLowerCase();
    router.push(`/consumer/stocks/${ticker}`);
  };

  const handleViewAll = () => {
    router.push("/consumer/portfolio");
  };

  return (
    <div className="bg-[#161616] rounded-lg border border-[#2a2a2a]">
      <div className="border-b border-[#1c1c1c] p-4 flex items-center justify-between">
        <div>
          <h3 className="text-white font-medium text-base mb-1">
            Your Portfolio
          </h3>
          <p className="text-[#666666] text-xs">Real-time portfolio tracking</p>
        </div>
        {showPartial && (
          <button
            onClick={handleViewAll}
            className="text-[#00b05e] text-xs hover:underline"
          >
            View All →
          </button>
        )}
      </div>
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr className="border-b border-[#1c1c1c]">
              <th className="text-left p-3 text-[#999999] text-xs font-bold uppercase tracking-wider">
                Company
              </th>
              <th className="text-left p-3 text-[#999999] text-xs font-bold uppercase tracking-wider">
                Sector
              </th>
              <th className="text-left p-3 text-[#999999] text-xs font-bold uppercase tracking-wider">
                Exchange
              </th>
              <th className="text-left p-3 text-[#999999] text-xs font-bold uppercase tracking-wider">
                Risk Rating
              </th>
              <th className="text-right p-3 text-[#999999] text-xs font-bold uppercase tracking-wider">
                Price
              </th>
              <th className="text-center p-3 text-[#999999] text-xs font-bold uppercase tracking-wider">
                Trend
              </th>
              <th className="text-right p-3 text-[#999999] text-xs font-bold uppercase tracking-wider">
                Daily Change
              </th>
              <th className="text-right p-3 text-[#999999] text-xs font-bold uppercase tracking-wider">
                Returns
              </th>
            </tr>
          </thead>
          <tbody>
            {displayedRows.map((row, idx) => (
              <tr
                key={idx}
                className="border-b border-[#1c1c1c] hover:bg-[#1a1a1a] cursor-pointer transition-colors"
                onClick={() => handleStockClick(row.company)}
              >
                <td className="p-3">
                  <span className="text-white text-sm hover:text-[#00b05e] transition-colors">
                    {row.company}
                  </span>
                </td>
                <td className="p-3">
                  <span className="text-[#cccccc] text-sm">{row.sector}</span>
                </td>
                <td className="p-3">
                  <span className="bg-[#1a1a1a] px-2 py-1 rounded text-[#999999] text-xs">
                    {row.exchange}
                  </span>
                </td>
                <td className="p-3">
                  <span
                    className={`px-2 py-1 rounded text-xs ${getRiskColor(
                      row.riskRating
                    )}`}
                  >
                    {row.riskRating}
                  </span>
                </td>
                <td className="p-3 text-right">
                  <span className="text-white text-sm">{row.price}</span>
                </td>
                <td className="p-3 text-center">
                  <div className="flex items-center justify-center">
                    {row.trend === "up" ? (
                      <TrendingUp className="w-4 h-4 text-[#00b05e]" />
                    ) : (
                      <TrendingDown className="w-4 h-4 text-[#fb2c36]" />
                    )}
                  </div>
                </td>
                <td className="p-3 text-right">
                  <div className="flex items-center justify-end gap-1">
                    {row.dailyChange.startsWith("+") ? (
                      <TrendingUp className="w-3 h-3 text-[#00b05e]" />
                    ) : (
                      <TrendingDown className="w-3 h-3 text-[#fb2c36]" />
                    )}
                    <span
                      className={`text-sm font-normal ${getChangeColor(
                        row.dailyChange
                      )}`}
                    >
                      {row.dailyChangePercent}
                    </span>
                  </div>
                </td>
                <td className="p-3 text-right">
                  <span
                    className={`text-sm font-normal ${getChangeColor(
                      row.returns
                    )}`}
                  >
                    {row.returns}
                  </span>
                </td>
              </tr>
            ))}
            {hasMore && (
              <tr>
                <td colSpan={8} className="p-3 text-center">
                  <button
                    onClick={handleViewAll}
                    className="text-[#00b05e] text-xs hover:underline"
                  >
                    View {rows.length - MAX_ROWS_TO_SHOW} more...
                  </button>
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
