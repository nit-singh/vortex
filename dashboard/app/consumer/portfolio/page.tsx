"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Sidebar from "@/components/dashboard/Sidebar";
import PortfolioTable from "@/components/dashboard/PortfolioTable";
import { portfolioApi } from "@/lib/api";

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

interface Portfolio {
  metrics?: Array<{
    batch?: number;
    sharpe_ratio?: number;
    max_drawdown?: number;
    total_return?: number;
    annualized_return?: number;
    volatility?: number;
  }>;
  final_portfolio_value?: number;
  peak_value?: number;
  current_value?: number;
  final_weights?: Record<string, number>;
}

interface CalculatedMetrics {
  invested_amount?: number;
  total_portfolio_value?: number;
  unrealized_gain_loss?: number;
  unrealized_gain_loss_percent?: number;
  today_change?: number;
  today_change_percent?: number;
  non_zero_allocations?: number;
  total_allocations?: number;
  stock_values?: Record<string, number>;
  stock_initial_investments?: Record<string, number>;
  stock_returns?: Record<string, number>;
  stock_returns_percent?: Record<string, number>;
  stock_prices?: Record<string, number>;
  stock_daily_changes?: Record<string, number>;
  stock_sectors?: Record<string, string>;
}

export default function PortfolioPage() {
  const router = useRouter();
  const [userName, setUserName] = useState("Daksh");
  const [userId, setUserId] = useState<string>("");
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null);
  const [calculatedMetrics, setCalculatedMetrics] =
    useState<CalculatedMetrics | null>(null);
  const [portfolioRows, setPortfolioRows] = useState<PortfolioRow[]>([]);
  const [portfolioLoading, setPortfolioLoading] = useState(true);
  const [portfolioMessage, setPortfolioMessage] = useState<string | null>(null);

  useEffect(() => {
    const name = localStorage.getItem("userName");
    const id = localStorage.getItem("userId");
    if (name) setUserName(name);
    if (id) setUserId(id);

    // Check if questionnaire is submitted
    const isQuestionnaireSubmitted = localStorage.getItem(
      "isQuestionnaireSubmitted"
    );
    if (isQuestionnaireSubmitted !== "true") {
      router.push("/consumer/questionnaire");
      return;
    }
  }, [router]);

  // Fetch portfolio data
  useEffect(() => {
    if (!userId) return;

    const fetchPortfolio = async () => {
      try {
        setPortfolioLoading(true);
        const data = await portfolioApi.getUserPortfolio(userId);
        if (data.portfolio) {
          setPortfolio(data.portfolio);
          setCalculatedMetrics(data.calculated_metrics || null);
          setPortfolioMessage(null);
        } else {
          setPortfolio(null);
          setCalculatedMetrics(null);
          setPortfolioMessage(
            data.message ||
              "No portfolio allocated. Complete KYC Verification to generate a portfolio"
          );
        }
      } catch (error: any) {
        console.error("Failed to fetch portfolio:", error);
        setPortfolio(null);
        setCalculatedMetrics(null);
        setPortfolioMessage(
          error.response?.data?.message ||
            "No portfolio allocated. Complete KYC Verification to generate a portfolio"
        );
      } finally {
        setPortfolioLoading(false);
      }
    };

    fetchPortfolio();
  }, [userId]);

  // Transform portfolio data to table rows
  useEffect(() => {
    if (portfolio && calculatedMetrics && portfolio.final_weights) {
      const rows: PortfolioRow[] = Object.entries(portfolio.final_weights)
        .filter(([_, weight]) => weight > 0.001) // Only non-zero allocations
        .map(([ticker, weight]) => {
          const stockReturn = calculatedMetrics.stock_returns_percent?.[ticker];
          const stockPrice = calculatedMetrics.stock_prices?.[ticker] || 0;
          const dailyChange =
            calculatedMetrics.stock_daily_changes?.[ticker] || 0;
          const dailyChangePercent = dailyChange * 100;
          const sector = calculatedMetrics.stock_sectors?.[ticker] || "Unknown";

          // Remove .NS suffix for display
          const displayTicker = ticker.replace(".NS", "");

          return {
            company: displayTicker,
            sector: sector,
            exchange: "NSE",
            riskRating: "Medium" as const,
            price:
              stockPrice > 0
                ? `₹${stockPrice.toLocaleString("en-IN", {
                    maximumFractionDigits: 2,
                  })}`
                : "₹0",
            dailyChange:
              dailyChangePercent >= 0
                ? `+${dailyChangePercent.toFixed(2)}%`
                : `${dailyChangePercent.toFixed(2)}%`,
            dailyChangePercent:
              dailyChangePercent >= 0
                ? `+${dailyChangePercent.toFixed(2)}%`
                : `${dailyChangePercent.toFixed(2)}%`,
            returns:
              stockReturn !== undefined
                ? `${stockReturn >= 0 ? "+" : ""}${stockReturn.toFixed(2)}%`
                : `${(weight * 100).toFixed(2)}%`,
            trend: (dailyChangePercent >= 0 ? "up" : "down") as "up" | "down",
          };
        })
        .sort((a, b) => {
          // Sort by returns (descending)
          const aReturn = parseFloat(a.returns.replace(/[+%]/g, ""));
          const bReturn = parseFloat(b.returns.replace(/[+%]/g, ""));
          return bReturn - aReturn;
        });

      setPortfolioRows(rows);
    } else {
      setPortfolioRows([]);
    }
  }, [portfolio, calculatedMetrics]);

  return (
    <div className="min-h-screen bg-gradient-to-b from-[#0d0d0d] to-[#121212]">
      <Sidebar userName={userName} />
      <div className="ml-64">
        {/* Header */}
        <div className="bg-[#0d0d0d] border-b border-[#1a1a1a] px-6 py-4">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-white font-medium text-base mb-1">
                Portfolio
              </h1>
              <p className="text-[#666666] text-sm">
                Your complete investment portfolio
              </p>
            </div>
          </div>
        </div>

        {/* Main Content */}
        <div className="p-4">
          {portfolioLoading ? (
            <div className="flex items-center justify-center h-64">
              <div className="text-[#999999]">Loading portfolio...</div>
            </div>
          ) : portfolioMessage && !portfolio ? (
            <div className="bg-[#1a1a1a] border border-[#2a2a2a] rounded-lg p-8 text-center">
              <div className="text-[#999999] text-base mb-2">
                {portfolioMessage}
              </div>
              <p className="text-[#666666] text-sm">
                Please complete your KYC verification and wait for admin
                approval.
              </p>
            </div>
          ) : portfolioRows.length > 0 ? (
            <div className="mb-4">
              <div className="mb-4 text-[#999999] text-sm">
                Showing{" "}
                {calculatedMetrics?.non_zero_allocations ||
                  portfolioRows.length}{" "}
                of{" "}
                {calculatedMetrics?.total_allocations || portfolioRows.length}{" "}
                holdings
              </div>
              <PortfolioTable rows={portfolioRows} showPartial={false} />
            </div>
          ) : (
            <div className="bg-[#1a1a1a] border border-[#2a2a2a] rounded-lg p-8 text-center">
              <div className="text-[#999999] text-base mb-2">
                No portfolio data available
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
