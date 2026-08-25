"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { FileText, ChevronRight, Calendar } from "lucide-react";
import { kycReportApi } from "@/lib/api";

interface RecentReportsProps {
  userId: string;
}

interface ReportData {
  report: string | null;
  generated_at: string | null;
  available: boolean;
}

export default function RecentReports({ userId }: RecentReportsProps) {
  const router = useRouter();
  const [report, setReport] = useState<ReportData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchReport = async () => {
      try {
        const data = await kycReportApi.fetchKYCReport(userId);
        if (data.report) {
          setReport({
            report: data.report,
            generated_at: data.generated_at,
            available: true,
          });
        } else {
          setReport({
            report: null,
            generated_at: null,
            available: false,
          });
        }
      } catch (error) {
        console.error("Failed to fetch report:", error);
        setReport({
          report: null,
          generated_at: null,
          available: false,
        });
      } finally {
        setLoading(false);
      }
    };

    if (userId) {
      fetchReport();
    }
  }, [userId]);

  const handleViewAll = () => {
    router.push("/consumer/reports");
  };

  // Extract a preview from the report (first few lines)
  const getReportPreview = (reportText: string | null) => {
    if (!reportText) return "No report available";

    // Extract first section or first 150 characters
    const lines = reportText.split("\n").filter((line) => line.trim());
    if (lines.length > 0) {
      const firstLine = lines[0].replace(/^#+\s*/, ""); // Remove markdown headers
      return firstLine.length > 100
        ? firstLine.substring(0, 100) + "..."
        : firstLine;
    }
    return reportText.substring(0, 100) + "...";
  };

  const formatDate = (dateString: string | null) => {
    if (!dateString) return "";
    try {
      const date = new Date(dateString);
      return date.toLocaleDateString("en-US", {
        month: "short",
        day: "numeric",
        year: "numeric",
      });
    } catch {
      return "";
    }
  };

  return (
    <div className="bg-gradient-to-b from-[#2a2a2a] to-[#1c1c1c] rounded-lg shadow-lg p-[1px] h-full">
      <div className="bg-[#161616] rounded-lg h-full">
        <div className="border-b border-[#1c1c1c] p-4">
          <div className="flex items-center justify-between mb-1">
            <h3 className="text-white font-medium text-sm">Recent Reports</h3>
            <button
              onClick={handleViewAll}
              className="text-[#00b05e] text-[9px] hover:underline flex items-center gap-1"
            >
              View All <ChevronRight className="w-3 h-3" />
            </button>
          </div>
          <p className="text-[#666666] text-[10px]">KYC verification reports</p>
        </div>
        <div className="p-4">
          {loading ? (
            <div className="text-center py-6">
              <p className="text-[#666666] text-xs">Loading...</p>
            </div>
          ) : !report?.available || !report?.report ? (
            <div className="text-center py-6">
              <FileText className="w-8 h-8 text-[#666666] mx-auto mb-2" />
              <p className="text-[#666666] text-xs">No reports available</p>
              <p className="text-[#666666] text-[9px] mt-1">
                Complete KYC verification to generate reports
              </p>
            </div>
          ) : (
            <div
              className="p-3 bg-[#1a1a1a] rounded-lg border border-[#2a2a2a] hover:border-[#00b05e] cursor-pointer transition-colors"
              onClick={handleViewAll}
            >
              <div className="flex items-start gap-2 mb-2">
                <FileText className="w-4 h-4 text-[#00b05e] flex-shrink-0 mt-0.5" />
                <div className="flex-1 min-w-0">
                  <h4 className="text-white text-xs font-medium mb-1">
                    KYC Verification Report
                  </h4>
                  <p className="text-[#999999] text-[10px] leading-relaxed line-clamp-2">
                    {getReportPreview(report.report)}
                  </p>
                </div>
              </div>
              {report.generated_at && (
                <div className="flex items-center gap-1.5 mt-2 pt-2 border-t border-[#2a2a2a]">
                  <Calendar className="w-3 h-3 text-[#666666]" />
                  <span className="text-[#666666] text-[9px]">
                    {formatDate(report.generated_at)}
                  </span>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
