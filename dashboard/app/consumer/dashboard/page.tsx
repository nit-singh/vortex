"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Sidebar from "@/components/dashboard/Sidebar";
import InvestmentSummaryCard from "@/components/dashboard/InvestmentSummaryCard";
import PortfolioPerformanceCard from "@/components/dashboard/PortfolioPerformanceCard";
import PortfolioTable from "@/components/dashboard/PortfolioTable";
import ChatbotButton from "@/components/chatbot/ChatbotButton";
import RiskScoreBadge from "@/components/dashboard/RiskScoreBadge";
import KYCStatusBadge from "@/components/dashboard/KYCStatusBadge";
import NotificationDropdown from "@/components/alerts/NotificationDropdown";
import SlidingAlert from "@/components/alerts/SlidingAlert";
import { Settings, User } from "lucide-react";
import { alertsApi, portfolioApi } from "@/lib/api";

interface Alert {
  _id: string;
  title: string;
  message: string;
  severity: "info" | "minor" | "major" | "critical";
  created_at: string;
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

export default function ConsumerDashboard() {
  const router = useRouter();
  const [userName, setUserName] = useState("Daksh");
  const [userEmail, setUserEmail] = useState("");
  const [userId, setUserId] = useState<string>("");
  const [currentAlert, setCurrentAlert] = useState<Alert | null>(null);
  const [lastAlertId, setLastAlertId] = useState<string | null>(null);
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null);
  const [calculatedMetrics, setCalculatedMetrics] =
    useState<CalculatedMetrics | null>(null);
  const [portfolioLoading, setPortfolioLoading] = useState(true);
  const [portfolioMessage, setPortfolioMessage] = useState<string | null>(null);

