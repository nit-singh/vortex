"use client";

import { useEffect, useState } from "react";
import { useRouter, useParams } from "next/navigation";
import Sidebar from "@/components/dashboard/Sidebar";
import ChatbotButton from "@/components/chatbot/ChatbotButton";
import {
  ArrowLeft,
  Bell,
  Settings,
  User,
  TrendingUp,
  TrendingDown,
  Download,
} from "lucide-react";
import { stockApi, portfolioApi } from "@/lib/api";
import axios from "axios";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

// Helper function to format markdown content
function formatMarkdown(markdown: string): string {
  const lines = markdown.split("\n");
  const output: string[] = [];
  let inTable = false;
  let tableRows: string[][] = [];
  let tableHeaders: string[] = [];

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trim();

    // Check for table rows
    if (line.startsWith("|") && line.endsWith("|")) {
      const cells = line
        .split("|")
        .map((cell) => cell.trim())
        .filter((cell) => cell.length > 0);

      // Check if it's a separator row
      if (cells.length > 0 && cells.every((cell) => /^-+$/.test(cell))) {
        // This is a separator, the previous line was headers
        if (output.length > 0 && output[output.length - 1].includes("|")) {
          // Extract headers from previous line
          const prevLine = output.pop() || "";
          tableHeaders = prevLine
            .replace(/<[^>]*>/g, "")
            .split("|")
            .map((cell) => cell.trim())
            .filter((cell) => cell.length > 0);
        }
        inTable = true;
        continue;
      }

      if (cells.length > 0) {
        if (!inTable) {
          // First row - treat as headers
          tableHeaders = cells;
          inTable = true;
        } else {
          // Data row
          tableRows.push(cells);
        }
        continue;
      }
    }

    // If we were in a table and hit a non-table line, close the table
    if (inTable) {
      if (tableHeaders.length > 0 || tableRows.length > 0) {
        let tableHtml =
          '<table class="w-full my-3 border-collapse markdown-table">';
        if (tableHeaders.length > 0) {
          tableHtml += "<thead><tr>";
          tableHeaders.forEach((header) => {
            tableHtml += `<th class="px-3 py-2 text-left text-[#999999] font-medium border-b border-neutral-700 bg-[#1a1a1a]">${formatInlineMarkdown(
              header
            )}</th>`;
          });
          tableHtml += "</tr></thead>";
        }
        if (tableRows.length > 0) {
          tableHtml += "<tbody>";
          tableRows.forEach((row) => {
            tableHtml += "<tr>";
            row.forEach((cell) => {
              tableHtml += `<td class="px-3 py-2 text-white border-b border-neutral-800">${formatInlineMarkdown(
                cell
              )}</td>`;
            });
            tableHtml += "</tr>";
          });
          tableHtml += "</tbody>";
        }
        tableHtml += "</table>";
        output.push(tableHtml);
        tableRows = [];
        tableHeaders = [];
        inTable = false;
      }
    }

    // Process non-table lines
    if (line.length > 0) {
      // Headers
      if (line.startsWith("### ")) {
        output.push(
          `<h3 class="text-white text-sm font-semibold mt-4 mb-2">${formatInlineMarkdown(
            line.substring(4)
          )}</h3>`
        );
      } else if (line.startsWith("## ")) {
        output.push(
          `<h2 class="text-white text-base font-bold mt-5 mb-3 border-b border-neutral-700 pb-2">${formatInlineMarkdown(
            line.substring(3)
          )}</h2>`
        );
      } else if (line.startsWith("# ")) {
        output.push(
          `<h1 class="text-white text-lg font-bold mt-6 mb-4">${formatInlineMarkdown(
            line.substring(2)
          )}</h1>`
        );
      } else if (line.startsWith("- ")) {
        // List item
        output.push(
          `<li class="ml-4 mb-1 text-[#e0e0e0]">${formatInlineMarkdown(
            line.substring(2)
          )}</li>`
        );
      } else {
        // Regular paragraph
        output.push(
          `<p class="mb-2 text-[#e0e0e0]">${formatInlineMarkdown(line)}</p>`
        );
      }
    } else {
      // Empty line
      output.push("<br />");
    }
  }

  // Handle table at end
  if (inTable && (tableHeaders.length > 0 || tableRows.length > 0)) {
    let tableHtml =
      '<table class="w-full my-3 border-collapse markdown-table">';
    if (tableHeaders.length > 0) {
      tableHtml += "<thead><tr>";
      tableHeaders.forEach((header) => {
        tableHtml += `<th class="px-3 py-2 text-left text-[#999999] font-medium border-b border-neutral-700 bg-[#1a1a1a]">${formatInlineMarkdown(
          header
        )}</th>`;
      });
      tableHtml += "</tr></thead>";
    }
    if (tableRows.length > 0) {
      tableHtml += "<tbody>";
      tableRows.forEach((row) => {
        tableHtml += "<tr>";
        row.forEach((cell) => {
          tableHtml += `<td class="px-3 py-2 text-white border-b border-neutral-800">${formatInlineMarkdown(
            cell
          )}</td>`;
        });
        tableHtml += "</tr>";
      });
      tableHtml += "</tbody>";
    }
    tableHtml += "</table>";
    output.push(tableHtml);
  }

  // Group consecutive list items
  let html = output.join("\n");
  html = html.replace(/(<li[^>]*>.*?<\/li>\s*)+/g, (match) => {
    return `<ul class="list-disc list-inside space-y-1 my-2 ml-4">${match}</ul>`;
  });

  // Clean up empty paragraphs
  html = html.replace(/<p[^>]*>\s*<\/p>/g, "");

  // Clean up multiple consecutive breaks
  html = html.replace(/(<br \/>\s*){3,}/g, "<br /><br />");

  return html;
}

