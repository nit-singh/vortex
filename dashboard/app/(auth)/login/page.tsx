"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Mail, Lock, Eye, EyeOff } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { authApi } from "@/lib/api";

export default function LoginPage() {
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
      // Regular user login - Call Flask API
      const response = await authApi.login(email, password);

      if (response.success) {
        // Store user info in localStorage
        localStorage.setItem("isAuthenticated", "true");
        localStorage.setItem("userEmail", response.email);
        localStorage.setItem("userType", response.userType);
        localStorage.setItem("userId", response.userId);
        localStorage.setItem("userName", response.name);
        localStorage.setItem(
          "isQuestionnaireSubmitted",
          response.isQuestionnaireSubmitted ? "true" : "false"
        );

        // Also store userId in sessionStorage as backup
        if (response.userId) {
          sessionStorage.setItem("userId", response.userId);
        }

        // Check if questionnaire is submitted
        if (
          !response.isQuestionnaireSubmitted &&
          response.userType === "consumer"
        ) {
          // Redirect to questionnaire if not submitted
          router.push("/consumer/questionnaire");
          return;
        }

        // Check if there's a redirect destination
        const redirectPath = localStorage.getItem("redirectAfterLogin");
        if (redirectPath) {
          localStorage.removeItem("redirectAfterLogin");
          router.push(redirectPath);
        } else {
          // Redirect based on user type
          if (response.userType === "company") {
            router.push("/company/dashboard");
          } else {
            router.push("/consumer/dashboard");
          }
        }
      }
    } catch (err: any) {
      setError(
        err.response?.data?.message ||
          err.message ||
          "Invalid email or password. Please try again."
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
            Welcome Back
          </h1>
          <p className="text-[14px] text-[#999999]">
            Sign in to continue to Pathway
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
                placeholder="Email"
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

            {/* Forgot Password Link */}
            <div className="text-right">
              <button
                type="button"
                onClick={() => router.push("/forgot-password")}
                className="text-[14px] text-[#00b05e] hover:underline"
              >
                Forgot Password?
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

            {/* Divider */}
            <div className="relative my-[24px]">
              <div className="absolute inset-0 flex items-center">
                <div className="w-full border-t border-[#2a2a2a]"></div>
              </div>
              <div className="relative flex justify-center text-xs uppercase">
                <span className="bg-[#1a1a1a] px-2 text-[#666666]">
                  Or continue with
                </span>
              </div>
            </div>

            {/* Google Sign In */}
            <Button
              type="button"
              variant="outline"
              className="w-full h-[48px] bg-[#0d0d0d] border-[#2a2a2a] text-white hover:bg-[#1a1a1a] relative"
            >
              <svg
                className="absolute left-[16px] h-[18px] w-[18px]"
                viewBox="0 0 24 24"
              >
                <path
                  fill="currentColor"
                  d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"
                />
                <path
                  fill="currentColor"
                  d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
                />
                <path
                  fill="currentColor"
                  d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"
                />
                <path
                  fill="currentColor"
                  d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"
                />
              </svg>
              <span className="ml-[8px]">Sign in with Google</span>
            </Button>

            {/* Sign Up Link */}
            <div className="text-center mt-[24px]">
              <span className="text-[14px] text-[#999999]">
                Don&apos;t have an account?{" "}
              </span>
              <button
                type="button"
                onClick={() => router.push("/register")}
                className="text-[14px] text-[#00b05e] hover:underline font-medium"
              >
                Sign Up
              </button>
            </div>

            {/* Admin Login Link */}
            <div className="text-center mt-[16px] pt-[16px] border-t border-[#2a2a2a]">
              <button
                type="button"
                onClick={() => router.push("/admin/login")}
                className="text-[12px] text-[#00b05e] hover:underline"
              >
                Admin Login
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  );
}