  useEffect(() => {
    const email = localStorage.getItem("userEmail");
    const name = localStorage.getItem("userName");
    const id = localStorage.getItem("userId");
    if (email) setUserEmail(email);
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

  // Poll for new alerts
  useEffect(() => {
    if (!userId) return;

    const pollAlerts = async () => {
      try {
        const data = await alertsApi.getUnreadAlerts(userId, 1);
        if (data.alerts && data.alerts.length > 0) {
          const latestAlert = data.alerts[0];
          // Only show if it's a new alert
          if (latestAlert._id !== lastAlertId) {
            setCurrentAlert(latestAlert);
            setLastAlertId(latestAlert._id);
          }
        }
      } catch (error) {
        console.error("Failed to poll alerts:", error);
      }
    };

    pollAlerts();
    const interval = setInterval(pollAlerts, 10000); // Poll every 10 seconds
    return () => clearInterval(interval);
  }, [userId, lastAlertId]);

  const handleMarkAsRead = async (alertId: string) => {
    try {
      await alertsApi.markAsRead(alertId);
    } catch (error) {
      console.error("Failed to mark alert as read:", error);
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-b from-[#0d0d0d] to-[#121212]">
      <Sidebar userName={userName} />
      <div className="ml-64">
        {/* Header */}
        <div className="bg-[#0d0d0d] border-b border-[#1a1a1a] px-6 py-4">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-white font-medium text-base mb-1">
                Hi {userName}!
              </h1>
              <p className="text-[#666666] text-sm">
                Your personalized investment overview.
              </p>
            </div>
            <div className="flex items-center gap-3">
              {userId && <RiskScoreBadge userId={userId} />}
              {userId && <KYCStatusBadge userId={userId} />}
              {userId && (
                <NotificationDropdown
                  userId={userId}
                  onMarkAsRead={handleMarkAsRead}
                />
              )}
              <button className="w-9 h-9 rounded-lg hover:bg-[#1a1a1a] flex items-center justify-center transition-colors">
                <Settings className="w-[18px] h-[18px] text-[#999999]" />
              </button>
              <button className="w-9 h-9 rounded-lg hover:bg-[#1a1a1a] flex items-center justify-center transition-colors">
                <User className="w-[18px] h-[18px] text-[#999999]" />
              </button>
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
          ) : portfolio ? (
            <>
              {/* Top Cards Row */}
              <div className="grid grid-cols-2 gap-4 mb-4 items-stretch">
                <InvestmentSummaryCard
                  totalPortfolioValue={
                    calculatedMetrics?.total_portfolio_value
                      ? `₹${calculatedMetrics.total_portfolio_value.toLocaleString(
                          "en-IN",
                          { maximumFractionDigits: 0 }
                        )}`
                      : portfolio.final_portfolio_value
                      ? `₹${portfolio.final_portfolio_value.toLocaleString(
                          "en-IN",
                          { maximumFractionDigits: 0 }
                        )}`
                      : "₹0"
                  }
                  investedAmount={
                    calculatedMetrics?.invested_amount
                      ? `₹${calculatedMetrics.invested_amount.toLocaleString(
                          "en-IN",
                          { maximumFractionDigits: 0 }
                        )}`
                      : "₹0"
                  }
                  unrealizedGains={
                    calculatedMetrics?.unrealized_gain_loss !== undefined
                      ? `${
                          calculatedMetrics.unrealized_gain_loss >= 0 ? "+" : ""
                        }₹${Math.abs(
                          calculatedMetrics.unrealized_gain_loss
                        ).toLocaleString("en-IN", {
                          maximumFractionDigits: 0,
                        })}`
                      : "₹0"
                  }
                  unrealizedGainsPercent={
                    calculatedMetrics?.unrealized_gain_loss_percent !==
                    undefined
                      ? `${
                          calculatedMetrics.unrealized_gain_loss_percent >= 0
                            ? "+"
                            : ""
                        }${calculatedMetrics.unrealized_gain_loss_percent.toFixed(
                          2
                        )}%`
                      : portfolio.metrics && portfolio.metrics[0]?.total_return
                      ? `+${(portfolio.metrics[0].total_return * 100).toFixed(
                          2
                        )}%`
                      : "0%"
                  }
                  todaysChange={
                    calculatedMetrics?.today_change !== undefined
                      ? `${
                          calculatedMetrics.today_change >= 0 ? "+" : ""
                        }₹${Math.abs(
                          calculatedMetrics.today_change
                        ).toLocaleString("en-IN", {
                          maximumFractionDigits: 0,
                        })}`
                      : "+₹0"
                  }
                  todaysChangePercent={
                    calculatedMetrics?.today_change_percent !== undefined
                      ? `${
                          calculatedMetrics.today_change_percent >= 0 ? "+" : ""
                        }${calculatedMetrics.today_change_percent.toFixed(2)}%`
                      : "0%"
                  }
                />
                <PortfolioPerformanceCard
                  bestPerformers={
                    calculatedMetrics?.stock_returns_percent &&
                    portfolio.final_weights
                      ? Object.entries(calculatedMetrics.stock_returns_percent)
                          .filter(([ticker]) => {
                            const weight =
                              portfolio.final_weights?.[ticker] || 0;
                            return weight > 0.001; // Only non-zero allocations
                          })
                          .map(([ticker, returnPercent]) => {
                            const displayTicker = ticker.replace(".NS", "");
                            return {
                              ticker: displayTicker,
                              change: `${
                                returnPercent >= 0 ? "+" : ""
                              }${returnPercent.toFixed(2)}%`,
                              changePercent: `${
                                returnPercent >= 0 ? "+" : ""
                              }${returnPercent.toFixed(2)}%`,
                            };
                          })
                          .sort((a, b) => {
                            const aVal = parseFloat(
                              a.changePercent.replace(/[+%]/g, "")
                            );
                            const bVal = parseFloat(
                              b.changePercent.replace(/[+%]/g, "")
                            );
                            return bVal - aVal; // Sort descending
                          })
                          .slice(0, 4) // Top 4 performers
                      : []
                  }
                />
              </div>

              {/* Portfolio Table */}
              {portfolio.final_weights &&
              Object.keys(portfolio.final_weights).length > 0 ? (
                <div className="mb-4">
                  <div className="mb-2 text-[#999999] text-xs">
                    Non-zero allocations:{" "}
                    {calculatedMetrics?.non_zero_allocations || 0}/
                    {calculatedMetrics?.total_allocations ||
                      Object.keys(portfolio.final_weights).length}
                  </div>
                  <PortfolioTable
                    showPartial={true}
                    rows={Object.entries(portfolio.final_weights)
                      .filter(([_, weight]) => weight > 0.001) // Filter out very small weights
                      .map(([ticker, weight]) => {
                        const stockReturn =
                          calculatedMetrics?.stock_returns_percent?.[ticker];
                        const stockPrice =
                          calculatedMetrics?.stock_prices?.[ticker] || 0;
                        const dailyChange =
                          calculatedMetrics?.stock_daily_changes?.[ticker] || 0;
                        const dailyChangePercent = dailyChange * 100;
                        const sector =
                          calculatedMetrics?.stock_sectors?.[ticker] ||
                          "Unknown";
                        return {
                          company: ticker,
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
                              ? `${
                                  stockReturn >= 0 ? "+" : ""
                                }${stockReturn.toFixed(2)}%`
                              : `${(weight * 100).toFixed(2)}%`,
                        };
                      })
                      .slice(0, 5)} // Show top 5 holdings
                  />
                </div>
              ) : (
                <div className="mb-4">
                  <PortfolioTable showPartial={true} />
                </div>
              )}
            </>
          ) : null}
        </div>
      </div>

      {/* Chatbot Button */}
      <ChatbotButton />

      {/* Sliding Alert */}
      {currentAlert && (
        <SlidingAlert
          alert={currentAlert}
          onClose={() => setCurrentAlert(null)}
          onMarkAsRead={handleMarkAsRead}
        />
      )}
    </div>
  );
}
