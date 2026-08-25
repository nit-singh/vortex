"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

export default function Home() {
  const router = useRouter();
  const [isChecking, setIsChecking] = useState(true);

  useEffect(() => {
    // Check authentication status - must be exactly "true"
    const checkAuth = () => {
      // Use strict equality check
      const authStatus = localStorage.getItem("isAuthenticated");
      const isAuthenticated = authStatus === "true";

      if (isAuthenticated) {
        // User is authenticated, redirect to appropriate dashboard
        const userType = localStorage.getItem("userType");
        if (userType === "admin") {
          router.push("/admin/dashboard");
        } else if (userType === "company") {
          router.push("/company/dashboard");
        } else {
          router.push("/consumer/dashboard");
        }
      } else {
        // User is not authenticated, redirect to login
        router.push("/login");
      }
      setIsChecking(false);
    };

    // Small delay to ensure localStorage is available
    const timer = setTimeout(checkAuth, 100);
    return () => clearTimeout(timer);
  }, [router]);

  // Show loading while checking auth
  if (isChecking) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-[#0d0d0d] to-[#121212]">
        <div className="text-white">Loading...</div>
      </div>
    );
  }

  return null;
}
