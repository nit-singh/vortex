"use client";

import { useEffect, useState, useRef, useCallback } from "react";
import { useRouter } from "next/navigation";
import { FileText, Calendar, Download, ArrowLeft } from "lucide-react";
import { kycReportApi } from "@/lib/api";
import jsPDF from "jspdf";
import html2canvas from "html2canvas";

interface MasterJson {
  verification_status?: {
    document_verification?: boolean;
    video_verification?: boolean;
    overall_status?: boolean;
    summary?: {
      total_mismatches?: number;
      total_warnings?: number;
      missing_fields?: number;
    };
  };
  personal_details?: {
    pan_number?: {
      mask?: string;
      last4?: string;
      validated?: boolean;
    };
    aadhaar_number?: {
      mask?: string;
      last4?: string;
      validated?: boolean;
    };
    name?: { value?: string; source?: string };
    date_of_birth?: { value?: string; source?: string };
    age?: { value?: number; source?: string };
    gender?: { value?: string; source?: string };
    address?: { value?: string; source?: string };
    citizenship?: { value?: string; source?: string };
  };
  financial_details?: {
    total_income?: { value?: number; source?: string };
    taxes_paid?: { value?: number; source?: string };
    amount_to_invest?: { value?: number; source?: string };
    itr_type?: { value?: string; source?: string };
    filing_status?: { value?: string; source?: string };
    filing_timeliness?: { value?: string; source?: string };
  };
  document_verification_details?: {
    is_verified?: boolean;
    mismatches?: Array<{ field?: string; reason?: string }>;
    warnings?: Array<{ field?: string; reason?: string }>;
    missing_fields?: string[];
  };
  video_verification_details?: {
    final_decision?: string;
    liveness_check?: { passed?: boolean };
  };
}