// Helper to format inline markdown (bold, italic)
function formatInlineMarkdown(text: string): string {
  // Escape HTML
  let html = text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");

  // Bold (**text**)
  html = html.replace(
    /\*\*(.*?)\*\*/g,
    '<strong class="text-white font-semibold">$1</strong>'
  );

  // Italic (*text*) - but not if it's part of **
  html = html.replace(
    /(?<!\*)\*([^*]+?)\*(?!\*)/g,
    '<em class="text-[#cccccc]">$1</em>'
  );

  return html;
}

interface StockHistory {
  date: string;
  close: number;
  open: number;
  high: number;
  low: number;
  volume: number;
  daily_change: number;
}

interface StockData {
  ticker: string;
  sector: string;
  industry: string;
  current_price: number;
  current_change: number;
  history: StockHistory[];
}

interface PortfolioPosition {
  investedAmount: number;
  currentValue: number;
  totalGain: number;
  totalGainPercent: number;
  portfolioWeight: number;
}

export default function StockDetailPage() {
  const router = useRouter();
  const params = useParams();
  const symbol = params?.symbol as string;
  const [stockData, setStockData] = useState<StockData | null>(null);
  const [portfolioPosition, setPortfolioPosition] =
    useState<PortfolioPosition | null>(null);
  const [userName, setUserName] = useState("Daksh");
  const [userId, setUserId] = useState<string>("");
  const [timeRange, setTimeRange] = useState<"1W" | "1M">("1M");
  const [loading, setLoading] = useState(true);
  const [xaiData, setXaiData] = useState<{
    summary_points: string[];
    markdown: string | null;
    weight: number | null;
    as_of: string | null;
    llm_used: boolean;
    available: boolean;
  } | null>(null);

  useEffect(() => {
    const name = localStorage.getItem("userName");
    const id = localStorage.getItem("userId");
    if (name) setUserName(name);
    if (id) setUserId(id);
  }, []);

  useEffect(() => {
    if (!symbol) return;

    const fetchStockData = async () => {
      try {
        setLoading(true);
        console.log("Fetching stock data for symbol:", symbol);

        // Clean up symbol (remove .NS if present, API will add it)
        const cleanSymbol = symbol?.replace(".NS", "").toUpperCase();
        console.log("Cleaned symbol:", cleanSymbol);

        const data = await stockApi.getStockHistory(cleanSymbol);
        console.log("Stock data received:", data);

        // Validate response structure
        if (!data || !data.history) {
          console.error("Invalid stock data response:", data);
          setStockData(null);
          return;
        }

        // Ensure history is an array
        if (!Array.isArray(data.history)) {
          console.error("History is not an array:", data.history);
          setStockData(null);
          return;
        }

        setStockData(data);
      } catch (error: any) {
        console.error("Failed to fetch stock data:", error);
        console.error("Error details:", error.response?.data || error.message);
        console.error("Error stack:", error.stack);
        // Set stockData to null to show error state
        setStockData(null);
      } finally {
        setLoading(false);
      }
    };

    fetchStockData();
  }, [symbol]);

  useEffect(() => {
    if (!symbol) return;

    const fetchXaiData = async () => {
      try {
        const cleanSymbol = symbol?.replace(".NS", "").toUpperCase();
        const response = await axios.get(
          `${
            process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000"
          }/api/v1/stock/${cleanSymbol}/xai`
        );
        setXaiData({
          summary_points: response.data.summary_points || [],
          markdown: response.data.markdown || null,
          weight: response.data.weight || null,
          as_of: response.data.as_of || null,
          llm_used: response.data.llm_used || false,
          available: response.data.available || false,
        });
      } catch (error: any) {
        console.error("Failed to fetch XAI data:", error);
        setXaiData({
          summary_points: [],
          markdown: null,
          weight: null,
          as_of: null,
          llm_used: false,
          available: false,
        });
      }
    };

    fetchXaiData();
  }, [symbol]);

  useEffect(() => {
    if (!userId || !symbol || !stockData) return;

    const fetchPortfolioPosition = async () => {
      try {
        const portfolioData = await portfolioApi.getUserPortfolio(userId);
        if (portfolioData.portfolio && portfolioData.calculated_metrics) {
          const weights = portfolioData.portfolio.final_weights || {};
          const tickerKey = symbol.toUpperCase();
          const tickerWithNS = `${tickerKey}.NS`;

          // Try to find the ticker in portfolio (with or without .NS)
          const weight = weights[tickerKey] || weights[tickerWithNS] || 0;

          if (weight > 0.001) {
            const investedAmount =
              portfolioData.calculated_metrics.invested_amount || 0;
            const stockInitialInvestment =
              portfolioData.calculated_metrics.stock_initial_investments?.[
                tickerKey
              ] ||
              portfolioData.calculated_metrics.stock_initial_investments?.[
                tickerWithNS
              ] ||
              0;
            const stockValue =
              portfolioData.calculated_metrics.stock_values?.[tickerKey] ||
              portfolioData.calculated_metrics.stock_values?.[tickerWithNS] ||
              0;
            const stockReturn =
              portfolioData.calculated_metrics.stock_returns?.[tickerKey] ||
              portfolioData.calculated_metrics.stock_returns?.[tickerWithNS] ||
              0;
            const stockReturnPercent =
              portfolioData.calculated_metrics.stock_returns_percent?.[
                tickerKey
              ] ||
              portfolioData.calculated_metrics.stock_returns_percent?.[
                tickerWithNS
              ] ||
              0;

            setPortfolioPosition({
              investedAmount: stockInitialInvestment,
              currentValue: stockValue,
              totalGain: stockReturn,
              totalGainPercent: stockReturnPercent,
              portfolioWeight: weight * 100,
            });
          }
        }
      } catch (error) {
        console.error("Failed to fetch portfolio position:", error);
      }
    };

    fetchPortfolioPosition();
  }, [userId, symbol, stockData]);

  if (loading) {
    return (
      <div className="min-h-screen bg-gradient-to-b from-[#0d0d0d] to-[#121212]">
        <Sidebar userName={userName} />
        <div className="ml-64 flex items-center justify-center h-screen">
          <p className="text-white">Loading stock data...</p>
        </div>
      </div>
    );
  }

  if (!stockData) {
    return (
      <div className="min-h-screen bg-gradient-to-b from-[#0d0d0d] to-[#121212]">
        <Sidebar userName={userName} />
        <div className="ml-64 flex flex-col items-center justify-center h-screen">
          <p className="text-white text-lg mb-2">Failed to load stock data</p>
          <p className="text-[#666666] text-sm mb-4">Ticker: {symbol}</p>
          <button
            onClick={() => router.back()}
            className="px-4 py-2 bg-[#00b05e] text-white rounded-lg hover:bg-[#00a050] transition-colors"
          >
            Go Back
          </button>
        </div>
      </div>
    );
  }

  // Filter history based on time range
  const getFilteredHistory = () => {
    if (!stockData.history || stockData.history.length === 0) return [];

    // Sort history by date first
    const sortedHistory = [...stockData.history].sort((a, b) => {
      return new Date(a.date).getTime() - new Date(b.date).getTime();
    });

    // Get the latest date in the data
    const latestDate = new Date(sortedHistory[sortedHistory.length - 1].date);
    let cutoffDate = new Date(latestDate);

    switch (timeRange) {
      case "1W":
        cutoffDate.setDate(cutoffDate.getDate() - 7);
        break;
      case "1M":
        cutoffDate.setMonth(cutoffDate.getMonth() - 1);
        break;
    }

    // Filter based on the latest date in data, not today's date
    const filtered = sortedHistory.filter((item) => {
      const itemDate = new Date(item.date);
      return itemDate >= cutoffDate;
    });

    // If filtered is empty (data is too old), return last 30 days worth of data
    if (filtered.length === 0 && sortedHistory.length > 0) {
      const last30Days = sortedHistory.slice(-30);
      return last30Days;
    }

    return filtered;
  };

  const filteredHistory = getFilteredHistory();
  const chartData = filteredHistory.map((item) => ({
    date: new Date(item.date).toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
    }),
    close: Number(item.close) || 0,
    open: Number(item.open) || 0,
    high: Number(item.high) || 0,
    low: Number(item.low) || 0,
  }));

  // Debug logging
  console.log("Chart data points:", chartData.length);
  if (chartData.length > 0) {
    console.log("First point:", chartData[0]);
    console.log("Last point:", chartData[chartData.length - 1]);
  } else {
    console.log("No chart data! History length:", stockData?.history?.length);
    console.log("Filtered history length:", filteredHistory?.length);
  }

  // Debug logging
  console.log("Chart data:", chartData.length, "points");
  console.log("First few points:", chartData.slice(0, 3));

  const getRiskColor = (change: number) => {
    if (change > 0.05)
      return "bg-[rgba(251,44,54,0.1)] border-[rgba(251,44,54,0.3)] text-[#fb2c36]";
    if (change > 0)
      return "bg-[rgba(255,184,0,0.1)] border-[rgba(255,184,0,0.3)] text-[#ffb800]";
    return "bg-[rgba(0,176,94,0.1)] border-[#00b05e] text-[#00b05e]";
  };

  const getRiskRating = (change: number) => {
    if (Math.abs(change) > 0.05) return "High";
    if (Math.abs(change) > 0.02) return "Medium";
    return "Low";
  };

  const riskRating = getRiskRating(stockData.current_change);
  const changePercent = (stockData.current_change * 100).toFixed(2);
  const isPositive = stockData.current_change >= 0;

  // Calculate 52W high/low from history
  const prices = stockData.history.map((h) => h.close);
  const weekHigh52 = prices.length > 0 ? Math.max(...prices) : 0;
  const weekLow52 = prices.length > 0 ? Math.min(...prices) : 0;

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
              <button className="w-9 h-9 rounded-lg hover:bg-[#1a1a1a] flex items-center justify-center transition-colors">
                <Bell className="w-[18px] h-[18px] text-[#999999]" />
              </button>
              <button className="w-9 h-9 rounded-lg hover:bg-[#1a1a1a] flex items-center justify-center transition-colors">
                <Settings className="w-[18px] h-[18px] text-[#999999]" />
              </button>
              <button className="w-9 h-9 rounded-lg hover:bg-[#1a1a1a] flex items-center justify-center transition-colors">
                <User className="w-[18px] h-[18px] text-[#999999]" />
              </button>
            </div>
          </div>
        </div>

        {/* Stock Header */}
        <div className="bg-[#0c0c0c] border-b border-neutral-800 px-5 py-4">
          <div className="flex items-center gap-4">
            <button
              onClick={() => router.back()}
              className="w-6 h-6 bg-[#1a1a1a] rounded-md flex items-center justify-center hover:bg-[#2a2a2a] transition-colors"
            >
              <ArrowLeft className="w-3 h-3 text-[#999999]" />
            </button>
            <div className="flex-1">
              <div className="flex items-center gap-3 mb-2">
                <h2 className="text-white font-medium text-base">
                  {stockData.ticker}
                </h2>
                <div className="flex items-center gap-2">
                  <span className="px-2 py-1 rounded-full border text-[8px] bg-[rgba(26,58,92,0.3)] border-[#1a3a5c] text-[#5baaff]">
                    {stockData.sector}
                  </span>
                  <span
                    className={`px-2 py-1 rounded-full border text-[8px] ${getRiskColor(
                      stockData.current_change
                    )}`}
                  >
                    {riskRating} Risk
                  </span>
                </div>
              </div>
              <div className="flex items-center gap-3">
                <p className="text-white font-medium text-xl">
                  ₹
                  {stockData.current_price.toLocaleString("en-IN", {
                    maximumFractionDigits: 2,
                  })}
                </p>
                <div
                  className={`flex items-center gap-1 px-2 py-1 rounded text-[10px] ${
                    isPositive
                      ? "bg-[rgba(0,176,94,0.1)] text-[#00b05e]"
                      : "bg-[rgba(239,68,68,0.1)] text-[#ef4444]"
                  }`}
                >
                  {isPositive ? (
                    <TrendingUp className="w-3 h-3" />
                  ) : (
                    <TrendingDown className="w-3 h-3" />
                  )}
                  <span>
                    {isPositive ? "+" : ""}
                    {changePercent}%
                  </span>
                </div>
                <span className="text-[#666666] text-[9px]">Today</span>
              </div>
            </div>
          </div>
        </div>

        {/* Main Content */}
        <div className="p-4">
          <div className="grid grid-cols-3 gap-4">
            {/* Left Column - 2/3 width */}
            <div className="col-span-2 space-y-4">
              {/* Stock Chart */}
              <div className="bg-gradient-to-b from-[#2a2a2a] to-[#1c1c1c] rounded-lg shadow-lg p-[1px]">
                <div className="bg-[#161616] rounded-lg h-[400px] p-4">
                  <div className="flex gap-1 bg-[#0c0c0c] p-1 rounded-md mb-4 w-fit">
                    {(["1W", "1M"] as const).map((range) => (
                      <button
                        key={range}
                        onClick={() => setTimeRange(range)}
                        className={`px-3 py-1 rounded text-[9px] transition-colors ${
                          timeRange === range
                            ? "bg-[rgba(0,176,94,0.1)] border-b-2 border-[#00b05e] text-[#00b05e]"
                            : "text-[#999999] hover:text-white"
                        }`}
                      >
                        {range}
                      </button>
                    ))}
                  </div>
                  {chartData && chartData.length > 0 ? (
                    <ResponsiveContainer width="100%" height={320}>
                      <LineChart
                        data={chartData}
                        margin={{ top: 5, right: 10, left: 0, bottom: 5 }}
                      >
                        <CartesianGrid strokeDasharray="3 3" stroke="#2a2a2a" />
                        <XAxis
                          dataKey="date"
                          stroke="#666666"
                          style={{ fontSize: "10px" }}
                          angle={-45}
                          textAnchor="end"
                          height={60}
                        />
                        <YAxis
                          stroke="#666666"
                          style={{ fontSize: "10px" }}
                          domain={["dataMin", "dataMax"]}
                          tickFormatter={(value) => `₹${value.toFixed(0)}`}
                        />
                        <Tooltip
                          contentStyle={{
                            backgroundColor: "#1a1a1a",
                            border: "1px solid #2a2a2a",
                            borderRadius: "6px",
                            color: "#ffffff",
                          }}
                          formatter={(value: any) => [
                            `₹${Number(value).toFixed(2)}`,
                            "Close",
                          ]}
                        />
                        <Line
                          type="monotone"
                          dataKey="close"
                          stroke="#00b05e"
                          strokeWidth={2}
                          dot={false}
                          activeDot={{ r: 4 }}
                        />
                      </LineChart>
                    </ResponsiveContainer>
                  ) : (
                    <div className="h-[320px] bg-[#0c0c0c] rounded flex flex-col items-center justify-center">
                      <p className="text-[#666666] text-sm mb-2">
                        No chart data available
                      </p>
                      <p className="text-[#666666] text-xs">
                        History: {stockData?.history?.length || 0} points
                      </p>
                      <p className="text-[#666666] text-xs">
                        Filtered: {filteredHistory?.length || 0} points
                      </p>
                    </div>
                  )}
                </div>
              </div>

              {/* Bottom Row - Position and Company Stats */}
              <div className="grid grid-cols-2 gap-4">
                {/* Your Position */}
                {portfolioPosition ? (
                  <div className="bg-gradient-to-b from-[#2a2a2a] to-[#1c1c1c] rounded-lg shadow-lg p-[1px]">
                    <div className="bg-[#161616] rounded-lg h-[310px]">
                      <div className="border-b border-neutral-800 p-4">
                        <h3 className="text-white font-medium text-sm">
                          Your Position
                        </h3>
                      </div>
                      <div className="p-4 h-[calc(100%-73px)] flex flex-col">
                        <div className="flex items-center justify-between mb-6">
                          <div className="w-[151px] h-[151px] rounded-full bg-[#0c0c0c] flex items-center justify-center border-4 border-[#00b05e] border-t-transparent">
                            <div className="text-center">
                              <p
                                className={`font-medium text-xl ${
                                  portfolioPosition.totalGainPercent >= 0
                                    ? "text-[#00b05e]"
                                    : "text-[#ef4444]"
                                }`}
                              >
                                {portfolioPosition.totalGainPercent >= 0
                                  ? "+"
                                  : ""}
                                {portfolioPosition.totalGainPercent.toFixed(2)}%
                              </p>
                              <p className="text-[#666666] text-[10px]">
                                Total Returns
                              </p>
                            </div>
                          </div>
                          <div className="flex-1 ml-4 space-y-4">
                            <div className="text-right">
                              <p className="text-[#666666] text-[8px] mb-1">
                                Invested Amount
                              </p>
                              <p className="text-white text-xs font-medium">
                                ₹
                                {portfolioPosition.investedAmount.toLocaleString(
                                  "en-IN",
                                  { maximumFractionDigits: 0 }
                                )}
                              </p>
                            </div>
                            <div className="text-right">
                              <p className="text-[#666666] text-[8px] mb-1">
                                Current Value
                              </p>
                              <p className="text-white text-xs font-medium">
                                ₹
                                {portfolioPosition.currentValue.toLocaleString(
                                  "en-IN",
                                  { maximumFractionDigits: 0 }
                                )}
                              </p>
                            </div>
                            <div className="text-right">
                              <p className="text-[#666666] text-[8px] mb-1">
                                Total Gain
                              </p>
                              <p
                                className={`text-xs font-medium ${
                                  portfolioPosition.totalGain >= 0
                                    ? "text-[#00b05e]"
                                    : "text-[#ef4444]"
                                }`}
                              >
                                {portfolioPosition.totalGain >= 0 ? "+" : ""}₹
                                {Math.abs(
                                  portfolioPosition.totalGain
                                ).toLocaleString("en-IN", {
                                  maximumFractionDigits: 0,
                                })}
                              </p>
                            </div>
                            <div className="border-t border-neutral-800 pt-3 text-right">
                              <p className="text-[#666666] text-[8px] mb-1">
                                Portfolio Weight
                              </p>
                              <p className="text-white text-xs font-medium">
                                {portfolioPosition.portfolioWeight.toFixed(2)}%
                                of portfolio
                              </p>
                            </div>
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                ) : (
                  <div className="bg-gradient-to-b from-[#2a2a2a] to-[#1c1c1c] rounded-lg shadow-lg p-[1px]">
                    <div className="bg-[#161616] rounded-lg h-[310px] flex items-center justify-center">
                      <p className="text-[#666666] text-sm">
                        Not in your portfolio
                      </p>
                    </div>
                  </div>
                )}

                {/* Company Stats */}
                <div className="bg-gradient-to-b from-[#2a2a2a] to-[#1c1c1c] rounded-lg shadow-lg p-[1px]">
                  <div className="bg-[#161616] rounded-lg h-[310px]">
                    <div className="border-b border-neutral-800 p-4">
                      <h3 className="text-white font-medium text-sm">
                        Company Stats
                      </h3>
                    </div>
                    <div className="p-4 space-y-3">
                      <div className="flex justify-between items-center border-b border-neutral-800 pb-3">
                        <span className="text-[#999999] text-xs">Sector</span>
                        <span className="text-white text-xs font-medium">
                          {stockData.sector}
                        </span>
                      </div>
                      <div className="flex justify-between items-center border-b border-neutral-800 pb-3">
                        <span className="text-[#999999] text-xs">Industry</span>
                        <span className="text-white text-xs font-medium">
                          {stockData.industry}
                        </span>
                      </div>
                      <div className="flex justify-between items-center border-b border-neutral-800 pb-3">
                        <span className="text-[#999999] text-xs">
                          Current Price
                        </span>
                        <span className="text-white text-xs font-medium">
                          ₹
                          {stockData.current_price.toLocaleString("en-IN", {
                            maximumFractionDigits: 2,
                          })}
                        </span>
                      </div>
                      <div className="flex justify-between items-center border-b border-neutral-800 pb-3">
                        <span className="text-[#999999] text-xs">52W High</span>
                        <span className="text-white text-xs font-medium">
                          ₹
                          {weekHigh52.toLocaleString("en-IN", {
                            maximumFractionDigits: 2,
                          })}
                        </span>
                      </div>
                      <div className="flex justify-between items-center border-b border-neutral-800 pb-3">
                        <span className="text-[#999999] text-xs">52W Low</span>
                        <span className="text-white text-xs font-medium">
                          ₹
                          {weekLow52.toLocaleString("en-IN", {
                            maximumFractionDigits: 2,
                          })}
                        </span>
                      </div>
                      <div className="flex justify-between items-center">
                        <span className="text-[#999999] text-xs">
                          Risk Rating
                        </span>
                        <span
                          className={`text-xs font-medium ${getRiskColor(
                            stockData.current_change
                          )}`}
                        >
                          {riskRating}
                        </span>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            {/* Right Column - Why This Stock - 1/3 width, spans both rows */}
            <div className="bg-gradient-to-b from-[#2a2a2a] to-[#1c1c1c] rounded-lg shadow-lg p-[1px]">
              <div className="bg-[#161616] rounded-lg h-[calc(400px+310px+1rem)] p-4 flex flex-col">
                <div className="border-b border-neutral-800 pb-3 mb-4">
                  <div className="flex items-center justify-between mb-2">
                    <h3 className="text-white font-medium text-sm">
                      Why This Stock?
                    </h3>
                    {xaiData?.llm_used && (
                      <span className="px-2 py-0.5 bg-[rgba(0,176,94,0.1)] border border-[#00b05e] rounded text-[8px] text-[#00b05e]">
                        AI Analysis
                      </span>
                    )}
                  </div>
                  {xaiData?.as_of && (
                    <p className="text-[#666666] text-[9px]">
                      Analysis as of{" "}
                      {new Date(xaiData.as_of).toLocaleDateString("en-US", {
                        month: "short",
                        day: "numeric",
                        year: "numeric",
                      })}
                    </p>
                  )}
                  {xaiData?.weight && (
                    <p className="text-[#999999] text-[9px] mt-1">
                      Portfolio Weight: {(xaiData.weight * 100).toFixed(2)}%
                    </p>
                  )}
                </div>
                <div className="flex-1 overflow-y-auto space-y-3 pr-2 custom-scrollbar">
                  {xaiData &&
                  xaiData.available &&
                  xaiData.summary_points.length > 0 ? (
                    <>
                      {xaiData.summary_points.map((point, index) => (
                        <div
                          key={index}
                          className="p-3 bg-gradient-to-br from-[#0c0c0c] to-[#1a1a1a] rounded-lg border border-neutral-800 hover:border-[#00b05e]/30 transition-all duration-200"
                        >
                          <div className="flex items-start gap-2">
                            <div className="w-1.5 h-1.5 rounded-full bg-[#00b05e] mt-1.5 flex-shrink-0" />
                            <p className="text-white text-xs leading-relaxed flex-1">
                              {point}
                            </p>
                          </div>
                        </div>
                      ))}
                      {xaiData.markdown && (
                        <div className="mt-4 pt-4 border-t border-neutral-800">
                          <div className="flex items-center justify-between mb-3">
                            <p className="text-[#999999] text-[9px] uppercase tracking-wide font-medium">
                              Full Analysis Report
                            </p>
                            <button
                              onClick={() => {
                                if (xaiData.markdown) {
                                  const blob = new Blob([xaiData.markdown], {
                                    type: "text/markdown",
                                  });
                                  const url = URL.createObjectURL(blob);
                                  const a = document.createElement("a");
                                  a.href = url;
                                  a.download = `${symbol
                                    ?.replace(".NS", "")
                                    .toUpperCase()}_analysis_${
                                    xaiData.as_of || "report"
                                  }.md`;
                                  document.body.appendChild(a);
                                  a.click();
                                  document.body.removeChild(a);
                                  URL.revokeObjectURL(url);
                                }
                              }}
                              className="flex items-center gap-1.5 px-2 py-1 bg-[#00b05e]/10 hover:bg-[#00b05e]/20 border border-[#00b05e]/30 rounded text-[#00b05e] text-[9px] transition-colors"
                              title="Download full analysis report"
                            >
                              <Download className="w-3 h-3" />
                              Download
                            </button>
                          </div>
                          <div className="p-4 bg-[#0c0c0c] rounded-lg border border-neutral-800 max-h-[300px] overflow-y-auto custom-scrollbar">
                            <div
                              className="text-white text-xs leading-relaxed markdown-content"
                              dangerouslySetInnerHTML={{
                                __html: formatMarkdown(xaiData.markdown),
                              }}
                            />
                          </div>
                        </div>
                      )}
                    </>
                  ) : (
                    <div className="flex items-center justify-center h-[200px]">
                      <div className="text-center">
                        <p className="text-[#666666] text-sm mb-1">
                          {xaiData && !xaiData.available
                            ? "No analysis available"
                            : "Loading analysis..."}
                        </p>
                        {xaiData && !xaiData.available && (
                          <p className="text-[#666666] text-xs">
                            Run XAI analysis to see insights
                          </p>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Chatbot Button */}
      <ChatbotButton />
    </div>
  );
}
