"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Sidebar from "@/components/dashboard/Sidebar";
import { FileText } from "lucide-react";

export default function ReportsPage() {
  const router = useRouter();
  const [userName, setUserName] = useState("Daksh");

  useEffect(() => {
    const name = localStorage.getItem("userName");
    if (name) setUserName(name);

    // Check if questionnaire is submitted
    const isQuestionnaireSubmitted = localStorage.getItem(
      "isQuestionnaireSubmitted"
    );
    if (isQuestionnaireSubmitted !== "true") {
      router.push("/consumer/questionnaire");
      return;
    }
  }, [router]);

  return (
    <div className="min-h-screen bg-gradient-to-b from-[#0d0d0d] to-[#121212]">
      <Sidebar userName={userName} />
      <div className="ml-64">
        {/* Header */}
        <div className="bg-[#0d0d0d] border-b border-[#1a1a1a] px-6 py-4">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-white font-medium text-base mb-1">Reports</h1>
              <p className="text-[#666666] text-sm">
                Your investment and portfolio reports
              </p>
            </div>
          </div>
        </div>

        {/* Main Content */}
        <div className="p-6">
          <div className="bg-[#000000] rounded-lg border border-[#2a2a2a] p-8 text-center">
            <FileText className="w-12 h-12 text-[#666666] mx-auto mb-4" />
            <h3 className="text-white font-medium text-base mb-2">
              No Reports Available
            </h3>
            <p className="text-[#999999] text-sm">
              Reports will appear here once available
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
