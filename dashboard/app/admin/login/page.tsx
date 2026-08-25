"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Mail, Lock, Eye, EyeOff, ArrowLeft } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { authApi } from "@/lib/api";

export default function AdminLoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      // Call Flask API for admin login (backend handles admin credentials)
      const response = await authApi.login(email, password);

      if (response.success && response.userType === "admin") {
        // Admin login successful
        localStorage.setItem("isAuthenticated", "true");
        localStorage.setItem("userEmail", response.email);
        localStorage.setItem("userType", "admin");
        localStorage.setItem("userId", response.userId);
        localStorage.setItem("userName", response.name);
        localStorage.setItem("isQuestionnaireSubmitted", "true");

        router.push("/admin/dashboard");
        setLoading(false);
        return;
      } else {
        setError("Invalid admin credentials. Please try again.");
      }
    } catch (err: any) {
      setError(
        err.response?.data?.message ||
          err.message ||
          "Invalid credentials. Please try again."
      );
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-[#0d0d0d] to-[#121212] p-4">
      <div className="w-full max-w-[380px]">
        {/* Header */}
        <div className="text-center mb-[32px]">
          <h1 className="text-[28px] font-semibold text-white mb-[8px]">
            Admin Login
          </h1>
          <p className="text-[14px] text-[#999999]">
            Sign in to access the admin dashboard
          </p>
        </div>

        {/* Form Card */}
        <div className="bg-[#1a1a1a] rounded-[16px] p-[32px] border border-[#2a2a2a] relative">
          <form onSubmit={handleSubmit} className="space-y-[20px]">
            {/* Error Message */}
            {error && (
              <div className="bg-red-500/20 border border-red-500/30 text-red-500 text-sm p-3 rounded-md">
                {error}
              </div>
            )}

            {/* Email Field */}
            <div className="relative">
              <Mail className="absolute left-[16px] top-1/2 -translate-y-1/2 h-[18px] w-[18px] text-[#666666]" />
              <Input
                type="email"
                placeholder="Admin Email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                className="pl-[44px] h-[48px] bg-[#0d0d0d] border-[#2a2a2a] text-white placeholder:text-[#666666] focus:border-[#00b05e] focus:ring-0"
              />
            </div>

            {/* Password Field */}
            <div className="relative">
              <Lock className="absolute left-[16px] top-1/2 -translate-y-1/2 h-[18px] w-[18px] text-[#666666]" />
              <Input
                type={showPassword ? "text" : "password"}
                placeholder="Password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                className="pl-[44px] pr-[44px] h-[48px] bg-[#0d0d0d] border-[#2a2a2a] text-white placeholder:text-[#666666] focus:border-[#00b05e] focus:ring-0"
              />
              <button
                type="button"
                onClick={() => setShowPassword(!showPassword)}
                className="absolute right-[16px] top-1/2 -translate-y-1/2 text-[#666666] hover:text-white"
              >
                {showPassword ? (
                  <EyeOff className="h-[18px] w-[18px]" />
                ) : (
                  <Eye className="h-[18px] w-[18px]" />
                )}
              </button>
            </div>

            {/* Submit Button */}
            <Button
              type="submit"
              disabled={loading}
              className="w-full h-[48px] bg-[#00b05e] text-black font-medium hover:bg-[#00a055] disabled:opacity-50"
            >
              {loading ? "Signing in..." : "Sign In"}
            </Button>

            {/* Back to Regular Login */}
            <div className="text-center mt-[24px]">
              <button
                type="button"
                onClick={() => router.push("/login")}
                className="text-[14px] text-[#00b05e] hover:underline flex items-center justify-center gap-2"
              >
                <ArrowLeft className="w-4 h-4" />
                Back to User Login
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  );
}
