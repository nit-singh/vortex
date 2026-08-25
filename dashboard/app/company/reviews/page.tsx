"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import Navbar from "@/components/layout/navbar";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { getStatusColor } from "@/lib/utils";
import { Eye, Search } from "lucide-react";
import { Input } from "@/components/ui/input";

interface Review {
  id: string;
  userId: string;
  status: string;
  submittedAt: string;
  riskScore?: number;
}

export default function ReviewsPage() {
  const router = useRouter();
  const [reviews, setReviews] = useState<Review[]>([]);
  const [searchQuery, setSearchQuery] = useState("");

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

    // Load reviews from localStorage or API
    const savedReviews = localStorage.getItem("companyReviews");
    if (savedReviews) {
      setReviews(JSON.parse(savedReviews));
    }
  }, [router]);

  const filteredReviews = reviews.filter(
    (review) =>
      review.userId.toLowerCase().includes(searchQuery.toLowerCase()) ||
      review.id.toLowerCase().includes(searchQuery.toLowerCase())
  );

  return (
    <div className="min-h-screen bg-gradient-to-br from-[#0d0d0d] to-[#121212]">
      <Navbar />
      <div className="container mx-auto p-8">
        <div className="mb-8">
          <h1 className="text-3xl font-bold text-white mb-2">KYC Reviews</h1>
          <p className="text-gray-400">Review and manage KYC submissions</p>
        </div>

        <div className="mb-6">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
            <Input
              type="text"
              placeholder="Search by user ID or submission ID..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="pl-10 bg-[#1a1a1a] border-[#2a2a2a] text-white placeholder:text-gray-500"
            />
          </div>
        </div>

        <Card className="bg-[#1a1a1a] border-[#2a2a2a]">
          <CardHeader>
            <CardTitle className="text-white">All Submissions</CardTitle>
          </CardHeader>
          <CardContent>
            {filteredReviews.length === 0 ? (
              <div className="text-center py-12">
                <p className="text-gray-400">No reviews found</p>
                <p className="text-gray-500 text-sm mt-2">
                  Submissions will appear here when available
                </p>
              </div>
            ) : (
              <div className="space-y-4">
                {filteredReviews.map((review) => (
                  <div
                    key={review.id}
                    className="flex items-center justify-between p-4 bg-[#0d0d0d] rounded-lg hover:bg-[#2a2a2a] transition-colors"
                  >
                    <div className="flex-1">
                      <div className="flex items-center gap-4">
                        <div>
                          <p className="text-white font-medium">
                            Submission #{review.id.slice(0, 8)}
                          </p>
                          <p className="text-gray-400 text-sm">
                            User: {review.userId}
                          </p>
                        </div>
                        {review.riskScore !== undefined && (
                          <div>
                            <p className="text-gray-400 text-sm">Risk Score</p>
                            <p className="text-white font-medium">
                              {review.riskScore.toFixed(1)}/10
                            </p>
                          </div>
                        )}
                      </div>
                      <p className="text-gray-500 text-xs mt-2">
                        Submitted:{" "}
                        {new Date(review.submittedAt).toLocaleDateString()}
                      </p>
                    </div>
                    <div className="flex items-center gap-4">
                      <Badge className={getStatusColor(review.status)}>
                        {review.status}
                      </Badge>
                      <Link href={`/company/reviews/${review.id}`}>
                        <button className="p-2 bg-[#1a1a1a] hover:bg-[#2a2a2a] rounded-lg text-white transition-colors">
                          <Eye className="h-4 w-4" />
                        </button>
                      </Link>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
