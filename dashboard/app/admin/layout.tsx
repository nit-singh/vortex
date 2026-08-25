"use client";

import { usePathname } from "next/navigation";
import ProtectedRoute from "@/components/auth/ProtectedRoute";

export default function AdminLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const pathname = usePathname();

  // Don't protect the admin login page
  if (pathname === "/admin/login") {
    return <>{children}</>;
  }

  // Protect all other admin routes
  return <ProtectedRoute>{children}</ProtectedRoute>;
}
