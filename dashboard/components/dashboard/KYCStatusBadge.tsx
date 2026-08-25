"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ShieldCheck } from "lucide-react";
import { kycReportApi } from "@/lib/api";

interface KYCStatusBadgeProps {
  userId: string;
}

export default function KYCStatusBadge({ userId }: KYCStatusBadgeProps) {
  const router = useRouter();
  const [kycStatus, setKycStatus] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchKYCStatus = async () => {
      try {
        const data = await kycReportApi.fetchKYCReport(userId);

        // Use validation_status from backend - this reflects admin approval/rejection
        // If validation_status is "pending" or "review", show "IN REVIEW" regardless of validation result
        if (data.validation_status) {
          const validationStatus = data.validation_status.toLowerCase();
          if (validationStatus === "pending" || validationStatus === "review") {
            setKycStatus("IN REVIEW");
          } else if (validationStatus === "approved") {
            setKycStatus("VERIFIED");
          } else if (validationStatus === "rejected") {
            setKycStatus("REJECTED");
          } else {
            setKycStatus("IN REVIEW");
          }
        } else if (data.kyc_status) {
          // Fallback to kyc_status if validation_status not available
          setKycStatus(data.kyc_status);
        } else if (data.available && data.report) {
          // If validation completed but admin hasn't reviewed yet, show IN REVIEW
          setKycStatus("IN REVIEW");
        } else {
          setKycStatus("PENDING");
        }
      } catch (error) {
        console.error("Failed to fetch KYC status:", error);
        setKycStatus("PENDING");
      } finally {
        setLoading(false);
      }
    };

    if (userId) {
      fetchKYCStatus();
    }
  }, [userId]);

  // Show loading state or pending if no status yet
  if (loading) {
    return null;
  }

  // If status is null after loading, it means no report exists
  const displayStatus = kycStatus || "PENDING";

  const getStatusColor = (status: string) => {
    switch (status) {
      case "VERIFIED":
        return "text-[#00b05e]";
      case "REJECTED":
        return "text-red-400";
      case "IN REVIEW":
        return "text-yellow-400";
      case "PENDING":
        return "text-[#999999]";
      default:
        return "text-[#999999]";
    }
  };

  const getStatusBgColor = (status: string) => {
    switch (status) {
      case "VERIFIED":
        return "bg-[rgba(0,176,94,0.1)]";
      case "REJECTED":
        return "bg-[rgba(239,68,68,0.1)]";
      case "IN REVIEW":
        return "bg-[rgba(250,204,21,0.1)]";
      case "PENDING":
        return "bg-[rgba(153,153,153,0.1)]";
      default:
        return "bg-[rgba(153,153,153,0.1)]";
    }
  };

  const getStatusBorderColor = (status: string) => {
    switch (status) {
      case "VERIFIED":
        return "border-[#00b05e]";
      case "REJECTED":
        return "border-red-400";
      case "IN REVIEW":
        return "border-yellow-400";
      case "PENDING":
        return "border-[#2a2a2a]";
      default:
        return "border-[#2a2a2a]";
    }
  };

  const handleClick = () => {
    router.push("/consumer/kyc-report");
  };

  return (
    <button
      onClick={handleClick}
      className="flex items-center gap-2.5 px-3 py-2 bg-[#1a1a1a] border border-[#2a2a2a] rounded-lg hover:bg-[#222222] transition-colors cursor-pointer"
    >
      <ShieldCheck className="w-4 h-4 text-[#999999]" />
      <div className="flex items-center gap-2">
        <span className="text-[#999999] text-xs font-medium">KYC Status:</span>
        <span
          className={`px-2 py-0.5 rounded text-[10px] font-medium ${getStatusBgColor(
            displayStatus
          )} ${getStatusColor(displayStatus)}`}
        >
          {displayStatus}
        </span>
      </div>
    </button>
  );
}
