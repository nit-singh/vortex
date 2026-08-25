"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Navbar from "@/components/layout/navbar";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { getStatusColor } from "@/lib/utils";
import { Users, FileCheck, Clock, CheckCircle } from "lucide-react";

export default function CompanyDashboard() {
  const router = useRouter();
  const [userEmail, setUserEmail] = useState("");
  const [stats, setStats] = useState({
    totalSubmissions: 0,
    pending: 0,
    approved: 0,
    rejected: 0,
  });

  useEffect(() => {
    const userType = localStorage.getItem("userType");
    if (userType !== "company") {
      router.push("/consumer/dashboard");
      return;
    }

    const email = localStorage.getItem("userEmail");
    if (email) setUserEmail(email);

    // Load stats from localStorage or API
    const savedStats = localStorage.getItem("companyStats");
    if (savedStats) {
      setStats(JSON.parse(savedStats));
    }
  }, [router]);

  return (
    <div className="min-h-screen bg-gradient-to-br from-[#0d0d0d] to-[#121212]">
      <Navbar />
      <div className="container mx-auto p-8">
        <div className="mb-8">
          <h1 className="text-3xl font-bold text-white mb-2">
            Company Dashboard
          </h1>
          <p className="text-gray-400">Welcome back, {userEmail}</p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
          <Card className="bg-[#1a1a1a] border-[#2a2a2a]">
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium text-gray-400">
                Total Submissions
              </CardTitle>
              <Users className="h-4 w-4 text-gray-400" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold text-white">
                {stats.totalSubmissions}
              </div>
              <p className="text-xs text-gray-500 mt-1">All time submissions</p>
            </CardContent>
          </Card>

          <Card className="bg-[#1a1a1a] border-[#2a2a2a]">
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium text-gray-400">
                Pending Reviews
              </CardTitle>
              <Clock className="h-4 w-4 text-yellow-500" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold text-white">
                {stats.pending}
              </div>
              <p className="text-xs text-gray-500 mt-1">Awaiting review</p>
            </CardContent>
          </Card>

          <Card className="bg-[#1a1a1a] border-[#2a2a2a]">
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium text-gray-400">
                Approved
              </CardTitle>
              <CheckCircle className="h-4 w-4 text-green-500" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold text-white">
                {stats.approved}
              </div>
              <p className="text-xs text-gray-500 mt-1">
                Successfully approved
              </p>
            </CardContent>
          </Card>

          <Card className="bg-[#1a1a1a] border-[#2a2a2a]">
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium text-gray-400">
                Rejected
              </CardTitle>
              <FileCheck className="h-4 w-4 text-red-500" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold text-white">
                {stats.rejected}
              </div>
              <p className="text-xs text-gray-500 mt-1">Rejected submissions</p>
            </CardContent>
          </Card>
        </div>

        <Card className="bg-[#1a1a1a] border-[#2a2a2a]">
          <CardHeader>
            <CardTitle className="text-white">Recent Submissions</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              <div className="flex items-center justify-between p-4 bg-[#0d0d0d] rounded-lg">
                <div>
                  <p className="text-white font-medium">No submissions yet</p>
                  <p className="text-gray-400 text-sm">
                    Submissions will appear here
                  </p>
                </div>
                <Badge className={getStatusColor("pending")}>Pending</Badge>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
