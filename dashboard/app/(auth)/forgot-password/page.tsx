"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Mail, ArrowLeft } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";

export default function ForgotPasswordPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [sent, setSent] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);

    // Simulate API call
    setTimeout(() => {
      setLoading(false);
      setSent(true);
    }, 1000);
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-[#0d0d0d] to-[#121212] p-4">
      <div className="w-full max-w-[380px]">
        {/* Header */}
        <div className="text-center mb-[32px]">
          <h1 className="text-[28px] font-semibold text-white mb-[8px]">
            {sent ? "Check your email" : "Forgot Password"}
          </h1>
          <p className="text-[14px] text-[#999999]">
            {sent
              ? "We've sent a password reset link to your email"
              : "Enter your email to receive a password reset link"}
          </p>
        </div>

        {/* Form Card */}
        <div className="bg-[#1a1a1a] rounded-[16px] p-[32px] border border-[#2a2a2a] relative">
          {sent ? (
            <div className="space-y-[20px]">
              <div className="text-center py-4">
                <div className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-[#00b05e]/20 mb-4">
                  <Mail className="h-8 w-8 text-[#00b05e]" />
                </div>
                <p className="text-[14px] text-[#999999] mb-6">
                  If an account exists with {email}, you will receive a password
                  reset link shortly.
                </p>
              </div>
              <Button
                onClick={() => router.push("/login")}
                className="w-full h-[48px] bg-[#00b05e] text-black font-medium hover:bg-[#00a055]"
              >
                Back to Sign In
              </Button>
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="space-y-[20px]">
              {/* Email Field */}
              <div className="relative">
                <Mail className="absolute left-[16px] top-1/2 -translate-y-1/2 h-[18px] w-[18px] text-[#666666]" />
                <Input
                  type="email"
                  placeholder="Email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                  className="pl-[44px] h-[48px] bg-[#0d0d0d] border-[#2a2a2a] text-white placeholder:text-[#666666] focus:border-[#00b05e] focus:ring-0"
                />
              </div>

              {/* Submit Button */}
              <Button
                type="submit"
                disabled={loading}
                className="w-full h-[48px] bg-[#00b05e] text-black font-medium hover:bg-[#00a055] disabled:opacity-50"
              >
                {loading ? "Sending..." : "Send Reset Link"}
              </Button>

              {/* Back to Login */}
              <Button
                type="button"
                variant="ghost"
                onClick={() => router.push("/login")}
                className="w-full h-[48px] text-[#999999] hover:text-white hover:bg-[#2a2a2a]"
              >
                <ArrowLeft className="h-4 w-4 mr-2" />
                Back to Sign In
              </Button>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}
