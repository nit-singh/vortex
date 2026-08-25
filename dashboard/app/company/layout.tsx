"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import ProtectedRoute from "@/components/auth/ProtectedRoute";

export default function CompanyLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const router = useRouter();

  useEffect(() => {
    // Check if user is company type
    const userType = localStorage.getItem("userType");
    if (userType !== "company") {
      router.push("/consumer/dashboard");
    }
  }, [router]);

  return <ProtectedRoute>{children}</ProtectedRoute>;
}
