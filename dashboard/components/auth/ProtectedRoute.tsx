"use client";

import { useEffect, useState } from "react";
import { useRouter, usePathname } from "next/navigation";

interface ProtectedRouteProps {
  children: React.ReactNode;
}

export default function ProtectedRoute({ children }: ProtectedRouteProps) {
  const router = useRouter();
  const pathname = usePathname();
  const [isAuthenticated, setIsAuthenticated] = useState<boolean | null>(null);
  const [isChecking, setIsChecking] = useState(true);

  useEffect(() => {
    // Check if user is authenticated
    const checkAuth = () => {
      const authStatus = localStorage.getItem("isAuthenticated");
      const isAuth = authStatus === "true";

      setIsAuthenticated(isAuth);
      setIsChecking(false);

      // If not authenticated and trying to access protected route
      if (!isAuth) {
        // Allow access to auth pages without authentication
        if (
          pathname.startsWith("/login") ||
          pathname.startsWith("/register") ||
          pathname.startsWith("/admin/login")
        ) {
          // User is on an auth page, allow access
          return;
        }
        // Store the intended destination (only if not already on auth pages)
        localStorage.setItem("redirectAfterLogin", pathname);
        router.push("/login");
      }
    };

    checkAuth();
  }, [router, pathname]);

  // Show loading while checking authentication
  if (isChecking || isAuthenticated === null) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-[#0d0d0d] to-[#121212]">
        <div className="text-white">Loading...</div>
      </div>
    );
  }

  // If not authenticated, don't render children (redirect will happen)
  if (!isAuthenticated) {
    return null;
  }

  // User is authenticated, render children
  return <>{children}</>;
}