export default function KYCReportPage() {
  const router = useRouter();
  const reportRef = useRef<HTMLDivElement>(null);
  const [userId, setUserId] = useState<string>("");
  const [report, setReport] = useState<string | null>(null);
  const [masterJson, setMasterJson] = useState<MasterJson | null>(null);
  const [generatedAt, setGeneratedAt] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [parsedReport, setParsedReport] = useState<any>(null);

  const fetchReport = useCallback(async (id: string) => {
    setLoading(true);
    try {
      const data = await kycReportApi.fetchKYCReport(id);
      if (data.report) {
        setReport(data.report);
        const parsed = parseReportText(data.report);
        setParsedReport(parsed);
      }
      if (data.master_json) {
        setMasterJson(data.master_json);
      }
      if (data.generated_at) {
        setGeneratedAt(data.generated_at);
      }
    } catch (error) {
      console.error("Failed to fetch KYC report:", error);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const id = localStorage.getItem("userId");
    if (id) setUserId(id);

    // Check if questionnaire is submitted
    const isQuestionnaireSubmitted = localStorage.getItem(
      "isQuestionnaireSubmitted"
    );
    if (isQuestionnaireSubmitted !== "true") {
      router.push("/consumer/questionnaire");
      return;
    }

    // Fetch KYC report
    if (id) {
      fetchReport(id);
    }
  }, [router, fetchReport]);

  const formatDate = (dateString: string | null) => {
    if (!dateString) return "";
    try {
      const date = new Date(dateString);
      return date.toLocaleDateString("en-US", {
        month: "long",
        day: "numeric",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });
    } catch {
      return "";
    }
  };

  const formatCurrency = (amount: number | undefined | null) => {
    if (amount === null || amount === undefined) return "Not Available";
    return `₹${amount.toLocaleString("en-IN")}`;
  };

  // Parse markdown report into structured data
  const parseReportText = (reportText: string | null) => {
    if (!reportText) return null;

    const lines = reportText.split("\n");
    const parsed: any = {
      reportId: "",
      date: "",
      overallStatus: "",
      summary: "",
      identityVerification: [] as string[],
      financialOverview: [] as string[],
      behavioralAssessment: {} as Record<string, string>,
      finalDecision: {
        decision: "",
        rationale: [] as string[],
        recommendation: "",
      },
    };

    let currentSection = "";
    let inRationale = false;

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i].trim();

      // Extract Report ID
      if (line.startsWith("Report ID:")) {
        parsed.reportId = line.replace("Report ID:", "").trim();
        continue;
      }

      // Extract Date
      if (line.startsWith("Date:")) {
        parsed.date = line.replace("Date:", "").trim();
        continue;
      }

      // Extract Overall Status
      if (line.startsWith("Overall Status:")) {
        parsed.overallStatus = line.replace("Overall Status:", "").trim();
        continue;
      }

      // Section headers
      if (line.startsWith("## 1. Summary")) {
        currentSection = "summary";
        continue;
      } else if (line.startsWith("## 2. Identity Verification")) {
        currentSection = "identity";
        continue;
      } else if (line.startsWith("## 3. Financial Overview")) {
        currentSection = "financial";
        continue;
      } else if (line.startsWith("## 4. Behavioral Assessment")) {
        currentSection = "behavioral";
        continue;
      } else if (line.startsWith("## 5. Final Decision")) {
        currentSection = "decision";
        continue;
      }

      // Process content based on current section
      if (currentSection === "summary" && line && !line.startsWith("#")) {
        parsed.summary += (parsed.summary ? " " : "") + line;
      } else if (currentSection === "identity" && line.startsWith("-")) {
        parsed.identityVerification.push(line.replace(/^-\s*/, ""));
      } else if (currentSection === "financial" && line.startsWith("-")) {
        parsed.financialOverview.push(line.replace(/^-\s*/, ""));
      } else if (currentSection === "behavioral") {
        if (
          line &&
          !line.startsWith("#") &&
          !line.startsWith("-") &&
          line.includes(":")
        ) {
          const [key, ...valueParts] = line.split(":");
          if (key && valueParts.length > 0) {
            parsed.behavioralAssessment[key.trim()] = valueParts
              .join(":")
              .trim();
          }
        }
      } else if (currentSection === "decision") {
        if (line.startsWith("Decision:")) {
          parsed.finalDecision.decision = line.replace("Decision:", "").trim();
        } else if (line.startsWith("Rationale:")) {
          inRationale = true;
        } else if (inRationale && line.startsWith("-")) {
          parsed.finalDecision.rationale.push(line.replace(/^-\s*/, ""));
        } else if (line.startsWith("Recommendation:")) {
          inRationale = false;
          parsed.finalDecision.recommendation = line
            .replace("Recommendation:", "")
            .trim();
        } else if (
          !inRationale &&
          line &&
          !line.startsWith("#") &&
          !line.startsWith("-") &&
          !line.startsWith("Decision:") &&
          !line.startsWith("Rationale:")
        ) {
          parsed.finalDecision.recommendation +=
            (parsed.finalDecision.recommendation ? " " : "") + line;
        }
      }
    }

    return parsed;
  };

  const renderValue = (value: string) => {
    // Check if value contains [PASS] or [FAIL] and replace with styled badges
    if (!value.includes("[PASS]") && !value.includes("[FAIL]")) {
      return <span>{value}</span>;
    }

    const parts: (string | JSX.Element)[] = [];
    let remaining = value;
    let key = 0;

    // Process all [PASS] and [FAIL] occurrences
    while (remaining.length > 0) {
      const passIndex = remaining.indexOf("[PASS]");
      const failIndex = remaining.indexOf("[FAIL]");

      let nextIndex = -1;
      let badgeType: "PASS" | "FAIL" | null = null;

      if (passIndex !== -1 && failIndex !== -1) {
        // Both exist, use the one that comes first
        if (passIndex < failIndex) {
          nextIndex = passIndex;
          badgeType = "PASS";
        } else {
          nextIndex = failIndex;
          badgeType = "FAIL";
        }
      } else if (passIndex !== -1) {
        nextIndex = passIndex;
        badgeType = "PASS";
      } else if (failIndex !== -1) {
        nextIndex = failIndex;
        badgeType = "FAIL";
      }

      if (nextIndex === -1) {
        // No more badges, add remaining text
        if (remaining.length > 0) {
          parts.push(remaining);
        }
        break;
      }

      // Add text before the badge
      if (nextIndex > 0) {
        parts.push(remaining.substring(0, nextIndex));
      }

      // Add the badge
      if (badgeType === "PASS") {
        parts.push(
          <span
            key={`pass-${key++}`}
            className="inline-flex items-center px-2 py-0.5 rounded border border-[#00b05e] bg-[#00b05e]/10 text-[#00b05e] text-xs font-semibold"
          >
            PASS
          </span>
        );
        remaining = remaining.substring(nextIndex + 6); // 6 = length of "[PASS]"
      } else {
        parts.push(
          <span
            key={`fail-${key++}`}
            className="inline-flex items-center px-2 py-0.5 rounded border border-red-400 bg-red-400/10 text-red-400 text-xs font-semibold"
          >
            FAIL
          </span>
        );
        remaining = remaining.substring(nextIndex + 6); // 6 = length of "[FAIL]"
      }
    }

    return (
      <span className="inline-flex items-center flex-wrap gap-1">{parts}</span>
    );
  };

  const handleDownload = async () => {
    if (!parsedReport || !reportRef.current) return;

    try {
      const element = reportRef.current;

      // Capture the component as canvas
      const canvas = await html2canvas(element, {
        backgroundColor: "#000000",
        scale: 2, // Higher quality
        logging: false,
        useCORS: true,
        windowWidth: element.scrollWidth,
        windowHeight: element.scrollHeight,
      });

      const imgData = canvas.toDataURL("image/png");

      // Calculate PDF dimensions
      const imgWidth = canvas.width;
      const imgHeight = canvas.height;

      // Convert px to mm (1px ≈ 0.264583mm at 96dpi)
      const pxToMm = 0.264583;
      const imgWidthMm = imgWidth * pxToMm;
      const imgHeightMm = imgHeight * pxToMm;

      // Create PDF with dynamic size to fit content
      const pdf = new jsPDF({
        orientation: imgHeightMm > imgWidthMm ? "portrait" : "landscape",
        unit: "mm",
        format: [imgWidthMm, imgHeightMm],
      });

      // Add image to PDF
      pdf.addImage(imgData, "PNG", 0, 0, imgWidthMm, imgHeightMm);

      // Save PDF
      const fileName = `KYC_Report_${userId}_${
        new Date().toISOString().split("T")[0]
      }.pdf`;
      pdf.save(fileName);
    } catch (error) {
      console.error("Failed to generate PDF:", error);
      alert("Failed to generate PDF. Please try again.");
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-b from-[#0d0d0d] to-[#121212]">
      {/* Header */}
      <div className="bg-[#0d0d0d] border-b border-[#1a1a1a] px-6 py-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <button
              onClick={() => router.push("/consumer/dashboard")}
              className="p-2 rounded-lg hover:bg-[#1a1a1a] transition-colors"
            >
              <ArrowLeft className="w-5 h-5 text-[#999999]" />
            </button>
            <div>
              <h1 className="text-white font-medium text-base mb-1">
                KYC Verification Report
              </h1>
              <p className="text-[#666666] text-sm">
                Your KYC verification status and details
              </p>
            </div>
          </div>
          {parsedReport && (
            <button
              onClick={handleDownload}
              className="px-4 py-2 bg-[#00b05e] hover:bg-[#00a050] text-white text-xs font-medium rounded-lg flex items-center gap-2 transition-colors"
            >
              <Download className="w-4 h-4" />
              Download PDF
            </button>
          )}
        </div>
      </div>

      {/* Main Content */}
      <div className="p-6">
        {loading ? (
          <div className="bg-[#000000] rounded-lg border border-[#2a2a2a] p-8 text-center">
            <p className="text-[#999999] text-sm">Loading report...</p>
          </div>
        ) : !parsedReport ? (
          <div className="bg-[#000000] rounded-lg border border-[#2a2a2a] p-8 text-center">
            <FileText className="w-12 h-12 text-[#666666] mx-auto mb-4" />
            <h3 className="text-white font-medium text-base mb-2">
              No KYC Report Available
            </h3>
            <p className="text-[#999999] text-sm">
              Complete KYC verification to generate your report
            </p>
          </div>
        ) : (
          <div
            ref={reportRef}
            className="bg-[#000000] rounded-lg border border-[#2a2a2a] max-w-4xl mx-auto"
          >
            {/* Report Header */}
            <div className="bg-[#000000] border-b-2 border-[#2a2a2a] px-8 py-6">
              <div className="flex justify-between items-start">
                <div>
                  <h1 className="text-white font-bold text-2xl mb-1">
                    KYC VERIFICATION REPORT
                  </h1>
                  {parsedReport.date && (
                    <p className="text-[#999999] text-sm mt-2">
                      Date: {parsedReport.date}
                    </p>
                  )}
                  {generatedAt && (
                    <div className="flex items-center gap-2 mt-1">
                      <Calendar className="w-4 h-4 text-[#999999]" />
                      <span className="text-[#999999] text-xs">
                        Generated: {formatDate(generatedAt)}
                      </span>
                    </div>
                  )}
                </div>
                <div className="text-right">
                  {parsedReport.reportId && (
                    <>
                      <p className="text-[#999999] text-xs mb-1">Report ID</p>
                      <p className="text-white text-sm font-mono">
                        {parsedReport.reportId}
                      </p>
                    </>
                  )}
                  {parsedReport.overallStatus && (
                    <div className="mt-3">
                      <p className="text-[#999999] text-xs mb-1">
                        Overall Status
                      </p>
                      <p
                        className={`text-sm font-semibold ${
                          parsedReport.overallStatus === "PASS"
                            ? "text-green-400"
                            : parsedReport.overallStatus === "FAIL"
                            ? "text-red-400"
                            : "text-yellow-400"
                        }`}
                      >
                        {parsedReport.overallStatus}
                      </p>
                    </div>
                  )}
                </div>
              </div>
            </div>

            {/* Report Content */}
            <div className="p-8 bg-[#000000]">
              {/* Summary Section */}
              {parsedReport.summary && (
                <div className="mb-6">
                  <h2 className="text-white font-semibold text-lg mb-3 pb-2 border-b border-[#2a2a2a]">
                    1. Summary
                  </h2>
                  <div className="bg-[#000000] rounded border border-[#2a2a2a] p-5">
                    <p className="text-[#cccccc] text-sm leading-relaxed">
                      {parsedReport.summary}
                    </p>
                  </div>
                </div>
              )}

              {/* Identity Verification Section */}
              {parsedReport.identityVerification.length > 0 && (
                <div className="mb-6">
                  <h2 className="text-white font-semibold text-lg mb-3 pb-2 border-b border-[#2a2a2a]">
                    2. Identity Verification
                  </h2>
                  <div className="bg-[#000000] rounded border border-[#2a2a2a] p-5">
                    {parsedReport.identityVerification.map(
                      (item: string, index: number) => {
                        const [label, ...valueParts] = item.split(":");
                        const value = valueParts.join(":").trim();
                        return (
                          <div
                            key={index}
                            className="flex justify-between items-center py-2.5 border-b border-[#2a2a2a] last:border-b-0"
                          >
                            <span className="text-[#999999] text-sm font-medium">
                              {label?.trim()}
                            </span>
                            <span className="text-white text-sm font-semibold">
                              {renderValue(value)}
                            </span>
                          </div>
                        );
                      }
                    )}
                  </div>
                </div>
              )}

              {/* Financial Overview Section */}
              {parsedReport.financialOverview.length > 0 && (
                <div className="mb-6">
                  <h2 className="text-white font-semibold text-lg mb-3 pb-2 border-b border-[#2a2a2a]">
                    3. Financial Overview
                  </h2>
                  <div className="bg-[#000000] rounded border border-[#2a2a2a] p-5">
                    {parsedReport.financialOverview.map(
                      (item: string, index: number) => {
                        const [label, ...valueParts] = item.split(":");
                        const value = valueParts.join(":").trim();
                        return (
                          <div
                            key={index}
                            className="flex justify-between items-center py-2.5 border-b border-[#2a2a2a] last:border-b-0"
                          >
                            <span className="text-[#999999] text-sm font-medium">
                              {label?.trim()}
                            </span>
                            <span className="text-white text-sm font-semibold">
                              {renderValue(value)}
                            </span>
                          </div>
                        );
                      }
                    )}
                  </div>
                </div>
              )}

              {/* Behavioral Assessment Section */}
              {Object.keys(parsedReport.behavioralAssessment).length > 0 && (
                <div className="mb-6">
                  <h2 className="text-white font-semibold text-lg mb-3 pb-2 border-b border-[#2a2a2a]">
                    4. Behavioral Assessment
                  </h2>
                  <div className="bg-[#000000] rounded border border-[#2a2a2a] p-5">
                    {Object.entries(parsedReport.behavioralAssessment).map(
                      ([key, value], index) => (
                        <div
                          key={index}
                          className="flex flex-col py-2.5 border-b border-[#2a2a2a] last:border-b-0"
                        >
                          <span className="text-[#999999] text-sm font-medium mb-1">
                            {key}
                          </span>
                          <span className="text-[#cccccc] text-sm">
                            {renderValue(value as string)}
                          </span>
                        </div>
                      )
                    )}
                  </div>
                </div>
              )}

              {/* Final Decision Section */}
              {parsedReport.finalDecision && (
                <div className="mb-6">
                  <h2 className="text-white font-semibold text-lg mb-3 pb-2 border-b border-[#2a2a2a]">
                    5. Final Decision
                  </h2>
                  <div className="bg-[#000000] rounded border border-[#2a2a2a] p-5">
                    {parsedReport.finalDecision.decision && (
                      <div className="mb-4 pb-4 border-b border-[#2a2a2a]">
                        <span className="text-[#999999] text-sm font-medium mb-2 block">
                          Decision:
                        </span>
                        <span
                          className={`text-lg font-semibold ${
                            parsedReport.finalDecision.decision === "APPROVED"
                              ? "text-[#00b05e]"
                              : parsedReport.finalDecision.decision ===
                                "REJECTED"
                              ? "text-red-400"
                              : "text-yellow-400"
                          }`}
                        >
                          {parsedReport.finalDecision.decision}
                        </span>
                      </div>
                    )}
                    {parsedReport.finalDecision.rationale.length > 0 && (
                      <div className="mb-4">
                        <span className="text-[#999999] text-sm font-medium mb-2 block">
                          Rationale:
                        </span>
                        <ul className="list-disc ml-6 space-y-1.5">
                          {parsedReport.finalDecision.rationale.map(
                            (item: string, index: number) => (
                              <li
                                key={index}
                                className="text-[#cccccc] text-sm"
                              >
                                {renderValue(item)}
                              </li>
                            )
                          )}
                        </ul>
                      </div>
                    )}
                    {parsedReport.finalDecision.recommendation && (
                      <div className="pt-4 border-t border-[#2a2a2a]">
                        <span className="text-[#999999] text-sm font-medium mb-2 block">
                          Recommendation:
                        </span>
                        <p className="text-[#cccccc] text-sm leading-relaxed">
                          {renderValue(
                            parsedReport.finalDecision.recommendation
                          )}
                        </p>
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* Footer */}
              <div className="mt-8 pt-6 border-t-2 border-[#2a2a2a]">
                <p className="text-[#666666] text-xs text-center">
                  This is an electronically generated report. No signature
                  required.
                </p>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
