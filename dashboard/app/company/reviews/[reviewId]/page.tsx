"use client";

import { useEffect, useState } from "react";
import { useRouter, useParams } from "next/navigation";
import Navbar from "@/components/layout/navbar";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { getStatusColor, getRiskColor } from "@/lib/utils";
import { ArrowLeft, Check, X } from "lucide-react";

export default function ReviewDetailPage() {
  const router = useRouter();
  const params = useParams();
  const reviewId = params?.reviewId as string;
  const [review, setReview] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const isAuthenticated = localStorage.getItem("isAuthenticated");
    if (!isAuthenticated) {
      router.push("/login");
      return;
    }

    const userType = localStorage.getItem("userType");
    if (userType !== "company") {
      router.push("/consumer/dashboard");
      return;
    }

    // Simulate fetching review data
    setTimeout(() => {
      setReview({
        id: reviewId,
        userId: "user123",
        status: "pending",
        submittedAt: new Date().toISOString(),
        riskScore: 5.5,
        documents: {
          aadhaar: "uploaded",
          pan: "uploaded",
          itr: "uploaded",
          video: "uploaded",
        },
      });
      setLoading(false);
    }, 1000);
  }, [reviewId, router]);

  const handleApprove = () => {
    // Update review status
    if (review) {
      setReview({ ...review, status: "approved" });
    }
    router.push("/company/reviews");
  };

  const handleReject = () => {
    // Update review status
    if (review) {
      setReview({ ...review, status: "rejected" });
    }
    router.push("/company/reviews");
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-[#0d0d0d] to-[#121212]">
        <Navbar />
        <div className="container mx-auto p-8">
          <p className="text-white">Loading...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-[#0d0d0d] to-[#121212]">
      <Navbar />
      <div className="container mx-auto p-8">
        <Button
          onClick={() => router.push("/company/reviews")}
          variant="ghost"
          className="mb-4 text-gray-400 hover:text-white"
        >
          <ArrowLeft className="h-4 w-4 mr-2" />
          Back to Reviews
        </Button>

        <div className="mb-8">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-3xl font-bold text-white mb-2">
                Review Submission
              </h1>
              <p className="text-gray-400">Submission ID: {review?.id}</p>
            </div>
            <Badge className={getStatusColor(review?.status || "pending")}>
              {review?.status}
            </Badge>
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
          <Card className="bg-[#1a1a1a] border-[#2a2a2a]">
            <CardHeader>
              <CardTitle className="text-white">Submission Details</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div>
                <p className="text-gray-400 text-sm mb-1">User ID</p>
                <p className="text-white">{review?.userId}</p>
              </div>
              <div>
                <p className="text-gray-400 text-sm mb-1">Submitted At</p>
                <p className="text-white">
                  {new Date(review?.submittedAt).toLocaleString()}
                </p>
              </div>
              <div>
                <p className="text-gray-400 text-sm mb-1">Risk Score</p>
                <div className="flex items-center gap-2">
                  <p className="text-white text-xl font-bold">
                    {review?.riskScore?.toFixed(1)}
                  </p>
                  <Badge className={getRiskColor(review?.riskScore || 0)}>
                    /10
                  </Badge>
                </div>
              </div>
            </CardContent>
          </Card>

          <Card className="bg-[#1a1a1a] border-[#2a2a2a]">
            <CardHeader>
              <CardTitle className="text-white">Documents</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              <div className="flex items-center justify-between p-3 bg-[#0d0d0d] rounded-lg">
                <span className="text-white">Aadhaar Card</span>
                <Badge
                  className={
                    review?.documents?.aadhaar === "uploaded"
                      ? "bg-green-500/20 text-green-500"
                      : ""
                  }
                >
                  {review?.documents?.aadhaar || "Not uploaded"}
                </Badge>
              </div>
              <div className="flex items-center justify-between p-3 bg-[#0d0d0d] rounded-lg">
                <span className="text-white">PAN Card</span>
                <Badge
                  className={
                    review?.documents?.pan === "uploaded"
                      ? "bg-green-500/20 text-green-500"
                      : ""
                  }
                >
                  {review?.documents?.pan || "Not uploaded"}
                </Badge>
              </div>
              <div className="flex items-center justify-between p-3 bg-[#0d0d0d] rounded-lg">
                <span className="text-white">ITR</span>
                <Badge
                  className={
                    review?.documents?.itr === "uploaded"
                      ? "bg-green-500/20 text-green-500"
                      : ""
                  }
                >
                  {review?.documents?.itr || "Not uploaded"}
                </Badge>
              </div>
              <div className="flex items-center justify-between p-3 bg-[#0d0d0d] rounded-lg">
                <span className="text-white">Video Verification</span>
                <Badge
                  className={
                    review?.documents?.video === "uploaded"
                      ? "bg-green-500/20 text-green-500"
                      : ""
                  }
                >
                  {review?.documents?.video || "Not uploaded"}
                </Badge>
              </div>
            </CardContent>
          </Card>
        </div>

        {review?.status === "pending" && (
          <Card className="bg-[#1a1a1a] border-[#2a2a2a]">
            <CardHeader>
              <CardTitle className="text-white">Actions</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex gap-4">
                <Button
                  onClick={handleApprove}
                  className="flex-1 bg-[#00b05e] text-black hover:bg-[#00a055]"
                >
                  <Check className="h-4 w-4 mr-2" />
                  Approve
                </Button>
                <Button
                  onClick={handleReject}
                  variant="destructive"
                  className="flex-1"
                >
                  <X className="h-4 w-4 mr-2" />
                  Reject
                </Button>
              </div>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}
