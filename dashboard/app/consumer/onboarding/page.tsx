"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import Navbar from "@/components/layout/navbar";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

export default function OnboardingPage() {
  const router = useRouter();

  useEffect(() => {
    const isAuthenticated = localStorage.getItem("isAuthenticated");
    if (!isAuthenticated) {
      router.push("/login");
      return;
    }
  }, [router]);

  return (
    <div className="min-h-screen bg-gradient-to-br from-[#0d0d0d] to-[#121212]">
      <Navbar />
      <div className="container mx-auto p-8">
        <div className="mb-8">
          <h1 className="text-3xl font-bold text-white mb-2">Onboarding</h1>
          <p className="text-gray-400">Complete your profile setup</p>
        </div>

        <Card className="bg-[#1a1a1a] border-[#2a2a2a]">
          <CardHeader>
            <CardTitle className="text-white">Welcome to Pathway</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <p className="text-gray-400">
              Complete your onboarding process to start investing. Make sure you
              have completed the questionnaire and uploaded all required
              documents.
            </p>
            <div className="flex gap-4">
              <Button
                onClick={() => router.push("/consumer/questionnaire")}
                className="bg-[#00b05e] text-black hover:bg-[#00a055]"
              >
                Complete Questionnaire
              </Button>
              <Button
                onClick={() => router.push("/consumer/dashboard")}
                variant="outline"
                className="border-[#2a2a2a] text-white hover:bg-[#2a2a2a]"
              >
                Go to Dashboard
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
