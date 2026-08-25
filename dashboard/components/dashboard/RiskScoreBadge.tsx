"use client";

import { useEffect, useState } from "react";
import { BarChart3 } from "lucide-react";
import { riskApi } from "@/lib/api";

interface RiskScoreBadgeProps {
  userId: string;
}

export default function RiskScoreBadge({ userId }: RiskScoreBadgeProps) {
  const [riskScore, setRiskScore] = useState<number | null>(null);
  const [riskLabel, setRiskLabel] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchRiskScore = async () => {
      try {
        const data = await riskApi.getUserRiskScore(userId);
        if (data.risk_score) {
          setRiskScore(data.risk_score.risk_score);
          setRiskLabel(data.risk_score.risk_label);
        }
      } catch (error) {
        console.error("Failed to fetch risk score:", error);
      } finally {
        setLoading(false);
      }
    };

    if (userId) {
      fetchRiskScore();
    }
  }, [userId]);

  if (loading || riskScore === null) {
    return null;
  }

  const getRiskColor = (label: string | null) => {
    if (!label) return "text-[#999999]";
    const lowerLabel = label.toLowerCase();
    if (lowerLabel.includes("low") || lowerLabel.includes("conservative")) {
      return "text-[#00b05e]";
    } else if (
      lowerLabel.includes("medium") ||
      lowerLabel.includes("moderate")
    ) {
      return "text-[#f0b100]";
    } else if (
      lowerLabel.includes("high") ||
      lowerLabel.includes("aggressive")
    ) {
      return "text-[#fb2c36]";
    }
    return "text-[#999999]";
  };

  const getRiskBgColor = (label: string | null) => {
    if (!label) return "bg-[rgba(153,153,153,0.1)]";
    const lowerLabel = label.toLowerCase();
    if (lowerLabel.includes("low") || lowerLabel.includes("conservative")) {
      return "bg-[rgba(0,176,94,0.1)]";
    } else if (
      lowerLabel.includes("medium") ||
      lowerLabel.includes("moderate")
    ) {
      return "bg-[rgba(240,177,0,0.1)]";
    } else if (
      lowerLabel.includes("high") ||
      lowerLabel.includes("aggressive")
    ) {
      return "bg-[rgba(251,44,54,0.1)]";
    }
    return "bg-[rgba(153,153,153,0.1)]";
  };

  return (
    <div className="flex items-center gap-2.5 px-3 py-2 bg-[#1a1a1a] border border-[#2a2a2a] rounded-lg">
      <BarChart3 className="w-4 h-4 text-[#999999]" />
      <div className="flex items-center gap-2">
        <span className="text-[#999999] text-xs font-medium">Risk Score:</span>
        <span className={`text-sm font-semibold ${getRiskColor(riskLabel)}`}>
          {riskScore.toFixed(1)}
        </span>
        <span
          className={`px-2 py-0.5 rounded text-[10px] font-medium ${getRiskBgColor(
            riskLabel
          )} ${getRiskColor(riskLabel)}`}
        >
          {riskLabel || "N/A"}
        </span>
      </div>
    </div>
  );
}
